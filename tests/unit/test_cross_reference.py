"""Tests for cross-reference service (ontokit/services/cross_reference_service.py)."""

from rdflib import BNode, Graph, Literal, Namespace
from rdflib.namespace import OWL, RDF, RDFS

from ontokit.services.cross_reference_service import get_cross_references

EX = Namespace("http://example.org/")


def test_find_references_to_class() -> None:
    """Class used as range and domain should be found."""
    g = Graph()
    g.add((EX.Person, RDF.type, OWL.Class))
    g.add((EX.Person, RDFS.label, Literal("Person")))
    g.add((EX.worksFor, RDF.type, OWL.ObjectProperty))
    g.add((EX.worksFor, RDFS.domain, EX.Person))
    g.add((EX.knows, RDF.type, OWL.ObjectProperty))
    g.add((EX.knows, RDFS.range, EX.Person))

    result = get_cross_references(g, str(EX.Person))
    assert result.target_iri == str(EX.Person)
    assert result.total == 2

    contexts = {grp.context for grp in result.groups}
    assert "domain_iris" in contexts
    assert "range_iris" in contexts


def test_no_references() -> None:
    """Unreferenced entity should return empty groups."""
    g = Graph()
    g.add((EX.Isolated, RDF.type, OWL.Class))

    result = get_cross_references(g, str(EX.Isolated))
    assert result.total == 0
    assert len(result.groups) == 0


def test_references_with_blank_node() -> None:
    """Blank node owner resolution: reference via OWL restriction traced to named class."""
    g = Graph()
    g.add((EX.Animal, RDF.type, OWL.Class))
    g.add((EX.Animal, RDFS.label, Literal("Animal")))
    g.add((EX.Dog, RDF.type, OWL.Class))

    # Create an OWL restriction (blank node) that references EX.Animal
    restriction = BNode()
    g.add((restriction, RDF.type, OWL.Restriction))
    g.add((restriction, OWL.someValuesFrom, EX.Animal))
    # Dog subClassOf the restriction (blank node)
    g.add((EX.Dog, RDFS.subClassOf, restriction))

    result = get_cross_references(g, str(EX.Animal))
    # Should find EX.Dog as the owner of the blank node reference
    assert result.total >= 1
    all_source_iris = [ref.source_iri for grp in result.groups for ref in grp.references]
    assert str(EX.Dog) in all_source_iris


def test_subclass_reference() -> None:
    """A subClassOf reference should be found in parent_iris context."""
    g = Graph()
    g.add((EX.Animal, RDF.type, OWL.Class))
    g.add((EX.Dog, RDF.type, OWL.Class))
    g.add((EX.Dog, RDFS.subClassOf, EX.Animal))

    result = get_cross_references(g, str(EX.Animal))
    assert result.total >= 1
    parent_groups = [grp for grp in result.groups if grp.context == "parent_iris"]
    assert len(parent_groups) == 1
    assert parent_groups[0].references[0].source_iri == str(EX.Dog)
