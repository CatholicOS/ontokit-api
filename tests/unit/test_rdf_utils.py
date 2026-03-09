"""Tests for shared RDF utilities (ontokit/services/rdf_utils.py)."""

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS

from ontokit.services.rdf_utils import get_entity_type, is_deprecated

EX = Namespace("http://example.org/")


def test_get_entity_type_owl_class() -> None:
    g = Graph()
    g.add((EX.Animal, RDF.type, OWL.Class))
    assert get_entity_type(g, EX.Animal) == "class"


def test_get_entity_type_rdfs_class() -> None:
    g = Graph()
    g.add((EX.Animal, RDF.type, RDFS.Class))
    assert get_entity_type(g, EX.Animal) == "class"


def test_get_entity_type_object_property() -> None:
    g = Graph()
    g.add((EX.hasPart, RDF.type, OWL.ObjectProperty))
    assert get_entity_type(g, EX.hasPart) == "property"


def test_get_entity_type_datatype_property() -> None:
    g = Graph()
    g.add((EX.hasName, RDF.type, OWL.DatatypeProperty))
    assert get_entity_type(g, EX.hasName) == "property"


def test_get_entity_type_annotation_property() -> None:
    g = Graph()
    g.add((EX.note, RDF.type, OWL.AnnotationProperty))
    assert get_entity_type(g, EX.note) == "property"


def test_get_entity_type_rdf_property() -> None:
    g = Graph()
    g.add((EX.relates, RDF.type, RDF.Property))
    assert get_entity_type(g, EX.relates) == "property"


def test_get_entity_type_individual() -> None:
    g = Graph()
    g.add((EX.john, RDF.type, OWL.NamedIndividual))
    assert get_entity_type(g, EX.john) == "individual"


def test_get_entity_type_unknown() -> None:
    g = Graph()
    # URI exists but has no rdf:type matching _TYPE_CHECKS
    g.add((EX.mystery, RDFS.label, Literal("Mystery")))
    assert get_entity_type(g, EX.mystery) == "unknown"


def test_is_deprecated_true() -> None:
    g = Graph()
    g.add((EX.Old, OWL.deprecated, Literal(True)))
    assert is_deprecated(g, EX.Old) is True


def test_is_deprecated_string_true() -> None:
    g = Graph()
    g.add((EX.Old, OWL.deprecated, Literal("true")))
    assert is_deprecated(g, EX.Old) is True


def test_is_deprecated_one() -> None:
    g = Graph()
    g.add((EX.Old, OWL.deprecated, Literal("1")))
    assert is_deprecated(g, EX.Old) is True


def test_is_deprecated_false() -> None:
    g = Graph()
    g.add((EX.Fresh, RDF.type, OWL.Class))
    assert is_deprecated(g, EX.Fresh) is False


def test_is_deprecated_no_triples() -> None:
    g = Graph()
    assert is_deprecated(g, URIRef("http://example.org/nonexistent")) is False
