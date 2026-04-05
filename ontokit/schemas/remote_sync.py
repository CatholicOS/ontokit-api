"""Pydantic v2 schemas for remote sync configuration and events."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

SyncFrequency = Literal["6h", "12h", "24h", "48h", "weekly", "manual", "webhook"]
SyncUpdateMode = Literal["auto_apply", "review_required"]
RemoteSyncStatus = Literal["idle", "checking", "update_available", "up_to_date", "error"]
SyncEventType = Literal["check_no_changes", "update_found", "auto_applied", "pr_created", "error"]
SyncJobStatus = Literal["pending", "running", "complete", "failed", "not_found"]


# --- Request schemas ---


class RemoteSyncConfigCreate(BaseModel):
    """Create a new remote sync configuration."""

    repo_owner: str = Field(..., min_length=1, max_length=255)
    repo_name: str = Field(..., min_length=1, max_length=255)
    branch: str = Field(default="main", max_length=255)
    file_path: str = Field(..., min_length=1, max_length=1000)
    frequency: SyncFrequency = "manual"
    enabled: bool = False
    update_mode: SyncUpdateMode = "review_required"


class RemoteSyncConfigUpdate(BaseModel):
    """Update an existing remote sync configuration."""

    repo_owner: str | None = Field(default=None, min_length=1, max_length=255)
    repo_name: str | None = Field(default=None, min_length=1, max_length=255)
    branch: str | None = Field(default=None, max_length=255)
    file_path: str | None = Field(default=None, min_length=1, max_length=1000)
    frequency: SyncFrequency | None = None
    enabled: bool | None = None
    update_mode: SyncUpdateMode | None = None


# --- Response schemas ---


class RemoteSyncConfigResponse(BaseModel):
    """Response for remote sync configuration."""

    id: UUID
    project_id: UUID
    repo_owner: str
    repo_name: str
    branch: str
    file_path: str
    frequency: SyncFrequency
    enabled: bool
    update_mode: SyncUpdateMode
    status: RemoteSyncStatus
    last_check_at: datetime | None
    last_update_at: datetime | None
    next_check_at: datetime | None
    remote_commit_sha: str | None
    pending_pr_id: UUID | None
    error_message: str | None

    class Config:
        from_attributes = True


class SyncEventResponse(BaseModel):
    """Response for a single sync event."""

    id: UUID
    project_id: UUID
    config_id: UUID
    event_type: SyncEventType
    remote_commit_sha: str | None
    pr_id: UUID | None
    changes_summary: str | None
    error_message: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class SyncHistoryResponse(BaseModel):
    """Response for sync event history."""

    items: list[SyncEventResponse]
    total: int


class SyncCheckResponse(BaseModel):
    """Response when triggering a manual sync check."""

    message: str
    job_id: str
    status: str


class SyncJobStatusResponse(BaseModel):
    """Response for polling a background sync job."""

    job_id: str
    status: SyncJobStatus
    result: dict[str, object] | None = None
    error: str | None = None
