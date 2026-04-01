"""PostgreSQL index tables for ontology query optimization.

These tables provide a read-optimized projection of ontology data from
Turtle/RDF files stored in git. They enable fast tree navigation, search,
and class detail queries without loading the full RDF graph into memory.
"""

__all__ = [
    "IndexedAnnotation",
    "IndexedEntity",
    "IndexedHierarchy",
    "IndexedLabel",
    "IndexingStatus",
    "OntologyIndexStatus",
]

import uuid
from datetime import datetime
from enum import StrEnum

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


class IndexingStatus(StrEnum):
    PENDING = "pending"
    INDEXING = "indexing"
    READY = "ready"
    FAILED = "failed"


class OntologyIndexStatus(Base):
    """Tracks indexing state per (project, branch)."""

    __tablename__ = "ontology_index_status"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    branch: Mapped[str] = mapped_column(String(255), nullable=False)
    commit_hash: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=IndexingStatus.PENDING.value)
    entity_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )

    project: Mapped["Project"] = relationship()  # type: ignore[name-defined]  # noqa: F821

    __table_args__ = (UniqueConstraint("project_id", "branch", name="uq_ontology_index_status"),)

    def __repr__(self) -> str:
        return (
            f"<OntologyIndexStatus(id={self.id}, project_id={self.project_id}, "
            f"branch={self.branch!r}, status={self.status!r})>"
        )


class IndexedEntity(Base):
    """One row per OWL entity (class, property, individual)."""

    __tablename__ = "indexed_entities"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    branch: Mapped[str] = mapped_column(String(255), nullable=False)
    iri: Mapped[str] = mapped_column(String(2000), nullable=False)
    local_name: Mapped[str] = mapped_column(String(500), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(30), nullable=False)
    deprecated: Mapped[bool] = mapped_column(Boolean, default=False)

    labels: Mapped[list["IndexedLabel"]] = relationship(
        back_populates="entity", cascade="all, delete-orphan"
    )
    annotations: Mapped[list["IndexedAnnotation"]] = relationship(
        back_populates="entity", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("project_id", "branch", "iri", name="uq_indexed_entity"),
        Index("ix_indexed_entities_project_branch_type", "project_id", "branch", "entity_type"),
        Index(
            "ix_indexed_entities_local_name_trgm",
            "local_name",
            postgresql_using="gin",
            postgresql_ops={"local_name": "gin_trgm_ops"},
        ),
        Index(
            "ix_indexed_entities_iri_trgm",
            "iri",
            postgresql_using="gin",
            postgresql_ops={"iri": "gin_trgm_ops"},
        ),
    )

    def __repr__(self) -> str:
        return f"<IndexedEntity(id={self.id}, iri={self.iri!r}, type={self.entity_type!r})>"


class IndexedLabel(Base):
    """Multilingual labels for indexed entities."""

    __tablename__ = "indexed_labels"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    entity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("indexed_entities.id", ondelete="CASCADE")
    )
    property_iri: Mapped[str] = mapped_column(String(2000), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    lang: Mapped[str | None] = mapped_column(String(20), nullable=True)

    entity: Mapped["IndexedEntity"] = relationship(back_populates="labels")

    __table_args__ = (
        Index("ix_indexed_labels_entity_id", "entity_id"),
        Index(
            "ix_indexed_labels_value_trgm",
            "value",
            postgresql_using="gin",
            postgresql_ops={"value": "gin_trgm_ops"},
        ),
    )

    def __repr__(self) -> str:
        return f"<IndexedLabel(id={self.id}, value={self.value!r}, lang={self.lang!r})>"


class IndexedHierarchy(Base):
    """Parent-child class edges for the ontology hierarchy."""

    __tablename__ = "indexed_hierarchy"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    branch: Mapped[str] = mapped_column(String(255), nullable=False)
    child_iri: Mapped[str] = mapped_column(String(2000), nullable=False)
    parent_iri: Mapped[str] = mapped_column(String(2000), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "branch",
            "child_iri",
            "parent_iri",
            name="uq_indexed_hierarchy",
        ),
        Index("ix_indexed_hierarchy_parent", "project_id", "branch", "parent_iri"),
        Index("ix_indexed_hierarchy_child", "project_id", "branch", "child_iri"),
    )

    def __repr__(self) -> str:
        return f"<IndexedHierarchy(child={self.child_iri!r}, parent={self.parent_iri!r})>"


class IndexedAnnotation(Base):
    """Annotation properties beyond labels (DC, SKOS notes, etc.)."""

    __tablename__ = "indexed_annotations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    entity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("indexed_entities.id", ondelete="CASCADE")
    )
    property_iri: Mapped[str] = mapped_column(String(2000), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    lang: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_uri: Mapped[bool] = mapped_column(Boolean, default=False)

    entity: Mapped["IndexedEntity"] = relationship(back_populates="annotations")

    __table_args__ = (Index("ix_indexed_annotations_entity_id", "entity_id"),)

    def __repr__(self) -> str:
        return (
            f"<IndexedAnnotation(id={self.id}, property={self.property_iri!r}, "
            f"value={self.value!r})>"
        )
