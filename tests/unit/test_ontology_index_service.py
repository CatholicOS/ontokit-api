"""Tests for OntologyIndexService (ontokit/services/ontology_index.py)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from rdflib import Graph
from rdflib import Literal as RDFLiteral
from rdflib.namespace import RDFS

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
        assert result == 4


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
        mock_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_auto_commit_false(
        self, service: OntologyIndexService, mock_db: AsyncMock
    ) -> None:
        """With auto_commit=False, does not commit."""
        await service.delete_branch_index(PROJECT_ID, BRANCH, auto_commit=False)
        mock_db.commit.assert_not_awaited()


# ---------------------------------------------------------------------------
# _index_graph
# ---------------------------------------------------------------------------


class TestIndexGraph:
    @pytest.mark.asyncio
    async def test_index_graph_extracts_entities(
        self,
        service: OntologyIndexService,
        mock_db: AsyncMock,  # noqa: ARG002
        sample_graph: Graph,
    ) -> None:
        """_index_graph extracts classes and properties from the sample graph."""
        # sample_graph has: Person, Organization (owl:Class),
        # worksFor (ObjectProperty), hasName (DatatypeProperty) = 4 entities
        count = await service._index_graph(PROJECT_ID, BRANCH, sample_graph)
        assert count == 4

    @pytest.mark.asyncio
    async def test_index_graph_empty_graph(
        self,
        service: OntologyIndexService,
        mock_db: AsyncMock,  # noqa: ARG002
    ) -> None:
        """_index_graph returns 0 for an empty graph."""
        empty_graph = Graph()
        count = await service._index_graph(PROJECT_ID, BRANCH, empty_graph)
        assert count == 0

    @pytest.mark.asyncio
    async def test_index_graph_skips_owl_thing(
        self,
        service: OntologyIndexService,
        mock_db: AsyncMock,  # noqa: ARG002
    ) -> None:
        """_index_graph does not count owl:Thing as an entity."""
        from rdflib import URIRef
        from rdflib.namespace import OWL, RDF

        g = Graph()
        g.add((OWL.Thing, RDF.type, OWL.Class))
        g.add((URIRef("http://example.org/A"), RDF.type, OWL.Class))

        count = await service._index_graph(PROJECT_ID, BRANCH, g)
        assert count == 1


# ---------------------------------------------------------------------------
# search_entities
# ---------------------------------------------------------------------------


class TestSearchEntities:
    @pytest.mark.asyncio
    async def test_search_entities_returns_results(
        self, service: OntologyIndexService, mock_db: AsyncMock
    ) -> None:
        """search_entities returns matching entities."""
        # Mock count query
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 1

        # Mock entity row
        mock_entity_row = MagicMock()
        mock_entity_row.id = "entity-id-1"
        mock_entity_row.iri = "http://example.org/Person"
        mock_entity_row.local_name = "Person"
        mock_entity_row.entity_type = "class"
        mock_entity_row.deprecated = False

        mock_entities_result = MagicMock()
        mock_entities_result.all.return_value = [mock_entity_row]

        # Mock labels result (empty)
        mock_labels_result = MagicMock()
        mock_labels_result.scalars.return_value.all.return_value = []

        mock_db.execute.side_effect = [
            mock_count_result,  # count query
            mock_entities_result,  # entity query
            mock_labels_result,  # labels query
        ]

        result = await service.search_entities(PROJECT_ID, BRANCH, "Person")
        assert result["total"] == 1
        assert len(result["results"]) == 1
        assert result["results"][0]["iri"] == "http://example.org/Person"

    @pytest.mark.asyncio
    async def test_search_entities_no_matches(
        self, service: OntologyIndexService, mock_db: AsyncMock
    ) -> None:
        """search_entities returns empty results when nothing matches."""
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 0

        mock_entities_result = MagicMock()
        mock_entities_result.all.return_value = []

        mock_db.execute.side_effect = [
            mock_count_result,
            mock_entities_result,
        ]

        result = await service.search_entities(PROJECT_ID, BRANCH, "Nonexistent")
        assert result["total"] == 0
        assert result["results"] == []


# ---------------------------------------------------------------------------
# get_class_count
# ---------------------------------------------------------------------------


class TestGetClassCount:
    @pytest.mark.asyncio
    async def test_get_class_count_returns_count(
        self, service: OntologyIndexService, mock_db: AsyncMock
    ) -> None:
        """get_class_count returns the number of indexed classes."""
        mock_result = MagicMock()
        mock_result.scalar.return_value = 42
        mock_db.execute.return_value = mock_result

        count = await service.get_class_count(PROJECT_ID, BRANCH)
        assert count == 42

    @pytest.mark.asyncio
    async def test_get_class_count_returns_zero_when_none(
        self, service: OntologyIndexService, mock_db: AsyncMock
    ) -> None:
        """get_class_count returns 0 when scalar returns None."""
        mock_result = MagicMock()
        mock_result.scalar.return_value = None
        mock_db.execute.return_value = mock_result

        count = await service.get_class_count(PROJECT_ID, BRANCH)
        assert count == 0


# ---------------------------------------------------------------------------
# get_class_detail (as proxy for get_entity found/not found)
# ---------------------------------------------------------------------------


class TestGetClassDetail:
    @pytest.mark.asyncio
    async def test_get_class_detail_not_found(
        self, service: OntologyIndexService, mock_db: AsyncMock
    ) -> None:
        """get_class_detail returns None when entity not found."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        result = await service.get_class_detail(PROJECT_ID, BRANCH, "http://example.org/Missing")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_class_detail_found(
        self, service: OntologyIndexService, mock_db: AsyncMock
    ) -> None:
        """get_class_detail returns full entity info when found."""
        import uuid as _uuid

        entity = MagicMock()
        entity.id = _uuid.uuid4()
        entity.iri = "http://example.org/Person"
        entity.local_name = "Person"
        entity.entity_type = "class"
        entity.deprecated = False

        # First execute: entity lookup
        mock_entity_result = MagicMock()
        mock_entity_result.scalar_one_or_none.return_value = entity

        # labels, comments, parents, child_count, annotations
        mock_labels = MagicMock()
        mock_labels.scalars.return_value.all.return_value = []
        mock_comments = MagicMock()
        mock_comments.scalars.return_value.all.return_value = []
        mock_parents = MagicMock()
        mock_parents.all.return_value = []
        mock_child_count = MagicMock()
        mock_child_count.scalar.return_value = 0
        mock_annotations = MagicMock()
        mock_annotations.scalars.return_value.all.return_value = []

        mock_db.execute.side_effect = [
            mock_entity_result,
            mock_labels,
            mock_comments,
            mock_parents,
            mock_child_count,
            mock_annotations,
        ]

        result = await service.get_class_detail(PROJECT_ID, BRANCH, "http://example.org/Person")
        assert result is not None
        assert result["iri"] == "http://example.org/Person"
        assert result["child_count"] == 0

    @pytest.mark.asyncio
    async def test_get_class_detail_with_labels_and_parents(
        self, service: OntologyIndexService, mock_db: AsyncMock
    ) -> None:
        """get_class_detail returns labels, comments, parents, and annotations."""
        import uuid as _uuid

        entity_id = _uuid.uuid4()
        entity = MagicMock()
        entity.id = entity_id
        entity.iri = "http://example.org/Person"
        entity.local_name = "Person"
        entity.entity_type = "class"
        entity.deprecated = False

        # Entity lookup
        mock_entity_result = MagicMock()
        mock_entity_result.scalar_one_or_none.return_value = entity

        # Labels
        mock_label = MagicMock()
        mock_label.value = "Person"
        mock_label.lang = "en"
        mock_labels = MagicMock()
        mock_labels.scalars.return_value.all.return_value = [mock_label]

        # Comments
        mock_comment = MagicMock()
        mock_comment.value = "A human being"
        mock_comment.lang = "en"
        mock_comments = MagicMock()
        mock_comments.scalars.return_value.all.return_value = [mock_comment]

        # Parents
        mock_parents = MagicMock()
        mock_parents.all.return_value = [("http://example.org/Agent",)]

        # Parent label resolution: entity lookup + labels
        parent_entity = MagicMock()
        parent_entity.id = _uuid.uuid4()
        parent_entity.iri = "http://example.org/Agent"
        mock_parent_entities = MagicMock()
        mock_parent_entities.all.return_value = [parent_entity]

        mock_parent_labels = MagicMock()
        parent_label = MagicMock()
        parent_label.entity_id = parent_entity.id
        parent_label.property_iri = str(
            __import__("rdflib.namespace", fromlist=["RDFS"]).RDFS.label
        )
        parent_label.value = "Agent"
        parent_label.lang = "en"
        mock_parent_labels.scalars.return_value.all.return_value = [parent_label]

        # Child count
        mock_child_count = MagicMock()
        mock_child_count.scalar.return_value = 5

        # Annotations
        mock_annotations = MagicMock()
        mock_annotations.scalars.return_value.all.return_value = []

        mock_db.execute.side_effect = [
            mock_entity_result,
            mock_labels,
            mock_comments,
            mock_parents,
            mock_parent_entities,
            mock_parent_labels,
            mock_child_count,
            mock_annotations,
        ]

        result = await service.get_class_detail(PROJECT_ID, BRANCH, "http://example.org/Person")
        assert result is not None
        assert result["labels"] == [{"value": "Person", "lang": "en"}]
        assert result["comments"] == [{"value": "A human being", "lang": "en"}]
        assert "http://example.org/Agent" in result["parent_iris"]
        assert result["child_count"] == 5
        assert result["instance_count"] is None


