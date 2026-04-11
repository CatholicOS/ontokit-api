"""Tests for the build_entity_graph method on OntologyService."""

from __future__ import annotations

import uuid

import pytest
from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS, SKOS

from ontokit.services.ontology import OntologyService

EX = Namespace("http://example.org/ontology#")
PROJECT_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
BRANCH = "main"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _service_with_graph(g: Graph) -> OntologyService:
    svc = OntologyService(storage=None)
    svc.set_graph(PROJECT_ID, BRANCH, g)
    return svc


def _base_graph() -> Graph:
    """Graph with a simple 3-level hierarchy: Animal > Person > Student."""
    g = Graph()
    g.add((EX.Animal, RDF.type, OWL.Class))
    g.add((EX.Animal, RDFS.label, Literal("Animal", lang="en")))

    g.add((EX.Person, RDF.type, OWL.Class))
    g.add((EX.Person, RDFS.label, Literal("Person", lang="en")))
    g.add((EX.Person, RDFS.subClassOf, EX.Animal))
    g.add((EX.Person, RDFS.comment, Literal("A human being", lang="en")))

    g.add((EX.Student, RDF.type, OWL.Class))
    g.add((EX.Student, RDFS.label, Literal("Student", lang="en")))
    g.add((EX.Student, RDFS.subClassOf, EX.Person))

    g.add((EX.GradStudent, RDF.type, OWL.Class))
    g.add((EX.GradStudent, RDFS.label, Literal("Graduate Student", lang="en")))
    g.add((EX.GradStudent, RDFS.subClassOf, EX.Student))
    return g


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBuildEntityGraphBasic:
    @pytest.mark.asyncio
    async def test_returns_none_for_missing_class(self) -> None:
        g = Graph()
        svc = _service_with_graph(g)
        result = await svc.build_entity_graph(PROJECT_ID, str(EX.Missing), BRANCH)
        assert result is None

    @pytest.mark.asyncio
    async def test_focus_node(self) -> None:
        svc = _service_with_graph(_base_graph())
        result = await svc.build_entity_graph(PROJECT_ID, str(EX.Person), BRANCH)
        assert result is not None
        assert result.focus_iri == str(EX.Person)
        assert result.focus_label == "Person"

        focus_nodes = [n for n in result.nodes if n.is_focus]
        assert len(focus_nodes) == 1
        assert focus_nodes[0].node_type == "focus"

    @pytest.mark.asyncio
    async def test_ancestors_discovered(self) -> None:
        svc = _service_with_graph(_base_graph())
        result = await svc.build_entity_graph(PROJECT_ID, str(EX.Person), BRANCH)
        assert result is not None
        iris = {n.iri for n in result.nodes}
        assert str(EX.Animal) in iris

    @pytest.mark.asyncio
    async def test_descendants_discovered(self) -> None:
        svc = _service_with_graph(_base_graph())
        result = await svc.build_entity_graph(PROJECT_ID, str(EX.Person), BRANCH)
        assert result is not None
        iris = {n.iri for n in result.nodes}
        assert str(EX.Student) in iris

    @pytest.mark.asyncio
    async def test_edges_created(self) -> None:
        svc = _service_with_graph(_base_graph())
        result = await svc.build_entity_graph(PROJECT_ID, str(EX.Person), BRANCH)
        assert result is not None
        sub_edges = [e for e in result.edges if e.edge_type == "subClassOf"]
        assert len(sub_edges) >= 2  # Animal->Person, Person->Student

    @pytest.mark.asyncio
    async def test_root_class_detected(self) -> None:
        svc = _service_with_graph(_base_graph())
        result = await svc.build_entity_graph(PROJECT_ID, str(EX.Person), BRANCH)
        assert result is not None
        animal_node = next(n for n in result.nodes if n.iri == str(EX.Animal))
        assert animal_node.is_root is True
        assert animal_node.node_type == "root"

    @pytest.mark.asyncio
    async def test_definition_from_comment(self) -> None:
        svc = _service_with_graph(_base_graph())
        result = await svc.build_entity_graph(PROJECT_ID, str(EX.Person), BRANCH)
        assert result is not None
        person = next(n for n in result.nodes if n.iri == str(EX.Person))
        assert person.definition == "A human being"

    @pytest.mark.asyncio
    async def test_definition_from_skos(self) -> None:
        g = _base_graph()
        g.add((EX.Person, SKOS.definition, Literal("SKOS definition")))
        svc = _service_with_graph(g)
        result = await svc.build_entity_graph(PROJECT_ID, str(EX.Person), BRANCH)
        assert result is not None
        person = next(n for n in result.nodes if n.iri == str(EX.Person))
        # SKOS definition takes priority
        assert person.definition == "SKOS definition"

    @pytest.mark.asyncio
    async def test_child_count(self) -> None:
        svc = _service_with_graph(_base_graph())
        result = await svc.build_entity_graph(PROJECT_ID, str(EX.Person), BRANCH)
        assert result is not None
        person = next(n for n in result.nodes if n.iri == str(EX.Person))
        assert person.child_count == 1  # Student


