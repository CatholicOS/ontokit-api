"""ARQ worker for background task processing."""

import json
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from arq import ArqRedis, cron
from arq.connections import RedisSettings
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ontokit.core.config import settings
from ontokit.core.encryption import decrypt_token
from ontokit.git.bare_repository import BareGitRepositoryService
from ontokit.models.lint import LintIssue, LintRun, LintRunStatus
from ontokit.models.project import Project
from ontokit.models.pull_request import GitHubIntegration
from ontokit.models.user_github_token import UserGitHubToken
from ontokit.services.github_sync import sync_github_project
from ontokit.services.linter import LintResult, get_linter
from ontokit.services.normalization_service import NormalizationService
from ontokit.services.ontology import get_ontology_service
from ontokit.services.storage import get_storage_service

# Redis pubsub channels for remote sync updates
REMOTE_SYNC_UPDATES_CHANNEL = "remote_sync:updates"

logger = logging.getLogger(__name__)

# Redis pubsub channels for updates
LINT_UPDATES_CHANNEL = "lint:updates"
NORMALIZATION_UPDATES_CHANNEL = "normalization:updates"


ONTOLOGY_INDEX_UPDATES_CHANNEL = "ontology_index:updates"


async def run_ontology_index_task(
    ctx: dict[str, Any],
    project_id: str,
    branch: str = "main",
    commit_hash: str | None = None,
) -> dict[str, Any]:
    """
    Background task to build/rebuild the PostgreSQL ontology index.

    Args:
        ctx: ARQ context with db session and services
        project_id: The project UUID to index
        branch: The branch to index
        commit_hash: The commit hash to record (if None, determined from git)

    Returns:
        Dict with entity_count and status
    """
    db: AsyncSession = ctx["db"]
    redis: ArqRedis = ctx["redis"]

    project_uuid = UUID(project_id)

    try:
        # Verify project exists
        result = await db.execute(select(Project).where(Project.id == project_uuid))
        project = result.scalar_one_or_none()

        if not project:
            raise ValueError(f"Project {project_id} not found")

        if not project.source_file_path:
            raise ValueError(f"Project {project_id} has no ontology file")

        logger.info("Starting ontology index for project %s branch %s", project_id, branch)

        # Notify start
        await redis.publish(
            ONTOLOGY_INDEX_UPDATES_CHANNEL,
            json.dumps({"type": "index_started", "project_id": project_id, "branch": branch}),
        )

        # Load ontology from git or storage
        import os

        storage = get_storage_service()
        ontology_service = get_ontology_service(storage)
        filename = getattr(project, "git_ontology_path", None) or os.path.basename(
            project.source_file_path
        )

        git_service = BareGitRepositoryService()
        if git_service.repository_exists(project_uuid):
            graph = await ontology_service.load_from_git(
                project_uuid, branch, filename, git_service
            )
            # Determine commit hash from git if not provided
            if commit_hash is None:
                try:
                    repo = git_service.get_repository(project_uuid)
                    commit_hash = repo.get_branch_commit_hash(branch)
                except Exception:
                    commit_hash = "unknown"
        else:
            graph = await ontology_service.load_from_storage(
                project_uuid, project.source_file_path, branch
            )
            if commit_hash is None:
                commit_hash = "storage"

        # Run indexing
        from ontokit.services.ontology_index import OntologyIndexService

        index_service = OntologyIndexService(db)
        entity_count = await index_service.full_reindex(project_uuid, branch, graph, commit_hash)

        # Notify completion
        await redis.publish(
            ONTOLOGY_INDEX_UPDATES_CHANNEL,
            json.dumps(
                {
                    "type": "index_complete",
                    "project_id": project_id,
                    "branch": branch,
                    "entity_count": entity_count,
                }
            ),
        )

        return {
            "entity_count": entity_count,
            "status": "completed",
            "commit_hash": commit_hash,
        }

    except Exception as e:
        logger.exception(
            "Ontology index failed for project %s branch %s: %s",
            project_id,
            branch,
            e,
        )

        # Notify failure
        await redis.publish(
            ONTOLOGY_INDEX_UPDATES_CHANNEL,
            json.dumps(
                {
                    "type": "index_failed",
                    "project_id": project_id,
                    "branch": branch,
                    "error": str(e),
                }
            ),
        )

        raise


