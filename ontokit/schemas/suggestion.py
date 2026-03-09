"""Suggestion session schemas for request/response validation."""

from datetime import datetime

from pydantic import BaseModel, Field


class SuggestionSessionResponse(BaseModel):
    """Response when creating a suggestion session."""

    session_id: str
    branch: str
    created_at: datetime
    beacon_token: str

    class Config:
        from_attributes = True


class SuggestionSaveRequest(BaseModel):
    """Request body for saving content to a suggestion session."""

    content: str = Field(..., description="Full Turtle source content")
    entity_iri: str = Field(..., description="IRI of the entity being modified")
    entity_label: str = Field(..., description="Human-readable label of the entity")


class SuggestionSaveResponse(BaseModel):
    """Response after saving to a suggestion session."""

    commit_hash: str
    branch: str
    changes_count: int


class SuggestionSubmitRequest(BaseModel):
    """Request body for submitting a suggestion session as a PR."""

    summary: str | None = Field(default=None, description="Optional summary describing the changes")


class SuggestionSubmitResponse(BaseModel):
    """Response after submitting a suggestion session."""

    pr_number: int
    pr_url: str | None = None
    status: str


class SuggestionUser(BaseModel):
    """User info embedded in session summaries."""

    id: str
    name: str | None = None
    email: str | None = None


class SuggestionSessionSummary(BaseModel):
    """Summary of a suggestion session for list endpoint."""

    session_id: str
    branch: str
    changes_count: int
    last_activity: datetime
    entities_modified: list[str]
    status: str
    pr_number: int | None = None
    pr_url: str | None = None
    github_pr_url: str | None = None
    submitter: SuggestionUser | None = None
    reviewer: SuggestionUser | None = None
    reviewer_feedback: str | None = None
    reviewed_at: datetime | None = None
    revision: int | None = None
    summary: str | None = None

    class Config:
        from_attributes = True


class SuggestionSessionListResponse(BaseModel):
    """Response for listing suggestion sessions."""

    items: list[SuggestionSessionSummary]


class SuggestionBeaconRequest(BaseModel):
    """Request body for beacon save (sendBeacon flush)."""

    session_id: str
    content: str


# --- Review request schemas ---


class SuggestionRejectRequest(BaseModel):
    """Request body for rejecting a suggestion session."""

    reason: str = Field(..., min_length=1, description="Reason for rejection")


class SuggestionRequestChangesRequest(BaseModel):
    """Request body for requesting changes on a suggestion session."""

    feedback: str = Field(..., min_length=1, description="Feedback for the suggester")


class SuggestionResubmitRequest(BaseModel):
    """Request body for resubmitting a suggestion session."""

    summary: str | None = Field(default=None, description="Updated summary")
