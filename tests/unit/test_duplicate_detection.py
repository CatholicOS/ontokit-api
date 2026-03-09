"""Tests for duplicate detection service (ontokit/services/duplicate_detection_service.py)."""

from rdflib import Graph, Literal, Namespace
from rdflib.namespace import OWL, RDF, RDFS

from ontokit.services.duplicate_detection_service import find_duplicates

EX = Namespace("http://example.org/")


def test_find_duplicates_by_label() -> None:
    g = Graph()
    g.add((EX.Foo, RDF.type, OWL.Class))
    g.add((EX.Foo, RDFS.label, Literal("Widget")))
    g.add((EX.Bar, RDF.type, OWL.Class))
    g.add((EX.Bar, RDFS.label, Literal("Widget")))

    result = find_duplicates(g, threshold=0.85)
    assert len(result.clusters) == 1
    iris = {e.iri for e in result.clusters[0].entities}
    assert str(EX.Foo) in iris
    assert str(EX.Bar) in iris


def test_no_duplicates() -> None:
    g = Graph()
    g.add((EX.Apple, RDF.type, OWL.Class))
    g.add((EX.Apple, RDFS.label, Literal("Apple")))
    g.add((EX.Banana, RDF.type, OWL.Class))
    g.add((EX.Banana, RDFS.label, Literal("Banana")))

    result = find_duplicates(g, threshold=0.85)
    assert len(result.clusters) == 0


def test_similarity_zero_not_falsy() -> None:
    """Similarity of 0.0 should be handled correctly (not treated as None/falsy)."""
    g = Graph()
    g.add((EX.A, RDF.type, OWL.Class))
    g.add((EX.A, RDFS.label, Literal("AAAA")))
    g.add((EX.B, RDF.type, OWL.Class))
    g.add((EX.B, RDFS.label, Literal("ZZZZ")))

    result = find_duplicates(g, threshold=0.85)
    # Very different labels should not cluster
    assert len(result.clusters) == 0


def test_find_duplicates_cross_type() -> None:
    """Duplicates are only detected within the same entity type."""
    g = Graph()
    g.add((EX.Widget, RDF.type, OWL.Class))
    g.add((EX.Widget, RDFS.label, Literal("Widget")))
    g.add((EX.widgetProp, RDF.type, OWL.ObjectProperty))
    g.add((EX.widgetProp, RDFS.label, Literal("Widget")))

    result = find_duplicates(g, threshold=0.85)
    # Same label but different types — should NOT cluster
    assert len(result.clusters) == 0


def test_find_duplicates_similar_labels() -> None:
    """Very similar (but not identical) labels should cluster above threshold."""
    g = Graph()
    g.add((EX.PersonInfo, RDF.type, OWL.Class))
    g.add((EX.PersonInfo, RDFS.label, Literal("Person Information")))
    g.add((EX.PersonInformation, RDF.type, OWL.Class))
    g.add((EX.PersonInformation, RDFS.label, Literal("Person Informations")))

    result = find_duplicates(g, threshold=0.85)
    assert len(result.clusters) == 1
    assert result.clusters[0].similarity >= 0.85
