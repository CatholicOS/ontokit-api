"""Lint run and lint issue schemas."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

# Type definitions
LintIssueTypeValue = Literal["error", "warning", "info"]
LintRunStatusValue = Literal["pending", "running", "completed", "failed"]


class LintIssueBase(BaseModel):
    """Base lint issue fields."""

    issue_type: LintIssueTypeValue
    rule_id: str = Field(..., min_length=1, max_length=100)
    message: str
    subject_iri: str | None = None
    details: dict[str, Any] | None = None


class LintIssueCreate(LintIssueBase):
    """Schema for creating a lint issue (internal use)."""

    pass


class LintIssueResponse(LintIssueBase):
    """Schema for lint issue responses."""

    id: UUID
    run_id: UUID
    project_id: UUID
    created_at: datetime
    resolved_at: datetime | None = None

    class Config:
        from_attributes = True


class LintRunBase(BaseModel):
    """Base lint run fields."""

    status: LintRunStatusValue = "pending"


class LintRunCreate(LintRunBase):
    """Schema for creating a lint run (internal use)."""

    pass


class LintRunResponse(LintRunBase):
    """Schema for lint run responses."""

    id: UUID
    project_id: UUID
    started_at: datetime
    completed_at: datetime | None = None
    issues_found: int | None = None
    error_message: str | None = None

    class Config:
        from_attributes = True


class LintRunDetailResponse(LintRunResponse):
    """Schema for detailed lint run responses with issues."""

    issues: list[LintIssueResponse] = []

    class Config:
        from_attributes = True


class LintSummaryResponse(BaseModel):
    """Schema for lint summary responses."""

    project_id: UUID
    last_run: LintRunResponse | None = None
    error_count: int = 0
    warning_count: int = 0
    info_count: int = 0
    total_issues: int = 0


class LintTriggerResponse(BaseModel):
    """Schema for lint trigger response."""

    job_id: str
    status: str = "queued"
    message: str = "Lint job has been queued"


class LintIssueListResponse(BaseModel):
    """Paginated list of lint issues."""

    items: list[LintIssueResponse]
    total: int
    skip: int
    limit: int


class LintRunListResponse(BaseModel):
    """Paginated list of lint runs."""

    items: list[LintRunResponse]
    total: int
    skip: int
    limit: int


class LintRuleInfo(BaseModel):
    """Information about a lint rule."""

    rule_id: str
    name: str
    description: str
    severity: LintIssueTypeValue


class LintRulesResponse(BaseModel):
    """List of available lint rules."""

    rules: list[LintRuleInfo]
