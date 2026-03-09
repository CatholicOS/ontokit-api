"""Normalization API endpoints."""

import json
from datetime import datetime
from typing import Annotated
from uuid import UUID

from arq.jobs import Job, JobStatus
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ontokit.api.utils.redis import get_arq_pool
from ontokit.core.auth import OptionalUser, RequiredUser
from ontokit.core.database import get_db
from ontokit.schemas.project import NormalizationReportResponse
from ontokit.services.normalization_service import NormalizationService, get_normalization_service
from ontokit.services.project_service import ProjectService, get_project_service
from ontokit.services.storage import StorageService, get_storage_service

router = APIRouter()


# Response schemas
class NormalizationStatusResponse(BaseModel):
    """Status of normalization for a project."""

    needs_normalization: bool | None = None  # None means status unknown
    last_run: datetime | None = None
    last_run_id: str | None = None
    last_check: datetime | None = None
    preview_report: NormalizationReportResponse | None = None
    checking: bool = False  # True if a background check is in progress
    error: str | None = None


class RefreshStatusResponse(BaseModel):
    """Response when triggering a status refresh."""

    message: str
    job_id: str | None = None


class JobStatusResponse(BaseModel):
    """Status of a background job."""

    job_id: str
    status: str  # "pending", "running", "complete", "failed", "not_found"
    result: dict[str, object] | None = None
    error: str | None = None


class QueuedJobResponse(BaseModel):
    """Response when queuing a background job."""

    message: str
    job_id: str
    status: str = "queued"


class NormalizationRunResponse(BaseModel):
    """Response for a normalization run."""

    id: str
    project_id: str
    created_at: datetime
    triggered_by: str | None = None
    trigger_type: str
    report: NormalizationReportResponse
    is_dry_run: bool
    commit_hash: str | None = None
    # For dry runs, include content for diff preview
    original_content: str | None = None
    normalized_content: str | None = None


class NormalizationHistoryResponse(BaseModel):
    """List of normalization runs."""

    items: list[NormalizationRunResponse]
    total: int


class NormalizationTriggerRequest(BaseModel):
    """Request to trigger normalization."""

    dry_run: bool = False


# Dependencies
def get_storage() -> StorageService:
    """Dependency to get storage service."""
    return get_storage_service()


def get_service(db: Annotated[AsyncSession, Depends(get_db)]) -> ProjectService:
    """Dependency to get project service."""
    return get_project_service(db)


def get_norm_service(
    db: Annotated[AsyncSession, Depends(get_db)],
    storage: Annotated[StorageService, Depends(get_storage)],
) -> NormalizationService:
    """Dependency to get normalization service."""
    return get_normalization_service(db, storage)


# Endpoints
@router.get("/{project_id}/normalization/status", response_model=NormalizationStatusResponse)
async def get_normalization_status(
    project_id: UUID,
    project_service: Annotated[ProjectService, Depends(get_service)],
    norm_service: Annotated[NormalizationService, Depends(get_norm_service)],
    user: OptionalUser,
) -> NormalizationStatusResponse:
    """
    Get cached normalization status for a project.

    This returns the cached status from the database without running
    an expensive check. Use POST /normalization/refresh to trigger
    a background check if status is unknown or stale.

    Returns:
    - needs_normalization: True/False if known, None if never checked
    - last_run: When normalization was last applied
    - last_check: When status was last checked
    - checking: True if a background check is in progress
    """
    # Check access (validates user has permission to view this project)
    await project_service.get(project_id, user)

    # Get project model for the service
    db_project = await project_service._get_project(project_id)

    # Use cached status (fast, no expensive check)
    status_data = await norm_service.get_cached_status(db_project)

    return NormalizationStatusResponse(
        needs_normalization=status_data["needs_normalization"],
        last_run=status_data["last_run"],
        last_run_id=status_data.get("last_run_id"),
        last_check=status_data.get("last_check"),
        preview_report=(
            NormalizationReportResponse(**status_data["preview_report"])
            if status_data.get("preview_report")
            else None
        ),
        checking=status_data.get("checking", False),
        error=status_data.get("error"),
    )


