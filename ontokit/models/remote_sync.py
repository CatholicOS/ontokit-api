"""Remote sync configuration and event models."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ontokit.core.database import Base


class RemoteSyncConfig(Base):
    """Configuration for tracking a remote GitHub repository file."""

    __tablename__ = "remote_sync_configs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), unique=True
    )
    repo_owner: Mapped[str] = mapped_column(String(255), nullable=False)
    repo_name: Mapped[str] = mapped_column(String(255), nullable=False)
    branch: Mapped[str] = mapped_column(String(255), default="main")
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    frequency: Mapped[str] = mapped_column(String(50), default="manual")
    enabled: Mapped[bool] = mapped_column(default=False)
    update_mode: Mapped[str] = mapped_column(String(50), default="review_required")
    status: Mapped[str] = mapped_column(String(50), default="idle")

    last_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_update_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    remote_commit_sha: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pending_pr_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("pull_requests.id", ondelete="SET NULL"), nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )

    # Relationships
    events: Mapped[list["SyncEvent"]] = relationship(
        back_populates="config", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return (
            f"<RemoteSyncConfig(id={self.id}, project_id={self.project_id}, "
            f"repo={self.repo_owner}/{self.repo_name})>"
        )


class SyncEvent(Base):
    """Record of a remote sync check or update event."""

    __tablename__ = "sync_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    config_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("remote_sync_configs.id", ondelete="CASCADE")
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    remote_commit_sha: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pr_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("pull_requests.id", ondelete="SET NULL"), nullable=True
    )
    changes_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    config: Mapped["RemoteSyncConfig"] = relationship(back_populates="events")

    def __repr__(self) -> str:
        return (
            f"<SyncEvent(id={self.id}, project_id={self.project_id}, "
            f"event_type={self.event_type!r})>"
        )
