"""Notification endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from ontokit.core.auth import RequiredUser
from ontokit.core.database import get_db
from ontokit.schemas.notification import NotificationListResponse
from ontokit.services.notification_service import NotificationService, get_notification_service

router = APIRouter()


def get_service(db: Annotated[AsyncSession, Depends(get_db)]) -> NotificationService:
    """Dependency to get notification service."""
    return get_notification_service(db)


@router.get("", response_model=NotificationListResponse)
async def list_notifications(
    service: Annotated[NotificationService, Depends(get_service)],
    user: RequiredUser,
    unread_only: bool = Query(default=False),
) -> NotificationListResponse:
    """List notifications for the current user."""
    return await service.list_notifications(user.id, unread_only=unread_only)


@router.post("/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_notification_read(
    notification_id: UUID,
    service: Annotated[NotificationService, Depends(get_service)],
    user: RequiredUser,
) -> None:
    """Mark a single notification as read."""
    found = await service.mark_read(notification_id, user.id)
    if not found:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found",
        )


@router.post("/read-all", status_code=status.HTTP_204_NO_CONTENT)
async def mark_all_notifications_read(
    service: Annotated[NotificationService, Depends(get_service)],
    user: RequiredUser,
) -> None:
    """Mark all notifications as read for the current user."""
    await service.mark_all_read(user.id)
