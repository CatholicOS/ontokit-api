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
        mock_ontology_service.get_root_tree_nodes.assert_awaited_once()
        service._enqueue_reindex_if_stale.assert_awaited_once()

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
        mock_ontology_service.get_root_tree_nodes.assert_awaited_once()
        service._enqueue_reindex_if_stale.assert_awaited_once()


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
        mock_ontology_service.get_class_count.assert_awaited_once()
        service._enqueue_reindex_if_stale.assert_awaited_once()


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
        mock_ontology_service.serialize.assert_awaited_once()