class TestBuildEntityGraphDepthLimits:
    @pytest.mark.asyncio
    async def test_ancestors_depth_limit(self) -> None:
        """With ancestors_depth=0, no ancestors are traversed."""
        svc = _service_with_graph(_base_graph())
        result = await svc.build_entity_graph(
            PROJECT_ID, str(EX.Student), BRANCH, ancestors_depth=0
        )
        assert result is not None
        iris = {n.iri for n in result.nodes}
        assert str(EX.Animal) not in iris
        assert str(EX.Person) not in iris

    @pytest.mark.asyncio
    async def test_descendants_depth_limit(self) -> None:
        """With descendants_depth=0, no descendants are traversed."""
        svc = _service_with_graph(_base_graph())
        result = await svc.build_entity_graph(
            PROJECT_ID, str(EX.Person), BRANCH, descendants_depth=0
        )
        assert result is not None
        iris = {n.iri for n in result.nodes}
        assert str(EX.Student) not in iris

    @pytest.mark.asyncio
    async def test_descendants_depth_1(self) -> None:
        """With descendants_depth=1, only direct children are found."""
        svc = _service_with_graph(_base_graph())
        result = await svc.build_entity_graph(
            PROJECT_ID, str(EX.Person), BRANCH, descendants_depth=1
        )
        assert result is not None
        iris = {n.iri for n in result.nodes}
        assert str(EX.Student) in iris
        assert str(EX.GradStudent) not in iris


class TestBuildEntityGraphMaxNodes:
    @pytest.mark.asyncio
    async def test_truncation(self) -> None:
        svc = _service_with_graph(_base_graph())
        result = await svc.build_entity_graph(PROJECT_ID, str(EX.Person), BRANCH, max_nodes=2)
        assert result is not None
        assert len(result.nodes) <= 2
        assert result.truncated is True
        assert result.total_concept_count > len(result.nodes)

    @pytest.mark.asyncio
    async def test_no_truncation(self) -> None:
        svc = _service_with_graph(_base_graph())
        result = await svc.build_entity_graph(PROJECT_ID, str(EX.Person), BRANCH, max_nodes=200)
        assert result is not None
        assert result.truncated is False


class TestBuildEntityGraphOwlRelations:
    @pytest.mark.asyncio
    async def test_equivalent_class(self) -> None:
        """equivalentClass edges appear between two visited nodes."""
        g = _base_graph()
        # Person and Student are both visited (ancestor/descendant).
        g.add((EX.Person, OWL.equivalentClass, EX.Student))
        svc = _service_with_graph(g)
        result = await svc.build_entity_graph(PROJECT_ID, str(EX.Person), BRANCH)
        assert result is not None
        equiv_edges = [e for e in result.edges if e.edge_type == "equivalentClass"]
        assert len(equiv_edges) == 1
        assert equiv_edges[0].label == "equivalentTo"

    @pytest.mark.asyncio
    async def test_disjoint_with(self) -> None:
        """disjointWith edges appear between two visited nodes."""
        g = _base_graph()
        # Person and Animal are both visited (focus + ancestor).
        g.add((EX.Person, OWL.disjointWith, EX.Animal))
        svc = _service_with_graph(g)
        result = await svc.build_entity_graph(PROJECT_ID, str(EX.Person), BRANCH)
        assert result is not None
        disj_edges = [e for e in result.edges if e.edge_type == "disjointWith"]
        assert len(disj_edges) == 1
        assert disj_edges[0].label == "disjointWith"