async def run_lint_task(
    ctx: dict[str, Any],
    project_id: str,
) -> dict[str, Any]:
    """
    Background task to lint an ontology project.

    Args:
        ctx: ARQ context with db session and services
        project_id: The project UUID to lint

    Returns:
        Dict with run_id and issues_found
    """
    db: AsyncSession = ctx["db"]
    redis: ArqRedis = ctx["redis"]

    project_uuid = UUID(project_id)
    run: LintRun | None = None

    try:
        # Verify project exists and get its details
        result = await db.execute(select(Project).where(Project.id == project_uuid))
        project = result.scalar_one_or_none()

        if not project:
            raise ValueError(f"Project {project_id} not found")

        if not project.source_file_path:
            raise ValueError(f"Project {project_id} has no ontology file")

        # Create lint run record
        run = LintRun(
            project_id=project_uuid,
            status=LintRunStatus.RUNNING.value,
        )
        db.add(run)
        await db.commit()
        await db.refresh(run)

        run_id = run.id
        logger.info(f"Started lint run {run_id} for project {project_id}")

        # Notify via pubsub that lint has started
        await redis.publish(
            LINT_UPDATES_CHANNEL,
            f'{{"type": "lint_started", "project_id": "{project_id}", "run_id": "{run_id}"}}',
        )

        # Load ontology from storage
        storage = get_storage_service()
        ontology_service = get_ontology_service(storage)

        graph = await ontology_service.load_from_storage(
            project_uuid,
            project.source_file_path,
        )

        # Run linting
        linter = get_linter()
        lint_results: list[LintResult] = await linter.lint(graph, project_uuid)

        # Save issues to database
        for lint_result in lint_results:
            issue = LintIssue(
                run_id=run_id,
                project_id=project_uuid,
                issue_type=lint_result.issue_type,
                rule_id=lint_result.rule_id,
                message=lint_result.message,
                subject_iri=lint_result.subject_iri,
                details=lint_result.details,
            )
            db.add(issue)

        # Update run status
        run.status = LintRunStatus.COMPLETED.value
        run.completed_at = datetime.now(UTC)
        run.issues_found = len(lint_results)

        await db.commit()

        logger.info(
            f"Completed lint run {run_id} for project {project_id}: "
            f"found {len(lint_results)} issues"
        )

        # Notify via pubsub that lint is complete
        await redis.publish(
            LINT_UPDATES_CHANNEL,
            f'{{"type": "lint_complete", "project_id": "{project_id}", '
            f'"run_id": "{run_id}", "issues_found": {len(lint_results)}}}',
        )

        return {
            "run_id": str(run_id),
            "issues_found": len(lint_results),
            "status": "completed",
        }

    except Exception as e:
        logger.exception(f"Lint run failed for project {project_id}: {e}")

        # Update run status to failed
        if run:
            run.status = LintRunStatus.FAILED.value
            run.completed_at = datetime.now(UTC)
            run.error_message = str(e)
            await db.commit()

            # Notify via pubsub that lint failed
            await redis.publish(
                LINT_UPDATES_CHANNEL,
                f'{{"type": "lint_failed", "project_id": "{project_id}", '
                f'"run_id": "{run.id}", "error": "{str(e)}"}}',
            )

        raise


async def check_normalization_status_task(
    ctx: dict[str, Any],
    project_id: str,
) -> dict[str, Any]:
    """
    Background task to check if a project needs normalization.

    Args:
        ctx: ARQ context with db session and services
        project_id: The project UUID to check

    Returns:
        Dict with needs_normalization status
    """
    db: AsyncSession = ctx["db"]
    redis: ArqRedis = ctx["redis"]

    project_uuid = UUID(project_id)

    try:
        # Verify project exists
        result = await db.execute(select(Project).where(Project.id == project_uuid))
        project = result.scalar_one_or_none()

        if not project:
            logger.warning(f"Project {project_id} not found for normalization check")
            return {"needs_normalization": False, "error": "Project not found"}

        if not project.source_file_path:
            return {"needs_normalization": False, "error": "No ontology file"}

        # Check normalization status
        storage = get_storage_service()
        norm_service = NormalizationService(db, storage)

        status = await norm_service.check_normalization_status(project)

        # Publish status update via Redis
        await redis.publish(
            NORMALIZATION_UPDATES_CHANNEL,
            f'{{"type": "normalization_status", "project_id": "{project_id}", '
            f'"needs_normalization": {str(status["needs_normalization"]).lower()}}}',
        )

        logger.info(
            f"Normalization check for project {project_id}: "
            f"needs_normalization={status['needs_normalization']}"
        )

        return {
            "project_id": project_id,
            "needs_normalization": status["needs_normalization"],
            "last_run": str(status["last_run"]) if status["last_run"] else None,
            "error": status.get("error"),
        }

    except Exception as e:
        logger.exception(f"Normalization check failed for project {project_id}: {e}")
        return {
            "project_id": project_id,
            "needs_normalization": False,
            "error": str(e),
        }


