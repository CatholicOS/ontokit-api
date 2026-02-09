"""Project and project member schemas."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


# Role type for project members
ProjectRole = Literal["owner", "admin", "editor", "viewer"]


class ProjectBase(BaseModel):
    """Base project fields."""

    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    is_public: bool = False


class ProjectCreate(ProjectBase):
    """Schema for creating a project."""

    pass


class ProjectUpdate(BaseModel):
    """Schema for updating a project."""

    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    is_public: bool | None = None


class ProjectOwner(BaseModel):
    """Minimal owner information for project responses."""

    id: str
    name: str | None = None
    email: str | None = None


class ProjectResponse(ProjectBase):
    """Schema for project responses."""

    id: UUID
    owner_id: str
    owner: ProjectOwner | None = None
    created_at: datetime
    updated_at: datetime | None = None
    member_count: int = 0
    user_role: ProjectRole | None = None  # Current user's role in the project

    class Config:
        from_attributes = True


class ProjectListResponse(BaseModel):
    """Paginated list of projects."""

    items: list[ProjectResponse]
    total: int
    skip: int
    limit: int


# Project Member Schemas


class MemberBase(BaseModel):
    """Base member fields."""

    user_id: str
    role: ProjectRole = "viewer"


class MemberCreate(MemberBase):
    """Schema for adding a member to a project."""

    pass


class MemberUpdate(BaseModel):
    """Schema for updating a member's role."""

    role: ProjectRole


class MemberUser(BaseModel):
    """User information for member responses."""

    id: str
    name: str | None = None
    email: str | None = None


class MemberResponse(MemberBase):
    """Schema for member responses."""

    id: UUID
    project_id: UUID
    user: MemberUser | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class MemberListResponse(BaseModel):
    """List of project members."""

    items: list[MemberResponse]
    total: int
