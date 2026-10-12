"""Schemas for anonymous suggestion session endpoints."""

from datetime import datetime

from pydantic import BaseModel, Field


class AnonymousSessionCreateResponse(BaseModel):
    """Response when creating an anonymous suggestion session."""

    session_id: str
    branch: str
    created_at: datetime
    anonymous_token: str

    class Config:
        from_attributes = True


class AnonymousSubmitRequest(BaseModel):
    """Request body for submitting an anonymous suggestion session."""

    summary: str | None = Field(default=None, description="Optional summary of the changes")
    submitter_name: str | None = Field(
        default=None, description="Optional name to credit with the suggestion"
    )
    submitter_email: str | None = Field(
        default=None, description="Optional email to associate with the suggestion"
    )
    # Spam-control field. Deliberately documented as an ordinary optional
    # website URL: the real semantics (filled -> silent fake success) must not
    # appear in the public OpenAPI schema, which bots can read.
    honeypot: str | None = Field(
        default=None,
        alias="website",
        description="Optional website URL",
    )

    model_config = {"populate_by_name": True}


class AnonymousSubmitResponse(BaseModel):
    """Response after submitting an anonymous suggestion session."""

    pr_number: int
    pr_url: str | None = None
    status: str
