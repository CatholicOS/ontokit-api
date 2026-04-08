"""Tests for IndexedOntologyService (ontokit/services/indexed_ontology.py)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from ontokit.services.indexed_ontology import IndexedOntologyService

PROJECT_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
BRANCH = "main"
CLASS_IRI = "http://example.org/ontology#Person"


@pytest.fixture
def mock_ontology_service() -> AsyncMock:
    """Create a mock OntologyService."""
    svc = AsyncMock()
    svc.get_root_tree_nodes = AsyncMock(return_value=[])
    svc.get_children_tree_nodes = AsyncMock(return_value=[])
    svc.get_class_count = AsyncMock(return_value=42)
    svc.get_class = AsyncMock(return_value=None)
    svc.get_ancestor_path = AsyncMock(return_value=[])
    svc.search_entities = AsyncMock(return_value=MagicMock(results=[], total=0))
    svc.serialize = AsyncMock(return_value="<turtle>")
    return svc


@pytest.fixture
def mock_db() -> AsyncMock:
    """Create an async mock of AsyncSession."""
    return AsyncMock()


@pytest.fixture
def service(mock_ontology_service: AsyncMock, mock_db: AsyncMock) -> IndexedOntologyService:
    """Create an IndexedOntologyService with mocked dependencies."""
    svc = IndexedOntologyService(mock_ontology_service, mock_db)
    # Replace the real OntologyIndexService with an AsyncMock for tests.
    svc.index = AsyncMock()
    return svc


class TestShouldUseIndex:
    """Tests for _should_use_index()."""

    @pytest.mark.asyncio
    async def test_returns_true_when_index_ready(self, service: IndexedOntologyService) -> None:
        """Returns True when the index reports ready."""
        service.index.is_index_ready = AsyncMock(return_value=True)  # type: ignore[method-assign]
        result = await service._should_use_index(PROJECT_ID, BRANCH)
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_index_not_ready(
        self, service: IndexedOntologyService
    ) -> None:
        """Returns False when the index is not ready."""
        service.index.is_index_ready = AsyncMock(return_value=False)  # type: ignore[method-assign]
        result = await service._should_use_index(PROJECT_ID, BRANCH)
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_on_exception(self, service: IndexedOntologyService) -> None:
        """Returns False when the index check raises an exception (e.g., table missing)."""
        service.index.is_index_ready = AsyncMock(  # type: ignore[method-assign]
            side_effect=Exception("table not found")
        )
        result = await service._should_use_index(PROJECT_ID, BRANCH)
        assert result is False


class TestGetRootTreeNodesFallback:
    """Tests for get_root_tree_nodes() fallback behavior."""

    @pytest.mark.asyncio
    async def test_falls_back_to_rdflib_when_index_not_ready(
        self,
        service: IndexedOntologyService,
        mock_ontology_service: AsyncMock,
    ) -> None:
        """Falls back to OntologyService when index is not ready."""
        service.index.is_index_ready = AsyncMock(return_value=False)  # type: ignore[method-assign]
        service._enqueue_reindex_if_stale = AsyncMock()  # type: ignore[method-assign]

        await service.get_root_tree_nodes(PROJECT_ID, branch=BRANCH)
        mock_ontology_service.get_root_tree_nodes.assert_awaited_once_with(PROJECT_ID, None, BRANCH)
        service._enqueue_reindex_if_stale.assert_awaited_once_with(PROJECT_ID, BRANCH)

    @pytest.mark.asyncio
    async def test_uses_index_when_ready(
        self,
        service: IndexedOntologyService,
        mock_ontology_service: AsyncMock,
    ) -> None:
        """Uses the index when it is ready."""
        service.index.is_index_ready = AsyncMock(return_value=True)  # type: ignore[method-assign]
        service.index.get_root_classes = AsyncMock(  # type: ignore[method-assign]
            return_value=[
                {"iri": CLASS_IRI, "label": "Person", "child_count": 0, "deprecated": False}
            ]
        )

        nodes = await service.get_root_tree_nodes(PROJECT_ID, branch=BRANCH)
        assert len(nodes) == 1
        assert nodes[0].iri == CLASS_IRI
        mock_ontology_service.get_root_tree_nodes.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_falls_back_when_index_query_fails(
        self,
        service: IndexedOntologyService,
        mock_ontology_service: AsyncMock,
    ) -> None:
        """Falls back to RDFLib when the index query raises an exception."""
        service.index.is_index_ready = AsyncMock(return_value=True)  # type: ignore[method-assign]
        service.index.get_root_classes = AsyncMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("query failed")
        )
        service._enqueue_reindex_if_stale = AsyncMock()  # type: ignore[method-assign]

        await service.get_root_tree_nodes(PROJECT_ID, branch=BRANCH)
        mock_ontology_service.get_root_tree_nodes.assert_awaited_once_with(PROJECT_ID, None, BRANCH)
        service._enqueue_reindex_if_stale.assert_awaited_once_with(PROJECT_ID, BRANCH)


class TestGetClassCount:
    """Tests for get_class_count() delegation."""

    @pytest.mark.asyncio
    async def test_delegates_to_index(
        self, service: IndexedOntologyService, mock_ontology_service: AsyncMock
    ) -> None:
        """Uses the index for class count when ready."""
        service.index.is_index_ready = AsyncMock(return_value=True)  # type: ignore[method-assign]
        service.index.get_class_count = AsyncMock(return_value=100)  # type: ignore[method-assign]

        count = await service.get_class_count(PROJECT_ID, branch=BRANCH)
        assert count == 100
        mock_ontology_service.get_class_count.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_falls_back_to_rdflib(
        self, service: IndexedOntologyService, mock_ontology_service: AsyncMock
    ) -> None:
        """Falls back to OntologyService when index is not ready."""
        service.index.is_index_ready = AsyncMock(return_value=False)  # type: ignore[method-assign]
        service._enqueue_reindex_if_stale = AsyncMock()  # type: ignore[method-assign]
        mock_ontology_service.get_class_count = AsyncMock(return_value=42)

        count = await service.get_class_count(PROJECT_ID, branch=BRANCH)
        assert count == 42
        mock_ontology_service.get_class_count.assert_awaited_once_with(PROJECT_ID, BRANCH)
        service._enqueue_reindex_if_stale.assert_awaited_once_with(PROJECT_ID, BRANCH)

    @pytest.mark.asyncio
    async def test_falls_back_when_index_query_fails(
        self, service: IndexedOntologyService, mock_ontology_service: AsyncMock
    ) -> None:
        """Falls back to OntologyService when the index query raises."""
        service.index.is_index_ready = AsyncMock(  # type: ignore[method-assign]
            return_value=True
        )
        service.index.get_class_count = AsyncMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("query failed")
        )
        service._enqueue_reindex_if_stale = AsyncMock()  # type: ignore[method-assign]
        mock_ontology_service.get_class_count = AsyncMock(return_value=42)

        count = await service.get_class_count(PROJECT_ID, branch=BRANCH)
        assert count == 42
        mock_ontology_service.get_class_count.assert_awaited_once_with(PROJECT_ID, BRANCH)
        service._enqueue_reindex_if_stale.assert_awaited_once_with(PROJECT_ID, BRANCH)


class TestSerializePassThrough:
    """Tests for serialize() pass-through."""

    @pytest.mark.asyncio
    async def test_always_delegates_to_ontology_service(
        self, service: IndexedOntologyService, mock_ontology_service: AsyncMock
    ) -> None:
        """serialize() always uses OntologyService, never the index."""
        mock_ontology_service.serialize = AsyncMock(return_value="<turtle content>")

        result = await service.serialize(PROJECT_ID, format="turtle", branch=BRANCH)
        assert result == "<turtle content>"
        mock_ontology_service.serialize.assert_awaited_once_with(PROJECT_ID, "turtle", BRANCH)


# ──────────────────────────────────────────────
# _enqueue_reindex_if_stale
# ──────────────────────────────────────────────


class TestEnqueueReindexIfStale:
    """Tests for _enqueue_reindex_if_stale()."""

    @pytest.mark.asyncio
    async def test_no_pool_returns_early(self, service: IndexedOntologyService) -> None:
        """Returns immediately when ARQ pool is None."""
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "ontokit.services.indexed_ontology.IndexedOntologyService._enqueue_reindex_if_stale",
                service._enqueue_reindex_if_stale,
            )

            # Patch get_arq_pool to return None
            async def _fake_get_arq_pool() -> None:
                return None

            mp.setattr("ontokit.api.utils.redis.get_arq_pool", _fake_get_arq_pool)
            await service._enqueue_reindex_if_stale(PROJECT_ID, BRANCH)
            # No exception means success; index methods should not be called for status
            # since we return early when pool is None.

    @pytest.mark.asyncio
    async def test_enqueues_when_stale_with_commit_hash(
        self, service: IndexedOntologyService
    ) -> None:
        """Enqueues a re-index when index is stale (commit hash provided)."""
        mock_pool = AsyncMock()
        mock_pool.enqueue_job = AsyncMock()

        async def _fake_get_arq_pool() -> AsyncMock:
            return mock_pool

        service.index.get_index_status = AsyncMock(return_value="some_status")  # type: ignore[method-assign]
        service.index.is_index_stale = AsyncMock(return_value=True)  # type: ignore[method-assign]

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("ontokit.api.utils.redis.get_arq_pool", _fake_get_arq_pool)
            await service._enqueue_reindex_if_stale(PROJECT_ID, BRANCH, commit_hash="abc123")

        mock_pool.enqueue_job.assert_awaited_once_with(
            "run_ontology_index_task",
            str(PROJECT_ID),
            BRANCH,
            "abc123",
        )

    @pytest.mark.asyncio
    async def test_skips_enqueue_when_not_stale(self, service: IndexedOntologyService) -> None:
        """Does not enqueue when index exists and is not stale."""
        mock_pool = AsyncMock()
        mock_pool.enqueue_job = AsyncMock()

        async def _fake_get_arq_pool() -> AsyncMock:
            return mock_pool

        service.index.get_index_status = AsyncMock(return_value="some_status")  # type: ignore[method-assign]
        service.index.is_index_stale = AsyncMock(return_value=False)  # type: ignore[method-assign]

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("ontokit.api.utils.redis.get_arq_pool", _fake_get_arq_pool)
            await service._enqueue_reindex_if_stale(PROJECT_ID, BRANCH, commit_hash="abc123")

        mock_pool.enqueue_job.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_skips_when_no_commit_hash_and_status_exists(
        self, service: IndexedOntologyService
    ) -> None:
        """Does not enqueue when no commit hash and status already exists."""
        mock_pool = AsyncMock()
        mock_pool.enqueue_job = AsyncMock()

        async def _fake_get_arq_pool() -> AsyncMock:
            return mock_pool

        service.index.get_index_status = AsyncMock(return_value="some_status")  # type: ignore[method-assign]

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("ontokit.api.utils.redis.get_arq_pool", _fake_get_arq_pool)
            await service._enqueue_reindex_if_stale(PROJECT_ID, BRANCH)

        mock_pool.enqueue_job.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_enqueues_when_no_commit_hash_and_no_status(
        self, service: IndexedOntologyService
    ) -> None:
        """Enqueues when no commit hash and no existing index status."""
        mock_pool = AsyncMock()
        mock_pool.enqueue_job = AsyncMock()

        async def _fake_get_arq_pool() -> AsyncMock:
            return mock_pool

        service.index.get_index_status = AsyncMock(return_value=None)  # type: ignore[method-assign]

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("ontokit.api.utils.redis.get_arq_pool", _fake_get_arq_pool)
            await service._enqueue_reindex_if_stale(PROJECT_ID, BRANCH)

        mock_pool.enqueue_job.assert_awaited_once_with(
            "run_ontology_index_task",
            str(PROJECT_ID),
            BRANCH,
            None,
        )

    @pytest.mark.asyncio
    async def test_skips_when_commit_hash_but_no_status(
        self, service: IndexedOntologyService
    ) -> None:
        """Does not enqueue when commit hash provided but no index status exists."""
        mock_pool = AsyncMock()
        mock_pool.enqueue_job = AsyncMock()

        async def _fake_get_arq_pool() -> AsyncMock:
            return mock_pool

        service.index.get_index_status = AsyncMock(return_value=None)  # type: ignore[method-assign]

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("ontokit.api.utils.redis.get_arq_pool", _fake_get_arq_pool)
            await service._enqueue_reindex_if_stale(PROJECT_ID, BRANCH, commit_hash="abc123")

        mock_pool.enqueue_job.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_handles_exception_gracefully(self, service: IndexedOntologyService) -> None:
        """Catches exceptions and logs them without raising."""

        async def _fake_get_arq_pool() -> AsyncMock:
            raise RuntimeError("redis down")

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("ontokit.api.utils.redis.get_arq_pool", _fake_get_arq_pool)
            # Should not raise
            await service._enqueue_reindex_if_stale(PROJECT_ID, BRANCH)


# ──────────────────────────────────────────────
# get_children_tree_nodes
# ──────────────────────────────────────────────


class TestGetChildrenTreeNodes:
    """Tests for get_children_tree_nodes()."""

    @pytest.mark.asyncio
    async def test_uses_index_when_ready(
        self, service: IndexedOntologyService, mock_ontology_service: AsyncMock
    ) -> None:
        """Uses the index path when index is ready."""
        service.index.is_index_ready = AsyncMock(return_value=True)  # type: ignore[method-assign]
        service.index.get_class_children = AsyncMock(  # type: ignore[method-assign]
            return_value=[
                {"iri": CLASS_IRI, "label": "Person", "child_count": 2, "deprecated": False}
            ]
        )

        nodes = await service.get_children_tree_nodes(PROJECT_ID, CLASS_IRI, branch=BRANCH)
        assert len(nodes) == 1
        assert nodes[0].iri == CLASS_IRI
        assert nodes[0].child_count == 2
        mock_ontology_service.get_children_tree_nodes.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_falls_back_when_index_not_ready(
        self, service: IndexedOntologyService, mock_ontology_service: AsyncMock
    ) -> None:
        """Falls back to OntologyService when index is not ready."""
        service.index.is_index_ready = AsyncMock(return_value=False)  # type: ignore[method-assign]
        service._enqueue_reindex_if_stale = AsyncMock()  # type: ignore[method-assign]

        await service.get_children_tree_nodes(PROJECT_ID, CLASS_IRI, branch=BRANCH)
        mock_ontology_service.get_children_tree_nodes.assert_awaited_once_with(
            PROJECT_ID, CLASS_IRI, None, BRANCH
        )

    @pytest.mark.asyncio
    async def test_falls_back_when_index_query_fails(
        self, service: IndexedOntologyService, mock_ontology_service: AsyncMock
    ) -> None:
        """Falls back to RDFLib when index query raises."""
        service.index.is_index_ready = AsyncMock(return_value=True)  # type: ignore[method-assign]
        service.index.get_class_children = AsyncMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("query failed")
        )
        service._enqueue_reindex_if_stale = AsyncMock()  # type: ignore[method-assign]

        await service.get_children_tree_nodes(PROJECT_ID, CLASS_IRI, branch=BRANCH)
        mock_ontology_service.get_children_tree_nodes.assert_awaited_once_with(
            PROJECT_ID, CLASS_IRI, None, BRANCH
        )


# ──────────────────────────────────────────────
# get_class
# ──────────────────────────────────────────────


class TestGetClass:
    """Tests for get_class()."""

    @pytest.mark.asyncio
    async def test_uses_index_when_ready(
        self, service: IndexedOntologyService, mock_ontology_service: AsyncMock
    ) -> None:
        """Returns class detail from the index when ready."""
        service.index.is_index_ready = AsyncMock(return_value=True)  # type: ignore[method-assign]
        service.index.get_class_detail = AsyncMock(  # type: ignore[method-assign]
            return_value={
                "iri": CLASS_IRI,
                "labels": [{"value": "Person", "lang": "en"}],
                "comments": [{"value": "A human being", "lang": "en"}],
                "deprecated": False,
                "parent_iris": [],
                "parent_labels": {},
                "equivalent_iris": [],
                "disjoint_iris": [],
                "child_count": 3,
                "instance_count": 0,
                "annotations": [
                    {
                        "property_iri": "http://www.w3.org/2000/01/rdf-schema#seeAlso",
                        "property_label": "seeAlso",
                        "values": [{"value": "http://example.org", "lang": ""}],
                    }
                ],
            }
        )

        result = await service.get_class(PROJECT_ID, CLASS_IRI, branch=BRANCH)
        assert result is not None
        assert str(result.iri) == CLASS_IRI
        assert len(result.labels) == 1
        assert result.labels[0].value == "Person"
        assert len(result.comments) == 1
        assert result.child_count == 3
        assert len(result.annotations) == 1
        assert result.annotations[0].property_iri == (
            "http://www.w3.org/2000/01/rdf-schema#seeAlso"
        )
        mock_ontology_service.get_class.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_falls_back_when_index_not_ready(
        self, service: IndexedOntologyService, mock_ontology_service: AsyncMock
    ) -> None:
        """Falls back to OntologyService when index is not ready."""
        service.index.is_index_ready = AsyncMock(return_value=False)  # type: ignore[method-assign]
        service._enqueue_reindex_if_stale = AsyncMock()  # type: ignore[method-assign]

        await service.get_class(PROJECT_ID, CLASS_IRI, branch=BRANCH)
        mock_ontology_service.get_class.assert_awaited_once_with(
            PROJECT_ID, CLASS_IRI, None, BRANCH
        )

    @pytest.mark.asyncio
    async def test_falls_back_when_index_query_fails(
        self, service: IndexedOntologyService, mock_ontology_service: AsyncMock
    ) -> None:
        """Falls back to RDFLib when index query raises."""
        service.index.is_index_ready = AsyncMock(return_value=True)  # type: ignore[method-assign]
        service.index.get_class_detail = AsyncMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("query failed")
        )
        service._enqueue_reindex_if_stale = AsyncMock()  # type: ignore[method-assign]

        await service.get_class(PROJECT_ID, CLASS_IRI, branch=BRANCH)
        mock_ontology_service.get_class.assert_awaited_once_with(
            PROJECT_ID, CLASS_IRI, None, BRANCH
        )

    @pytest.mark.asyncio
    async def test_falls_back_when_index_returns_none(
        self, service: IndexedOntologyService, mock_ontology_service: AsyncMock
    ) -> None:
        """Falls back to OntologyService when index returns None for class detail."""
        service.index.is_index_ready = AsyncMock(return_value=True)  # type: ignore[method-assign]
        service.index.get_class_detail = AsyncMock(return_value=None)  # type: ignore[method-assign]
        service._enqueue_reindex_if_stale = AsyncMock()  # type: ignore[method-assign]

        await service.get_class(PROJECT_ID, CLASS_IRI, branch=BRANCH)
        mock_ontology_service.get_class.assert_awaited_once_with(
            PROJECT_ID, CLASS_IRI, None, BRANCH
        )


# ──────────────────────────────────────────────
# get_ancestor_path
# ──────────────────────────────────────────────


class TestGetAncestorPath:
    """Tests for get_ancestor_path()."""

    @pytest.mark.asyncio
    async def test_uses_index_when_ready(
        self, service: IndexedOntologyService, mock_ontology_service: AsyncMock
    ) -> None:
        """Returns ancestor path from the index when ready."""
        service.index.is_index_ready = AsyncMock(return_value=True)  # type: ignore[method-assign]
        service.index.get_ancestor_path = AsyncMock(  # type: ignore[method-assign]
            return_value=[
                {
                    "iri": "http://example.org/ontology#Thing",
                    "label": "Thing",
                    "child_count": 5,
                    "deprecated": False,
                },
                {"iri": CLASS_IRI, "label": "Person", "child_count": 0, "deprecated": False},
            ]
        )

        nodes = await service.get_ancestor_path(PROJECT_ID, CLASS_IRI, branch=BRANCH)
        assert len(nodes) == 2
        assert nodes[0].iri == "http://example.org/ontology#Thing"
        assert nodes[1].iri == CLASS_IRI
        mock_ontology_service.get_ancestor_path.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_falls_back_when_index_not_ready(
        self, service: IndexedOntologyService, mock_ontology_service: AsyncMock
    ) -> None:
        """Falls back to OntologyService when index is not ready."""
        service.index.is_index_ready = AsyncMock(return_value=False)  # type: ignore[method-assign]
        service._enqueue_reindex_if_stale = AsyncMock()  # type: ignore[method-assign]

        await service.get_ancestor_path(PROJECT_ID, CLASS_IRI, branch=BRANCH)
        mock_ontology_service.get_ancestor_path.assert_awaited_once_with(
            PROJECT_ID, CLASS_IRI, None, BRANCH
        )

    @pytest.mark.asyncio
    async def test_falls_back_when_index_query_fails(
        self, service: IndexedOntologyService, mock_ontology_service: AsyncMock
    ) -> None:
        """Falls back to RDFLib when index query raises."""
        service.index.is_index_ready = AsyncMock(return_value=True)  # type: ignore[method-assign]
        service.index.get_ancestor_path = AsyncMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("query failed")
        )
        service._enqueue_reindex_if_stale = AsyncMock()  # type: ignore[method-assign]

        await service.get_ancestor_path(PROJECT_ID, CLASS_IRI, branch=BRANCH)
        mock_ontology_service.get_ancestor_path.assert_awaited_once_with(
            PROJECT_ID, CLASS_IRI, None, BRANCH
        )


# ──────────────────────────────────────────────
# search_entities
# ──────────────────────────────────────────────


class TestSearchEntities:
    """Tests for search_entities()."""

    @pytest.mark.asyncio
    async def test_uses_index_when_ready(
        self, service: IndexedOntologyService, mock_ontology_service: AsyncMock
    ) -> None:
        """Returns search results from the index when ready."""
        service.index.is_index_ready = AsyncMock(return_value=True)  # type: ignore[method-assign]
        service.index.search_entities = AsyncMock(  # type: ignore[method-assign]
            return_value={
                "results": [
                    {
                        "iri": CLASS_IRI,
                        "label": "Person",
                        "entity_type": "class",
                        "deprecated": False,
                    }
                ],
                "total": 1,
            }
        )

        response = await service.search_entities(PROJECT_ID, "Person", branch=BRANCH)
        assert response.total == 1
        assert len(response.results) == 1
        assert response.results[0].iri == CLASS_IRI
        assert response.results[0].entity_type == "class"
        mock_ontology_service.search_entities.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_falls_back_when_index_not_ready(
        self, service: IndexedOntologyService, mock_ontology_service: AsyncMock
    ) -> None:
        """Falls back to OntologyService when index is not ready."""
        service.index.is_index_ready = AsyncMock(return_value=False)  # type: ignore[method-assign]
        service._enqueue_reindex_if_stale = AsyncMock()  # type: ignore[method-assign]

        await service.search_entities(PROJECT_ID, "Person", branch=BRANCH)
        mock_ontology_service.search_entities.assert_awaited_once_with(
            PROJECT_ID, "Person", None, None, 50, BRANCH
        )

    @pytest.mark.asyncio
    async def test_falls_back_when_index_query_fails(
        self, service: IndexedOntologyService, mock_ontology_service: AsyncMock
    ) -> None:
        """Falls back to RDFLib when index query raises."""
        service.index.is_index_ready = AsyncMock(return_value=True)  # type: ignore[method-assign]
        service.index.search_entities = AsyncMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("query failed")
        )
        service._enqueue_reindex_if_stale = AsyncMock()  # type: ignore[method-assign]

        await service.search_entities(PROJECT_ID, "Person", branch=BRANCH)
        mock_ontology_service.search_entities.assert_awaited_once_with(
            PROJECT_ID, "Person", None, None, 50, BRANCH
        )
