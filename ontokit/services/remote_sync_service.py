"""Business logic for remote sync configuration and event management."""

import logging
from uuid import UUID

from arq.jobs import Job, JobStatus
from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ontokit.api.utils.redis import get_arq_pool
from ontokit.core.auth import CurrentUser
from ontokit.models.remote_sync import RemoteSyncConfig, SyncEvent
from ontokit.schemas.remote_sync import (
    RemoteSyncConfigCreate,
    RemoteSyncConfigResponse,
    RemoteSyncConfigUpdate,
    SyncCheckResponse,
    SyncEventResponse,
    SyncHistoryResponse,
    SyncJobStatusResponse,
)
from ontokit.services.project_service import get_project_service

logger = logging.getLogger(__name__)


class RemoteSyncService:
    """Service for managing remote sync configurations and events."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _verify_access(
        self,
        project_id: UUID,
        user: CurrentUser,
        require_admin: bool = False,
    ) -> str | None:
        """Verify user has access and return their role.

        Raises HTTPException if project not found or access denied.
        Returns user_role string.
        """
        service = get_project_service(self.db)
        project_response = await service.get(project_id, user)

        if (
            require_admin
            and project_response.user_role not in ("owner", "admin")
            and not user.is_superadmin
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin access required to manage remote sync configuration",
            )

        return project_response.user_role

    async def get_config(
        self, project_id: UUID, user: CurrentUser
    ) -> RemoteSyncConfigResponse | None:
        """Get remote sync configuration for a project.

        Returns None if no configuration exists.
        """
        await self._verify_access(project_id, user)

        result = await self.db.execute(
            select(RemoteSyncConfig).where(RemoteSyncConfig.project_id == project_id)
        )
        config = result.scalar_one_or_none()

        if not config:
            return None

        return RemoteSyncConfigResponse.model_validate(config)

    async def save_config(
        self,
        project_id: UUID,
        data: RemoteSyncConfigCreate | RemoteSyncConfigUpdate,
        user: CurrentUser,
    ) -> RemoteSyncConfigResponse:
        """Create or update remote sync configuration (PUT / upsert semantics)."""
        await self._verify_access(project_id, user, require_admin=True)

        result = await self.db.execute(
            select(RemoteSyncConfig).where(RemoteSyncConfig.project_id == project_id)
        )
        config = result.scalar_one_or_none()

        if config is None:
            # Create new config — require full payload
            if isinstance(data, RemoteSyncConfigUpdate):
                # Treat partial update on non-existent config as create with defaults
                config = RemoteSyncConfig(project_id=project_id)
                for field, value in data.model_dump(exclude_unset=True).items():
                    setattr(config, field, value)
            else:
                config = RemoteSyncConfig(
                    project_id=project_id,
                    **data.model_dump(),
                )
            self.db.add(config)
        else:
            # Update existing config
            update_data = data.model_dump(exclude_unset=True)
            for field, value in update_data.items():
                setattr(config, field, value)

        await self.db.commit()
        await self.db.refresh(config)

        return RemoteSyncConfigResponse.model_validate(config)

    async def delete_config(self, project_id: UUID, user: CurrentUser) -> None:
        """Delete remote sync configuration."""
        await self._verify_access(project_id, user, require_admin=True)

        result = await self.db.execute(
            select(RemoteSyncConfig).where(RemoteSyncConfig.project_id == project_id)
        )
        config = result.scalar_one_or_none()

        if not config:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Remote sync not configured for this project",
            )

        await self.db.delete(config)
        await self.db.commit()

    async def trigger_check(self, project_id: UUID, user: CurrentUser) -> SyncCheckResponse:
        """Trigger a manual remote sync check via background job."""
        await self._verify_access(project_id, user, require_admin=True)

        # Verify config exists
        result = await self.db.execute(
            select(RemoteSyncConfig).where(RemoteSyncConfig.project_id == project_id)
        )
        config = result.scalar_one_or_none()

        if not config:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Remote sync not configured for this project",
            )

        if config.status == "checking":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A remote check is already in progress",
            )

        # Update status to checking
        config.status = "checking"
        await self.db.commit()

        # Enqueue background job
        pool = await get_arq_pool()
        job = await pool.enqueue_job("run_remote_check_task", str(project_id))

        if job is None:
            config.status = "error"
            config.error_message = "Failed to enqueue check job"
            await self.db.commit()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to enqueue remote check job",
            )

        return SyncCheckResponse(
            message="Remote check has been queued",
            job_id=job.job_id,
            status="queued",
        )

    async def get_job_status(
        self, project_id: UUID, job_id: str, user: CurrentUser
    ) -> SyncJobStatusResponse:
        """Get the status of a background sync job."""
        await self._verify_access(project_id, user)

        pool = await get_arq_pool()
        job = Job(job_id, redis=pool)

        try:
            job_status = await job.status()
        except Exception:
            return SyncJobStatusResponse(
                job_id=job_id,
                status="not_found",
            )

        # Map ARQ JobStatus to our schema
        status_map: dict[JobStatus, str] = {
            JobStatus.deferred: "pending",
            JobStatus.queued: "pending",
            JobStatus.in_progress: "running",
            JobStatus.complete: "complete",
            JobStatus.not_found: "not_found",
        }
        mapped_status = status_map.get(job_status, "not_found")

        result_data: dict[str, object] | None = None
        error_msg: str | None = None

        if job_status == JobStatus.complete:
            try:
                info = await job.result_info()
                if info is not None:
                    if info.success:
                        result_data = info.result
                    else:
                        mapped_status = "failed"
                        error_msg = str(info.result) if info.result else None
            except Exception:
                pass

        return SyncJobStatusResponse(
            job_id=job_id,
            status=mapped_status,  # type: ignore[arg-type]
            result=result_data,
            error=error_msg,
        )

    async def get_history(
        self, project_id: UUID, limit: int, user: CurrentUser
    ) -> SyncHistoryResponse:
        """Get sync event history for a project."""
        await self._verify_access(project_id, user)

        # Get total count
        count_result = await self.db.execute(
            select(func.count(SyncEvent.id)).where(SyncEvent.project_id == project_id)
        )
        total = count_result.scalar() or 0

        # Get events
        result = await self.db.execute(
            select(SyncEvent)
            .where(SyncEvent.project_id == project_id)
            .order_by(SyncEvent.created_at.desc())
            .limit(limit)
        )
        events = result.scalars().all()

        return SyncHistoryResponse(
            items=[SyncEventResponse.model_validate(event) for event in events],
            total=total,
        )


def get_remote_sync_service(db: AsyncSession) -> RemoteSyncService:
    """Factory function for dependency injection."""
    return RemoteSyncService(db)
