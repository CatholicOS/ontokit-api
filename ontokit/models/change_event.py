"""Entity change event model for tracking ontology modifications."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ontokit.core.database import Base


class ChangeEventType(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    RENAME = "rename"
    REPARENT = "reparent"
    DEPRECATE = "deprecate"


class EntityChangeEvent(Base):
    __tablename__ = "entity_change_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    branch: Mapped[str] = mapped_column(String(255))
    entity_iri: Mapped[str] = mapped_column(String(2000))
    entity_type: Mapped[str] = mapped_column(String(50))
    event_type: Mapped[str] = mapped_column(String(50))
    user_id: Mapped[str] = mapped_column(String(255))
    user_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    commit_hash: Mapped[str | None] = mapped_column(String(40), nullable=True)
    changed_fields: Mapped[list[str]] = mapped_column(JSON, default=list)
    old_values: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    new_values: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped["Project"] = relationship()  # type: ignore[name-defined]  # noqa: F821

    __table_args__ = (
        Index("ix_change_events_project_entity", "project_id", "entity_iri"),
        Index("ix_change_events_project_time", "project_id", "created_at"),
        Index("ix_change_events_project_branch_time", "project_id", "branch", "created_at"),
    )
