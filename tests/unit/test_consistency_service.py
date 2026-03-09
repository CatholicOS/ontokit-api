"""Tests for consistency checking service (ontokit/services/consistency_service.py)."""

from rdflib import Graph, Literal, Namespace
from rdflib.namespace import OWL, RDF, RDFS

from ontokit.services.consistency_service import (
    _check_cycle_detect,
    _check_dangling_ref,
    _check_deprecated_parent,
    _check_duplicate_label,
    _check_missing_comment,
    _check_missing_label,
    _check_multi_root,
    _check_orphan_class,
    _check_unused_property,
    run_consistency_check,
)

EX = Namespace("http://example.org/")


# ---------------------------------------------------------------------------
# orphan_class
# ---------------------------------------------------------------------------


def test_orphan_class() -> None:
    g = Graph()
    g.add((EX.Lonely, RDF.type, OWL.Class))
    issues = _check_orphan_class(g)
    assert len(issues) == 1
    assert issues[0].rule_id == "orphan_class"
    assert issues[0].entity_iri == str(EX.Lonely)


def test_non_orphan_class() -> None:
    g = Graph()
    g.add((EX.Animal, RDF.type, OWL.Class))
    g.add((EX.Dog, RDF.type, OWL.Class))
    g.add((EX.Dog, RDFS.subClassOf, EX.Animal))
    issues = _check_orphan_class(g)
    assert len(issues) == 0


# ---------------------------------------------------------------------------
# cycle_detect
# ---------------------------------------------------------------------------


def test_cycle_detect() -> None:
    g = Graph()
    g.add((EX.A, RDF.type, OWL.Class))
    g.add((EX.B, RDF.type, OWL.Class))
    g.add((EX.A, RDFS.subClassOf, EX.B))
    g.add((EX.B, RDFS.subClassOf, EX.A))
    issues = _check_cycle_detect(g)
    assert len(issues) >= 1
    assert issues[0].rule_id == "cycle_detect"
    assert issues[0].severity == "error"


def test_no_cycle() -> None:
    g = Graph()
    g.add((EX.A, RDF.type, OWL.Class))
    g.add((EX.B, RDF.type, OWL.Class))
    g.add((EX.C, RDF.type, OWL.Class))
    g.add((EX.C, RDFS.subClassOf, EX.B))
    g.add((EX.B, RDFS.subClassOf, EX.A))
    issues = _check_cycle_detect(g)
    assert len(issues) == 0


# ---------------------------------------------------------------------------
# unused_property
# ---------------------------------------------------------------------------


def test_unused_property() -> None:
    g = Graph()
    g.add((EX.hasPart, RDF.type, OWL.ObjectProperty))
    issues = _check_unused_property(g)
    assert len(issues) == 1
    assert issues[0].rule_id == "unused_property"
    assert issues[0].entity_iri == str(EX.hasPart)


def test_used_property() -> None:
    g = Graph()
    g.add((EX.hasPart, RDF.type, OWL.ObjectProperty))
    g.add((EX.Car, EX.hasPart, EX.Engine))
    issues = _check_unused_property(g)
    assert len(issues) == 0


# ---------------------------------------------------------------------------
# missing_label / missing_comment
# ---------------------------------------------------------------------------


def test_missing_label() -> None:
    g = Graph()
    g.add((EX.Animal, RDF.type, OWL.Class))
    issues = _check_missing_label(g)
    assert any(i.rule_id == "missing_label" and i.entity_iri == str(EX.Animal) for i in issues)


def test_has_label_no_issue() -> None:
    g = Graph()
    g.add((EX.Animal, RDF.type, OWL.Class))
    g.add((EX.Animal, RDFS.label, Literal("Animal")))
    issues = _check_missing_label(g)
    assert not any(i.entity_iri == str(EX.Animal) for i in issues)


def test_missing_comment() -> None:
    g = Graph()
    g.add((EX.Animal, RDF.type, OWL.Class))
    issues = _check_missing_comment(g)
    assert any(i.rule_id == "missing_comment" and i.entity_iri == str(EX.Animal) for i in issues)


def test_has_comment_no_issue() -> None:
    g = Graph()
    g.add((EX.Animal, RDF.type, OWL.Class))
    g.add((EX.Animal, RDFS.comment, Literal("A living organism")))
    issues = _check_missing_comment(g)
    assert not any(i.entity_iri == str(EX.Animal) for i in issues)