# ---------------------------------------------------------------------------
# get_root_classes (SQL-based)
# ---------------------------------------------------------------------------


class TestGetRootClasses:
    @pytest.mark.asyncio
    async def test_returns_root_classes(
        self, service: OntologyIndexService, mock_db: AsyncMock
    ) -> None:
        """get_root_classes returns classes not appearing as children."""
        # Main query returns root class rows
        root_row = MagicMock()
        root_row.iri = "http://example.org/Animal"
        root_row.local_name = "Animal"
        root_row.deprecated = False
        root_row.child_count = 2

        mock_roots_result = MagicMock()
        mock_roots_result.all.return_value = [root_row]

        # Label resolution: entities + labels
        entity_row = MagicMock()
        entity_row.id = uuid.uuid4()
        entity_row.iri = "http://example.org/Animal"
        mock_entities = MagicMock()
        mock_entities.all.return_value = [entity_row]

        mock_label = MagicMock()
        mock_label.entity_id = entity_row.id
        mock_label.property_iri = str(__import__("rdflib.namespace", fromlist=["RDFS"]).RDFS.label)
        mock_label.value = "Animal"
        mock_label.lang = "en"
        mock_labels = MagicMock()
        mock_labels.scalars.return_value.all.return_value = [mock_label]

        mock_db.execute.side_effect = [mock_roots_result, mock_entities, mock_labels]

        result = await service.get_root_classes(PROJECT_ID, BRANCH)
        assert len(result) == 1
        assert result[0]["iri"] == "http://example.org/Animal"
        assert result[0]["label"] == "Animal"
        assert result[0]["child_count"] == 2

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_classes(
        self, service: OntologyIndexService, mock_db: AsyncMock
    ) -> None:
        """get_root_classes returns empty list when no classes exist."""
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_db.execute.return_value = mock_result

        result = await service.get_root_classes(PROJECT_ID, BRANCH)
        assert result == []


