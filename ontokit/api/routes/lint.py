"""Lint API endpoints for ontology health checking."""

import asyncio
import contextlib
import json
import logging
from datetime import UTC, datetime
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from sqlalchemy import case, delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ontokit.api.utils.redis import get_arq_pool
from ontokit.core.auth import CurrentUser, OptionalUser, RequiredUser
from ontokit.core.constants import LINT_UPDATES_CHANNEL
from ontokit.core.database import get_db
from ontokit.git.bare_repository import BareGitRepositoryService
from ontokit.models.lint import LintIssue, LintRun, LintRunStatus
from ontokit.models.lint_config import ProjectLintConfig
from ontokit.models.project import Project
from ontokit.schemas.lint import (
    LintConfigResponse,
    LintConfigUpdate,
    LintIssueListResponse,
    LintIssueResponse,
    LintIssueTypeValue,
    LintLevelInfo,
    LintLevelsResponse,
    LintRuleInfo,
    LintRulesResponse,
    LintRunDetailResponse,
    LintRunListResponse,
    LintRunResponse,
    LintRunStatusValue,
    LintSummaryResponse,
    LintTriggerResponse,
    SubjectTypeValue,
)
from ontokit.services.linter import ALL_RULE_IDS, LINT_LEVEL_DEFINITIONS, get_available_rules
from ontokit.services.project_service import get_project_service

logger = logging.getLogger(__name__)

router = APIRouter()


async def verify_project_access(
    project_id: UUID,
    db: AsyncSession,
    user: CurrentUser | None,
    require_write: bool = False,
    require_manage: bool = False,
) -> Project:
    """
    Verify user has access to the project.

    Args:
        project_id: The project UUID
        db: Database session
        user: Current user (from auth)
        require_write: If True, require editor/admin/owner access
        require_manage: If True, require admin/owner access

    Returns:
        The Project model if access is granted

    Raises:
        HTTPException: If project not found or access denied
    """
    service = get_project_service(db)
    try:
        project_response = await service.get(project_id, user)
    except HTTPException:
        raise

    # Get the actual project model
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()

    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    if require_manage and project_response.user_role not in ("owner", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )

    if require_write and project_response.user_role not in ("owner", "admin", "editor"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Write access required",
        )

    return project


@router.post(
    "/{project_id}/lint/run",
    response_model=LintTriggerResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_lint(
    project_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: RequiredUser,
) -> LintTriggerResponse:
    """
    Trigger a new lint run for the project.

    The linting runs asynchronously in a background worker.
    Use the WebSocket endpoint or polling to get updates.

    Requires authentication.
    """
    project = await verify_project_access(project_id, db, user)

    # Allow git-only projects: the worker resolves the ontology from the bare
    # repository when source_file_path is absent. Mirror the worker's loading
    # logic so the only requests rejected here are those the worker itself
    # would have to fail.
    git_service = BareGitRepositoryService()
    if not project.source_file_path and not git_service.repository_exists(project_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Project has no ontology file to lint",
        )

    # Check for already running lint
    result = await db.execute(
        select(LintRun)
        .where(LintRun.project_id == project_id)
        .where(LintRun.status.in_([LintRunStatus.PENDING.value, LintRunStatus.RUNNING.value]))
    )
    existing_run = result.scalar_one_or_none()

    if existing_run:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A lint run is already in progress for this project",
        )

    # Enqueue the lint job
    try:
        pool = await get_arq_pool()
        job = await pool.enqueue_job("run_lint_task", str(project_id))

        if job is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to enqueue lint job",
            )

        return LintTriggerResponse(
            job_id=job.job_id,
            status="queued",
            message="Lint job has been queued",
        )

    except Exception as e:
        logger.exception(f"Failed to enqueue lint job for project {project_id}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start lint: {e}",
        ) from e


