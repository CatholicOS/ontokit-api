"""Lint run and lint issue database models."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

if TYPE_CHECKING:
    from axigraph.models.project import Project

from axigraph.core.database import Base


class LintRunStatus(StrEnum):
    """Status values for lint runs."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class LintIssueType(StrEnum):
    """Severity levels for lint issues."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class LintRun(Base):
    """Lint run model for tracking linting job executions."""

    __tablename__ = "lint_runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(50), default=LintRunStatus.PENDING.value)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    issues_found: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    project: Mapped["Project"] = relationship(back_populates="lint_runs")
    issues: Mapped[list["LintIssue"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<LintRun(id={self.id}, project_id={self.project_id}, status={self.status!r})>"


class LintIssue(Base):
    """Lint issue model for storing individual issues found during linting."""

    __tablename__ = "lint_issues"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lint_runs.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    issue_type: Mapped[str] = mapped_column(String(50), nullable=False)
    rule_id: Mapped[str] = mapped_column(String(100), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    subject_iri: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    run: Mapped["LintRun"] = relationship(back_populates="issues")

    def __repr__(self) -> str:
        return (
            f"<LintIssue(id={self.id}, rule_id={self.rule_id!r}, issue_type={self.issue_type!r})>"
        )