async def run_normalization_task(
    ctx: dict[str, Any],
    project_id: str,
    user_id: str | None = None,
    user_name: str | None = None,
    user_email: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Background task to run normalization with canonical bnode identifiers.

    This is the expensive operation that creates deterministic bnode IDs
    using SHA-256 hashing. It should be run as a background task for large
    ontologies.

    Args:
        ctx: ARQ context with db session and services
        project_id: The project UUID to normalize
        user_id: ID of the user who triggered normalization
        user_name: Name of the user (for commit author)
        user_email: Email of the user (for commit author)
        dry_run: If True, don't commit changes

    Returns:
        Dict with run_id and status
    """
    db: AsyncSession = ctx["db"]
    redis: ArqRedis = ctx["redis"]

    project_uuid = UUID(project_id)

    try:
        # Notify start
        await redis.publish(
            NORMALIZATION_UPDATES_CHANNEL,
            f'{{"type": "normalization_started", "project_id": "{project_id}", '
            f'"dry_run": {str(dry_run).lower()}}}',
        )

        # Get project
        result = await db.execute(select(Project).where(Project.id == project_uuid))
        project = result.scalar_one_or_none()

        if not project:
            raise ValueError(f"Project {project_id} not found")

        if not project.source_file_path:
            raise ValueError(f"Project {project_id} has no ontology file")

        # Create mock user for the service
        class MockUser:
            def __init__(self, uid: str | None, name: str | None, email: str | None):
                self.id = uid
                self.name = name or "OntoKit System"
                self.email = email or "system@ontokit.dev"

        user = MockUser(user_id, user_name, user_email) if user_id else None

        # Run normalization
        storage = get_storage_service()
        norm_service = NormalizationService(db, storage)

        run, original_content, normalized_content = await norm_service.run_normalization(
            project=project,
            user=user,  # type: ignore[arg-type]
            trigger_type="manual",
            dry_run=dry_run,
        )

        logger.info(
            f"Normalization {'preview' if dry_run else 'run'} completed for project {project_id}, "
            f"run_id={run.id}"
        )

        # Notify completion
        await redis.publish(
            NORMALIZATION_UPDATES_CHANNEL,
            f'{{"type": "normalization_complete", "project_id": "{project_id}", '
            f'"run_id": "{run.id}", "dry_run": {str(dry_run).lower()}, '
            f'"commit_hash": "{run.commit_hash or ""}"}}',
        )

        return {
            "project_id": project_id,
            "run_id": str(run.id),
            "dry_run": dry_run,
            "commit_hash": run.commit_hash,
            "status": "completed",
        }

    except Exception as e:
        logger.exception(f"Normalization failed for project {project_id}: {e}")

        # Notify failure
        await redis.publish(
            NORMALIZATION_UPDATES_CHANNEL,
            f'{{"type": "normalization_failed", "project_id": "{project_id}", '
            f'"error": "{str(e)}"}}',
        )

        return {
            "project_id": project_id,
            "error": str(e),
            "status": "failed",
        }


async def check_all_projects_normalization(ctx: dict[str, Any]) -> dict[str, Any]:
    """
    Cron task to check all projects for normalization needs.

    This runs periodically and publishes updates for any projects
    that need normalization.
    """
    db: AsyncSession = ctx["db"]
    redis: ArqRedis = ctx["redis"]

    try:
        # Get all projects with ontology files
        result = await db.execute(select(Project).where(Project.source_file_path.isnot(None)))
        projects = result.scalars().all()

        storage = get_storage_service()
        norm_service = NormalizationService(db, storage)

        projects_needing_normalization = []

        for project in projects:
            try:
                status = await norm_service.check_normalization_status(project)
                if status["needs_normalization"]:
                    projects_needing_normalization.append(str(project.id))

                    # Publish status update
                    await redis.publish(
                        NORMALIZATION_UPDATES_CHANNEL,
                        f'{{"type": "normalization_status", "project_id": "{project.id}", '
                        f'"needs_normalization": true}}',
                    )
            except Exception as e:
                logger.warning(f"Failed to check normalization for project {project.id}: {e}")

        logger.info(
            f"Normalization check complete: {len(projects_needing_normalization)} of "
            f"{len(projects)} projects need normalization"
        )

        return {
            "total_projects": len(projects),
            "projects_needing_normalization": len(projects_needing_normalization),
            "project_ids": projects_needing_normalization,
        }

    except Exception as e:
        logger.exception(f"All projects normalization check failed: {e}")
        raise


async def auto_submit_stale_suggestions(ctx: dict[str, Any]) -> dict[str, Any]:
    """Auto-create PRs for abandoned suggestion sessions (inactive 30+ min)."""
    db: AsyncSession = ctx["db"]

    try:
        from ontokit.services.suggestion_service import SuggestionService

        service = SuggestionService(db)
        count = await service.auto_submit_stale_sessions()

        logger.info(f"Auto-submit complete: {count} stale suggestion sessions submitted")
        return {"auto_submitted": count}

    except Exception as e:
        logger.exception(f"Auto-submit stale suggestions failed: {e}")
        raise


async def run_embedding_generation_task(
    ctx: dict[str, Any],
    project_id: str,
    branch: str,
    job_id: str,
) -> dict[str, Any]:
    """Background task to generate embeddings for an entire project."""
    db: AsyncSession = ctx["db"]

    try:
        from ontokit.services.embedding_service import EmbeddingService

        service = EmbeddingService(db)
        await service.embed_project(UUID(project_id), branch, UUID(job_id))

        logger.info(f"Embedding generation completed for project {project_id} branch {branch}")
        return {"project_id": project_id, "branch": branch, "job_id": job_id, "status": "completed"}

    except Exception as e:
        logger.exception(f"Embedding generation failed for project {project_id}: {e}")
        raise


async def run_single_entity_embed_task(
    ctx: dict[str, Any],
    project_id: str,
    branch: str,
    entity_iri: str,
) -> dict[str, Any]:
    """Background task to re-embed a single entity."""
    db: AsyncSession = ctx["db"]

    try:
        from ontokit.services.embedding_service import EmbeddingService

        service = EmbeddingService(db)
        await service.embed_single_entity(UUID(project_id), branch, entity_iri)

        logger.info(f"Re-embedded entity {entity_iri} for project {project_id}")
        return {"project_id": project_id, "entity_iri": entity_iri, "status": "completed"}

    except Exception as e:
        logger.exception(f"Single entity embed failed for {entity_iri}: {e}")
        raise


async def run_batch_entity_embed_task(
    ctx: dict[str, Any],
    project_id: str,
    branch: str,
    entity_iris: list[str],
) -> dict[str, Any]:
    """Background task to re-embed a batch of entities."""
    db: AsyncSession = ctx["db"]

    try:
        from ontokit.services.embedding_service import EmbeddingService

        service = EmbeddingService(db)
        for entity_iri in entity_iris:
            await service.embed_single_entity(UUID(project_id), branch, entity_iri)

        logger.info(f"Re-embedded {len(entity_iris)} entities for project {project_id}")
        return {
            "project_id": project_id,
            "entity_count": len(entity_iris),
            "status": "completed",
        }

    except Exception as e:
        logger.exception(f"Batch entity embed failed for project {project_id}: {e}")
        raise


async def sync_github_projects(ctx: dict[str, Any]) -> dict[str, Any]:
    """Periodic task: pull from remote + push local commits for all GitHub-connected projects."""
    db: AsyncSession = ctx["db"]

    try:
        # Get all integrations with sync_enabled=True and sync_status != "conflict"
        result = await db.execute(
            select(GitHubIntegration).where(
                GitHubIntegration.sync_enabled == True,  # noqa: E712
                GitHubIntegration.sync_status != "conflict",
            )
        )
        integrations = result.scalars().all()

        git_service = BareGitRepositoryService()
        synced = 0
        errors = 0

        for integration in integrations:
            # Resolve PAT from connected_by_user_id
            if not integration.connected_by_user_id:
                logger.debug(
                    f"Skipping sync for project {integration.project_id}: no connected_by_user_id"
                )
                continue

            token_result = await db.execute(
                select(UserGitHubToken).where(
                    UserGitHubToken.user_id == integration.connected_by_user_id
                )
            )
            token_row = token_result.scalar_one_or_none()
            if not token_row:
                logger.warning(
                    f"Skipping sync for project {integration.project_id}: "
                    f"no GitHub token for user {integration.connected_by_user_id}"
                )
                continue

            try:
                pat = decrypt_token(token_row.encrypted_token)
            except Exception:
                logger.warning(
                    f"Skipping sync for project {integration.project_id}: failed to decrypt token"
                )
                continue

            try:
                sync_result = await sync_github_project(integration, pat, git_service, db)
                logger.info(f"Synced project {integration.project_id}: {sync_result}")
                synced += 1
            except Exception as e:
                logger.exception(f"Failed to sync project {integration.project_id}: {e}")
                errors += 1

        logger.info(
            f"GitHub sync complete: {synced} synced, {errors} errors, {len(integrations)} total"
        )

        return {
            "total": len(integrations),
            "synced": synced,
            "errors": errors,
        }

    except Exception as e:
        logger.exception(f"GitHub sync cron job failed: {e}")
        raise


async def run_remote_check_task(
    ctx: dict[str, Any],
    project_id: str,
) -> dict[str, Any]:
    """
    Background task to check a remote GitHub repository for changes.

    Compares the remote file content with the current project ontology
    and records a SyncEvent with the outcome.
    """
    db: AsyncSession = ctx["db"]
    redis: ArqRedis = ctx["redis"]

    project_uuid = UUID(project_id)

    try:
        from ontokit.models.remote_sync import RemoteSyncConfig, SyncEvent
        from ontokit.services.github_service import get_github_service

        # Get sync config
        config_result = await db.execute(
            select(RemoteSyncConfig).where(RemoteSyncConfig.project_id == project_uuid)
        )
        config = config_result.scalar_one_or_none()

        if not config:
            return {"status": "failed", "error": "Remote sync not configured"}

        # Get project
        project_result = await db.execute(select(Project).where(Project.id == project_uuid))
        project = project_result.scalar_one_or_none()

        if not project:
            return {"status": "failed", "error": "Project not found"}

        # Notify start
        await redis.publish(
            REMOTE_SYNC_UPDATES_CHANNEL,
            f'{{"type": "remote_check_started", "project_id": "{project_id}"}}',
        )

        # Get a GitHub token — try the project's connected user first
        token: str | None = None
        integration_result = await db.execute(
            select(GitHubIntegration).where(GitHubIntegration.project_id == project_uuid)
        )
        integration = integration_result.scalar_one_or_none()

        if integration and integration.connected_by_user_id:
            token_result = await db.execute(
                select(UserGitHubToken).where(
                    UserGitHubToken.user_id == integration.connected_by_user_id
                )
            )
            token_row = token_result.scalar_one_or_none()
            if token_row:
                token = decrypt_token(token_row.encrypted_token)

        if not token:
            config.status = "error"
            config.error_message = "No GitHub token available for remote check"
            event = SyncEvent(
                project_id=project_uuid,
                config_id=config.id,
                event_type="error",
                error_message="No GitHub token available",
            )
            db.add(event)
            await db.commit()
            return {"status": "failed", "error": "No GitHub token available"}

        # Fetch remote file content
        github_service = get_github_service()
        remote_content = await github_service.get_file_content(
            token=token,
            owner=config.repo_owner,
            repo=config.repo_name,
            path=config.file_path,
            ref=config.branch,
        )

        # Load current project ontology content for comparison
        storage = get_storage_service()
        current_content: bytes | None = None
        if project.source_file_path:
            try:
                # Strip bucket prefix if present
                parts = project.source_file_path.split("/", 1)
                if len(parts) == 2 and parts[0] == storage.bucket:
                    object_name = parts[1]
                else:
                    object_name = project.source_file_path
                current_content = await storage.download_file(object_name)
            except Exception:
                logger.warning(f"Could not load current ontology for project {project_id}")

        # Compare contents
        has_changes = current_content is None or remote_content != current_content

        if has_changes:
            event_type = "update_found"
            config.status = "update_available"
            changes_summary = "Remote file differs from local ontology"
        else:
            event_type = "check_no_changes"
            config.status = "up_to_date"
            changes_summary = None

        config.last_check_at = datetime.now(UTC)
        config.error_message = None

        event = SyncEvent(
            project_id=project_uuid,
            config_id=config.id,
            event_type=event_type,
            changes_summary=changes_summary,
        )
        db.add(event)
        await db.commit()

        logger.info(
            f"Remote check for project {project_id}: "
            f"{'changes found' if has_changes else 'up to date'}"
        )

        # Notify completion
        await redis.publish(
            REMOTE_SYNC_UPDATES_CHANNEL,
            f'{{"type": "remote_check_complete", "project_id": "{project_id}", '
            f'"has_changes": {str(has_changes).lower()}}}',
        )

        return {
            "project_id": project_id,
            "status": "completed",
            "has_changes": has_changes,
            "event_type": event_type,
        }

    except Exception as e:
        logger.exception(f"Remote check failed for project {project_id}: {e}")

        # Record error event
        try:
            err_result = await db.execute(
                select(RemoteSyncConfig).where(RemoteSyncConfig.project_id == project_uuid)
            )
            config = err_result.scalar_one_or_none()
            if config:
                config.status = "error"
                config.error_message = str(e)
                event = SyncEvent(
                    project_id=project_uuid,
                    config_id=config.id,
                    event_type="error",
                    error_message=str(e),
                )
                db.add(event)
                await db.commit()
        except Exception:
            logger.exception("Failed to record remote check error event")

        # Notify failure
        await redis.publish(
            REMOTE_SYNC_UPDATES_CHANNEL,
            f'{{"type": "remote_check_failed", "project_id": "{project_id}", "error": "{str(e)}"}}',
        )

        raise


async def startup(ctx: dict[str, Any]) -> None:
    """Initialize worker context on startup."""
    logger.info("Starting ARQ worker...")

    # Create database engine and session factory
    engine = create_async_engine(
        str(settings.database_url),
        echo=settings.debug,
        pool_pre_ping=True,
    )
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    # Store in context
    ctx["engine"] = engine
    ctx["session_factory"] = session_factory

    logger.info("ARQ worker started successfully")


async def shutdown(ctx: dict[str, Any]) -> None:
    """Cleanup worker context on shutdown."""
    logger.info("Shutting down ARQ worker...")

    # Close database engine
    engine = ctx.get("engine")
    if engine:
        await engine.dispose()

    logger.info("ARQ worker shut down successfully")


async def on_job_start(ctx: dict[str, Any]) -> None:
    """Called before each job starts. Creates a new database session."""
    session_factory = ctx["session_factory"]
    ctx["db"] = session_factory()


async def on_job_end(ctx: dict[str, Any]) -> None:
    """Called after each job ends. Closes the database session."""
    db = ctx.get("db")
    if db:
        await db.close()


def get_redis_settings() -> RedisSettings:
    """Get Redis settings from application config."""
    # Parse Redis URL
    redis_url = str(settings.redis_url)
    # RedisSettings expects host, port, database separately
    # URL format: redis://host:port/db

    from urllib.parse import urlparse

    parsed = urlparse(redis_url)
    host = parsed.hostname or "localhost"
    port = parsed.port or 6379
    database = int(parsed.path.lstrip("/") or "0")

    return RedisSettings(
        host=host,
        port=port,
        database=database,
    )


class WorkerSettings:
    """ARQ worker settings."""

    functions = [
        run_ontology_index_task,
        run_lint_task,
        check_normalization_status_task,
        run_normalization_task,
        check_all_projects_normalization,
        sync_github_projects,
        auto_submit_stale_suggestions,
        run_embedding_generation_task,
        run_single_entity_embed_task,
        run_batch_entity_embed_task,
        run_remote_check_task,
    ]
    redis_settings = get_redis_settings()

    on_startup = startup
    on_shutdown = shutdown
    on_job_start = on_job_start
    on_job_end = on_job_end

    # Cron jobs
    cron_jobs = [
        # Normalization check every hour
        cron(check_all_projects_normalization, hour=None, minute=0),
        # GitHub sync every 5 minutes
        cron(
            sync_github_projects,
            hour=None,
            minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55},
        ),
        # Auto-submit stale suggestion sessions every 10 minutes
        cron(
            auto_submit_stale_suggestions,
            hour=None,
            minute={5, 15, 25, 35, 45, 55},
        ),
    ]

    # Job settings
    max_jobs = 10
    job_timeout = 300  # 5 minutes
    keep_result = 3600  # 1 hour
    poll_delay = 0.5

    # Queue name
    queue_name = "arq:queue"