# ---------------------------------------------------------------------------
# duplicate_label
# ---------------------------------------------------------------------------


def test_duplicate_label() -> None:
    g = Graph()
    g.add((EX.Foo, RDF.type, OWL.Class))
    g.add((EX.Foo, RDFS.label, Literal("Thing", lang="en")))
    g.add((EX.Bar, RDF.type, OWL.Class))
    g.add((EX.Bar, RDFS.label, Literal("Thing", lang="en")))
    issues = _check_duplicate_label(g)
    assert len(issues) == 2
    iris = {i.entity_iri for i in issues}
    assert str(EX.Foo) in iris
    assert str(EX.Bar) in iris


def test_no_duplicate_label() -> None:
    g = Graph()
    g.add((EX.Foo, RDF.type, OWL.Class))
    g.add((EX.Foo, RDFS.label, Literal("Foo")))
    g.add((EX.Bar, RDF.type, OWL.Class))
    g.add((EX.Bar, RDFS.label, Literal("Bar")))
    issues = _check_duplicate_label(g)
    assert len(issues) == 0


# ---------------------------------------------------------------------------
# deprecated_parent
# ---------------------------------------------------------------------------


def test_deprecated_parent() -> None:
    g = Graph()
    g.add((EX.Parent, RDF.type, OWL.Class))
    g.add((EX.Parent, OWL.deprecated, Literal(True)))
    g.add((EX.Child, RDF.type, OWL.Class))
    g.add((EX.Child, RDFS.subClassOf, EX.Parent))
    issues = _check_deprecated_parent(g)
    assert len(issues) == 1
    assert issues[0].rule_id == "deprecated_parent"
    assert issues[0].entity_iri == str(EX.Child)


def test_no_deprecated_parent() -> None:
    g = Graph()
    g.add((EX.Parent, RDF.type, OWL.Class))
    g.add((EX.Child, RDF.type, OWL.Class))
    g.add((EX.Child, RDFS.subClassOf, EX.Parent))
    issues = _check_deprecated_parent(g)
    assert len(issues) == 0


# ---------------------------------------------------------------------------
# dangling_ref
# ---------------------------------------------------------------------------


def test_dangling_ref() -> None:
    g = Graph()
    g.add((EX.Child, RDF.type, OWL.Class))
    g.add((EX.Child, RDFS.subClassOf, EX.Phantom))
    issues = _check_dangling_ref(g)
    assert len(issues) == 1
    assert issues[0].rule_id == "dangling_ref"
    assert issues[0].entity_iri == str(EX.Child)


def test_no_dangling_ref() -> None:
    g = Graph()
    g.add((EX.Parent, RDF.type, OWL.Class))
    g.add((EX.Child, RDF.type, OWL.Class))
    g.add((EX.Child, RDFS.subClassOf, EX.Parent))
    issues = _check_dangling_ref(g)
    assert len(issues) == 0


# ---------------------------------------------------------------------------
# multi_root
# ---------------------------------------------------------------------------


def test_multi_root() -> None:
    g = Graph()
    # Create 6 root classes (threshold is >5)
    for i in range(6):
        cls = EX[f"Root{i}"]
        g.add((cls, RDF.type, OWL.Class))
    issues = _check_multi_root(g)
    assert len(issues) == 1
    assert issues[0].rule_id == "multi_root"
    assert issues[0].details is not None
    assert issues[0].details["root_count"] == 6


def test_no_multi_root() -> None:
    g = Graph()
    # 5 root classes — at threshold, should NOT trigger
    for i in range(5):
        cls = EX[f"Root{i}"]
        g.add((cls, RDF.type, OWL.Class))
    issues = _check_multi_root(g)
    assert len(issues) == 0


# ---------------------------------------------------------------------------
# run_consistency_check (integration)
# ---------------------------------------------------------------------------


def test_run_consistency_check() -> None:
    g = Graph()
    g.add((EX.Animal, RDF.type, OWL.Class))
    g.add((EX.Animal, RDFS.label, Literal("Animal")))
    g.add((EX.Animal, RDFS.comment, Literal("A living organism")))
    result = run_consistency_check(g, project_id="proj-1", branch="main")
    assert result.project_id == "proj-1"
    assert result.branch == "main"
    assert result.duration_ms >= 0
    assert isinstance(result.issues, list)
