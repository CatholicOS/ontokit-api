"""Tests for OntologyIndexService (ontokit/services/ontology_index.py)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from rdflib import Graph

from ontokit.models.ontology_index import IndexingStatus, OntologyIndexStatus
from ontokit.services.ontology_index import (
    OntologyIndexService,
    _extract_local_name,
)

PROJECT_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
BRANCH = "main"
COMMIT_HASH = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"


@pytest.fixture
def mock_db() -> AsyncMock:
    """Create an async mock of AsyncSession."""
    session = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.execute = AsyncMock()
    session.add = Mock()
    return session


@pytest.fixture
def service(mock_db: AsyncMock) -> OntologyIndexService:
    return OntologyIndexService(db=mock_db)


# ---------------------------------------------------------------------------
# _extract_local_name (module-level helper)
# ---------------------------------------------------------------------------


class TestExtractLocalName:
    def test_hash_separator(self) -> None:
        """Extracts name after '#' in IRI."""
        assert _extract_local_name("http://example.org/ontology#Person") == "Person"

    def test_slash_separator(self) -> None:
        """Extracts name after last '/' when no '#'."""
        assert _extract_local_name("http://example.org/ontology/Person") == "Person"

    def test_no_separator(self) -> None:
        """Returns the full IRI when no '#' or '/' is present."""
        assert _extract_local_name("Person") == "Person"


# ---------------------------------------------------------------------------
# get_index_status
# ---------------------------------------------------------------------------


class TestGetIndexStatus:
    @pytest.mark.asyncio
    async def test_returns_status_when_exists(
        self, service: OntologyIndexService, mock_db: AsyncMock
    ) -> None:
        """Returns the OntologyIndexStatus row when it exists."""
        status_obj = MagicMock(spec=OntologyIndexStatus)
        status_obj.status = IndexingStatus.READY.value
        status_obj.commit_hash = COMMIT_HASH

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = status_obj
        mock_db.execute.return_value = mock_result

        result = await service.get_index_status(PROJECT_ID, BRANCH)
        assert result is status_obj

    @pytest.mark.asyncio
    async def test_returns_none_when_missing(
        self, service: OntologyIndexService, mock_db: AsyncMock
    ) -> None:
        """Returns None when no status row exists."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        result = await service.get_index_status(PROJECT_ID, BRANCH)
        assert result is None


# ---------------------------------------------------------------------------
# is_index_ready
# ---------------------------------------------------------------------------


class TestIsIndexReady:
    @pytest.mark.asyncio
    async def test_ready_when_status_is_ready(
        self, service: OntologyIndexService, mock_db: AsyncMock
    ) -> None:
        """Returns True when status is 'ready'."""
        status_obj = MagicMock()
        status_obj.status = IndexingStatus.READY.value
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = status_obj
        mock_db.execute.return_value = mock_result

        assert await service.is_index_ready(PROJECT_ID, BRANCH) is True

    @pytest.mark.asyncio
    async def test_not_ready_when_status_is_indexing(
        self, service: OntologyIndexService, mock_db: AsyncMock
    ) -> None:
        """Returns False when status is 'indexing'."""
        status_obj = MagicMock()
        status_obj.status = IndexingStatus.INDEXING.value
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = status_obj
        mock_db.execute.return_value = mock_result

        assert await service.is_index_ready(PROJECT_ID, BRANCH) is False

    @pytest.mark.asyncio
    async def test_not_ready_when_no_status(
        self, service: OntologyIndexService, mock_db: AsyncMock
    ) -> None:
        """Returns False when no status row exists."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        assert await service.is_index_ready(PROJECT_ID, BRANCH) is False


# ---------------------------------------------------------------------------
# is_index_stale
# ---------------------------------------------------------------------------


class TestIsIndexStale:
    @pytest.mark.asyncio
    async def test_stale_when_no_status(
        self, service: OntologyIndexService, mock_db: AsyncMock
    ) -> None:
        """Returns True when no status row exists."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        assert await service.is_index_stale(PROJECT_ID, BRANCH, COMMIT_HASH) is True

    @pytest.mark.asyncio
    async def test_not_stale_when_hash_matches(
        self, service: OntologyIndexService, mock_db: AsyncMock
    ) -> None:
        """Returns False when commit hash matches."""
        status_obj = MagicMock()
        status_obj.commit_hash = COMMIT_HASH
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = status_obj
        mock_db.execute.return_value = mock_result

        assert await service.is_index_stale(PROJECT_ID, BRANCH, COMMIT_HASH) is False

    @pytest.mark.asyncio
    async def test_stale_when_hash_differs(
        self, service: OntologyIndexService, mock_db: AsyncMock
    ) -> None:
        """Returns True when commit hash differs."""
        status_obj = MagicMock()
        status_obj.commit_hash = "old_hash_1234567890123456789012345678"
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = status_obj
        mock_db.execute.return_value = mock_result

        assert await service.is_index_stale(PROJECT_ID, BRANCH, COMMIT_HASH) is True


