"""Ontology index service for PostgreSQL-backed ontology queries.

Provides fast SQL-based queries as an alternative to loading full RDF graphs
into memory. The index is populated from Turtle/RDF files and kept in sync
via background re-indexing triggered on commits.
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from rdflib import Graph, URIRef
from rdflib import Literal as RDFLiteral
from rdflib.namespace import OWL, RDF, RDFS, SKOS
from sqlalchemy import delete, func, select, text, update
from sqlalchemy import insert as sa_insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ontokit.core.database import Base
from ontokit.models.ontology_index import (
    IndexedAnnotation,
    IndexedEntity,
    IndexedHierarchy,
    IndexedLabel,
    IndexingStatus,
    OntologyIndexStatus,
)
from ontokit.services.ontology import (
    ANNOTATION_PROPERTIES,
    DEFAULT_LABEL_PREFERENCES,
    LABEL_PROPERTY_MAP,
)

logger = logging.getLogger(__name__)

# Batch size for bulk inserts
BATCH_SIZE = 1000

# Entity type constants matching the plan
ENTITY_TYPE_CLASS = "class"
ENTITY_TYPE_OBJECT_PROPERTY = "object_property"
ENTITY_TYPE_DATATYPE_PROPERTY = "datatype_property"
ENTITY_TYPE_ANNOTATION_PROPERTY = "annotation_property"
ENTITY_TYPE_INDIVIDUAL = "individual"

# RDF type to entity_type mapping (includes both OWL and RDFS base types)
RDF_TYPE_MAP: list[tuple[URIRef, str]] = [
    (OWL.Class, ENTITY_TYPE_CLASS),
    (RDFS.Class, ENTITY_TYPE_CLASS),
    (OWL.ObjectProperty, ENTITY_TYPE_OBJECT_PROPERTY),
    (OWL.DatatypeProperty, ENTITY_TYPE_DATATYPE_PROPERTY),
    (OWL.AnnotationProperty, ENTITY_TYPE_ANNOTATION_PROPERTY),
    (RDF.Property, ENTITY_TYPE_OBJECT_PROPERTY),
    (OWL.NamedIndividual, ENTITY_TYPE_INDIVIDUAL),
]

# Label properties to index
LABEL_PROPERTIES: list[tuple[str, URIRef]] = [
    (str(RDFS.label), RDFS.label),
    (str(SKOS.prefLabel), SKOS.prefLabel),
    (str(SKOS.altLabel), SKOS.altLabel),
    (str(URIRef("http://purl.org/dc/terms/title")), URIRef("http://purl.org/dc/terms/title")),
    (
        str(URIRef("http://purl.org/dc/elements/1.1/title")),
        URIRef("http://purl.org/dc/elements/1.1/title"),
    ),
]


def _extract_local_name(iri: str) -> str:
    """Extract the local name from an IRI (after # or last /)."""
    if "#" in iri:
        return iri.split("#")[-1]
    return iri.rsplit("/", 1)[-1]


class OntologyIndexService:
    """Service for populating and querying the ontology index tables."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ──────────────────────────────────────────────
    # Status queries
    # ──────────────────────────────────────────────

    async def get_index_status(self, project_id: UUID, branch: str) -> OntologyIndexStatus | None:
        """Get the current index status for a project/branch."""
        result = await self.db.execute(
            select(OntologyIndexStatus).where(
                OntologyIndexStatus.project_id == project_id,
                OntologyIndexStatus.branch == branch,
            )
        )
        return result.scalar_one_or_none()

    async def is_index_ready(self, project_id: UUID, branch: str) -> bool:
        """Check if the index is in 'ready' state."""
        status = await self.get_index_status(project_id, branch)
        return status is not None and status.status == IndexingStatus.READY.value

    async def is_index_stale(self, project_id: UUID, branch: str, current_commit_hash: str) -> bool:
        """Check if the index is stale (commit_hash doesn't match git HEAD)."""
        status = await self.get_index_status(project_id, branch)
        if status is None:
            return True
        return status.commit_hash != current_commit_hash

    # ──────────────────────────────────────────────
    # Full reindex
    # ──────────────────────────────────────────────

    async def full_reindex(
        self,
        project_id: UUID,
        branch: str,
        graph: Graph,
        commit_hash: str,
    ) -> int:
        """
        Perform a full reindex of an ontology graph into the index tables.

        Returns the number of entities indexed.
        """
        # Upsert status to 'indexing', skip if already indexing
        status_row = await self._upsert_status(project_id, branch, IndexingStatus.INDEXING)
        if status_row is None:
            logger.info(
                "Skipping reindex for project %s branch %s: already indexing",
                project_id,
                branch,
            )
            return 0

        try:
            # Delete existing data for this project/branch
            await self._delete_index_data(project_id, branch)

            # Extract and insert entities
            entity_count = await self._index_graph(project_id, branch, graph)

            # Update status to ready
            await self.db.execute(
                update(OntologyIndexStatus)
                .where(
                    OntologyIndexStatus.project_id == project_id,
                    OntologyIndexStatus.branch == branch,
                )
                .values(
                    status=IndexingStatus.READY.value,
                    commit_hash=commit_hash,
                    entity_count=entity_count,
                    error_message=None,
                    indexed_at=datetime.now(UTC),
                )
            )
            await self.db.commit()

            logger.info(
                "Indexed %d entities for project %s branch %s (commit %s)",
                entity_count,
                project_id,
                branch,
                commit_hash[:8],
            )
            return entity_count

        except Exception as e:
            await self.db.rollback()
            # Update status to failed
            try:
                await self.db.execute(
                    update(OntologyIndexStatus)
                    .where(
                        OntologyIndexStatus.project_id == project_id,
                        OntologyIndexStatus.branch == branch,
                    )
                    .values(
                        status=IndexingStatus.FAILED.value,
                        error_message=str(e)[:2000],
                    )
                )
                await self.db.commit()
            except Exception:
                logger.exception("Failed to update index status to failed")
            raise

    async def _upsert_status(
        self,
        project_id: UUID,
        branch: str,
        new_status: IndexingStatus,
    ) -> OntologyIndexStatus | None:
        """
        Upsert the index status row. Returns None if already indexing
        (to prevent concurrent indexing).
        """
        # Allow reclaiming stale INDEXING locks older than 10 minutes
        stale_threshold = datetime.now(UTC) - timedelta(minutes=10)

        insert_stmt = pg_insert(OntologyIndexStatus).values(
            id=uuid.uuid4(),
            project_id=project_id,
            branch=branch,
            status=new_status.value,
            updated_at=datetime.now(UTC),
        )
        upsert_stmt = insert_stmt.on_conflict_do_update(
            index_elements=["project_id", "branch"],
            set_={
                "status": new_status.value,
                "updated_at": datetime.now(UTC),
            },
            where=(
                (OntologyIndexStatus.status != IndexingStatus.INDEXING.value)
                | (OntologyIndexStatus.updated_at < stale_threshold)
                | (OntologyIndexStatus.updated_at.is_(None))
            ),
        )
        result = await self.db.execute(upsert_stmt)
        await self.db.commit()

        if result.rowcount == 0:  # type: ignore[attr-defined]
            return None

        # Fetch and return the row
        return await self.get_index_status(project_id, branch)

    async def _delete_index_data(self, project_id: UUID, branch: str) -> None:
        """Delete all index data for a project/branch."""
        # Delete entities (cascade will handle labels and annotations)
        await self.db.execute(
            delete(IndexedEntity).where(
                IndexedEntity.project_id == project_id,
                IndexedEntity.branch == branch,
            )
        )
        # Delete hierarchy rows directly (no FK to entities)
        await self.db.execute(
            delete(IndexedHierarchy).where(
                IndexedHierarchy.project_id == project_id,
                IndexedHierarchy.branch == branch,
            )
        )

    async def _index_graph(self, project_id: UUID, branch: str, graph: Graph) -> int:
        """Extract data from RDF graph and insert into index tables.

        Flushes each buffer when it reaches BATCH_SIZE to avoid
        accumulating the entire projection in memory for large ontologies.
        """
        owl_thing = OWL.Thing
        entity_count = 0

        # Buffers flushed incrementally at BATCH_SIZE
        entity_rows: list[dict[str, Any]] = []
        label_rows: list[dict[str, Any]] = []
        hierarchy_rows: list[dict[str, Any]] = []
        annotation_rows: list[dict[str, Any]] = []

        # Track entity IDs by IRI for label/annotation FK
        entity_ids: dict[str, uuid.UUID] = {}

        for rdf_type, entity_type in RDF_TYPE_MAP:
            for subject in graph.subjects(RDF.type, rdf_type):
                if not isinstance(subject, URIRef):
                    continue
                if subject == owl_thing:
                    continue

                iri_str = str(subject)

                # Skip if already processed (entity might have multiple types)
                if iri_str in entity_ids:
                    continue

                entity_id = uuid.uuid4()
                entity_ids[iri_str] = entity_id
                local_name = _extract_local_name(iri_str)

                # Check deprecated
                deprecated = False
                for obj in graph.objects(subject, OWL.deprecated):
                    if str(obj).lower() in ("true", "1"):
                        deprecated = True
                        break

                entity_rows.append(
                    {
                        "id": entity_id,
                        "project_id": project_id,
                        "branch": branch,
                        "iri": iri_str,
                        "local_name": local_name,
                        "entity_type": entity_type,
                        "deprecated": deprecated,
                    }
                )
                entity_count += 1

                # Extract labels
                for prop_iri_str, prop_uri in LABEL_PROPERTIES:
                    for obj in graph.objects(subject, prop_uri):
                        if isinstance(obj, RDFLiteral):
                            label_rows.append(
                                {
                                    "id": uuid.uuid4(),
                                    "entity_id": entity_id,
                                    "property_iri": prop_iri_str,
                                    "value": str(obj),
                                    "lang": obj.language,
                                }
                            )

                # Extract hierarchy (only for classes)
                if entity_type == ENTITY_TYPE_CLASS:
                    for parent in graph.objects(subject, RDFS.subClassOf):
                        if isinstance(parent, URIRef):
                            hierarchy_rows.append(
                                {
                                    "id": uuid.uuid4(),
                                    "project_id": project_id,
                                    "branch": branch,
                                    "child_iri": iri_str,
                                    "parent_iri": str(parent),
                                }
                            )

                # Extract rdfs:comment as annotation (handled separately from
                # ANNOTATION_PROPERTIES in ontology.py, but we index it here
                # so get_class_detail can retrieve comments)
                for obj in graph.objects(subject, RDFS.comment):
                    if isinstance(obj, RDFLiteral):
                        annotation_rows.append(
                            {
                                "id": uuid.uuid4(),
                                "entity_id": entity_id,
                                "property_iri": str(RDFS.comment),
                                "value": str(obj),
                                "lang": obj.language,
                                "is_uri": False,
                            }
                        )

                # Extract annotations (beyond labels)
                for _prop_label, prop_uri in ANNOTATION_PROPERTIES.items():
                    for obj in graph.objects(subject, prop_uri):
                        if isinstance(obj, RDFLiteral):
                            annotation_rows.append(
                                {
                                    "id": uuid.uuid4(),
                                    "entity_id": entity_id,
                                    "property_iri": str(prop_uri),
                                    "value": str(obj),
                                    "lang": obj.language,
                                    "is_uri": False,
                                }
                            )
                        elif isinstance(obj, URIRef):
                            annotation_rows.append(
                                {
                                    "id": uuid.uuid4(),
                                    "entity_id": entity_id,
                                    "property_iri": str(prop_uri),
                                    "value": str(obj),
                                    "lang": None,
                                    "is_uri": True,
                                }
                            )

                # Flush buffers incrementally to avoid unbounded memory growth.
                # Always flush entities first (labels/annotations have FK to entities).
                needs_flush = (
                    len(entity_rows) >= BATCH_SIZE
                    or len(label_rows) >= BATCH_SIZE
                    or len(hierarchy_rows) >= BATCH_SIZE
                    or len(annotation_rows) >= BATCH_SIZE
                )
                if needs_flush:
                    await self._flush_buffer(IndexedEntity, entity_rows)
                    await self._flush_buffer(IndexedLabel, label_rows)
                    await self._flush_buffer(IndexedHierarchy, hierarchy_rows)
                    await self._flush_buffer(IndexedAnnotation, annotation_rows)

        # Flush remaining rows
        await self._flush_buffer(IndexedEntity, entity_rows)
        await self._flush_buffer(IndexedLabel, label_rows)
        await self._flush_buffer(IndexedHierarchy, hierarchy_rows)
        await self._flush_buffer(IndexedAnnotation, annotation_rows)

        return entity_count

    async def _flush_buffer(self, model: type[Base], rows: list[dict[str, Any]]) -> None:
        """Insert all rows in the buffer and clear it."""
        if not rows:
            return
        await self._batch_insert(model, rows)
        rows.clear()

    async def _batch_insert(self, model: type[Base], rows: list[dict[str, Any]]) -> None:
        """Insert rows in batches."""
        if not rows:
            return
        stmt = sa_insert(model)
        for i in range(0, len(rows), BATCH_SIZE):
            batch = rows[i : i + BATCH_SIZE]
            await self.db.execute(stmt, batch)

    # ──────────────────────────────────────────────
    # Delete operations
    # ──────────────────────────────────────────────

    async def delete_branch_index(
        self, project_id: UUID, branch: str, *, auto_commit: bool = True
    ) -> None:
        """Delete all index data for a project/branch, including status.

        When auto_commit=True (the default), commits the transaction after
        deleting. Pass auto_commit=False when participating in a larger
        transaction — the caller is responsible for committing.
        """
        await self._delete_index_data(project_id, branch)
        await self.db.execute(
            delete(OntologyIndexStatus).where(
                OntologyIndexStatus.project_id == project_id,
                OntologyIndexStatus.branch == branch,
            )
        )
        if auto_commit:
            await self.db.commit()

    # ──────────────────────────────────────────────
    # Query methods
    # ──────────────────────────────────────────────

    async def get_root_classes(
        self,
        project_id: UUID,
        branch: str,
        label_preferences: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Get root classes — classes not appearing as child in hierarchy,
        or whose only parent is owl:Thing.
        """
        owl_thing_iri = str(OWL.Thing)

        # Subquery: IRIs that appear as children with a non-owl:Thing parent
        has_real_parent = (
            select(IndexedHierarchy.child_iri)
            .where(
                IndexedHierarchy.project_id == project_id,
                IndexedHierarchy.branch == branch,
                IndexedHierarchy.parent_iri != owl_thing_iri,
            )
            .correlate(None)
            .scalar_subquery()
        )

        # Count children for each root class
        child_count_sub = (
            select(func.count())
            .select_from(IndexedHierarchy)
            .where(
                IndexedHierarchy.project_id == project_id,
                IndexedHierarchy.branch == branch,
                IndexedHierarchy.parent_iri == IndexedEntity.iri,
            )
            .correlate(IndexedEntity)
            .scalar_subquery()
        )

        stmt = (
            select(
                IndexedEntity.iri,
                IndexedEntity.local_name,
                IndexedEntity.deprecated,
                child_count_sub.label("child_count"),
            )
            .where(
                IndexedEntity.project_id == project_id,
                IndexedEntity.branch == branch,
                IndexedEntity.entity_type == ENTITY_TYPE_CLASS,
                IndexedEntity.iri.notin_(has_real_parent),
                IndexedEntity.iri != owl_thing_iri,
            )
            .order_by(IndexedEntity.local_name)
        )

        result = await self.db.execute(stmt)
        rows = result.all()

        # Bulk-resolve labels for all root classes
        iris = [row.iri for row in rows]
        label_map = await self._resolve_labels_bulk(project_id, branch, iris, label_preferences)

        nodes = [
            {
                "iri": row.iri,
                "label": label_map.get(row.iri) or row.local_name,
                "child_count": row.child_count or 0,
                "deprecated": row.deprecated,
            }
            for row in rows
        ]

        # Sort by resolved label
        nodes.sort(key=lambda n: n["label"].lower())
        return nodes

    async def get_class_children(
        self,
        project_id: UUID,
        branch: str,
        parent_iri: str,
        label_preferences: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Get direct children of a class."""
        # Sub-count of grandchildren
        grandchild_count = (
            select(func.count())
            .select_from(IndexedHierarchy)
            .where(
                IndexedHierarchy.project_id == project_id,
                IndexedHierarchy.branch == branch,
                IndexedHierarchy.parent_iri == IndexedEntity.iri,
            )
            .correlate(IndexedEntity)
            .scalar_subquery()
        )

        stmt = (
            select(
                IndexedEntity.iri,
                IndexedEntity.local_name,
                IndexedEntity.deprecated,
                grandchild_count.label("child_count"),
            )
            .join(
                IndexedHierarchy,
                (IndexedHierarchy.child_iri == IndexedEntity.iri)
                & (IndexedHierarchy.project_id == IndexedEntity.project_id)
                & (IndexedHierarchy.branch == IndexedEntity.branch),
            )
            .where(
                IndexedEntity.project_id == project_id,
                IndexedEntity.branch == branch,
                IndexedEntity.entity_type == ENTITY_TYPE_CLASS,
                IndexedHierarchy.parent_iri == parent_iri,
            )
            .order_by(IndexedEntity.local_name)
        )

        result = await self.db.execute(stmt)
        rows = result.all()

        # Bulk-resolve labels for all children
        iris = [row.iri for row in rows]
        label_map = await self._resolve_labels_bulk(project_id, branch, iris, label_preferences)

        nodes = [
            {
                "iri": row.iri,
                "label": label_map.get(row.iri) or row.local_name,
                "child_count": row.child_count or 0,
                "deprecated": row.deprecated,
            }
            for row in rows
        ]

        nodes.sort(key=lambda n: n["label"].lower())
        return nodes

    async def get_class_detail(
        self,
        project_id: UUID,
        branch: str,
        class_iri: str,
        label_preferences: list[str] | None = None,
    ) -> dict[str, Any] | None:
        """Get full details for a class."""
        # Get entity
        result = await self.db.execute(
            select(IndexedEntity).where(
                IndexedEntity.project_id == project_id,
                IndexedEntity.branch == branch,
                IndexedEntity.iri == class_iri,
                IndexedEntity.entity_type == ENTITY_TYPE_CLASS,
            )
        )
        entity = result.scalar_one_or_none()
        if entity is None:
            return None

        # Get labels (rdfs:label specifically)
        # Lang fallback: "en" for labels/comments (human text), "" for annotations
        # (may include URIs). Matches ontology.py _class_to_response behavior.
        rdfs_label_iri = str(RDFS.label)
        labels_result = await self.db.execute(
            select(IndexedLabel).where(
                IndexedLabel.entity_id == entity.id,
                IndexedLabel.property_iri == rdfs_label_iri,
            )
        )
        labels = [
            {"value": lbl.value, "lang": lbl.lang or "en"} for lbl in labels_result.scalars().all()
        ]

        # Get comments (from annotations with rdfs:comment property)
        rdfs_comment_iri = str(RDFS.comment)
        comments_result = await self.db.execute(
            select(IndexedAnnotation).where(
                IndexedAnnotation.entity_id == entity.id,
                IndexedAnnotation.property_iri == rdfs_comment_iri,
            )
        )
        comments = [
            {"value": a.value, "lang": a.lang or "en"} for a in comments_result.scalars().all()
        ]

        # Get parent IRIs
        parents_result = await self.db.execute(
            select(IndexedHierarchy.parent_iri).where(
                IndexedHierarchy.project_id == project_id,
                IndexedHierarchy.branch == branch,
                IndexedHierarchy.child_iri == class_iri,
            )
        )
        parent_iris = [row[0] for row in parents_result.all()]

        # Resolve parent labels in bulk
        parent_label_map = await self._resolve_labels_bulk(
            project_id, branch, parent_iris, label_preferences
        )
        parent_labels: dict[str, str] = {
            iri: parent_label_map.get(iri) or _extract_local_name(iri) for iri in parent_iris
        }

        # Count children
        child_count_result = await self.db.execute(
            select(func.count()).where(
                IndexedHierarchy.project_id == project_id,
                IndexedHierarchy.branch == branch,
                IndexedHierarchy.parent_iri == class_iri,
            )
        )
        child_count = child_count_result.scalar() or 0

        # Instance counting via index is not supported —
        # RDF stores (individual, rdf:type, class) which we don't index as hierarchy.
        # Return None so the frontend can distinguish "not indexed" from "zero".
        instance_count = None

        # Get annotations (excluding rdfs:comment and label properties
        # which are already returned via IndexedLabel)
        label_property_iris = {str(uri) for _, uri in LABEL_PROPERTIES}
        excluded_iris = label_property_iris | {rdfs_comment_iri}
        annotations_result = await self.db.execute(
            select(IndexedAnnotation).where(
                IndexedAnnotation.entity_id == entity.id,
                IndexedAnnotation.property_iri.notin_(excluded_iris),
            )
        )
        annotations_by_prop: dict[str, list[dict[str, str]]] = {}
        for ann in annotations_result.scalars().all():
            key = ann.property_iri
            if key not in annotations_by_prop:
                annotations_by_prop[key] = []
            annotations_by_prop[key].append(
                {
                    "value": ann.value,
                    "lang": ann.lang or "",
                }
            )

        # Build annotation property list matching the response format
        annotation_list = []
        for prop_iri, values in annotations_by_prop.items():
            # Find the short label for this property
            prop_label = prop_iri
            for short_name, uri in ANNOTATION_PROPERTIES.items():
                if str(uri) == prop_iri:
                    prop_label = short_name
                    break

            annotation_list.append(
                {
                    "property_iri": prop_iri,
                    "property_label": prop_label,
                    "values": values,
                }
            )

        return {
            "iri": entity.iri,
            "labels": labels,
            "comments": comments,
            "deprecated": entity.deprecated,
            "parent_iris": parent_iris,
            "parent_labels": parent_labels,
            "equivalent_iris": None,
            "disjoint_iris": None,
            "child_count": child_count,
            "instance_count": instance_count,
            "annotations": annotation_list,
        }

    async def get_ancestor_path(
        self,
        project_id: UUID,
        branch: str,
        class_iri: str,
        label_preferences: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Get the path from root to a specific class using recursive CTE.

        Returns a list of tree nodes from root down to (but not including)
        the target class.
        """
        owl_thing_iri = str(OWL.Thing)

        # Check if entity exists
        exists_result = await self.db.execute(
            select(IndexedEntity.iri).where(
                IndexedEntity.project_id == project_id,
                IndexedEntity.branch == branch,
                IndexedEntity.iri == class_iri,
                IndexedEntity.entity_type == ENTITY_TYPE_CLASS,
            )
        )
        if exists_result.scalar_one_or_none() is None:
            return []

        # Use raw SQL for recursive CTE as it's cleaner
        cte_sql = text("""
            WITH RECURSIVE ancestors AS (
                SELECT parent_iri, child_iri, 1 as depth
                FROM indexed_hierarchy
                WHERE project_id = :project_id
                  AND branch = :branch
                  AND child_iri = :class_iri
                  AND parent_iri != :owl_thing

                UNION ALL

                SELECT h.parent_iri, h.child_iri, a.depth + 1
                FROM indexed_hierarchy h
                JOIN ancestors a ON h.child_iri = a.parent_iri
                WHERE h.project_id = :project_id
                  AND h.branch = :branch
                  AND h.parent_iri != :owl_thing
                  AND a.depth < 100
            )
            SELECT DISTINCT parent_iri FROM ancestors
            ORDER BY parent_iri
        """)

        result = await self.db.execute(
            cte_sql,
            {
                "project_id": str(project_id),
                "branch": branch,
                "class_iri": class_iri,
                "owl_thing": owl_thing_iri,
            },
        )
        ancestor_iris = [row[0] for row in result.all()]

        if not ancestor_iris:
            return []

        # Build path in correct order (root to target)
        # We need to walk the hierarchy to order them
        path = await self._order_ancestor_path(
            project_id, branch, class_iri, ancestor_iris, owl_thing_iri
        )

        # Batch-fetch all data for path nodes to avoid N+1 queries

        # 1. Entity info (id, deprecated) for all path IRIs
        entities_result = await self.db.execute(
            select(IndexedEntity.id, IndexedEntity.iri, IndexedEntity.deprecated).where(
                IndexedEntity.project_id == project_id,
                IndexedEntity.branch == branch,
                IndexedEntity.iri.in_(path),
            )
        )
        entity_map: dict[str, tuple[uuid.UUID, bool]] = {}
        entity_ids: list[uuid.UUID] = []
        for row in entities_result.all():
            entity_map[row.iri] = (row.id, row.deprecated)
            entity_ids.append(row.id)

        # 2. Child counts grouped by parent_iri
        child_counts_result = await self.db.execute(
            select(
                IndexedHierarchy.parent_iri,
                func.count().label("cnt"),
            )
            .where(
                IndexedHierarchy.project_id == project_id,
                IndexedHierarchy.branch == branch,
                IndexedHierarchy.parent_iri.in_(path),
            )
            .group_by(IndexedHierarchy.parent_iri)
        )
        child_count_map: dict[str, int] = {
            row.parent_iri: row.cnt for row in child_counts_result.all()
        }

        # 3. Bulk label resolution
        labels_result = await self.db.execute(
            select(IndexedLabel).where(IndexedLabel.entity_id.in_(entity_ids))
        )
        labels_by_entity: dict[uuid.UUID, list[Any]] = {}
        for lbl in labels_result.scalars().all():
            labels_by_entity.setdefault(lbl.entity_id, []).append(lbl)

        prefs = label_preferences or DEFAULT_LABEL_PREFERENCES

        # Assemble nodes from in-memory maps
        nodes = []
        for iri in path:
            entity_info = entity_map.get(iri)
            entity_id = entity_info[0] if entity_info else None
            deprecated = entity_info[1] if entity_info else False

            label = (
                self._pick_preferred_label(labels_by_entity.get(entity_id, []), prefs)
                if entity_id
                else None
            )

            nodes.append(
                {
                    "iri": iri,
                    "label": label or _extract_local_name(iri),
                    "child_count": child_count_map.get(iri, 0),
                    "deprecated": deprecated,
                }
            )

        return nodes

    async def _order_ancestor_path(
        self,
        project_id: UUID,
        branch: str,
        target_iri: str,
        ancestor_iris: list[str],
        owl_thing_iri: str,
    ) -> list[str]:
        """Order ancestors from root to nearest parent of target."""
        if not ancestor_iris:
            return []

        ancestor_set = set(ancestor_iris)

        # Build child -> [parents in ancestor_set] map with a single query.
        # Include target_iri so we can walk upward from it.
        all_children = list(ancestor_set | {target_iri})
        result = await self.db.execute(
            select(IndexedHierarchy.child_iri, IndexedHierarchy.parent_iri).where(
                IndexedHierarchy.project_id == project_id,
                IndexedHierarchy.branch == branch,
                IndexedHierarchy.child_iri.in_(all_children),
                IndexedHierarchy.parent_iri != owl_thing_iri,
            )
        )
        parents_by_child: dict[str, list[str]] = {}
        for row in result.all():
            if row[1] in ancestor_set:
                parents_by_child.setdefault(row[0], []).append(row[1])

        # Walk from target upward using the in-memory map
        path: list[str] = []
        visited: set[str] = set()
        current = target_iri

        while True:
            if current in visited:
                break
            visited.add(current)

            ancestor_parents = sorted(parents_by_child.get(current, []))
            if not ancestor_parents:
                break

            parent = ancestor_parents[0]
            path.append(parent)
            current = parent

        path.reverse()
        return path

    async def get_class_count(self, project_id: UUID, branch: str) -> int:
        """Get total number of classes in the index."""
        owl_thing_iri = str(OWL.Thing)
        result = await self.db.execute(
            select(func.count()).where(
                IndexedEntity.project_id == project_id,
                IndexedEntity.branch == branch,
                IndexedEntity.entity_type == ENTITY_TYPE_CLASS,
                IndexedEntity.iri != owl_thing_iri,
            )
        )
        return result.scalar() or 0

    async def search_entities(
        self,
        project_id: UUID,
        branch: str,
        query: str,
        entity_types: list[str] | None = None,
        label_preferences: list[str] | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """
        Search for entities using trigram matching on local_name, iri, and labels.

        Paging is pushed into SQL and labels are resolved in bulk to avoid N+1.
        """
        # Map frontend entity types to index entity types
        type_mapping: dict[str, list[str]] = {
            "class": [ENTITY_TYPE_CLASS],
            "property": [
                ENTITY_TYPE_OBJECT_PROPERTY,
                ENTITY_TYPE_DATATYPE_PROPERTY,
                ENTITY_TYPE_ANNOTATION_PROPERTY,
            ],
            "individual": [ENTITY_TYPE_INDIVIDUAL],
        }

        allowed_types = entity_types or ["class", "property", "individual"]
        index_types: list[str] = []
        for t in allowed_types:
            if t in type_mapping:
                index_types.extend(type_mapping[t])

        owl_thing_iri = str(OWL.Thing)

        # Base filter conditions
        base_where = [
            IndexedEntity.project_id == project_id,
            IndexedEntity.branch == branch,
            IndexedEntity.entity_type.in_(index_types),
            IndexedEntity.iri != owl_thing_iri,
        ]

        if query != "*":
            query_pattern = f"%{query}%"
            # Subquery: entity IDs matching via labels
            label_match = (
                select(IndexedLabel.entity_id)
                .join(IndexedEntity, IndexedLabel.entity_id == IndexedEntity.id)
                .where(
                    IndexedEntity.project_id == project_id,
                    IndexedEntity.branch == branch,
                    IndexedLabel.value.ilike(query_pattern),
                )
                .scalar_subquery()
            )
            base_where.append(
                IndexedEntity.local_name.ilike(query_pattern)
                | IndexedEntity.iri.ilike(query_pattern)
                | IndexedEntity.id.in_(label_match)
            )

        # Count total matches in SQL
        count_stmt = select(func.count()).select_from(IndexedEntity).where(*base_where)
        total = (await self.db.execute(count_stmt)).scalar() or 0

        # Fetch paged results
        stmt = (
            select(
                IndexedEntity.id,
                IndexedEntity.iri,
                IndexedEntity.local_name,
                IndexedEntity.entity_type,
                IndexedEntity.deprecated,
            )
            .where(*base_where)
            .order_by(IndexedEntity.local_name)
            .limit(limit)
        )

        result = await self.db.execute(stmt)
        rows = result.all()

        if not rows:
            return {"results": [], "total": total}

        # Bulk-resolve labels for the returned page
        entity_ids = [row.id for row in rows]
        labels_result = await self.db.execute(
            select(IndexedLabel).where(IndexedLabel.entity_id.in_(entity_ids))
        )
        # Group labels by entity_id
        labels_by_entity: dict[uuid.UUID, list[Any]] = {}
        for lbl in labels_result.scalars().all():
            labels_by_entity.setdefault(lbl.entity_id, []).append(lbl)

        # Map entity types back to API types
        reverse_type_map = {
            ENTITY_TYPE_CLASS: "class",
            ENTITY_TYPE_OBJECT_PROPERTY: "property",
            ENTITY_TYPE_DATATYPE_PROPERTY: "property",
            ENTITY_TYPE_ANNOTATION_PROPERTY: "property",
            ENTITY_TYPE_INDIVIDUAL: "individual",
        }

        prefs = label_preferences or DEFAULT_LABEL_PREFERENCES
        results = []
        for row in rows:
            label = self._pick_preferred_label(labels_by_entity.get(row.id, []), prefs)
            results.append(
                {
                    "iri": row.iri,
                    "label": label or row.local_name,
                    "entity_type": reverse_type_map.get(row.entity_type, row.entity_type),
                    "deprecated": row.deprecated,
                }
            )

        # Sort: prefix matches first, then alphabetical.
        # NOTE: This runs after SQL LIMIT, so better prefix matches beyond the
        # limit may be excluded. To fix, either push prefix-ordering into the SQL
        # query (e.g., CASE WHEN on label similarity) or over-fetch and trim.
        if query != "*":
            query_lower = query.lower()

            def sort_key(r: dict[str, Any]) -> tuple[int, str]:
                label_lower = r["label"].lower()
                if label_lower.startswith(query_lower):
                    return (0, label_lower)
                return (1, label_lower)

            results.sort(key=sort_key)

        return {"results": results, "total": total}

    @staticmethod
    def _pick_preferred_label(
        labels: list[Any],
        preferences: list[str],
    ) -> str | None:
        """Pick the preferred label from a pre-fetched list (no DB queries)."""
        if not labels:
            return None

        for pref_string in preferences:
            if "@" in pref_string:
                prop_part, lang = pref_string.rsplit("@", 1)
            else:
                prop_part = pref_string
                lang = None

            prop_uri_ref = LABEL_PROPERTY_MAP.get(prop_part)
            if prop_uri_ref is None:
                continue
            prop_iri_str = str(prop_uri_ref)

            for label in labels:
                if label.property_iri != prop_iri_str:
                    continue
                if lang is None or (lang == "" and label.lang is None) or label.lang == lang:
                    return label.value  # type: ignore[no-any-return]

        # Fallback: any rdfs:label
        rdfs_label_iri = str(RDFS.label)
        for label in labels:
            if label.property_iri == rdfs_label_iri:
                return label.value  # type: ignore[no-any-return]

        return None

    # ──────────────────────────────────────────────
    # Label resolution
    # ──────────────────────────────────────────────

    async def _resolve_labels_bulk(
        self,
        project_id: UUID,
        branch: str,
        iris: list[str],
        preferences: list[str] | None = None,
    ) -> dict[str, str | None]:
        """Resolve preferred labels for multiple IRIs in a single DB query.

        Returns a dict mapping IRI -> preferred label (or None).
        """
        if not iris:
            return {}

        prefs = preferences or DEFAULT_LABEL_PREFERENCES

        # Get entity IDs for all IRIs
        entities_result = await self.db.execute(
            select(IndexedEntity.id, IndexedEntity.iri).where(
                IndexedEntity.project_id == project_id,
                IndexedEntity.branch == branch,
                IndexedEntity.iri.in_(iris),
            )
        )
        iri_to_entity_id: dict[str, uuid.UUID] = {}
        entity_ids: list[uuid.UUID] = []
        for row in entities_result.all():
            iri_to_entity_id[row.iri] = row.id
            entity_ids.append(row.id)

        if not entity_ids:
            return dict.fromkeys(iris)

        # Bulk fetch all labels
        labels_result = await self.db.execute(
            select(IndexedLabel).where(IndexedLabel.entity_id.in_(entity_ids))
        )
        labels_by_entity: dict[uuid.UUID, list[Any]] = {}
        for lbl in labels_result.scalars().all():
            labels_by_entity.setdefault(lbl.entity_id, []).append(lbl)

        # Resolve for each IRI
        result: dict[str, str | None] = {}
        for iri in iris:
            entity_id = iri_to_entity_id.get(iri)
            if entity_id is None:
                result[iri] = None
            else:
                result[iri] = self._pick_preferred_label(labels_by_entity.get(entity_id, []), prefs)
        return result