@router.get("/{project_id}/lint/status", response_model=LintSummaryResponse)
async def get_lint_status(
    project_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: OptionalUser,
) -> LintSummaryResponse:
    """
    Get the current lint status and summary for a project.

    Returns the most recent lint run and issue counts by severity.
    """
    await verify_project_access(project_id, db, user)

    # Get the most recent lint run
    result = await db.execute(
        select(LintRun)
        .where(LintRun.project_id == project_id)
        .order_by(LintRun.started_at.desc())
        .limit(1)
    )
    last_run = result.scalar_one_or_none()

    # Count issues by type from the most recent completed run
    error_count = 0
    warning_count = 0
    info_count = 0

    if last_run and last_run.status == LintRunStatus.COMPLETED.value:
        # Count issues by type
        count_result = await db.execute(
            select(LintIssue.issue_type, func.count(LintIssue.id))
            .where(LintIssue.run_id == last_run.id)
            .where(LintIssue.resolved_at.is_(None))
            .group_by(LintIssue.issue_type)
        )
        counts = {row[0]: row[1] for row in count_result.all()}
        error_count = counts.get("error", 0)
        warning_count = counts.get("warning", 0)
        info_count = counts.get("info", 0)

    last_run_response = None
    if last_run:
        last_run_response = LintRunResponse(
            id=last_run.id,
            project_id=last_run.project_id,
            status=cast("LintRunStatusValue", last_run.status),
            started_at=last_run.started_at,
            completed_at=last_run.completed_at,
            issues_found=last_run.issues_found,
            error_message=last_run.error_message,
        )

    return LintSummaryResponse(
        project_id=project_id,
        last_run=last_run_response,
        error_count=error_count,
        warning_count=warning_count,
        info_count=info_count,
        total_issues=error_count + warning_count + info_count,
    )


@router.get("/{project_id}/lint/runs", response_model=LintRunListResponse)
async def list_lint_runs(
    project_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: OptionalUser,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
) -> LintRunListResponse:
    """
    List all lint runs for a project.

    Returns paginated lint run history.
    """
    await verify_project_access(project_id, db, user)

    # Get total count
    count_result = await db.execute(
        select(func.count(LintRun.id)).where(LintRun.project_id == project_id)
    )
    total = count_result.scalar() or 0

    # Get runs
    # skip/limit are FastAPI Query params typed as int with ge=0 / ge=1,le=100
    # bounds — they cannot carry SQL. SQLAlchemy .offset()/.limit() bind their
    # arguments as parameters, so the resulting query is parameterized.
    result = await db.execute(
        # nosemgrep: python.fastapi.db.generic-sql-fastapi.generic-sql-fastapi
        select(LintRun)
        .where(LintRun.project_id == project_id)
        .order_by(LintRun.started_at.desc())
        .offset(skip)
        .limit(limit)
    )
    runs = result.scalars().all()

    return LintRunListResponse(
        items=[
            LintRunResponse(
                id=run.id,
                project_id=run.project_id,
                status=cast("LintRunStatusValue", run.status),
                started_at=run.started_at,
                completed_at=run.completed_at,
                issues_found=run.issues_found,
                error_message=run.error_message,
            )
            for run in runs
        ],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/{project_id}/lint/runs/{run_id}", response_model=LintRunDetailResponse)
async def get_lint_run(
    project_id: UUID,
    run_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: OptionalUser,
) -> LintRunDetailResponse:
    """
    Get details of a specific lint run including all issues.
    """
    await verify_project_access(project_id, db, user)

    # Get the run
    result = await db.execute(
        select(LintRun).where(LintRun.id == run_id).where(LintRun.project_id == project_id)
    )
    run = result.scalar_one_or_none()

    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lint run not found",
        )

    # Get issues for this run
    issues_result = await db.execute(
        select(LintIssue)
        .where(LintIssue.run_id == run_id)
        .order_by(
            # Order by severity (error > warning > info)
            case(
                (LintIssue.issue_type == "error", 0),
                (LintIssue.issue_type == "warning", 1),
                else_=2,
            ),
            LintIssue.rule_id,
        )
    )
    issues = issues_result.scalars().all()

    return LintRunDetailResponse(
        id=run.id,
        project_id=run.project_id,
        status=cast("LintRunStatusValue", run.status),
        started_at=run.started_at,
        completed_at=run.completed_at,
        issues_found=run.issues_found,
        error_message=run.error_message,
        issues=[
            LintIssueResponse(
                id=issue.id,
                run_id=issue.run_id,
                project_id=issue.project_id,
                issue_type=cast("LintIssueTypeValue", issue.issue_type),
                rule_id=issue.rule_id,
                message=issue.message,
                subject_iri=issue.subject_iri,
                subject_type=cast("SubjectTypeValue | None", issue.subject_type),
                details=issue.details,
                created_at=issue.created_at,
                resolved_at=issue.resolved_at,
            )
            for issue in issues
        ],
    )