# ---------------------------------------------------------------------------
# full_reindex
# ---------------------------------------------------------------------------


class TestFullReindex:
    @pytest.mark.asyncio
    async def test_skips_when_already_indexing(
        self, service: OntologyIndexService, mock_db: AsyncMock, sample_graph: Graph
    ) -> None:
        """Returns 0 when another indexing is in progress (upsert returns None)."""
        # _upsert_status returns None when already indexing
        mock_upsert_result = MagicMock()
        mock_upsert_result.rowcount = 0
        mock_db.execute.return_value = mock_upsert_result

        result = await service.full_reindex(PROJECT_ID, BRANCH, sample_graph, COMMIT_HASH)
        assert result == 0

    @pytest.mark.asyncio
    async def test_indexes_entities_from_graph(
        self, service: OntologyIndexService, mock_db: AsyncMock, sample_graph: Graph
    ) -> None:
        """Indexes entities from the RDF graph and returns count."""
        # First call: _upsert_status (INSERT ON CONFLICT)
        mock_upsert_result = MagicMock()
        mock_upsert_result.rowcount = 1
        # Second call: get_index_status (returns the status)
        status_obj = MagicMock(spec=OntologyIndexStatus)
        status_obj.status = IndexingStatus.INDEXING.value
        mock_status_result = MagicMock()
        mock_status_result.scalar_one_or_none.return_value = status_obj

        # Subsequent calls: delete, batch inserts, update status
        mock_db.execute.side_effect = [
            mock_upsert_result,  # _upsert_status INSERT
            mock_status_result,  # get_index_status after upsert
            MagicMock(),  # _delete_index_data (entities)
            MagicMock(),  # _delete_index_data (hierarchy)
            # batch inserts (entities, labels, hierarchy, annotations) x2 (flush + final)
            MagicMock(),
            MagicMock(),
            MagicMock(),
            MagicMock(),
            MagicMock(),
            MagicMock(),
            MagicMock(),
            MagicMock(),
            MagicMock(),  # update status to ready
        ]

        result = await service.full_reindex(PROJECT_ID, BRANCH, sample_graph, COMMIT_HASH)
        # The sample graph has Person, Organization as owl:Class, worksFor as ObjectProperty,
        # hasName as DatatypeProperty = 4 entities
        assert result > 0


# ---------------------------------------------------------------------------
# _delete_index_data
# ---------------------------------------------------------------------------


class TestDeleteIndexData:
    @pytest.mark.asyncio
    async def test_deletes_entities_and_hierarchy(
        self, service: OntologyIndexService, mock_db: AsyncMock
    ) -> None:
        """Deletes both entity rows and hierarchy rows."""
        await service._delete_index_data(PROJECT_ID, BRANCH)
        assert mock_db.execute.call_count == 2


# ---------------------------------------------------------------------------
# delete_branch_index
# ---------------------------------------------------------------------------


class TestDeleteBranchIndex:
    @pytest.mark.asyncio
    async def test_auto_commit_true(
        self, service: OntologyIndexService, mock_db: AsyncMock
    ) -> None:
        """With auto_commit=True, commits after deletion."""
        await service.delete_branch_index(PROJECT_ID, BRANCH, auto_commit=True)
        assert mock_db.commit.called

    @pytest.mark.asyncio
    async def test_auto_commit_false(
        self, service: OntologyIndexService, mock_db: AsyncMock
    ) -> None:
        """With auto_commit=False, does not commit."""
        await service.delete_branch_index(PROJECT_ID, BRANCH, auto_commit=False)
        assert not mock_db.commit.called
