"""Join request management endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import RequiredUser
from app.core.database import get_db
from app.schemas.join_request import (
    JoinRequestAction,
    JoinRequestCreate,
    JoinRequestListResponse,
    JoinRequestResponse,
    MyJoinRequestResponse,
    PendingJoinRequestsSummary,
)
from app.services.join_request_service import JoinRequestService, get_join_request_service

router = APIRouter()


def get_service(db: Annotated[AsyncSession, Depends(get_db)]) -> JoinRequestService:
    """Dependency to get join request service with database session."""
    return get_join_request_service(db)


@router.get(
    "/join-requests/pending-summary",
    response_model=PendingJoinRequestsSummary,
)
async def get_pending_summary(
    service: Annotated[JoinRequestService, Depends(get_service)],
    user: RequiredUser,
) -> PendingJoinRequestsSummary:
    """Get a summary of pending join requests across all projects the user manages."""
    return await service.get_pending_summary(user)


@router.post(
    "/{project_id}/join-requests",
    response_model=JoinRequestResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_join_request(
    project_id: UUID,
    data: JoinRequestCreate,
    service: Annotated[JoinRequestService, Depends(get_service)],
    user: RequiredUser,
) -> JoinRequestResponse:
    """Submit a request to join a public project."""
    return await service.create_request(project_id, data, user)


@router.get(
    "/{project_id}/join-requests/mine",
    response_model=MyJoinRequestResponse,
)
async def get_my_join_request(
    project_id: UUID,
    service: Annotated[JoinRequestService, Depends(get_service)],
    user: RequiredUser,
) -> MyJoinRequestResponse:
    """Check the current user's join request status for a project."""
    return await service.get_my_request(project_id, user)


@router.get(
    "/{project_id}/join-requests",
    response_model=JoinRequestListResponse,
)
async def list_join_requests(
    project_id: UUID,
    service: Annotated[JoinRequestService, Depends(get_service)],
    user: RequiredUser,
    status_filter: str | None = Query(default=None, alias="status", description="Filter by status"),
) -> JoinRequestListResponse:
    """List join requests for a project (admin/owner only)."""
    return await service.list_requests(project_id, user, status_filter)


@router.post(
    "/{project_id}/join-requests/{request_id}/approve",
    response_model=JoinRequestResponse,
)
async def approve_join_request(
    project_id: UUID,
    request_id: UUID,
    service: Annotated[JoinRequestService, Depends(get_service)],
    user: RequiredUser,
    action: JoinRequestAction | None = None,
) -> JoinRequestResponse:
    """Approve a join request (admin/owner only)."""
    return await service.approve_request(
        project_id, request_id, action or JoinRequestAction(), user
    )


@router.post(
    "/{project_id}/join-requests/{request_id}/decline",
    response_model=JoinRequestResponse,
)
async def decline_join_request(
    project_id: UUID,
    request_id: UUID,
    service: Annotated[JoinRequestService, Depends(get_service)],
    user: RequiredUser,
    action: JoinRequestAction | None = None,
) -> JoinRequestResponse:
    """Decline a join request (admin/owner only)."""
    return await service.decline_request(
        project_id, request_id, action or JoinRequestAction(), user
    )


@router.delete(
    "/{project_id}/join-requests/{request_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def withdraw_join_request(
    project_id: UUID,
    request_id: UUID,
    service: Annotated[JoinRequestService, Depends(get_service)],
    user: RequiredUser,
) -> None:
    """Withdraw a pending join request (requester only)."""
    await service.withdraw_request(project_id, request_id, user)
