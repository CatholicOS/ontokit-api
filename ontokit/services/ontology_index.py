"""Ontology index service for PostgreSQL-backed ontology queries.

Provides fast SQL-based queries as an alternative to loading full RDF graphs
into memory. The index is populated from Turtle/RDF files and kept in sync
via background re-indexing triggered on commits.
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from rdflib import Graph, URIRef
from rdflib import Literal as RDFLiteral
from rdflib.namespace import OWL, RDF, RDFS, SKOS
from sqlalchemy import delete, func, select, text, update
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

# RDF type to entity_type mapping
RDF_TYPE_MAP: list[tuple[URIRef, str]] = [
    (OWL.Class, ENTITY_TYPE_CLASS),
    (OWL.ObjectProperty, ENTITY_TYPE_OBJECT_PROPERTY),
    (OWL.DatatypeProperty, ENTITY_TYPE_DATATYPE_PROPERTY),
    (OWL.AnnotationProperty, ENTITY_TYPE_ANNOTATION_PROPERTY),
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
        insert_stmt = pg_insert(OntologyIndexStatus).values(
            id=uuid.uuid4(),
            project_id=project_id,
            branch=branch,
            status=new_status.value,
        )
        upsert_stmt = insert_stmt.on_conflict_do_update(
            index_elements=["project_id", "branch"],
            set_={
                "status": new_status.value,
                "updated_at": datetime.now(UTC),
            },
            where=OntologyIndexStatus.status != IndexingStatus.INDEXING.value,
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
        """Extract data from RDF graph and insert into index tables."""
        owl_thing = OWL.Thing
        entity_count = 0

        # Collect all entities, labels, hierarchy, annotations
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

        # Batch insert all rows
        await self._batch_insert(IndexedEntity, entity_rows)
        await self._batch_insert(IndexedLabel, label_rows)
        await self._batch_insert(IndexedHierarchy, hierarchy_rows)
        await self._batch_insert(IndexedAnnotation, annotation_rows)

        return entity_count

    async def _batch_insert(self, model: type[Base], rows: list[dict[str, Any]]) -> None:
        """Insert rows in batches."""
        if not rows:
            return
        from sqlalchemy import insert

        stmt = insert(model)
        for i in range(0, len(rows), BATCH_SIZE):
            batch = rows[i : i + BATCH_SIZE]
            await self.db.execute(stmt, batch)

    # ──────────────────────────────────────────────
    # Delete operations
    # ──────────────────────────────────────────────

    async def delete_branch_index(
        self, project_id: UUID, branch: str, *, auto_commit: bool = True
    ) -> None:
        """Delete all index data for a project/branch, including status."""
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

        nodes = []
        for row in rows:
            label = await self._resolve_preferred_label(
                project_id, branch, row.iri, label_preferences
            )
            nodes.append(
                {
                    "iri": row.iri,
                    "label": label or row.local_name,
                    "child_count": row.child_count or 0,
                    "deprecated": row.deprecated,
                }
            )

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

        nodes = []
        for row in rows:
            label = await self._resolve_preferred_label(
                project_id, branch, row.iri, label_preferences
            )
            nodes.append(
                {
                    "iri": row.iri,
                    "label": label or row.local_name,
                    "child_count": row.child_count or 0,
                    "deprecated": row.deprecated,
                }
            )

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

        # Resolve parent labels
        parent_labels: dict[str, str] = {}
        for parent_iri in parent_iris:
            label = await self._resolve_preferred_label(
                project_id, branch, parent_iri, label_preferences
            )
            parent_labels[parent_iri] = label or _extract_local_name(parent_iri)

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
        # The RDFLib fallback handles accurate instance counts.
        instance_count = 0

        # Get annotations (excluding rdfs:label and rdfs:comment)
        annotations_result = await self.db.execute(
            select(IndexedAnnotation).where(
                IndexedAnnotation.entity_id == entity.id,
                IndexedAnnotation.property_iri != rdfs_comment_iri,
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
            "equivalent_iris": [],
            "disjoint_iris": [],
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

        # Convert to tree nodes
        nodes = []
        for iri in path:
            label = await self._resolve_preferred_label(project_id, branch, iri, label_preferences)
            # Count children for this ancestor
            child_count_result = await self.db.execute(
                select(func.count()).where(
                    IndexedHierarchy.project_id == project_id,
                    IndexedHierarchy.branch == branch,
                    IndexedHierarchy.parent_iri == iri,
                )
            )
            child_count = child_count_result.scalar() or 0

            # Check deprecated
            dep_result = await self.db.execute(
                select(IndexedEntity.deprecated).where(
                    IndexedEntity.project_id == project_id,
                    IndexedEntity.branch == branch,
                    IndexedEntity.iri == iri,
                )
            )
            deprecated = dep_result.scalar() or False

            nodes.append(
                {
                    "iri": iri,
                    "label": label or _extract_local_name(iri),
                    "child_count": child_count,
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

        # Build parent->child map from hierarchy for the ancestors
        ancestor_set = set(ancestor_iris)
        parent_map: dict[str, str | None] = dict.fromkeys(ancestor_iris)

        result = await self.db.execute(
            select(IndexedHierarchy.child_iri, IndexedHierarchy.parent_iri).where(
                IndexedHierarchy.project_id == project_id,
                IndexedHierarchy.branch == branch,
                IndexedHierarchy.child_iri.in_(ancestor_iris),
                IndexedHierarchy.parent_iri != owl_thing_iri,
            )
        )
        for row in result.all():
            if row[1] in ancestor_set:
                parent_map[row[0]] = row[1]

        # Walk from target upward, collecting the path
        path: list[str] = []
        visited: set[str] = set()
        current = target_iri

        while True:
            if current in visited:
                break
            visited.add(current)

            # Find the parent of current that's in our ancestor set
            parent_result = await self.db.execute(
                select(IndexedHierarchy.parent_iri).where(
                    IndexedHierarchy.project_id == project_id,
                    IndexedHierarchy.branch == branch,
                    IndexedHierarchy.child_iri == current,
                    IndexedHierarchy.parent_iri != owl_thing_iri,
                )
            )
            parents = [r[0] for r in parent_result.all()]
            ancestor_parents = [p for p in parents if p in ancestor_set]

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
        query_pattern = f"%{query}%"

        if query == "*":
            # Match everything
            stmt = (
                select(
                    IndexedEntity.iri,
                    IndexedEntity.local_name,
                    IndexedEntity.entity_type,
                    IndexedEntity.deprecated,
                )
                .where(
                    IndexedEntity.project_id == project_id,
                    IndexedEntity.branch == branch,
                    IndexedEntity.entity_type.in_(index_types),
                    IndexedEntity.iri != owl_thing_iri,
                )
                .order_by(IndexedEntity.local_name)
            )
        else:
            # Subquery: entities matching via labels
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

            stmt = (
                select(
                    IndexedEntity.iri,
                    IndexedEntity.local_name,
                    IndexedEntity.entity_type,
                    IndexedEntity.deprecated,
                )
                .where(
                    IndexedEntity.project_id == project_id,
                    IndexedEntity.branch == branch,
                    IndexedEntity.entity_type.in_(index_types),
                    IndexedEntity.iri != owl_thing_iri,
                    (
                        IndexedEntity.local_name.ilike(query_pattern)
                        | IndexedEntity.iri.ilike(query_pattern)
                        | IndexedEntity.id.in_(label_match)
                    ),
                )
                .order_by(IndexedEntity.local_name)
            )

        result = await self.db.execute(stmt)
        rows = result.all()

        # Map entity types back to API types
        reverse_type_map = {
            ENTITY_TYPE_CLASS: "class",
            ENTITY_TYPE_OBJECT_PROPERTY: "property",
            ENTITY_TYPE_DATATYPE_PROPERTY: "property",
            ENTITY_TYPE_ANNOTATION_PROPERTY: "property",
            ENTITY_TYPE_INDIVIDUAL: "individual",
        }

        results = []
        for row in rows:
            label = await self._resolve_preferred_label(
                project_id, branch, row.iri, label_preferences
            )
            results.append(
                {
                    "iri": row.iri,
                    "label": label or row.local_name,
                    "entity_type": reverse_type_map.get(row.entity_type, row.entity_type),
                    "deprecated": row.deprecated,
                }
            )

        # Sort: prefix matches first, then alphabetical
        query_lower = query.lower()

        def sort_key(r: dict[str, Any]) -> tuple[int, str]:
            label_lower = r["label"].lower()
            if label_lower.startswith(query_lower):
                return (0, label_lower)
            return (1, label_lower)

        if query != "*":
            results.sort(key=sort_key)

        total = len(results)
        results = results[:limit]

        return {"results": results, "total": total}

    # ──────────────────────────────────────────────
    # Label resolution
    # ──────────────────────────────────────────────

    async def _resolve_preferred_label(
        self,
        project_id: UUID,
        branch: str,
        iri: str,
        preferences: list[str] | None = None,
    ) -> str | None:
        """
        Resolve the preferred label for an entity using SQL,
        matching the logic of select_preferred_label() from ontology.py.
        """
        prefs = preferences or DEFAULT_LABEL_PREFERENCES

        # Get entity_id
        entity_result = await self.db.execute(
            select(IndexedEntity.id).where(
                IndexedEntity.project_id == project_id,
                IndexedEntity.branch == branch,
                IndexedEntity.iri == iri,
            )
        )
        entity_id = entity_result.scalar_one_or_none()
        if entity_id is None:
            return None

        # Get all labels for this entity
        labels_result = await self.db.execute(
            select(IndexedLabel).where(IndexedLabel.entity_id == entity_id)
        )
        labels = labels_result.scalars().all()

        if not labels:
            return None

        # Apply preference ordering
        for pref_string in prefs:
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
                    return label.value

        # Fallback: any rdfs:label
        rdfs_label_iri = str(RDFS.label)
        for label in labels:
            if label.property_iri == rdfs_label_iri:
                return label.value

        return None
