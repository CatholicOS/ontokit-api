"""Join request schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class JoinRequestCreate(BaseModel):
    """Schema for creating a join request."""

    message: str = Field(
        ...,
        min_length=10,
        max_length=1000,
        description="Message explaining why you want to join this project",
    )


class JoinRequestAction(BaseModel):
    """Schema for admin approve/decline action."""

    response_message: str | None = Field(
        None,
        max_length=1000,
        description="Optional message from the admin",
    )


class JoinRequestUser(BaseModel):
    """User information embedded in join request responses."""

    id: str
    name: str | None = None
    email: str | None = None


class JoinRequestResponse(BaseModel):
    """Schema for join request responses."""

    id: UUID
    project_id: UUID
    user_id: str
    user: JoinRequestUser | None = None
    message: str
    status: str
    responded_by: str | None = None
    responder: JoinRequestUser | None = None
    responded_at: datetime | None = None
    response_message: str | None = None
    created_at: datetime
    updated_at: datetime | None = None

    class Config:
        from_attributes = True


class JoinRequestListResponse(BaseModel):
    """Paginated list of join requests."""

    items: list[JoinRequestResponse]
    total: int


class MyJoinRequestResponse(BaseModel):
    """Response for checking the current user's join request status."""

    has_pending_request: bool
    request: JoinRequestResponse | None = None


class ProjectPendingCount(BaseModel):
    """Pending count for a single project."""

    project_id: UUID
    project_name: str
    pending_count: int


class PendingJoinRequestsSummary(BaseModel):
    """Summary of pending join requests across managed projects."""

    total_pending: int
    by_project: list[ProjectPendingCount]
