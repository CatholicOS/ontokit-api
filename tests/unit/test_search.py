"""Tests for the search service (ontokit/services/search.py)."""

from uuid import uuid4

import pytest
from rdflib import Graph, Literal, Namespace
from rdflib.namespace import OWL, RDF, RDFS

from ontokit.schemas.search import SearchQuery, SPARQLQuery
from ontokit.services.search import SearchService, _sanitize_tsquery_input

DUMMY_PROJECT_ID = str(uuid4())


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sample_graph() -> Graph:
    """Build a small RDFLib graph with two classes for SPARQL testing."""
    g = Graph()
    EX = Namespace("http://example.org/")
    g.bind("ex", EX)

    g.add((EX.Person, RDF.type, OWL.Class))
    g.add((EX.Person, RDFS.label, Literal("Person", lang="en")))
    g.add((EX.Organization, RDF.type, OWL.Class))
    g.add((EX.Organization, RDFS.label, Literal("Organization", lang="en")))
    return g


# ---------------------------------------------------------------------------
# _sanitize_tsquery_input tests
# ---------------------------------------------------------------------------


def test_sanitize_tsquery_basic() -> None:
    """Plain words are joined with ' & '."""
    assert _sanitize_tsquery_input("hello world") == "hello & world"


def test_sanitize_tsquery_special_chars() -> None:
    """Special characters are stripped; remaining tokens joined with ' & '."""
    assert _sanitize_tsquery_input("test:foo(bar)") == "test & foo & bar"


def test_sanitize_tsquery_empty() -> None:
    """An empty string returns an empty string."""
    assert _sanitize_tsquery_input("") == ""


def test_sanitize_tsquery_only_special_chars() -> None:
    """A string with only special characters returns empty."""
    assert _sanitize_tsquery_input(":::!!!") == ""


def test_sanitize_tsquery_extra_whitespace() -> None:
    """Multiple spaces between words are collapsed."""
    assert _sanitize_tsquery_input("  hello   world  ") == "hello & world"


# ---------------------------------------------------------------------------
# SearchService.search — no database
# ---------------------------------------------------------------------------


async def test_search_no_db_returns_empty() -> None:
    """When no database session is available, search returns an empty response."""
    svc = SearchService(db=None)
    query = SearchQuery(query="anything")

    result = await svc.search(query)

    assert result.results == []
    assert result.total == 0
    assert result.query == "anything"
    assert result.took_ms >= 0


# ---------------------------------------------------------------------------
# SearchService.execute_sparql
# ---------------------------------------------------------------------------


async def test_execute_sparql_select(sample_graph: Graph) -> None:
    """A SELECT query returns variable names and binding rows."""
    svc = SearchService()
    sparql = SPARQLQuery(
        query=(
            "SELECT ?cls ?label WHERE {"
            "  ?cls a <http://www.w3.org/2002/07/owl#Class> ."
            "  ?cls <http://www.w3.org/2000/01/rdf-schema#label> ?label ."
            "}"
        ),
        ontology_id=DUMMY_PROJECT_ID,
    )

    resp = await svc.execute_sparql(sparql, graph=sample_graph)

    assert resp.query_type == "SELECT"
    assert resp.variables is not None
    assert "cls" in resp.variables
    assert "label" in resp.variables
    assert resp.bindings is not None
    assert len(resp.bindings) == 2  # Person and Organization

    # Verify binding content
    labels = {row["label"].value for row in resp.bindings}
    assert "Person" in labels
    assert "Organization" in labels

    # Verify types
    for row in resp.bindings:
        assert row["cls"].type == "uri"
        assert row["label"].type == "literal"
        assert row["label"].lang == "en"


async def test_execute_sparql_ask(sample_graph: Graph) -> None:
    """An ASK query returns a boolean result."""
    svc = SearchService()
    sparql = SPARQLQuery(
        query="ASK { ?x a <http://www.w3.org/2002/07/owl#Class> }",
        ontology_id=DUMMY_PROJECT_ID,
    )

    resp = await svc.execute_sparql(sparql, graph=sample_graph)

    assert resp.query_type == "ASK"
    assert resp.boolean is True


async def test_execute_sparql_ask_false(sample_graph: Graph) -> None:
    """An ASK query returns False when the pattern has no match."""
    svc = SearchService()
    sparql = SPARQLQuery(
        query=("ASK { <http://example.org/DoesNotExist> a <http://www.w3.org/2002/07/owl#Class> }"),
        ontology_id=DUMMY_PROJECT_ID,
    )

    resp = await svc.execute_sparql(sparql, graph=sample_graph)

    assert resp.query_type == "ASK"
    assert resp.boolean is False


async def test_execute_sparql_construct(sample_graph: Graph) -> None:
    """A CONSTRUCT query returns a serialized graph string."""
    svc = SearchService()
    sparql = SPARQLQuery(
        query=(
            "CONSTRUCT {"
            "  ?cls <http://www.w3.org/2000/01/rdf-schema#label> ?label"
            "} WHERE {"
            "  ?cls a <http://www.w3.org/2002/07/owl#Class> ."
            "  ?cls <http://www.w3.org/2000/01/rdf-schema#label> ?label"
            "}"
        ),
        ontology_id=DUMMY_PROJECT_ID,
    )

    resp = await svc.execute_sparql(sparql, graph=sample_graph)

    assert resp.query_type == "CONSTRUCT"
    assert resp.graph is not None
    assert isinstance(resp.graph, str)
    # The serialized turtle should contain the label text
    assert "Person" in resp.graph
    assert "Organization" in resp.graph


async def test_execute_sparql_empty_graph() -> None:
    """A SELECT on an empty graph returns empty results (no crash)."""
    svc = SearchService()
    sparql = SPARQLQuery(
        query="SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 10",
        ontology_id=DUMMY_PROJECT_ID,
    )

    resp = await svc.execute_sparql(sparql, graph=None)

    assert resp.query_type == "SELECT"
    assert resp.bindings is not None
    assert len(resp.bindings) == 0
    assert resp.took_ms >= 0


async def test_execute_sparql_invalid_query() -> None:
    """An invalid SPARQL query raises ValueError during query type detection."""
    svc = SearchService()
    sparql = SPARQLQuery(
        query="THIS IS NOT VALID SPARQL AT ALL !!!",
        ontology_id=DUMMY_PROJECT_ID,
    )

    with pytest.raises(ValueError, match="Invalid SPARQL query"):
        await svc.execute_sparql(sparql, graph=Graph())