@router.post("/{project_id}/normalization/refresh", response_model=RefreshStatusResponse)
async def refresh_normalization_status(
    project_id: UUID,
    project_service: Annotated[ProjectService, Depends(get_service)],
    user: OptionalUser,
) -> RefreshStatusResponse:
    """
    Trigger a background job to check normalization status.

    This queues an async job that downloads and parses the ontology
    to determine if normalization is needed. Results will be available
    via the GET /normalization/status endpoint once complete.
    """
    # Check access
    await project_service.get(project_id, user)

    # Queue background job
    pool = await get_arq_pool()
    job = await pool.enqueue_job(
        "check_normalization_status_task",
        str(project_id),
    )

    return RefreshStatusResponse(
        message="Normalization status check queued",
        job_id=job.job_id if job else None,
    )


@router.post("/{project_id}/normalization/queue", response_model=QueuedJobResponse)
async def queue_normalization(
    project_id: UUID,
    request: NormalizationTriggerRequest,
    project_service: Annotated[ProjectService, Depends(get_service)],
    user: RequiredUser,
) -> QueuedJobResponse:
    """
    Queue normalization as a background job.

    For large ontologies, use this instead of POST /normalization to avoid
    request timeouts. The canonical bnode hashing can take a long time for
    large graphs.

    Poll GET /normalization/jobs/{job_id} for status updates.

    Requires editor role or higher.
    """
    # Check access
    project = await project_service.get(project_id, user)

    if project.user_role not in ("owner", "admin", "editor"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Must be an editor or higher to run normalization",
        )

    if not project.source_file_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Project has no ontology file",
        )

    # Queue background job
    pool = await get_arq_pool()
    job = await pool.enqueue_job(
        "run_normalization_task",
        str(project_id),
        user.id,
        user.name,
        user.email,
        request.dry_run,
    )

    if not job:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to queue normalization job",
        )

    return QueuedJobResponse(
        message="Normalization job queued",
        job_id=job.job_id,
        status="queued",
    )


@router.get("/{project_id}/normalization/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(
    project_id: UUID,
    job_id: str,
    project_service: Annotated[ProjectService, Depends(get_service)],
    user: OptionalUser,
) -> JobStatusResponse:
    """
    Get the status of a normalization background job.

    Returns the job status and result if complete.
    """
    # Check access
    await project_service.get(project_id, user)

    pool = await get_arq_pool()

    # Create Job instance to query status
    job = Job(job_id, redis=pool)
    job_status = await job.status()

    # Map ARQ JobStatus enum to our status strings
    status_map = {
        JobStatus.deferred: "pending",
        JobStatus.queued: "pending",
        JobStatus.in_progress: "running",
        JobStatus.complete: "complete",
        JobStatus.not_found: "not_found",
    }

    mapped_status = status_map.get(job_status, "not_found")

    # Handle not found case
    if mapped_status == "not_found":
        return JobStatusResponse(
            job_id=job_id,
            status="not_found",
            error="Job not found or expired",
        )

    # Only try to get result if job is complete
    result = None
    if mapped_status == "complete":
        try:
            result = await job.result(poll_delay=0, timeout=0)
        except TimeoutError:
            # Job result not yet available (shouldn't happen if status is complete)
            pass
        except Exception:
            # Job might have failed or result expired
            pass

    return JobStatusResponse(
        job_id=job_id,
        status=mapped_status,
        result=result if isinstance(result, dict) else None,
        error=result.get("error") if isinstance(result, dict) and "error" in result else None,
    )


@router.get("/{project_id}/normalization/jobs", response_model=list[JobStatusResponse])
async def list_recent_jobs(
    project_id: UUID,
    project_service: Annotated[ProjectService, Depends(get_service)],
    user: OptionalUser,
) -> list[JobStatusResponse]:
    """
    List recent normalization jobs for a project.

    Note: ARQ doesn't provide easy job listing, so this returns jobs
    from the normalization_runs table that were triggered recently.
    """
    # Check access
    await project_service.get(project_id, user)

    # For now, return empty list - ARQ doesn't have built-in job listing
    # Jobs are tracked via the normalization_runs table instead
    return []


