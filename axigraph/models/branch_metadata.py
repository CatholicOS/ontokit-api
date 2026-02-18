"""Branch metadata model for tracking branch authorship."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from axigraph.core.database import Base


class BranchMetadata(Base):
    """Tracks who created each branch in a project."""

    __tablename__ = "branch_metadata"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    branch_name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_by_id: Mapped[str] = mapped_column(String(255), nullable=False)
    created_by_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("project_id", "branch_name", name="uq_branch_metadata"),)

    def __repr__(self) -> str:
        return (
            f"<BranchMetadata(project_id={self.project_id}, "
            f"branch={self.branch_name!r}, created_by={self.created_by_id!r})>"
        )