# ---------------------------------------------------------------------------
# get_class_children (SQL-based)
# ---------------------------------------------------------------------------


class TestGetClassChildren:
    @pytest.mark.asyncio
    async def test_returns_children(
        self, service: OntologyIndexService, mock_db: AsyncMock
    ) -> None:
        """get_class_children returns direct children of a class."""
        child_row = MagicMock()
        child_row.iri = "http://example.org/Dog"
        child_row.local_name = "Dog"
        child_row.deprecated = False
        child_row.child_count = 0

        mock_children_result = MagicMock()
        mock_children_result.all.return_value = [child_row]

        # Label resolution
        entity_row = MagicMock()
        entity_row.id = uuid.uuid4()
        entity_row.iri = "http://example.org/Dog"
        mock_entities = MagicMock()
        mock_entities.all.return_value = [entity_row]

        mock_labels = MagicMock()
        mock_labels.scalars.return_value.all.return_value = []

        mock_db.execute.side_effect = [mock_children_result, mock_entities, mock_labels]

        result = await service.get_class_children(PROJECT_ID, BRANCH, "http://example.org/Animal")
        assert len(result) == 1
        assert result[0]["iri"] == "http://example.org/Dog"
        assert result[0]["label"] == "Dog"  # falls back to local_name

    @pytest.mark.asyncio
    async def test_returns_empty_for_leaf(
        self, service: OntologyIndexService, mock_db: AsyncMock
    ) -> None:
        """get_class_children returns empty for a leaf class."""
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_db.execute.return_value = mock_result

        result = await service.get_class_children(PROJECT_ID, BRANCH, "http://example.org/Leaf")
        assert result == []


