"""Analytics API endpoints — entity history, project activity, contributors."""

import logging
from typing import Annotated
from urllib.parse import unquote
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ontokit.core.auth import CurrentUser, OptionalUser
from ontokit.core.database import get_db
from ontokit.schemas.analytics import (
    ContributorStats,
    EntityHistoryResponse,
    HotEntity,
    ProjectActivity,
)
from ontokit.services.change_event_service import ChangeEventService
from ontokit.services.project_service import get_project_service

logger = logging.getLogger(__name__)

router = APIRouter()


async def _verify_access(project_id: UUID, db: AsyncSession, user: CurrentUser | None) -> None:
    from fastapi import HTTPException

    service = get_project_service(db)
    try:
        await service.get(project_id, user)
    except HTTPException:
        raise


@router.get(
    "/{project_id}/analytics/activity",
    response_model=ProjectActivity,
)
async def get_project_activity(
    project_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: OptionalUser,
    days: int = Query(default=30, ge=1, le=365),
) -> ProjectActivity:
    """Get project activity over time."""
    await _verify_access(project_id, db, user)
    service = ChangeEventService(db)
    return await service.get_activity(project_id, days)


@router.get(
    "/{project_id}/analytics/entity/{iri:path}/history",
    response_model=EntityHistoryResponse,
)
async def get_entity_history(
    project_id: UUID,
    iri: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: OptionalUser,
    branch: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> EntityHistoryResponse:
    """Get change history for a specific entity."""
    await _verify_access(project_id, db, user)
    decoded_iri = unquote(iri)
    service = ChangeEventService(db)
    return await service.get_entity_history(project_id, decoded_iri, branch, limit)


@router.get(
    "/{project_id}/analytics/hot-entities",
    response_model=list[HotEntity],
)
async def get_hot_entities(
    project_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: OptionalUser,
    limit: int = Query(default=20, ge=1, le=100),
) -> list[HotEntity]:
    """Get most frequently edited entities in the last 30 days."""
    await _verify_access(project_id, db, user)
    service = ChangeEventService(db)
    return await service.get_hot_entities(project_id, limit)


@router.get(
    "/{project_id}/analytics/contributors",
    response_model=list[ContributorStats],
)
async def get_contributors(
    project_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: OptionalUser,
    days: int = Query(default=30, ge=1, le=365),
) -> list[ContributorStats]:
    """Get contributor statistics."""
    await _verify_access(project_id, db, user)
    service = ChangeEventService(db)
    return await service.get_contributors(project_id, days)
