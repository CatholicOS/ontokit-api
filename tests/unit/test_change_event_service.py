"""Tests for ChangeEventService (ontokit/services/change_event_service.py)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import OWL, RDF, RDFS

from ontokit.models.change_event import ChangeEventType, EntityChangeEvent
from ontokit.services.change_event_service import ChangeEventService

PROJECT_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
BRANCH = "main"
USER_ID = "user-123"
USER_NAME = "Test User"
COMMIT_HASH = "a1b2c3d4"
ENTITY_IRI = "http://example.org/ontology#Person"


@pytest.fixture
def mock_db() -> AsyncMock:
    """Create an async mock of AsyncSession."""
    session = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock()
    session.add = Mock()
    return session


@pytest.fixture
def service(mock_db: AsyncMock) -> ChangeEventService:
    """Create a ChangeEventService with mocked DB."""
    return ChangeEventService(mock_db)


class TestRecordEvent:
    """Tests for record_event()."""

    @pytest.mark.asyncio
    async def test_creates_entity_change_event(
        self, service: ChangeEventService, mock_db: AsyncMock
    ) -> None:
        """record_event creates an EntityChangeEvent and adds it to the session."""
        result = await service.record_event(
            project_id=PROJECT_ID,
            branch=BRANCH,
            entity_iri=ENTITY_IRI,
            entity_type="class",
            event_type=ChangeEventType.CREATE,
            user_id=USER_ID,
            user_name=USER_NAME,
            commit_hash=COMMIT_HASH,
        )
        mock_db.add.assert_called_once()
        assert isinstance(result, EntityChangeEvent)
        assert result.project_id == PROJECT_ID
        assert result.entity_iri == ENTITY_IRI
        assert result.event_type == ChangeEventType.CREATE

    @pytest.mark.asyncio
    async def test_defaults_changed_fields_to_empty_list(
        self,
        service: ChangeEventService,
        mock_db: AsyncMock,  # noqa: ARG002
    ) -> None:
        """changed_fields defaults to an empty list when None."""
        result = await service.record_event(
            project_id=PROJECT_ID,
            branch=BRANCH,
            entity_iri=ENTITY_IRI,
            entity_type="class",
            event_type=ChangeEventType.UPDATE,
            user_id=USER_ID,
            changed_fields=None,
        )
        assert result.changed_fields == []


class TestRecordEventsFromDiff:
    """Tests for record_events_from_diff()."""

    @pytest.mark.asyncio
    async def test_detects_created_entities(
        self, service: ChangeEventService, mock_db: AsyncMock
    ) -> None:
        """Entities in new_graph but not old_graph produce CREATE events."""
        old_graph = Graph()
        new_graph = Graph()
        uri = URIRef("http://example.org/ontology#NewClass")
        new_graph.add((uri, RDF.type, OWL.Class))
        new_graph.add((uri, RDFS.label, Literal("New Class")))

        events = await service.record_events_from_diff(
            PROJECT_ID, BRANCH, old_graph, new_graph, USER_ID, USER_NAME, COMMIT_HASH
        )
        assert len(events) == 1
        assert events[0].event_type == ChangeEventType.CREATE
        mock_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_detects_deleted_entities(
        self,
        service: ChangeEventService,
        mock_db: AsyncMock,  # noqa: ARG002
    ) -> None:
        """Entities in old_graph but not new_graph produce DELETE events."""
        old_graph = Graph()
        uri = URIRef("http://example.org/ontology#OldClass")
        old_graph.add((uri, RDF.type, OWL.Class))
        old_graph.add((uri, RDFS.label, Literal("Old Class")))

        new_graph = Graph()

        events = await service.record_events_from_diff(
            PROJECT_ID, BRANCH, old_graph, new_graph, USER_ID, USER_NAME, COMMIT_HASH
        )
        assert len(events) == 1
        assert events[0].event_type == ChangeEventType.DELETE

    @pytest.mark.asyncio
    async def test_detects_renamed_entities(
        self,
        service: ChangeEventService,
        mock_db: AsyncMock,  # noqa: ARG002
    ) -> None:
        """Entities with only label changes produce RENAME events."""
        uri = URIRef("http://example.org/ontology#MyClass")

        old_graph = Graph()
        old_graph.add((uri, RDF.type, OWL.Class))
        old_graph.add((uri, RDFS.label, Literal("Old Name")))

        new_graph = Graph()
        new_graph.add((uri, RDF.type, OWL.Class))
        new_graph.add((uri, RDFS.label, Literal("New Name")))

        events = await service.record_events_from_diff(
            PROJECT_ID, BRANCH, old_graph, new_graph, USER_ID, USER_NAME, COMMIT_HASH
        )
        assert len(events) == 1
        assert events[0].event_type == ChangeEventType.RENAME

    @pytest.mark.asyncio
    async def test_no_changes_produces_no_events(
        self, service: ChangeEventService, mock_db: AsyncMock
    ) -> None:
        """Identical graphs produce no events and no commit."""
        graph = Graph()
        uri = URIRef("http://example.org/ontology#Same")
        graph.add((uri, RDF.type, OWL.Class))
        graph.add((uri, RDFS.label, Literal("Same")))

        events = await service.record_events_from_diff(
            PROJECT_ID, BRANCH, graph, graph, USER_ID, USER_NAME, COMMIT_HASH
        )
        assert events == []
        mock_db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_none_old_graph_all_creates(
        self,
        service: ChangeEventService,
        mock_db: AsyncMock,  # noqa: ARG002
    ) -> None:
        """When old_graph is None, all entities in new_graph are CREATE events."""
        new_graph = Graph()
        uri1 = URIRef("http://example.org/ontology#A")
        uri2 = URIRef("http://example.org/ontology#B")
        new_graph.add((uri1, RDF.type, OWL.Class))
        new_graph.add((uri2, RDF.type, OWL.Class))

        events = await service.record_events_from_diff(
            PROJECT_ID, BRANCH, None, new_graph, USER_ID, USER_NAME, COMMIT_HASH
        )
        assert len(events) == 2
        assert all(e.event_type == ChangeEventType.CREATE for e in events)


class TestGetEntityHistory:
    """Tests for get_entity_history()."""

    @pytest.mark.asyncio
    async def test_returns_entity_history_response(
        self, service: ChangeEventService, mock_db: AsyncMock
    ) -> None:
        """get_entity_history returns an EntityHistoryResponse with events."""
        row = MagicMock()
        row.id = uuid.uuid4()
        row.project_id = PROJECT_ID
        row.branch = BRANCH
        row.entity_iri = ENTITY_IRI
        row.entity_type = "class"
        row.event_type = "create"
        row.user_id = USER_ID
        row.user_name = USER_NAME
        row.commit_hash = COMMIT_HASH
        row.changed_fields = []
        row.old_values = None
        row.new_values = None
        row.created_at = datetime.now(UTC)

        # First execute: items query
        items_result = MagicMock()
        items_result.scalars.return_value.all.return_value = [row]

        # Second execute: count query
        count_result = MagicMock()
        count_result.scalar.return_value = 1

        mock_db.execute.side_effect = [items_result, count_result]

        response = await service.get_entity_history(PROJECT_ID, ENTITY_IRI)
        assert response.entity_iri == ENTITY_IRI
        assert response.total == 1
        assert len(response.events) == 1


class TestGetActivity:
    """Tests for get_activity()."""

    @pytest.mark.asyncio
    async def test_returns_project_activity(
        self, service: ChangeEventService, mock_db: AsyncMock
    ) -> None:
        """get_activity returns ProjectActivity with daily_counts, total, and top_editors."""
        day_row = MagicMock()
        day_row.day = datetime(2025, 1, 15, tzinfo=UTC)
        day_row.cnt = 5

        daily_result = MagicMock()
        daily_result.__iter__ = Mock(return_value=iter([day_row]))

        total_result = MagicMock()
        total_result.scalar.return_value = 5

        editor_row = MagicMock()
        editor_row.user_id = USER_ID
        editor_row.user_name = USER_NAME
        editor_row.cnt = 5

        editors_result = MagicMock()
        editors_result.__iter__ = Mock(return_value=iter([editor_row]))

        mock_db.execute.side_effect = [daily_result, total_result, editors_result]

        activity = await service.get_activity(PROJECT_ID, days=30)
        assert activity.total_events == 5
        assert len(activity.daily_counts) == 1
        assert activity.daily_counts[0].count == 5
        assert len(activity.top_editors) == 1


class TestGetHotEntities:
    """Tests for get_hot_entities()."""

    @pytest.mark.asyncio
    async def test_returns_hot_entities(
        self, service: ChangeEventService, mock_db: AsyncMock
    ) -> None:
        """get_hot_entities returns a list of HotEntity objects."""
        row = MagicMock()
        row.entity_iri = ENTITY_IRI
        row.entity_type = "class"
        row.edit_count = 10
        row.editor_count = 3
        row.last_edited_at = datetime.now(UTC)

        result = MagicMock()
        result.__iter__ = Mock(return_value=iter([row]))
        mock_db.execute.return_value = result

        hot = await service.get_hot_entities(PROJECT_ID, limit=20)
        assert len(hot) == 1
        assert hot[0].entity_iri == ENTITY_IRI
        assert hot[0].edit_count == 10
        assert hot[0].editor_count == 3


class TestGetContributors:
    """Tests for get_contributors()."""

    @pytest.mark.asyncio
    async def test_returns_contributor_stats(
        self, service: ChangeEventService, mock_db: AsyncMock
    ) -> None:
        """get_contributors returns a list of ContributorStats objects."""
        row = MagicMock()
        row.user_id = USER_ID
        row.user_name = USER_NAME
        row.create_count = 3
        row.update_count = 5
        row.delete_count = 1
        row.total_count = 9
        row.last_active_at = datetime.now(UTC)

        result = MagicMock()
        result.__iter__ = Mock(return_value=iter([row]))
        mock_db.execute.return_value = result

        contributors = await service.get_contributors(PROJECT_ID, days=30)
        assert len(contributors) == 1
        assert contributors[0].user_id == USER_ID
        assert contributors[0].total_count == 9
        assert contributors[0].create_count == 3
