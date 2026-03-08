"""Embedding models for vector search and similarity."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ontokit.core.database import Base

# Import Vector conditionally to avoid hard failure if pgvector not installed
try:
    from pgvector.sqlalchemy import Vector
except ImportError:
    Vector = None  # type: ignore[assignment,misc]


class ProjectEmbeddingConfig(Base):
    __tablename__ = "project_embedding_configs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), unique=True
    )
    provider: Mapped[str] = mapped_column(String(50), default="local")
    model_name: Mapped[str] = mapped_column(String(200), default="all-MiniLM-L6-v2")
    api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    dimensions: Mapped[int] = mapped_column(Integer, default=384)
    auto_embed_on_save: Mapped[bool] = mapped_column(Boolean, default=False)
    last_full_embed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )

    project: Mapped["Project"] = relationship()  # type: ignore[name-defined]  # noqa: F821


class EntityEmbedding(Base):
    __tablename__ = "entity_embeddings"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    branch: Mapped[str] = mapped_column(String(255), default="main")
    entity_iri: Mapped[str] = mapped_column(String(2000))
    entity_type: Mapped[str] = mapped_column(String(50))
    label: Mapped[str | None] = mapped_column(String(500), nullable=True)
    embedding_text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[Any] = mapped_column(Vector() if Vector is not None else Text, nullable=False)
    provider: Mapped[str] = mapped_column(String(50))
    model_name: Mapped[str] = mapped_column(String(200))
    deprecated: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("project_id", "branch", "entity_iri", name="uq_entity_embedding"),
        Index("ix_entity_embeddings_project_branch", "project_id", "branch"),
    )


class EmbeddingJob(Base):
    __tablename__ = "embedding_jobs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    branch: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(50), default="pending")
    total_entities: Mapped[int] = mapped_column(Integer, default=0)
    embedded_entities: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    project: Mapped["Project"] = relationship()  # type: ignore[name-defined]  # noqa: F821