# ---------------------------------------------------------------------------
# get_ancestor_path (SQL-based)
# ---------------------------------------------------------------------------


class TestGetAncestorPath:
    @pytest.mark.asyncio
    async def test_returns_empty_for_missing_entity(
        self, service: OntologyIndexService, mock_db: AsyncMock
    ) -> None:
        """get_ancestor_path returns empty for non-existent entity."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        result = await service.get_ancestor_path(PROJECT_ID, BRANCH, "http://example.org/Missing")
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_for_root_class(
        self, service: OntologyIndexService, mock_db: AsyncMock
    ) -> None:
        """get_ancestor_path returns empty for a root class (no ancestors)."""
        # Entity exists
        mock_exists = MagicMock()
        mock_exists.scalar_one_or_none.return_value = "http://example.org/Root"

        # CTE returns no ancestors
        mock_cte = MagicMock()
        mock_cte.all.return_value = []

        mock_db.execute.side_effect = [mock_exists, mock_cte]

        result = await service.get_ancestor_path(PROJECT_ID, BRANCH, "http://example.org/Root")
        assert result == []


# ---------------------------------------------------------------------------
# _pick_preferred_label
# ---------------------------------------------------------------------------


class TestPickPreferredLabel:
    def test_returns_matching_label(self) -> None:
        """Picks the label matching the preference."""
        from rdflib.namespace import RDFS

        label = MagicMock()
        label.property_iri = str(RDFS.label)
        label.value = "Person"
        label.lang = "en"

        result = OntologyIndexService._pick_preferred_label([label], ["rdfs:label@en"])
        assert result == "Person"

    def test_returns_none_when_empty(self) -> None:
        """Returns None when no labels are available."""
        result = OntologyIndexService._pick_preferred_label([], ["rdfs:label@en"])
        assert result is None

    def test_falls_back_to_rdfs_label(self) -> None:
        """Falls back to any rdfs:label when no preference matches."""
        from rdflib.namespace import RDFS

        label = MagicMock()
        label.property_iri = str(RDFS.label)
        label.value = "Persona"
        label.lang = "es"

        result = OntologyIndexService._pick_preferred_label([label], ["rdfs:label@fr"])
        assert result == "Persona"

    def test_preference_without_at_matches_any_lang(self) -> None:
        """Preference without '@' sets lang=None and matches label with lang=None."""
        from rdflib.namespace import RDFS

        label = MagicMock()
        label.property_iri = str(RDFS.label)
        label.value = "NoLangLabel"
        label.lang = None

        # "rdfs:label" without @ means prop_part="rdfs:label", lang=None
        result = OntologyIndexService._pick_preferred_label([label], ["rdfs:label"])
        assert result == "NoLangLabel"

    def test_unknown_prop_part_is_skipped(self) -> None:
        """Preferences with an unknown property name are skipped."""
        from rdflib.namespace import RDFS

        label = MagicMock()
        label.property_iri = str(RDFS.label)
        label.value = "Fallback"
        label.lang = "en"

        # "foo:bar@en" won't map to a known property, should skip and fallback
        result = OntologyIndexService._pick_preferred_label([label], ["foo:bar@en"])
        assert result == "Fallback"

    def test_returns_none_when_no_rdfs_label_fallback(self) -> None:
        """Returns None when no preferences match and no rdfs:label exists."""
        label = MagicMock()
        label.property_iri = "http://example.org/custom-prop"
        label.value = "Custom"
        label.lang = "en"

        result = OntologyIndexService._pick_preferred_label([label], ["foo:bar@en"])
        assert result is None


# ---------------------------------------------------------------------------
# full_reindex error path (lines 171-189)
# ---------------------------------------------------------------------------


class TestFullReindexErrorPath:
    @pytest.mark.asyncio
    async def test_rollback_and_status_update_on_error(
        self, service: OntologyIndexService, mock_db: AsyncMock
    ) -> None:
        """On error in full_reindex, rollback and update status to FAILED."""
        # _upsert_status returns rowcount=1 (allowed to proceed)
        mock_upsert_result = MagicMock()
        mock_upsert_result.rowcount = 1

        # get_index_status returns a status
        status_obj = MagicMock(spec=OntologyIndexStatus)
        status_obj.status = IndexingStatus.INDEXING.value
        mock_status_result = MagicMock()
        mock_status_result.scalar_one_or_none.return_value = status_obj

        call_count = 0

        async def side_effect(*_args: object, **_kwargs: object) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_upsert_result  # _upsert_status
            if call_count == 2:
                return mock_status_result  # get_index_status
            if call_count == 3:
                raise RuntimeError("DB error during delete")  # _delete_index_data
            return MagicMock()

        mock_db.execute = AsyncMock(side_effect=side_effect)

        with pytest.raises(RuntimeError, match="DB error during delete"):
            await service.full_reindex(PROJECT_ID, BRANCH, Graph(), COMMIT_HASH)

        mock_db.rollback.assert_awaited()


# ---------------------------------------------------------------------------
# _index_graph with deprecated entities (lines 287-289)
# ---------------------------------------------------------------------------


class TestIndexGraphDeprecated:
    @pytest.mark.asyncio
    async def test_index_graph_detects_deprecated_entities(
        self,
        service: OntologyIndexService,
        mock_db: AsyncMock,  # noqa: ARG002
    ) -> None:
        """_index_graph detects owl:deprecated = 'true' on entities."""
        from rdflib import URIRef
        from rdflib.namespace import OWL, RDF

        g = Graph()
        entity = URIRef("http://example.org/DeprecatedClass")
        g.add((entity, RDF.type, OWL.Class))
        g.add((entity, OWL.deprecated, RDFLiteral("true")))

        count = await service._index_graph(PROJECT_ID, BRANCH, g)
        assert count == 1


# ---------------------------------------------------------------------------
# get_class_detail with annotations (lines 669-672, 683-689)
# ---------------------------------------------------------------------------


class TestGetClassDetailAnnotations:
    @pytest.mark.asyncio
    async def test_get_class_detail_with_annotations(
        self, service: OntologyIndexService, mock_db: AsyncMock
    ) -> None:
        """get_class_detail returns annotations grouped by property."""
        import uuid as _uuid

        entity_id = _uuid.uuid4()
        entity = MagicMock()
        entity.id = entity_id
        entity.iri = "http://example.org/Thing"
        entity.local_name = "Thing"
        entity.entity_type = "class"
        entity.deprecated = False

        mock_entity_result = MagicMock()
        mock_entity_result.scalar_one_or_none.return_value = entity

        mock_labels = MagicMock()
        mock_labels.scalars.return_value.all.return_value = []
        mock_comments = MagicMock()
        mock_comments.scalars.return_value.all.return_value = []
        mock_parents = MagicMock()
        mock_parents.all.return_value = []
        mock_child_count = MagicMock()
        mock_child_count.scalar.return_value = 0

        # Annotation with a property that is NOT a label property
        ann = MagicMock()
        ann.property_iri = "http://purl.org/dc/elements/1.1/creator"
        ann.value = "John Doe"
        ann.lang = None
        mock_annotations = MagicMock()
        mock_annotations.scalars.return_value.all.return_value = [ann]

        mock_db.execute.side_effect = [
            mock_entity_result,
            mock_labels,
            mock_comments,
            mock_parents,
            mock_child_count,
            mock_annotations,
        ]

        result = await service.get_class_detail(PROJECT_ID, BRANCH, "http://example.org/Thing")
        assert result is not None
        assert len(result["annotations"]) == 1
        assert result["annotations"][0]["property_iri"] == "http://purl.org/dc/elements/1.1/creator"
        assert result["annotations"][0]["values"][0]["value"] == "John Doe"


# ---------------------------------------------------------------------------
# get_ancestor_path with ancestors (lines 778-898)
# ---------------------------------------------------------------------------


class TestGetAncestorPathWithAncestors:
    @pytest.mark.asyncio
    async def test_returns_ordered_ancestors(
        self, service: OntologyIndexService, mock_db: AsyncMock
    ) -> None:
        """get_ancestor_path returns ordered path from root to target's parent."""
        import uuid as _uuid

        # Entity exists
        mock_exists = MagicMock()
        mock_exists.scalar_one_or_none.return_value = "http://example.org/C"

        # CTE returns ancestors
        mock_cte = MagicMock()
        mock_cte.all.return_value = [
            ("http://example.org/A",),
            ("http://example.org/B",),
        ]

        # _order_ancestor_path: hierarchy query
        row_a = MagicMock()
        row_a.__getitem__ = lambda _self, i: ["http://example.org/B", "http://example.org/A"][i]
        row_b = MagicMock()
        row_b.__getitem__ = lambda _self, i: ["http://example.org/C", "http://example.org/B"][i]
        mock_hierarchy = MagicMock()
        mock_hierarchy.all.return_value = [row_a, row_b]

        # Entity info for path nodes
        eid_a = _uuid.uuid4()
        eid_b = _uuid.uuid4()
        row_ea = MagicMock(id=eid_a, iri="http://example.org/A", deprecated=False)
        row_eb = MagicMock(id=eid_b, iri="http://example.org/B", deprecated=False)
        mock_entities = MagicMock()
        mock_entities.all.return_value = [row_ea, row_eb]

        # Child counts
        cc_a = MagicMock(parent_iri="http://example.org/A", cnt=1)
        cc_b = MagicMock(parent_iri="http://example.org/B", cnt=2)
        mock_child_counts = MagicMock()
        mock_child_counts.all.return_value = [cc_a, cc_b]

        # Labels
        mock_labels = MagicMock()
        mock_labels.scalars.return_value.all.return_value = []

        mock_db.execute.side_effect = [
            mock_exists,  # entity exists check
            mock_cte,  # CTE ancestors
            mock_hierarchy,  # _order_ancestor_path
            mock_entities,  # entity info
            mock_child_counts,  # child counts
            mock_labels,  # labels
        ]

        result = await service.get_ancestor_path(PROJECT_ID, BRANCH, "http://example.org/C")
        assert len(result) == 2
        # Path should be A -> B (root to nearest parent)
        assert result[0]["iri"] == "http://example.org/A"
        assert result[1]["iri"] == "http://example.org/B"