@router.get("/{project_id}/lint/issues", response_model=LintIssueListResponse)
async def get_lint_issues(
    project_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: OptionalUser,
    issue_type: str | None = Query(
        default=None, description="Filter by issue type (error, warning, info)"
    ),
    rule_id: str | None = Query(default=None, description="Filter by rule ID"),
    subject_iri: str | None = Query(
        default=None, description="Filter by subject IRI (the class/property the issue relates to)"
    ),
    include_resolved: bool = Query(default=False, description="Include resolved issues"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> LintIssueListResponse:
    """
    Get lint issues for a project.

    By default returns unresolved issues from the most recent completed run.
    """
    await verify_project_access(project_id, db, user)

    # Find the most recent completed run
    run_result = await db.execute(
        select(LintRun)
        .where(LintRun.project_id == project_id)
        .where(LintRun.status == LintRunStatus.COMPLETED.value)
        .order_by(LintRun.started_at.desc())
        .limit(1)
    )
    last_run = run_result.scalar_one_or_none()

    if not last_run:
        return LintIssueListResponse(items=[], total=0, skip=skip, limit=limit)

    # Build query
    query = select(LintIssue).where(LintIssue.run_id == last_run.id)

    if issue_type:
        query = query.where(LintIssue.issue_type == issue_type)

    if rule_id:
        query = query.where(LintIssue.rule_id == rule_id)

    if subject_iri:
        query = query.where(LintIssue.subject_iri == subject_iri)

    if not include_resolved:
        query = query.where(LintIssue.resolved_at.is_(None))

    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0

    # Get issues
    query = (
        query.order_by(
            case(
                (LintIssue.issue_type == "error", 0),
                (LintIssue.issue_type == "warning", 1),
                else_=2,
            ),
            LintIssue.rule_id,
        )
        .offset(skip)
        .limit(limit)
    )

    # skip/limit are FastAPI Query params typed as int with ge=0 / ge=1,le=500
    # bounds, and the issue_type/rule_id/subject_iri filters reach the query
    # through SQLAlchemy .where() comparisons that bind as parameters. None of
    # the user-controlled values are interpolated into SQL text.
    # nosemgrep: python.fastapi.db.generic-sql-fastapi.generic-sql-fastapi
    result = await db.execute(query)
    issues = result.scalars().all()

    return LintIssueListResponse(
        items=[
            LintIssueResponse(
                id=issue.id,
                run_id=issue.run_id,
                project_id=issue.project_id,
                issue_type=cast("LintIssueTypeValue", issue.issue_type),
                rule_id=issue.rule_id,
                message=issue.message,
                subject_iri=issue.subject_iri,
                subject_type=cast("SubjectTypeValue | None", issue.subject_type),
                details=issue.details,
                created_at=issue.created_at,
                resolved_at=issue.resolved_at,
            )
            for issue in issues
        ],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.delete(
    "/{project_id}/lint/issues/{issue_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def dismiss_issue(
    project_id: UUID,
    issue_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: RequiredUser,
) -> None:
    """
    Dismiss/resolve a lint issue.

    This marks the issue as resolved. It will not appear in subsequent
    lint issue lists unless include_resolved=true is set.

    Requires authentication and editor access.
    """
    await verify_project_access(project_id, db, user, require_write=True)

    # Get the issue
    result = await db.execute(
        select(LintIssue).where(LintIssue.id == issue_id).where(LintIssue.project_id == project_id)
    )
    issue = result.scalar_one_or_none()

    if not issue:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lint issue not found",
        )

    if issue.resolved_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Issue is already resolved",
        )

    # Mark as resolved
    issue.resolved_at = datetime.now(UTC)
    await db.commit()


@router.delete(
    "/{project_id}/lint/results",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def clear_lint_results(
    project_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: RequiredUser,
) -> None:
    """
    Clear terminal lint results (runs and issues) for a project.

    Only completed and failed runs are removed; in-flight runs (pending or
    running) are preserved so the worker can finish updating them. Requires
    authentication and admin/owner access.
    """
    await verify_project_access(project_id, db, user, require_manage=True)

    # Delete only terminal runs; pending/running stay so the worker can finish
    # updating them (issues cascade-delete via relationship).
    await db.execute(
        delete(LintRun)
        .where(LintRun.project_id == project_id)
        .where(LintRun.status.in_([LintRunStatus.COMPLETED.value, LintRunStatus.FAILED.value]))
    )
    await db.commit()


def _serialize_lint_config(
    project_id: UUID, config: ProjectLintConfig | None
) -> LintConfigResponse:
    """Build a LintConfigResponse from a ProjectLintConfig (or None for defaults)."""
    if config is None:
        return LintConfigResponse(
            project_id=project_id,
            effective_rules=sorted(ALL_RULE_IDS),
        )

    effective = config.get_enabled_rule_ids()
    enabled_list: list[str] | None = None
    if config.enabled_rules is not None:
        enabled_list = sorted(r.strip() for r in config.enabled_rules.split(",") if r.strip())

    return LintConfigResponse(
        project_id=project_id,
        lint_level=config.lint_level,
        enabled_rules=enabled_list,
        effective_rules=sorted(effective) if effective is not None else sorted(ALL_RULE_IDS),
        updated_at=config.updated_at,
    )


@router.get("/{project_id}/lint/config", response_model=LintConfigResponse)
async def get_lint_config(
    project_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: OptionalUser,
) -> LintConfigResponse:
    """
    Get the current lint configuration for a project.

    Returns the lint level and/or enabled rules, plus the effective set of
    rules that will be checked on the next lint run.
    """
    await verify_project_access(project_id, db, user)

    result = await db.execute(
        select(ProjectLintConfig).where(ProjectLintConfig.project_id == project_id)
    )
    config = result.scalar_one_or_none()
    return _serialize_lint_config(project_id, config)


@router.put("/{project_id}/lint/config", response_model=LintConfigResponse)
async def update_lint_config(
    project_id: UUID,
    body: LintConfigUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: RequiredUser,
) -> LintConfigResponse:
    """
    Update lint configuration for a project.

    Requires owner or admin role.

    ``lint_level`` and ``enabled_rules`` are mutually exclusive: set exactly one
    or set both to ``null`` to reset to all rules. Pass ``enabled_rules=[]`` to
    explicitly disable every rule.
    """
    await verify_project_access(project_id, db, user, require_manage=True)

    # enabled_rules=[] is stored as "" to distinguish from None (unset)
    enabled_rules_str: str | None = None
    if body.enabled_rules is not None:
        enabled_rules_str = ",".join(sorted(body.enabled_rules))

    # Upsert to handle concurrent first-time PUTs safely; RETURNING gives
    # us the persisted row in the same round trip. Wrapping in select(...).from_statement(...)
    # with populate_existing materializes the returned row as an ORM instance.
    #
    # body.lint_level / body.enabled_rules are validated by the Pydantic
    # LintConfigUpdate schema, and pg_insert(...).values(...) plus
    # on_conflict_do_update(set_=...) bind them as INSERT/UPDATE parameters.
    # from_statement() below receives a SQLAlchemy Core Insert (not text()),
    # so the resulting execute() runs a parameterized statement.
    insert_stmt = (
        pg_insert(ProjectLintConfig)
        .values(
            project_id=project_id,
            lint_level=body.lint_level,
            enabled_rules=enabled_rules_str,
        )
        .on_conflict_do_update(
            index_elements=[ProjectLintConfig.project_id],
            set_={
                "lint_level": body.lint_level,
                "enabled_rules": enabled_rules_str,
                "updated_at": func.now(),
            },
        )
        .returning(ProjectLintConfig)
    )
    orm_stmt = (
        select(ProjectLintConfig)
        # nosemgrep: python.fastapi.db.sqlalchemy-fastapi.sqlalchemy-fastapi
        .from_statement(insert_stmt)
        .execution_options(populate_existing=True)
    )
    # nosemgrep: python.fastapi.db.generic-sql-fastapi.generic-sql-fastapi
    result = await db.execute(orm_stmt)
    config = result.scalar_one()
    await db.commit()
    return _serialize_lint_config(project_id, config)


@router.get("/lint/levels", response_model=LintLevelsResponse)
async def get_lint_levels() -> LintLevelsResponse:
    """
    Get the list of available progressive lint levels.

    Each level includes all rules from the previous level plus additional rules.
    """
    return LintLevelsResponse(
        levels=[
            LintLevelInfo(
                level=lvl,
                name=defn.name,
                description=defn.description,
                rule_ids=sorted(defn.rules),
            )
            for lvl, defn in sorted(LINT_LEVEL_DEFINITIONS.items())
        ]
    )


@router.get("/lint/rules", response_model=LintRulesResponse)
async def get_lint_rules() -> LintRulesResponse:
    """
    Get the list of available lint rules.

    Returns information about all lint rules including their ID, name,
    description, and default severity.
    """
    rules = get_available_rules()
    return LintRulesResponse(
        rules=[
            LintRuleInfo(
                rule_id=rule.rule_id,
                name=rule.name,
                description=rule.description,
                severity=cast("LintIssueTypeValue", rule.severity),
                scope=rule.scope,
            )
            for rule in rules
        ]
    )


# WebSocket connection manager for lint updates
class LintConnectionManager:
    """Manages WebSocket connections for lint update notifications."""

    def __init__(self) -> None:
        self.active_connections: dict[str, list[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, project_id: str) -> None:
        """Add connection to project's connection list."""
        if project_id not in self.active_connections:
            self.active_connections[project_id] = []
        self.active_connections[project_id].append(websocket)
        logger.debug(f"WebSocket connected for project {project_id}")

    def disconnect(self, websocket: WebSocket, project_id: str) -> None:
        """Remove connection from project's connection list."""
        if project_id in self.active_connections:
            if websocket in self.active_connections[project_id]:
                self.active_connections[project_id].remove(websocket)
            if not self.active_connections[project_id]:
                del self.active_connections[project_id]
        logger.debug(f"WebSocket disconnected for project {project_id}")

    async def broadcast(self, project_id: str, message: dict[str, object]) -> None:
        """Send message to all connections for a project."""
        if project_id in self.active_connections:
            disconnected = []
            for connection in self.active_connections[project_id]:
                try:
                    await connection.send_json(message)
                except Exception:
                    disconnected.append(connection)

            # Clean up disconnected
            for conn in disconnected:
                self.disconnect(conn, project_id)


manager = LintConnectionManager()


@router.websocket("/{project_id}/lint/ws")
async def lint_websocket(
    websocket: WebSocket,
    project_id: UUID,
    token: str | None = Query(default=None, description="Bearer token for authentication"),
) -> None:
    """
    WebSocket endpoint for real-time lint updates.

    Connect to receive notifications when:
    - Lint run starts
    - Lint run completes
    - Lint run fails

    Messages are JSON objects with a "type" field indicating the event type.
    Pass ``token`` as a query parameter for authentication.
    """
    from ontokit.api.utils.ws_auth import authenticate_ws

    project_id_str = str(project_id)

    if not await authenticate_ws(websocket, project_id, token):
        return

    await manager.connect(websocket, project_id_str)

    pubsub = None
    try:
        # Subscribe to Redis pubsub for lint updates
        pool = await get_arq_pool()
        pubsub = pool.pubsub()
        await pubsub.subscribe(LINT_UPDATES_CHANNEL)

        # Keep connection alive and forward relevant messages
        while True:
            # Check for Redis messages (non-blocking with short timeout)
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)
            if message and message["type"] == "message":
                try:
                    data = json.loads(message["data"])
                    # Only forward messages for this project
                    if data.get("project_id") == project_id_str:
                        await websocket.send_json(data)
                except json.JSONDecodeError:
                    pass

            # Check for WebSocket messages with timeout (keepalive/close)
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=0.1)
            except TimeoutError:
                # No message received, continue loop
                pass
            except WebSocketDisconnect:
                break

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.exception(f"WebSocket error for project {project_id_str}: {e}")
        with contextlib.suppress(Exception):
            await websocket.close(code=1011, reason="Internal server error")
    finally:
        manager.disconnect(websocket, project_id_str)
        if pubsub:
            with contextlib.suppress(Exception):
                await pubsub.unsubscribe(LINT_UPDATES_CHANNEL)
            # aclose() can hang on a half-open connection; bound it so a stuck
            # Redis socket does not leak the request task.
            with contextlib.suppress(Exception, TimeoutError):
                await asyncio.wait_for(
                    pubsub.aclose(),  # type: ignore[no-untyped-call]
                    timeout=5.0,
                )
