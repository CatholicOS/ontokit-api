"""Extended tests for OntologyService (ontokit/services/ontology.py).

Covers graph lifecycle, class operations, and search — beyond the label
preference tests in test_ontology_service.py.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from rdflib import Graph, Namespace, URIRef

from ontokit.services.ontology import OntologyService

EX = Namespace("http://example.org/ontology#")
PROJECT_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
BRANCH = "main"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def ontology_service() -> OntologyService:
    """Create a fresh OntologyService (no storage)."""
    return OntologyService(storage=None)


@pytest.fixture
def loaded_service(sample_graph: Graph) -> OntologyService:
    """OntologyService with the sample graph pre-loaded."""
    svc = OntologyService(storage=None)
    svc.set_graph(PROJECT_ID, BRANCH, sample_graph)
    return svc


# ---------------------------------------------------------------------------
# set_graph / get_graph / is_loaded / unload
# ---------------------------------------------------------------------------


class TestGraphLifecycle:
    def test_set_graph_marks_loaded(self, ontology_service: OntologyService) -> None:
        """set_graph makes is_loaded return True."""
        g = Graph()
        ontology_service.set_graph(PROJECT_ID, BRANCH, g)
        assert ontology_service.is_loaded(PROJECT_ID, BRANCH) is True

    def test_is_loaded_false_initially(self, ontology_service: OntologyService) -> None:
        """A fresh service has no loaded graphs."""
        assert ontology_service.is_loaded(PROJECT_ID, BRANCH) is False

    @pytest.mark.asyncio
    async def test_get_graph_returns_cached(self, loaded_service: OntologyService) -> None:
        """get_graph returns the previously set graph."""
        graph = await loaded_service.get_graph(PROJECT_ID, BRANCH)
        assert isinstance(graph, Graph)
        assert len(graph) > 0

    @pytest.mark.asyncio
    async def test_get_graph_raises_when_not_loaded(
        self, ontology_service: OntologyService
    ) -> None:
        """get_graph raises ValueError when no graph is loaded."""
        with pytest.raises(ValueError, match="not loaded"):
            await ontology_service.get_graph(PROJECT_ID, BRANCH)

    def test_unload_specific_branch(self, loaded_service: OntologyService) -> None:
        """unload with a branch removes only that branch."""
        loaded_service.set_graph(PROJECT_ID, "dev", Graph())
        loaded_service.unload(PROJECT_ID, BRANCH)
        assert loaded_service.is_loaded(PROJECT_ID, BRANCH) is False
        assert loaded_service.is_loaded(PROJECT_ID, "dev") is True

    def test_unload_all_branches(self, loaded_service: OntologyService) -> None:
        """unload with branch=None removes all branches."""
        loaded_service.set_graph(PROJECT_ID, "dev", Graph())
        loaded_service.unload(PROJECT_ID, branch=None)
        assert loaded_service.is_loaded(PROJECT_ID, BRANCH) is False
        assert loaded_service.is_loaded(PROJECT_ID, "dev") is False

    def test_unload_nonexistent_is_noop(self, ontology_service: OntologyService) -> None:
        """unload on a non-loaded project does not raise."""
        ontology_service.unload(PROJECT_ID, BRANCH)  # should not raise


# ---------------------------------------------------------------------------
# load_from_git
# ---------------------------------------------------------------------------


class TestLoadFromGit:
    @pytest.mark.asyncio
    async def test_load_from_git_parses_turtle(
        self, ontology_service: OntologyService, sample_ontology_turtle: str
    ) -> None:
        """load_from_git parses Turtle content and caches the graph."""
        mock_git = MagicMock()
        mock_git.get_file_from_branch.return_value = sample_ontology_turtle.encode("utf-8")

        graph = await ontology_service.load_from_git(PROJECT_ID, BRANCH, "ontology.ttl", mock_git)

        assert isinstance(graph, Graph)
        assert len(graph) > 0
        assert ontology_service.is_loaded(PROJECT_ID, BRANCH)

    @pytest.mark.asyncio
    async def test_load_from_git_unsupported_format(
        self, ontology_service: OntologyService
    ) -> None:
        """load_from_git raises ValueError for unsupported file extension."""
        mock_git = MagicMock()

        with pytest.raises(ValueError, match="Unsupported file format"):
            await ontology_service.load_from_git(PROJECT_ID, BRANCH, "ontology.xyz", mock_git)


# ---------------------------------------------------------------------------
# load_from_storage
# ---------------------------------------------------------------------------


class TestLoadFromStorage:
    @pytest.mark.asyncio
    async def test_load_from_storage_parses_turtle(self, sample_ontology_turtle: str) -> None:
        """load_from_storage downloads and parses the file."""
        mock_storage = MagicMock()
        mock_storage.bucket = "ontokit"
        mock_storage.download_file = AsyncMock(return_value=sample_ontology_turtle.encode("utf-8"))

        svc = OntologyService(storage=mock_storage)
        graph = await svc.load_from_storage(PROJECT_ID, "ontokit/projects/123/ontology.ttl", BRANCH)

        assert isinstance(graph, Graph)
        assert len(graph) > 0
        mock_storage.download_file.assert_called_once()

    @pytest.mark.asyncio
    async def test_load_from_storage_no_storage_raises(self) -> None:
        """load_from_storage raises ValueError when storage is not configured."""
        svc = OntologyService(storage=None)

        with pytest.raises(ValueError, match="Storage service not configured"):
            await svc.load_from_storage(PROJECT_ID, "path/ontology.ttl", BRANCH)


# ---------------------------------------------------------------------------
# get_class
# ---------------------------------------------------------------------------


class TestGetClass:
    @pytest.mark.asyncio
    async def test_get_existing_class(self, loaded_service: OntologyService) -> None:
        """get_class returns a response for an existing class."""
        result = await loaded_service.get_class(PROJECT_ID, "http://example.org/ontology#Person")
        assert result is not None
        assert "Person" in str(result.iri)

    @pytest.mark.asyncio
    async def test_get_nonexistent_class(self, loaded_service: OntologyService) -> None:
        """get_class returns None for a missing class."""
        result = await loaded_service.get_class(
            PROJECT_ID, "http://example.org/ontology#NonExistent"
        )
        assert result is None


# ---------------------------------------------------------------------------
# list_classes
# ---------------------------------------------------------------------------


class TestListClasses:
    @pytest.mark.asyncio
    async def test_list_all_classes(self, loaded_service: OntologyService) -> None:
        """list_classes returns all classes."""
        result = await loaded_service.list_classes(PROJECT_ID)
        assert result.total == 2  # Person, Organization

    @pytest.mark.asyncio
    async def test_list_classes_with_parent_filter(self, loaded_service: OntologyService) -> None:
        """list_classes with parent_iri filters to children of that class."""
        # Neither Person nor Organization has a parent in the sample, so filtering
        # by a non-existent parent should return zero results.
        result = await loaded_service.list_classes(
            PROJECT_ID, parent_iri="http://example.org/ontology#NonExistentParent"
        )
        assert result.total == 0


# ---------------------------------------------------------------------------
# get_root_classes
# ---------------------------------------------------------------------------


class TestGetRootClasses:
    @pytest.mark.asyncio
    async def test_root_classes_are_parentless(self, loaded_service: OntologyService) -> None:
        """Root classes are those with no explicit parent."""
        roots = await loaded_service.get_root_classes(PROJECT_ID)
        iris = [str(r.iri) for r in roots]
        assert "http://example.org/ontology#Person" in iris
        assert "http://example.org/ontology#Organization" in iris

    @pytest.mark.asyncio
    async def test_root_classes_sorted_by_label(self, loaded_service: OntologyService) -> None:
        """Root classes are sorted alphabetically by label."""
        roots = await loaded_service.get_root_classes(PROJECT_ID)
        labels = [r.labels[0].value if r.labels else str(r.iri) for r in roots]
        assert labels == sorted(labels, key=str.lower)


# ---------------------------------------------------------------------------
# get_class_children / get_class_count
# ---------------------------------------------------------------------------


class TestClassHierarchy:
    @pytest.mark.asyncio
    async def test_get_class_children_empty(self, loaded_service: OntologyService) -> None:
        """get_class_children returns empty for a leaf class."""
        children = await loaded_service.get_class_children(
            PROJECT_ID, "http://example.org/ontology#Person"
        )
        assert children == []

    @pytest.mark.asyncio
    async def test_get_class_count(self, loaded_service: OntologyService) -> None:
        """get_class_count returns the correct number of classes."""
        count = await loaded_service.get_class_count(PROJECT_ID)
        assert count == 2


# ---------------------------------------------------------------------------
# search_entities
# ---------------------------------------------------------------------------


class TestSearchEntities:
    @pytest.mark.asyncio
    async def test_search_by_label(self, loaded_service: OntologyService) -> None:
        """Searching by label substring finds matching entities."""
        result = await loaded_service.search_entities(PROJECT_ID, "Person")
        assert result.total >= 1
        iris = [r.iri for r in result.results]
        assert any("Person" in iri for iri in iris)

    @pytest.mark.asyncio
    async def test_search_wildcard(self, loaded_service: OntologyService) -> None:
        """Searching with '*' returns all entities."""
        result = await loaded_service.search_entities(PROJECT_ID, "*")
        # Should find at least classes + properties
        assert result.total >= 4

    @pytest.mark.asyncio
    async def test_search_no_results(self, loaded_service: OntologyService) -> None:
        """Searching for a non-existent term returns zero results."""
        result = await loaded_service.search_entities(PROJECT_ID, "zzz_nonexistent_zzz")
        assert result.total == 0

    @pytest.mark.asyncio
    async def test_search_filter_by_entity_type(self, loaded_service: OntologyService) -> None:
        """Filtering by entity_types restricts results."""
        result = await loaded_service.search_entities(PROJECT_ID, "*", entity_types=["class"])
        for r in result.results:
            assert r.entity_type == "class"


# ---------------------------------------------------------------------------
# _find_ontology_iri
# ---------------------------------------------------------------------------


class TestFindOntologyIri:
    def test_finds_ontology_iri(self, sample_graph: Graph) -> None:
        """Finds the owl:Ontology IRI in the graph."""
        result = OntologyService._find_ontology_iri(sample_graph)
        assert result == "http://example.org/ontology"

    def test_returns_none_for_empty_graph(self) -> None:
        """Returns None for a graph with no owl:Ontology."""
        g = Graph()
        result = OntologyService._find_ontology_iri(g)
        assert result is None


# ---------------------------------------------------------------------------
# _class_to_response
# ---------------------------------------------------------------------------


class TestClassToResponse:
    @pytest.mark.asyncio
    async def test_class_response_has_labels(
        self, loaded_service: OntologyService, sample_graph: Graph
    ) -> None:
        """_class_to_response extracts labels from the graph."""
        response = await loaded_service._class_to_response(
            sample_graph, URIRef("http://example.org/ontology#Person")
        )
        label_values = [lbl.value for lbl in response.labels]
        assert "Person" in label_values

    @pytest.mark.asyncio
    async def test_class_response_has_comments(
        self, loaded_service: OntologyService, sample_graph: Graph
    ) -> None:
        """_class_to_response extracts comments from the graph."""
        response = await loaded_service._class_to_response(
            sample_graph, URIRef("http://example.org/ontology#Person")
        )
        comment_values = [c.value for c in response.comments]
        assert "A human being" in comment_values

    @pytest.mark.asyncio
    async def test_class_response_has_parent_info(self, loaded_service: OntologyService) -> None:
        """_class_to_response includes parent_iris and parent_labels for subclasses."""
        from rdflib import Literal as RDFLiteral
        from rdflib.namespace import OWL, RDF, RDFS

        g = Graph()
        parent = URIRef("http://example.org/ontology#Animal")
        child = URIRef("http://example.org/ontology#Dog")
        g.add((parent, RDF.type, OWL.Class))
        g.add((parent, RDFS.label, RDFLiteral("Animal", lang="en")))
        g.add((child, RDF.type, OWL.Class))
        g.add((child, RDFS.label, RDFLiteral("Dog", lang="en")))
        g.add((child, RDFS.subClassOf, parent))

        loaded_service.set_graph(PROJECT_ID, BRANCH, g)
        response = await loaded_service._class_to_response(g, child)
        assert str(parent) in response.parent_iris
        assert response.parent_labels[str(parent)] == "Animal"

    @pytest.mark.asyncio
    async def test_class_response_child_count(self, loaded_service: OntologyService) -> None:
        """_class_to_response counts direct children."""
        from rdflib.namespace import OWL, RDF, RDFS

        g = Graph()
        parent = URIRef("http://example.org/ontology#Animal")
        child1 = URIRef("http://example.org/ontology#Dog")
        child2 = URIRef("http://example.org/ontology#Cat")
        g.add((parent, RDF.type, OWL.Class))
        g.add((child1, RDF.type, OWL.Class))
        g.add((child2, RDF.type, OWL.Class))
        g.add((child1, RDFS.subClassOf, parent))
        g.add((child2, RDFS.subClassOf, parent))

        loaded_service.set_graph(PROJECT_ID, BRANCH, g)
        response = await loaded_service._class_to_response(g, parent)
        assert response.child_count == 2

    @pytest.mark.asyncio
    async def test_class_response_annotations(self, loaded_service: OntologyService) -> None:
        """_class_to_response extracts annotation properties (SKOS, DC)."""
        from rdflib import Literal as RDFLiteral
        from rdflib.namespace import OWL, RDF, RDFS, SKOS

        g = Graph()
        cls = URIRef("http://example.org/ontology#Person")
        g.add((cls, RDF.type, OWL.Class))
        g.add((cls, RDFS.label, RDFLiteral("Person", lang="en")))
        g.add((cls, SKOS.definition, RDFLiteral("A human being", lang="en")))

        loaded_service.set_graph(PROJECT_ID, BRANCH, g)
        response = await loaded_service._class_to_response(g, cls)
        annotation_labels = [a.property_label for a in response.annotations]
        assert "skos:definition" in annotation_labels

    @pytest.mark.asyncio
    async def test_class_response_deprecated_flag(self, loaded_service: OntologyService) -> None:
        """_class_to_response detects owl:deprecated annotation."""
        from rdflib import Literal as RDFLiteral
        from rdflib.namespace import OWL, RDF, XSD

        g = Graph()
        cls = URIRef("http://example.org/ontology#OldClass")
        g.add((cls, RDF.type, OWL.Class))
        g.add((cls, OWL.deprecated, RDFLiteral("true", datatype=XSD.boolean)))

        loaded_service.set_graph(PROJECT_ID, BRANCH, g)
        response = await loaded_service._class_to_response(g, cls)
        assert response.deprecated is True


# ---------------------------------------------------------------------------
# serialize
# ---------------------------------------------------------------------------


class TestSerialize:
    @pytest.mark.asyncio
    async def test_serialize_turtle(self, loaded_service: OntologyService) -> None:
        """serialize returns Turtle serialization."""
        result = await loaded_service.serialize(PROJECT_ID, format="turtle", branch=BRANCH)
        assert isinstance(result, str)
        assert "Person" in result

    @pytest.mark.asyncio
    async def test_serialize_xml(self, loaded_service: OntologyService) -> None:
        """serialize returns RDF/XML serialization."""
        result = await loaded_service.serialize(PROJECT_ID, format="xml", branch=BRANCH)
        assert isinstance(result, str)
        assert "rdf:RDF" in result or "RDF" in result


# ---------------------------------------------------------------------------
# get_root_tree_nodes / get_children_tree_nodes
# ---------------------------------------------------------------------------


class TestTreeNodes:
    @pytest.mark.asyncio
    async def test_get_root_tree_nodes(self, loaded_service: OntologyService) -> None:
        """get_root_tree_nodes returns tree nodes for root classes."""
        nodes = await loaded_service.get_root_tree_nodes(PROJECT_ID, branch=BRANCH)
        assert len(nodes) >= 2
        labels = [n.label for n in nodes]
        assert "Person" in labels
        assert "Organization" in labels

    @pytest.mark.asyncio
    async def test_get_children_tree_nodes_empty(self, loaded_service: OntologyService) -> None:
        """get_children_tree_nodes returns empty for leaf class."""
        nodes = await loaded_service.get_children_tree_nodes(
            PROJECT_ID, "http://example.org/ontology#Person", branch=BRANCH
        )
        assert nodes == []

    @pytest.mark.asyncio
    async def test_get_children_tree_nodes_with_children(self) -> None:
        """get_children_tree_nodes returns children with correct labels."""
        from rdflib import Literal as RDFLiteral
        from rdflib.namespace import OWL, RDF, RDFS

        g = Graph()
        parent = URIRef("http://example.org/ontology#Animal")
        child = URIRef("http://example.org/ontology#Dog")
        g.add((parent, RDF.type, OWL.Class))
        g.add((parent, RDFS.label, RDFLiteral("Animal", lang="en")))
        g.add((child, RDF.type, OWL.Class))
        g.add((child, RDFS.label, RDFLiteral("Dog", lang="en")))
        g.add((child, RDFS.subClassOf, parent))

        svc = OntologyService(storage=None)
        svc.set_graph(PROJECT_ID, BRANCH, g)
        nodes = await svc.get_children_tree_nodes(PROJECT_ID, str(parent), branch=BRANCH)
        assert len(nodes) == 1
        assert nodes[0].label == "Dog"


# ---------------------------------------------------------------------------
# get_ancestor_path
# ---------------------------------------------------------------------------


class TestGetAncestorPath:
    @pytest.mark.asyncio
    async def test_ancestor_path_root_class(self, loaded_service: OntologyService) -> None:
        """Root class returns empty ancestor path."""
        path = await loaded_service.get_ancestor_path(
            PROJECT_ID, "http://example.org/ontology#Person", branch=BRANCH
        )
        assert path == []

    @pytest.mark.asyncio
    async def test_ancestor_path_nonexistent_class(self, loaded_service: OntologyService) -> None:
        """Non-existent class returns empty path."""
        path = await loaded_service.get_ancestor_path(
            PROJECT_ID, "http://example.org/ontology#NonExistent", branch=BRANCH
        )
        assert path == []

    @pytest.mark.asyncio
    async def test_ancestor_path_with_hierarchy(self) -> None:
        """Returns path from root to parent of target."""
        from rdflib import Literal as RDFLiteral
        from rdflib.namespace import OWL, RDF, RDFS

        g = Graph()
        root = URIRef("http://example.org/ontology#Entity")
        mid = URIRef("http://example.org/ontology#Animal")
        leaf = URIRef("http://example.org/ontology#Dog")
        for cls in [root, mid, leaf]:
            g.add((cls, RDF.type, OWL.Class))
            local = str(cls).split("#")[-1]
            g.add((cls, RDFS.label, RDFLiteral(local, lang="en")))
        g.add((mid, RDFS.subClassOf, root))
        g.add((leaf, RDFS.subClassOf, mid))

        svc = OntologyService(storage=None)
        svc.set_graph(PROJECT_ID, BRANCH, g)
        path = await svc.get_ancestor_path(PROJECT_ID, str(leaf), branch=BRANCH)
        path_iris = [n.iri for n in path]
        assert str(root) in path_iris
        assert str(mid) in path_iris
        assert str(leaf) not in path_iris


# ---------------------------------------------------------------------------
# search_entities with entity type filter
# ---------------------------------------------------------------------------


class TestSearchEntitiesExtended:
    @pytest.mark.asyncio
    async def test_search_filter_properties_only(self, loaded_service: OntologyService) -> None:
        """Filtering by 'property' returns only properties."""
        result = await loaded_service.search_entities(PROJECT_ID, "*", entity_types=["property"])
        for r in result.results:
            assert r.entity_type == "property"
        assert result.total >= 2  # worksFor, hasName

    @pytest.mark.asyncio
    async def test_search_with_limit(self, loaded_service: OntologyService) -> None:
        """Limit restricts number of returned results."""
        result = await loaded_service.search_entities(PROJECT_ID, "*", limit=1)
        assert len(result.results) <= 1