# ---------------------------------------------------------------------------
# search_entities with prefix sort (lines 1005, 1040)
# ---------------------------------------------------------------------------


class TestSearchEntitiesPrefixSort:
    @pytest.mark.asyncio
    async def test_search_entities_sorts_prefix_matches_first(
        self, service: OntologyIndexService, mock_db: AsyncMock
    ) -> None:
        """search_entities sorts prefix matches before non-prefix matches."""
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 2

        row1 = MagicMock()
        row1.id = uuid.uuid4()
        row1.iri = "http://example.org/ZebraPerson"
        row1.local_name = "ZebraPerson"
        row1.entity_type = "class"
        row1.deprecated = False

        row2 = MagicMock()
        row2.id = uuid.uuid4()
        row2.iri = "http://example.org/PersonEntity"
        row2.local_name = "PersonEntity"
        row2.entity_type = "class"
        row2.deprecated = False

        mock_entities_result = MagicMock()
        mock_entities_result.all.return_value = [row1, row2]

        # Labels: give PersonEntity a label starting with "Person"
        label1 = MagicMock()
        label1.entity_id = row2.id
        label1.property_iri = str(RDFS.label)
        label1.value = "PersonEntity"
        label1.lang = "en"

        mock_labels_result = MagicMock()
        mock_labels_result.scalars.return_value.all.return_value = [label1]

        mock_db.execute.side_effect = [
            mock_count_result,
            mock_entities_result,
            mock_labels_result,
        ]

        result = await service.search_entities(PROJECT_ID, BRANCH, "Person")
        # PersonEntity should come first (prefix match), ZebraPerson second
        assert result["results"][0]["label"] == "PersonEntity"
        assert result["results"][1]["label"] == "ZebraPerson"


