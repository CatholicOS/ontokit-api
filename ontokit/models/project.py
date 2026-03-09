"""Project and ProjectMember database models."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

if TYPE_CHECKING:
    from ontokit.models.join_request import JoinRequest
    from ontokit.models.lint import LintRun
    from ontokit.models.normalization import NormalizationRun
    from ontokit.models.pull_request import GitHubIntegration, PullRequest
    from ontokit.models.suggestion_session import SuggestionSession

from ontokit.core.database import Base


class Project(Base):
    """Project model for organizing ontologies and collaborations."""

    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)
    owner_id: Mapped[str] = mapped_column(String(255), nullable=False)  # Zitadel user ID
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )

    # Import-related fields (optional, only set when project was created via import)
    source_file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ontology_iri: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    # Label preferences for ontology display (JSON array)
    # Format: ["rdfs:label@en", "rdfs:label@it", "rdfs:label", "skos:prefLabel@en"]
    label_preferences: Mapped[str | None] = mapped_column(String(2000), nullable=True)

    # Normalization report from initial import (JSON object)
    # Contains details about format conversion, prefix changes, etc.
    normalization_report: Mapped[str | None] = mapped_column(Text, nullable=True)

    # PR workflow settings
    # 0 = no approval required, 1+ = minimum number of approvals before merge
    pr_approval_required: Mapped[int] = mapped_column(Integer, default=0)

    # Relationships
    members: Mapped[list["ProjectMember"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    pull_requests: Mapped[list["PullRequest"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    github_integration: Mapped["GitHubIntegration | None"] = relationship(
        back_populates="project", cascade="all, delete-orphan", uselist=False
    )
    lint_runs: Mapped[list["LintRun"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    normalization_runs: Mapped[list["NormalizationRun"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    join_requests: Mapped[list["JoinRequest"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    suggestion_sessions: Mapped[list["SuggestionSession"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Project(id={self.id}, name={self.name!r}, is_public={self.is_public})>"


class ProjectMember(Base):
    """Project member model for managing access to private projects."""

    __tablename__ = "project_members"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)  # Zitadel user ID
    role: Mapped[str] = mapped_column(String(50), default="viewer")  # owner, admin, editor, viewer
    preferred_branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped["Project"] = relationship(back_populates="members")

    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_project_member"),)

    def __repr__(self) -> str:
        return f"<ProjectMember(project_id={self.project_id}, user_id={self.user_id!r}, role={self.role!r})>"
