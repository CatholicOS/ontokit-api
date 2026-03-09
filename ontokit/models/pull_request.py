"""Pull request, review, comment, and GitHub integration database models."""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ontokit.core.database import Base


class PRStatus(StrEnum):
    """Pull request status enum."""

    OPEN = "open"
    MERGED = "merged"
    CLOSED = "closed"


class ReviewStatus(StrEnum):
    """Pull request review status enum."""

    APPROVED = "approved"
    CHANGES_REQUESTED = "changes_requested"
    COMMENTED = "commented"


class PullRequest(Base):
    """Pull request model for tracking proposed changes."""

    __tablename__ = "pull_requests"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )

    # PR metadata
    pr_number: Mapped[int] = mapped_column(Integer, nullable=False)  # Project-scoped PR number
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Branch info
    source_branch: Mapped[str] = mapped_column(String(255), nullable=False)
    target_branch: Mapped[str] = mapped_column(String(255), nullable=False, default="main")

    # Status
    status: Mapped[str] = mapped_column(String(50), default=PRStatus.OPEN.value)

    # Author (Zitadel user ID)
    author_id: Mapped[str] = mapped_column(String(255), nullable=False)
    author_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    author_email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # GitHub integration (optional)
    github_pr_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    github_pr_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    # Merge info
    merged_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    merged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    merge_commit_hash: Mapped[str | None] = mapped_column(String(40), nullable=True)
    base_commit_hash: Mapped[str | None] = mapped_column(String(40), nullable=True)
    head_commit_hash: Mapped[str | None] = mapped_column(String(40), nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )

    # Relationships
    project: Mapped["Project"] = relationship(back_populates="pull_requests")
    reviews: Mapped[list["PullRequestReview"]] = relationship(
        back_populates="pull_request", cascade="all, delete-orphan"
    )
    comments: Mapped[list["PullRequestComment"]] = relationship(
        back_populates="pull_request", cascade="all, delete-orphan"
    )

    __table_args__ = (UniqueConstraint("project_id", "pr_number", name="uq_project_pr_number"),)

    def __repr__(self) -> str:
        return f"<PullRequest(id={self.id}, project_id={self.project_id}, pr_number={self.pr_number}, title={self.title!r})>"


class PullRequestReview(Base):
    """Pull request review model for tracking approvals and change requests."""

    __tablename__ = "pull_request_reviews"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    pull_request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pull_requests.id", ondelete="CASCADE"), nullable=False
    )

    # Reviewer (Zitadel user ID)
    reviewer_id: Mapped[str] = mapped_column(String(255), nullable=False)

    # Review status
    status: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # approved, changes_requested, commented
    body: Mapped[str | None] = mapped_column(Text, nullable=True)

    # GitHub integration (optional)
    github_review_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    pull_request: Mapped["PullRequest"] = relationship(back_populates="reviews")

    def __repr__(self) -> str:
        return f"<PullRequestReview(id={self.id}, reviewer_id={self.reviewer_id!r}, status={self.status!r})>"


class PullRequestComment(Base):
    """Pull request comment model for discussions."""

    __tablename__ = "pull_request_comments"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    pull_request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pull_requests.id", ondelete="CASCADE"), nullable=False
    )

    # Author (Zitadel user ID)
    author_id: Mapped[str] = mapped_column(String(255), nullable=False)
    author_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    author_email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Comment content
    body: Mapped[str] = mapped_column(Text, nullable=False)

    # Threading support (optional parent for replies)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("pull_request_comments.id", ondelete="CASCADE"), nullable=True
    )

    # GitHub integration (optional)
    github_comment_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )

    # Relationships
    pull_request: Mapped["PullRequest"] = relationship(back_populates="comments")
    parent: Mapped["PullRequestComment | None"] = relationship(
        remote_side=[id], back_populates="replies"
    )
    replies: Mapped[list["PullRequestComment"]] = relationship(
        back_populates="parent", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<PullRequestComment(id={self.id}, author_id={self.author_id!r})>"


class GitHubIntegration(Base):
    """GitHub integration settings for a project."""

    __tablename__ = "github_integrations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, unique=True
    )

    # GitHub repository info
    repo_owner: Mapped[str] = mapped_column(String(255), nullable=False)
    repo_name: Mapped[str] = mapped_column(String(255), nullable=False)

    # GitHub App installation (legacy, nullable for PAT-based auth)
    installation_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Webhook secret for signature verification (nullable when webhooks disabled)
    webhook_secret: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # PAT-based auth: the user who connected this integration
    connected_by_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Whether GitHub webhooks are enabled for this integration
    webhooks_enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    # GitHub webhook hook ID (set when auto-detected or auto-created)
    github_hook_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Branch settings
    default_branch: Mapped[str] = mapped_column(String(255), default="main")

    # Ontology file path within the repo (for GitHub-cloned projects)
    ontology_file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Turtle output file path within the repo (where normalized .ttl is written)
    # When source is already .ttl, this matches ontology_file_path.
    # When source is .owl/.rdf/etc., this points to the .ttl output location.
    turtle_file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Sync status
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sync_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sync_status: Mapped[str] = mapped_column(String(50), default="idle")
    # sync_status values: "idle", "syncing", "conflict", "error"
    sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )

    # Relationships
    project: Mapped["Project"] = relationship(back_populates="github_integration")

    def __repr__(self) -> str:
        return f"<GitHubIntegration(project_id={self.project_id}, repo={self.repo_owner}/{self.repo_name})>"


# Import Project at runtime to avoid circular imports
from ontokit.models.project import Project  # noqa: E402