class TestBuildEntityGraphSeeAlso:
    @pytest.mark.asyncio
    async def test_direct_see_also(self) -> None:
        g = _base_graph()
        g.add((EX.Related, RDF.type, OWL.Class))
        g.add((EX.Related, RDFS.label, Literal("Related")))
        g.add((EX.Person, RDFS.seeAlso, EX.Related))
        svc = _service_with_graph(g)
        result = await svc.build_entity_graph(PROJECT_ID, str(EX.Person), BRANCH)
        assert result is not None
        iris = {n.iri for n in result.nodes}
        assert str(EX.Related) in iris
        sa_edges = [e for e in result.edges if e.edge_type == "seeAlso"]
        assert len(sa_edges) >= 1

    @pytest.mark.asyncio
    async def test_see_also_disabled(self) -> None:
        g = _base_graph()
        g.add((EX.Related, RDF.type, OWL.Class))
        g.add((EX.Person, RDFS.seeAlso, EX.Related))
        svc = _service_with_graph(g)
        result = await svc.build_entity_graph(
            PROJECT_ID, str(EX.Person), BRANCH, include_see_also=False
        )
        assert result is not None
        iris = {n.iri for n in result.nodes}
        assert str(EX.Related) not in iris

    @pytest.mark.asyncio
    async def test_owl_restriction_see_also(self) -> None:
        """seeAlso encoded as OWL restriction (someValuesFrom) on subClassOf."""
        g = _base_graph()
        g.add((EX.Related, RDF.type, OWL.Class))
        restriction = BNode()
        g.add((restriction, RDF.type, OWL.Restriction))
        g.add((restriction, OWL.onProperty, RDFS.seeAlso))
        g.add((restriction, OWL.someValuesFrom, EX.Related))
        g.add((EX.Person, RDFS.subClassOf, restriction))
        svc = _service_with_graph(g)
        result = await svc.build_entity_graph(PROJECT_ID, str(EX.Person), BRANCH)
        assert result is not None
        iris = {n.iri for n in result.nodes}
        assert str(EX.Related) in iris

    @pytest.mark.asyncio
    async def test_owl_restriction_all_values_from(self) -> None:
        """seeAlso encoded as OWL restriction (allValuesFrom)."""
        g = _base_graph()
        g.add((EX.Related, RDF.type, OWL.Class))
        restriction = BNode()
        g.add((restriction, RDF.type, OWL.Restriction))
        g.add((restriction, OWL.onProperty, RDFS.seeAlso))
        g.add((restriction, OWL.allValuesFrom, EX.Related))
        g.add((EX.Person, RDFS.subClassOf, restriction))
        svc = _service_with_graph(g)
        result = await svc.build_entity_graph(PROJECT_ID, str(EX.Person), BRANCH)
        assert result is not None
        iris = {n.iri for n in result.nodes}
        assert str(EX.Related) in iris

    @pytest.mark.asyncio
    async def test_owl_restriction_has_value(self) -> None:
        """seeAlso encoded as OWL restriction (hasValue)."""
        g = _base_graph()
        g.add((EX.Related, RDF.type, OWL.Class))
        restriction = BNode()
        g.add((restriction, RDF.type, OWL.Restriction))
        g.add((restriction, OWL.onProperty, RDFS.seeAlso))
        g.add((restriction, OWL.hasValue, EX.Related))
        g.add((EX.Person, RDFS.subClassOf, restriction))
        svc = _service_with_graph(g)
        result = await svc.build_entity_graph(PROJECT_ID, str(EX.Person), BRANCH)
        assert result is not None
        iris = {n.iri for n in result.nodes}
        assert str(EX.Related) in iris

    @pytest.mark.asyncio
    async def test_incoming_see_also_on_focus(self) -> None:
        """Reverse seeAlso — another class references the focus via seeAlso."""
        g = _base_graph()
        g.add((EX.Referrer, RDF.type, OWL.Class))
        g.add((EX.Referrer, RDFS.seeAlso, EX.Person))
        svc = _service_with_graph(g)
        result = await svc.build_entity_graph(PROJECT_ID, str(EX.Person), BRANCH)
        assert result is not None
        iris = {n.iri for n in result.nodes}
        assert str(EX.Referrer) in iris

    @pytest.mark.asyncio
    async def test_incoming_restriction_see_also(self) -> None:
        """Reverse seeAlso via OWL restriction (someValuesFrom -> focus)."""
        g = _base_graph()
        g.add((EX.Referrer, RDF.type, OWL.Class))
        restriction = BNode()
        g.add((restriction, RDF.type, OWL.Restriction))
        g.add((restriction, OWL.onProperty, RDFS.seeAlso))
        g.add((restriction, OWL.someValuesFrom, EX.Person))
        g.add((EX.Referrer, RDFS.subClassOf, restriction))
        svc = _service_with_graph(g)
        result = await svc.build_entity_graph(PROJECT_ID, str(EX.Person), BRANCH)
        assert result is not None
        iris = {n.iri for n in result.nodes}
        assert str(EX.Referrer) in iris

    @pytest.mark.asyncio
    async def test_see_also_ancestors_traversed(self) -> None:
        """After discovering seeAlso nodes, their ancestors are also traversed."""
        g = _base_graph()
        # Create a separate branch: Category > Topic, Person seeAlso Topic
        g.add((EX.Category, RDF.type, OWL.Class))
        g.add((EX.Topic, RDF.type, OWL.Class))
        g.add((EX.Topic, RDFS.subClassOf, EX.Category))
        g.add((EX.Person, RDFS.seeAlso, EX.Topic))
        svc = _service_with_graph(g)
        result = await svc.build_entity_graph(PROJECT_ID, str(EX.Person), BRANCH)
        assert result is not None
        iris = {n.iri for n in result.nodes}
        assert str(EX.Topic) in iris
        assert str(EX.Category) in iris

    @pytest.mark.asyncio
    async def test_see_also_secondary_root(self) -> None:
        """Roots discovered via seeAlso branches get 'secondary_root' type."""
        g = _base_graph()
        g.add((EX.Category, RDF.type, OWL.Class))
        g.add((EX.Topic, RDF.type, OWL.Class))
        g.add((EX.Topic, RDFS.subClassOf, EX.Category))
        g.add((EX.Person, RDFS.seeAlso, EX.Topic))
        svc = _service_with_graph(g)
        result = await svc.build_entity_graph(PROJECT_ID, str(EX.Person), BRANCH)
        assert result is not None
        category = next(n for n in result.nodes if n.iri == str(EX.Category))
        assert category.node_type == "secondary_root"

    @pytest.mark.asyncio
    async def test_see_also_max_per_node(self) -> None:
        """max_see_also_per_node limits seeAlso targets collected per node."""
        g = _base_graph()
        for i in range(10):
            uri = URIRef(f"http://example.org/ontology#Related{i}")
            g.add((uri, RDF.type, OWL.Class))
            g.add((EX.Person, RDFS.seeAlso, uri))
        svc = _service_with_graph(g)
        result = await svc.build_entity_graph(
            PROJECT_ID, str(EX.Person), BRANCH, max_see_also_per_node=3
        )
        assert result is not None
        sa_edges = [e for e in result.edges if e.edge_type == "seeAlso"]
        assert len(sa_edges) == 3


