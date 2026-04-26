"""Lint run and lint issue schemas."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Type definitions
LintIssueTypeValue = Literal["error", "warning", "info"]
LintRunStatusValue = Literal["pending", "running", "completed", "failed"]
SubjectTypeValue = Literal["class", "property", "individual", "other"]


class LintIssueBase(BaseModel):
    """Base lint issue fields."""

    issue_type: LintIssueTypeValue
    rule_id: str = Field(..., min_length=1, max_length=100)
    message: str
    subject_iri: str | None = None
    subject_type: SubjectTypeValue | None = None
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

    model_config = ConfigDict(from_attributes=True)


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

    model_config = ConfigDict(from_attributes=True)


class LintRunDetailResponse(LintRunResponse):
    """Schema for detailed lint run responses with issues."""

    issues: list[LintIssueResponse] = []

    model_config = ConfigDict(from_attributes=True)


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
    scope: list[str] = Field(
        description="Entity types this rule applies to: class, property, individual",
    )


class LintRulesResponse(BaseModel):
    """List of available lint rules."""

    rules: list[LintRuleInfo]


# ---------------------------------------------------------------------------
# Per-project lint configuration
# ---------------------------------------------------------------------------


class LintLevelInfo(BaseModel):
    """Information about a progressive lint level."""

    level: int
    name: str
    description: str
    rule_ids: list[str]


class LintLevelsResponse(BaseModel):
    """List of available lint levels."""

    levels: list[LintLevelInfo]


class LintConfigResponse(BaseModel):
    """Current lint configuration for a project."""

    project_id: UUID
    lint_level: int | None = None
    enabled_rules: list[str] | None = None
    effective_rules: list[str]
    updated_at: datetime | None = None


class LintConfigUpdate(BaseModel):
    """Request body for updating lint configuration.

    ``lint_level`` and ``enabled_rules`` are mutually exclusive — see ``enforce_xor``.

    Set ``lint_level`` to use a preset level (1-5).
    Set ``enabled_rules`` to configure individual rules (can be empty list to disable all).
    Set both to ``None`` to reset to default (all rules).
    """

    lint_level: int | None = Field(default=None, ge=1, le=5)
    enabled_rules: list[str] | None = None

    @field_validator("enabled_rules")
    @classmethod
    def validate_rule_ids(cls, v: list[str] | None) -> list[str] | None:
        """Reject unknown rule IDs at schema level."""
        if v is None:
            return v
        from ontokit.services.linter import ALL_RULE_IDS

        invalid = set(v) - ALL_RULE_IDS
        if invalid:
            msg = f"Unknown rule IDs: {', '.join(sorted(invalid))}"
            raise ValueError(msg)
        return v

    @model_validator(mode="after")
    def enforce_xor(self) -> "LintConfigUpdate":
        """Reject contradictory bodies that set both a preset level and a custom
        rule list. Presets are immutable, so the two modes are mutually exclusive
        and the UI never sends both. Accepting both would persist a self-
        contradictory row whose response lies about effective rules."""
        if self.lint_level is not None and self.enabled_rules is not None:
            msg = (
                "lint_level and enabled_rules are mutually exclusive — choose preset OR custom mode"
            )
            raise ValueError(msg)
        return self