# ---------------------------------------------------------------------------
# _resolve_labels_bulk (lines 1116, 1131)
# ---------------------------------------------------------------------------


class TestResolveLabels:
    @pytest.mark.asyncio
    async def test_resolve_labels_bulk_empty_iris(self, service: OntologyIndexService) -> None:
        """_resolve_labels_bulk returns empty dict for empty IRI list."""
        result = await service._resolve_labels_bulk(PROJECT_ID, BRANCH, [])
        assert result == {}

    @pytest.mark.asyncio
    async def test_resolve_labels_bulk_no_entities_found(
        self, service: OntologyIndexService, mock_db: AsyncMock
    ) -> None:
        """_resolve_labels_bulk returns None for all IRIs when no entities found."""
        mock_entities = MagicMock()
        mock_entities.all.return_value = []
        mock_db.execute.return_value = mock_entities

        result = await service._resolve_labels_bulk(
            PROJECT_ID, BRANCH, ["http://example.org/Missing"]
        )
        assert result == {"http://example.org/Missing": None}

    @pytest.mark.asyncio
    async def test_resolve_labels_bulk_with_labels(
        self, service: OntologyIndexService, mock_db: AsyncMock
    ) -> None:
        """_resolve_labels_bulk resolves labels for found entities."""
        from rdflib.namespace import RDFS

        eid = uuid.uuid4()
        entity_row = MagicMock(id=eid, iri="http://example.org/A")
        mock_entities = MagicMock()
        mock_entities.all.return_value = [entity_row]

        label = MagicMock()
        label.entity_id = eid
        label.property_iri = str(RDFS.label)
        label.value = "ClassA"
        label.lang = "en"
        mock_labels = MagicMock()
        mock_labels.scalars.return_value.all.return_value = [label]

        mock_db.execute.side_effect = [mock_entities, mock_labels]

        result = await service._resolve_labels_bulk(PROJECT_ID, BRANCH, ["http://example.org/A"])
        assert result["http://example.org/A"] == "ClassA"