class TestBuildEntityGraphClassification:
    @pytest.mark.asyncio
    async def test_external_namespace_classified(self) -> None:
        g = _base_graph()
        ext = URIRef("http://www.w3.org/2004/02/skos/core#Concept")
        g.add((EX.Person, RDFS.seeAlso, ext))
        g.add((ext, RDF.type, OWL.Class))
        svc = _service_with_graph(g)
        result = await svc.build_entity_graph(PROJECT_ID, str(EX.Person), BRANCH)
        assert result is not None
        ext_node = next((n for n in result.nodes if n.iri == str(ext)), None)
        assert ext_node is not None
        assert ext_node.node_type == "external"

    @pytest.mark.asyncio
    async def test_property_classified(self) -> None:
        g = _base_graph()
        g.add((EX.myProp, RDF.type, OWL.ObjectProperty))
        g.add((EX.Person, RDFS.seeAlso, EX.myProp))
        svc = _service_with_graph(g)
        result = await svc.build_entity_graph(PROJECT_ID, str(EX.Person), BRANCH)
        assert result is not None
        prop_node = next((n for n in result.nodes if n.iri == str(EX.myProp)), None)
        assert prop_node is not None
        assert prop_node.node_type == "property"

    @pytest.mark.asyncio
    async def test_individual_classified(self) -> None:
        g = _base_graph()
        g.add((EX.john, RDF.type, EX.Person))
        g.add((EX.Person, RDFS.seeAlso, EX.john))
        svc = _service_with_graph(g)
        result = await svc.build_entity_graph(PROJECT_ID, str(EX.Person), BRANCH)
        assert result is not None
        ind_node = next((n for n in result.nodes if n.iri == str(EX.john)), None)
        assert ind_node is not None
        assert ind_node.node_type == "individual"

    @pytest.mark.asyncio
    async def test_local_name_fallback_fragment(self) -> None:
        """When no label exists, local name is extracted from fragment."""
        g = Graph()
        ns = Namespace("http://example.org/ont#")
        g.add((ns.MyClass, RDF.type, OWL.Class))
        svc = _service_with_graph(g)
        result = await svc.build_entity_graph(PROJECT_ID, str(ns.MyClass), BRANCH)
        assert result is not None
        assert result.focus_label == "MyClass"

    @pytest.mark.asyncio
    async def test_local_name_fallback_slash(self) -> None:
        """When no label exists, local name is extracted from last path segment."""
        g = Graph()
        uri = URIRef("http://example.org/ontology/SlashClass")
        g.add((uri, RDF.type, OWL.Class))
        svc = _service_with_graph(g)
        result = await svc.build_entity_graph(PROJECT_ID, str(uri), BRANCH)
        assert result is not None
        assert result.focus_label == "SlashClass"


