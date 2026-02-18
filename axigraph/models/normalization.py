"""Normalization run database model."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from axigraph.core.database import Base

if TYPE_CHECKING:
    from axigraph.models.project import Project


class NormalizationRun(Base):
    """Record of a normalization run on a project's ontology."""

    __tablename__ = "normalization_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )

    # When this normalization was performed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Who triggered it (null for automatic/system)
    triggered_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    trigger_type: Mapped[str] = mapped_column(
        String(50), default="manual"
    )  # "import", "manual", "automatic"

    # Report data (JSON)
    report_json: Mapped[str] = mapped_column(Text, nullable=False)

    # Summary fields for quick queries
    original_format: Mapped[str] = mapped_column(String(50), nullable=False)
    original_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    normalized_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    triple_count: Mapped[int] = mapped_column(Integer, nullable=False)
    prefixes_removed_count: Mapped[int] = mapped_column(Integer, default=0)
    prefixes_added_count: Mapped[int] = mapped_column(Integer, default=0)
    format_converted: Mapped[bool] = mapped_column(Boolean, default=False)

    # Was this a dry run (no changes committed)?
    is_dry_run: Mapped[bool] = mapped_column(Boolean, default=False)

    # Git commit hash if changes were committed
    commit_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Relationship
    project: Mapped["Project"] = relationship(back_populates="normalization_runs")

    def __repr__(self) -> str:
        return f"<NormalizationRun(id={self.id}, project_id={self.project_id}, trigger_type={self.trigger_type})>"
