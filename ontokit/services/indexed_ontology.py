"""Indexed ontology service — wrapper that uses SQL index when available, RDFLib fallback.

This service provides the same query interface as OntologyService but checks
the PostgreSQL index first for faster reads. If the index isn't ready or is
stale, it falls back to the RDFLib graph path and enqueues a re-index.
"""

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from ontokit.schemas.ontology import LocalizedString
from ontokit.schemas.owl_class import (
    AnnotationProperty,
    EntitySearchResponse,
    EntitySearchResult,
    OWLClassResponse,
    OWLClassTreeNode,
)
from ontokit.services.ontology import OntologyService
from ontokit.services.ontology_index import OntologyIndexService

logger = logging.getLogger(__name__)


class IndexedOntologyService:
    """
    Wrapper that routes ontology queries through the PostgreSQL index
    when available, falling back to RDFLib graph queries otherwise.
    """

    def __init__(
        self,
        ontology_service: OntologyService,
        db: AsyncSession,
    ) -> None:
        self.ontology = ontology_service
        self.index = OntologyIndexService(db)
        self.db = db

    async def _should_use_index(self, project_id: UUID, branch: str) -> bool:
        """Check if the index is ready and should be used."""
        try:
            return await self.index.is_index_ready(project_id, branch)
        except Exception:
            # Table may not exist if migration hasn't run yet
            return False

    async def _enqueue_reindex_if_stale(
        self,
        project_id: UUID,
        branch: str,
        commit_hash: str | None = None,
    ) -> None:
        """Enqueue a re-index job if the index is stale or missing."""
        try:
            from ontokit.api.utils.redis import get_arq_pool

            pool = await get_arq_pool()
            if pool is None:
                return

            status = await self.index.get_index_status(project_id, branch)
            if commit_hash:
                # Have a commit hash — only enqueue if index exists and is stale
                if status is None or not await self.index.is_index_stale(
                    project_id, branch, commit_hash
                ):
                    return
            else:
                # No commit hash — only enqueue if no index exists at all
                if status is not None:
                    return

            await pool.enqueue_job(
                "run_ontology_index_task",
                str(project_id),
                branch,
                commit_hash,
            )
            logger.info("Enqueued re-index for project %s branch %s", project_id, branch)
        except Exception:
            logger.debug("Failed to enqueue re-index", exc_info=True)

    # ──────────────────────────────────────────────
    # Tree navigation
    # ──────────────────────────────────────────────

    async def get_root_tree_nodes(
        self,
        project_id: UUID,
        label_preferences: list[str] | None = None,
        branch: str = "main",
    ) -> list[OWLClassTreeNode]:
        """Get root classes as tree nodes."""
        if await self._should_use_index(project_id, branch):
            try:
                nodes_data = await self.index.get_root_classes(
                    project_id, branch, label_preferences
                )
                return [
                    OWLClassTreeNode(
                        iri=n["iri"],
                        label=n["label"],
                        child_count=n["child_count"],
                        deprecated=n["deprecated"],
                    )
                    for n in nodes_data
                ]
            except Exception:
                logger.warning(
                    "Index query failed for root classes, falling back to RDFLib",
                    exc_info=True,
                )

        # Fallback to RDFLib — enqueue reindex for next time
        await self._enqueue_reindex_if_stale(project_id, branch)
        return await self.ontology.get_root_tree_nodes(project_id, label_preferences, branch)

    async def get_children_tree_nodes(
        self,
        project_id: UUID,
        class_iri: str,
        label_preferences: list[str] | None = None,
        branch: str = "main",
    ) -> list[OWLClassTreeNode]:
        """Get children of a class as tree nodes."""
        if await self._should_use_index(project_id, branch):
            try:
                nodes_data = await self.index.get_class_children(
                    project_id, branch, class_iri, label_preferences
                )
                return [
                    OWLClassTreeNode(
                        iri=n["iri"],
                        label=n["label"],
                        child_count=n["child_count"],
                        deprecated=n["deprecated"],
                    )
                    for n in nodes_data
                ]
            except Exception:
                logger.warning(
                    "Index query failed for children, falling back to RDFLib",
                    exc_info=True,
                )

        await self._enqueue_reindex_if_stale(project_id, branch)
        return await self.ontology.get_children_tree_nodes(
            project_id, class_iri, label_preferences, branch
        )

    async def get_class_count(self, project_id: UUID, branch: str = "main") -> int:
        """Get total number of classes."""
        if await self._should_use_index(project_id, branch):
            try:
                return await self.index.get_class_count(project_id, branch)
            except Exception:
                logger.warning(
                    "Index query failed for class count, falling back to RDFLib",
                    exc_info=True,
                )

        await self._enqueue_reindex_if_stale(project_id, branch)
        return await self.ontology.get_class_count(project_id, branch)

    async def get_class(
        self,
        project_id: UUID,
        class_iri: str,
        label_preferences: list[str] | None = None,
        branch: str = "main",
    ) -> OWLClassResponse | None:
        """Get class details."""
        if await self._should_use_index(project_id, branch):
            try:
                detail = await self.index.get_class_detail(
                    project_id, branch, class_iri, label_preferences
                )
                if detail is not None:
                    return OWLClassResponse(
                        iri=detail["iri"],
                        labels=[
                            LocalizedString(value=lbl["value"], lang=lbl["lang"])
                            for lbl in detail["labels"]
                        ],
                        comments=[
                            LocalizedString(value=c["value"], lang=c["lang"])
                            for c in detail["comments"]
                        ],
                        deprecated=detail["deprecated"],
                        parent_iris=detail["parent_iris"],
                        parent_labels=detail["parent_labels"],
                        equivalent_iris=detail["equivalent_iris"],
                        disjoint_iris=detail["disjoint_iris"],
                        child_count=detail["child_count"],
                        instance_count=detail["instance_count"],
                        annotations=[
                            AnnotationProperty(
                                property_iri=a["property_iri"],
                                property_label=a["property_label"],
                                values=[
                                    LocalizedString(value=v["value"], lang=v["lang"])
                                    for v in a["values"]
                                ],
                            )
                            for a in detail["annotations"]
                        ],
                    )
            except Exception:
                logger.warning(
                    "Index query failed for class detail, falling back to RDFLib",
                    exc_info=True,
                )

        await self._enqueue_reindex_if_stale(project_id, branch)
        return await self.ontology.get_class(project_id, class_iri, label_preferences, branch)

    async def get_ancestor_path(
        self,
        project_id: UUID,
        class_iri: str,
        label_preferences: list[str] | None = None,
        branch: str = "main",
    ) -> list[OWLClassTreeNode]:
        """Get ancestor path from root to class."""
        if await self._should_use_index(project_id, branch):
            try:
                nodes_data = await self.index.get_ancestor_path(
                    project_id, branch, class_iri, label_preferences
                )
                return [
                    OWLClassTreeNode(
                        iri=n["iri"],
                        label=n["label"],
                        child_count=n["child_count"],
                        deprecated=n["deprecated"],
                    )
                    for n in nodes_data
                ]
            except Exception:
                logger.warning(
                    "Index query failed for ancestors, falling back to RDFLib",
                    exc_info=True,
                )

        await self._enqueue_reindex_if_stale(project_id, branch)
        return await self.ontology.get_ancestor_path(
            project_id, class_iri, label_preferences, branch
        )

    async def search_entities(
        self,
        project_id: UUID,
        query: str,
        entity_types: list[str] | None = None,
        label_preferences: list[str] | None = None,
        limit: int = 50,
        branch: str = "main",
    ) -> EntitySearchResponse:
        """Search entities."""
        if await self._should_use_index(project_id, branch):
            try:
                result = await self.index.search_entities(
                    project_id, branch, query, entity_types, label_preferences, limit
                )
                return EntitySearchResponse(
                    results=[
                        EntitySearchResult(
                            iri=r["iri"],
                            label=r["label"],
                            entity_type=r["entity_type"],
                            deprecated=r["deprecated"],
                        )
                        for r in result["results"]
                    ],
                    total=result["total"],
                )
            except Exception:
                logger.warning(
                    "Index query failed for search, falling back to RDFLib",
                    exc_info=True,
                )

        await self._enqueue_reindex_if_stale(project_id, branch)
        return await self.ontology.search_entities(
            project_id, query, entity_types, label_preferences, limit, branch
        )

    # ──────────────────────────────────────────────
    # Pass-through methods (always use RDFLib)
    # ──────────────────────────────────────────────

    async def serialize(
        self, ontology_id: UUID, format: str = "turtle", branch: str = "main"
    ) -> str:
        """Serialize ontology — always uses RDFLib."""
        return await self.ontology.serialize(ontology_id, format, branch)
