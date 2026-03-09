"""Notification request/response schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class NotificationResponse(BaseModel):
    """Single notification item."""

    id: UUID
    type: str
    title: str
    body: str | None = None
    project_id: UUID
    project_name: str
    target_id: str | None = None
    target_url: str | None = None
    is_read: bool
    created_at: datetime

    class Config:
        from_attributes = True


class NotificationListResponse(BaseModel):
    """Paginated notification list with unread count."""

    items: list[NotificationResponse]
    total: int
    unread_count: int