class TestBuildEntityGraphEdgeCases:
    @pytest.mark.asyncio
    async def test_owl_thing_parent_skipped(self) -> None:
        """owl:Thing parents should not appear as nodes."""
        g = _base_graph()
        g.add((EX.Animal, RDFS.subClassOf, OWL.Thing))
        svc = _service_with_graph(g)
        result = await svc.build_entity_graph(PROJECT_ID, str(EX.Person), BRANCH)
        assert result is not None
        iris = {n.iri for n in result.nodes}
        assert str(OWL.Thing) not in iris

    @pytest.mark.asyncio
    async def test_duplicate_edges_prevented(self) -> None:
        """Same edge should not appear twice."""
        svc = _service_with_graph(_base_graph())
        result = await svc.build_entity_graph(PROJECT_ID, str(EX.Person), BRANCH)
        assert result is not None
        edge_ids = [e.id for e in result.edges]
        assert len(edge_ids) == len(set(edge_ids))

    @pytest.mark.asyncio
    async def test_already_visited_node_reused(self) -> None:
        """If a node is discovered via both ancestor and descendant BFS, it's not duplicated."""
        g = _base_graph()
        # Add a diamond: Student also subClassOf Animal (redundant)
        g.add((EX.Student, RDFS.subClassOf, EX.Animal))
        svc = _service_with_graph(g)
        result = await svc.build_entity_graph(PROJECT_ID, str(EX.Person), BRANCH)
        assert result is not None
        animal_nodes = [n for n in result.nodes if n.iri == str(EX.Animal)]
        assert len(animal_nodes) == 1
