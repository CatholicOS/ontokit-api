"""Remote sync API endpoints for tracking external GitHub repository files."""

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from ontokit.core.auth import RequiredUser
from ontokit.core.database import get_db
from ontokit.schemas.remote_sync import (
    RemoteSyncConfigCreate,
    RemoteSyncConfigResponse,
    RemoteSyncConfigUpdate,
    SyncCheckResponse,
    SyncHistoryResponse,
    SyncJobStatusResponse,
)
from ontokit.services.remote_sync_service import get_remote_sync_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "/{project_id}/remote-sync",
    response_model=RemoteSyncConfigResponse | None,
)
async def get_remote_sync_config(
    project_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: RequiredUser,
) -> RemoteSyncConfigResponse | None:
    """Get remote sync configuration for a project.

    Returns null if no configuration exists.
    """
    service = get_remote_sync_service(db)
    return await service.get_config(project_id, user)


@router.put(
    "/{project_id}/remote-sync",
    response_model=RemoteSyncConfigResponse,
)
async def save_remote_sync_config(
    project_id: UUID,
    data: RemoteSyncConfigCreate | RemoteSyncConfigUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: RequiredUser,
) -> RemoteSyncConfigResponse:
    """Create or update remote sync configuration.

    Uses PUT/upsert semantics: creates if not exists, updates if exists.
    Requires owner or admin role.
    """
    service = get_remote_sync_service(db)
    return await service.save_config(project_id, data, user)


@router.delete(
    "/{project_id}/remote-sync",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_remote_sync_config(
    project_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: RequiredUser,
) -> None:
    """Remove remote sync configuration.

    Requires owner or admin role.
    """
    service = get_remote_sync_service(db)
    await service.delete_config(project_id, user)


@router.post(
    "/{project_id}/remote-sync/check",
    response_model=SyncCheckResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_remote_check(
    project_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: RequiredUser,
) -> SyncCheckResponse:
    """Trigger a manual remote sync check.

    Enqueues a background job to compare the remote file with the local ontology.
    Returns a job ID for status polling.
    Requires owner or admin role.
    """
    service = get_remote_sync_service(db)
    return await service.trigger_check(project_id, user)


@router.get(
    "/{project_id}/remote-sync/jobs/{job_id}",
    response_model=SyncJobStatusResponse,
)
async def get_remote_check_job_status(
    project_id: UUID,
    job_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: RequiredUser,
) -> SyncJobStatusResponse:
    """Get the status of a background remote check job."""
    service = get_remote_sync_service(db)
    return await service.get_job_status(project_id, job_id, user)


@router.get(
    "/{project_id}/remote-sync/history",
    response_model=SyncHistoryResponse,
)
async def get_remote_sync_history(
    project_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: RequiredUser,
    limit: int = Query(default=20, ge=1, le=100),
) -> SyncHistoryResponse:
    """Get sync event history for a project."""
    service = get_remote_sync_service(db)
    return await service.get_history(project_id, limit, user)