@router.post("/{project_id}/normalization", response_model=NormalizationRunResponse)
async def run_normalization(
    project_id: UUID,
    request: NormalizationTriggerRequest,
    project_service: Annotated[ProjectService, Depends(get_service)],
    norm_service: Annotated[NormalizationService, Depends(get_norm_service)],
    user: RequiredUser,
) -> NormalizationRunResponse:
    """
    Trigger normalization of a project's ontology.

    Normalizes the ontology to canonical Turtle format and commits the changes.
    Use dry_run=true to preview changes without committing.

    Requires editor role or higher.
    """
    # Check access
    project = await project_service.get(project_id, user)

    if project.user_role not in ("owner", "admin", "editor"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Must be an editor or higher to run normalization",
        )

    if not project.source_file_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Project has no ontology file",
        )

    # Get project model for the service
    db_project = await project_service._get_project(project_id)

    try:
        run, original_content, normalized_content = await norm_service.run_normalization(
            project=db_project,
            user=user,
            trigger_type="manual",
            dry_run=request.dry_run,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Normalization failed: {e}",
        ) from e

    report_data = json.loads(run.report_json)

    return NormalizationRunResponse(
        id=str(run.id),
        project_id=str(run.project_id),
        created_at=run.created_at,
        triggered_by=run.triggered_by,
        trigger_type=run.trigger_type,
        report=NormalizationReportResponse(**report_data),
        is_dry_run=run.is_dry_run,
        commit_hash=run.commit_hash,
        original_content=original_content,
        normalized_content=normalized_content,
    )


@router.get("/{project_id}/normalization/history", response_model=NormalizationHistoryResponse)
async def get_normalization_history(
    project_id: UUID,
    project_service: Annotated[ProjectService, Depends(get_service)],
    norm_service: Annotated[NormalizationService, Depends(get_norm_service)],
    user: OptionalUser,
    limit: int = Query(default=10, ge=1, le=50),
    include_dry_runs: bool = Query(default=False),
) -> NormalizationHistoryResponse:
    """
    Get the normalization run history for a project.

    Returns a list of past normalization runs with their reports.
    """
    # Check access
    await project_service.get(project_id, user)

    runs = await norm_service.get_normalization_history(
        project_id, limit=limit, include_dry_runs=include_dry_runs
    )

    items = []
    for run in runs:
        report_data = json.loads(run.report_json)
        items.append(
            NormalizationRunResponse(
                id=str(run.id),
                project_id=str(run.project_id),
                created_at=run.created_at,
                triggered_by=run.triggered_by,
                trigger_type=run.trigger_type,
                report=NormalizationReportResponse(**report_data),
                is_dry_run=run.is_dry_run,
                commit_hash=run.commit_hash,
            )
        )

    return NormalizationHistoryResponse(items=items, total=len(items))


@router.get(
    "/{project_id}/normalization/runs/{run_id}",
    response_model=NormalizationRunResponse,
)
async def get_normalization_run(
    project_id: UUID,
    run_id: UUID,
    project_service: Annotated[ProjectService, Depends(get_service)],
    norm_service: Annotated[NormalizationService, Depends(get_norm_service)],
    user: OptionalUser,
) -> NormalizationRunResponse:
    """Get details of a specific normalization run."""
    # Check access
    await project_service.get(project_id, user)

    run = await norm_service.get_normalization_run(project_id, run_id)
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Normalization run not found",
        )

    report_data = json.loads(run.report_json)

    return NormalizationRunResponse(
        id=str(run.id),
        project_id=str(run.project_id),
        created_at=run.created_at,
        triggered_by=run.triggered_by,
        trigger_type=run.trigger_type,
        report=NormalizationReportResponse(**report_data),
        is_dry_run=run.is_dry_run,
        commit_hash=run.commit_hash,
    )
