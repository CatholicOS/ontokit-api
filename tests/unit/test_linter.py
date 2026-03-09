"""Tests for the ontology linter service (ontokit/services/linter.py)."""

from uuid import uuid4

import pytest
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS

from ontokit.services.linter import LINT_RULES, LintResult, OntologyLinter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

EX = Namespace("http://example.org/")

# A fixed project UUID used for every lint call (the linter does not use it
# beyond passing it through).
PROJECT_ID = uuid4()


def _results_with_rule(results: list[LintResult], rule_id: str) -> list[LintResult]:
    """Filter results to those matching a specific rule_id."""
    return [r for r in results if r.rule_id == rule_id]


# ---------------------------------------------------------------------------
# 1. test_missing_label
# ---------------------------------------------------------------------------


async def test_missing_label() -> None:
    """A class without rdfs:label should generate a 'missing-label' warning."""
    g = Graph()
    g.add((EX.Animal, RDF.type, OWL.Class))
    # No rdfs:label added

    linter = OntologyLinter(enabled_rules={"missing-label"})
    issues = await linter.lint(g, PROJECT_ID)

    matches = _results_with_rule(issues, "missing-label")
    assert len(matches) == 1
    assert matches[0].issue_type == "warning"
    assert matches[0].subject_iri == str(EX.Animal)


# ---------------------------------------------------------------------------
# 2. test_no_missing_label
# ---------------------------------------------------------------------------


async def test_no_missing_label() -> None:
    """A class with rdfs:label should NOT generate a 'missing-label' issue."""
    g = Graph()
    g.add((EX.Animal, RDF.type, OWL.Class))
    g.add((EX.Animal, RDFS.label, Literal("Animal", lang="en")))

    linter = OntologyLinter(enabled_rules={"missing-label"})
    issues = await linter.lint(g, PROJECT_ID)

    matches = _results_with_rule(issues, "missing-label")
    assert len(matches) == 0


# ---------------------------------------------------------------------------
# 3. test_missing_comment
# ---------------------------------------------------------------------------


async def test_missing_comment() -> None:
    """A class without rdfs:comment should generate a 'missing-comment' info."""
    g = Graph()
    g.add((EX.Animal, RDF.type, OWL.Class))
    g.add((EX.Animal, RDFS.label, Literal("Animal", lang="en")))
    # No rdfs:comment

    linter = OntologyLinter(enabled_rules={"missing-comment"})
    issues = await linter.lint(g, PROJECT_ID)

    matches = _results_with_rule(issues, "missing-comment")
    assert len(matches) == 1
    assert matches[0].issue_type == "info"
    assert matches[0].subject_iri == str(EX.Animal)


# ---------------------------------------------------------------------------
# 4. test_orphan_class
# ---------------------------------------------------------------------------


async def test_orphan_class() -> None:
    """A class with no parents (other than owl:Thing) and no children is orphaned."""
    g = Graph()
    g.add((EX.Lonely, RDF.type, OWL.Class))
    g.add((EX.Lonely, RDFS.label, Literal("Lonely", lang="en")))

    linter = OntologyLinter(enabled_rules={"orphan-class"})
    issues = await linter.lint(g, PROJECT_ID)

    matches = _results_with_rule(issues, "orphan-class")
    assert len(matches) == 1
    assert matches[0].issue_type == "warning"
    assert matches[0].subject_iri == str(EX.Lonely)


async def test_no_orphan_with_parent() -> None:
    """A class with an explicit parent is NOT orphaned."""
    g = Graph()
    g.add((EX.Animal, RDF.type, OWL.Class))
    g.add((EX.Dog, RDF.type, OWL.Class))
    g.add((EX.Dog, RDFS.subClassOf, EX.Animal))

    linter = OntologyLinter(enabled_rules={"orphan-class"})
    issues = await linter.lint(g, PROJECT_ID)

    # Dog has a parent (Animal), and Animal has a child (Dog)
    matches = _results_with_rule(issues, "orphan-class")
    assert len(matches) == 0


# ---------------------------------------------------------------------------
# 5. test_circular_hierarchy
# ---------------------------------------------------------------------------


async def test_circular_hierarchy() -> None:
    """A -> B -> A circular hierarchy should generate an error."""
    g = Graph()
    g.add((EX.A, RDF.type, OWL.Class))
    g.add((EX.B, RDF.type, OWL.Class))
    g.add((EX.A, RDFS.subClassOf, EX.B))
    g.add((EX.B, RDFS.subClassOf, EX.A))

    linter = OntologyLinter(enabled_rules={"circular-hierarchy"})
    issues = await linter.lint(g, PROJECT_ID)

    matches = _results_with_rule(issues, "circular-hierarchy")
    assert len(matches) >= 1
    assert matches[0].issue_type == "error"
    # The cycle should mention both classes
    cycle_iris = matches[0].details["cycle_iris"]
    assert str(EX.A) in cycle_iris
    assert str(EX.B) in cycle_iris


# ---------------------------------------------------------------------------
# 6. test_empty_label
# ---------------------------------------------------------------------------


async def test_empty_label() -> None:
    """A class with an empty-string label generates an 'empty-label' warning."""
    g = Graph()
    g.add((EX.Blank, RDF.type, OWL.Class))
    g.add((EX.Blank, RDFS.label, Literal("", lang="en")))

    linter = OntologyLinter(enabled_rules={"empty-label"})
    issues = await linter.lint(g, PROJECT_ID)

    matches = _results_with_rule(issues, "empty-label")
    assert len(matches) == 1
    assert matches[0].issue_type == "warning"
    assert matches[0].subject_iri == str(EX.Blank)


async def test_no_empty_label() -> None:
    """A class with a non-empty label does not trigger 'empty-label'."""
    g = Graph()
    g.add((EX.Valid, RDF.type, OWL.Class))
    g.add((EX.Valid, RDFS.label, Literal("Valid Class", lang="en")))

    linter = OntologyLinter(enabled_rules={"empty-label"})
    issues = await linter.lint(g, PROJECT_ID)

    matches = _results_with_rule(issues, "empty-label")
    assert len(matches) == 0


# ---------------------------------------------------------------------------
# 7. test_duplicate_label
# ---------------------------------------------------------------------------


async def test_duplicate_label() -> None:
    """Two classes sharing the same label generate 'duplicate-label' warnings."""
    g = Graph()
    g.add((EX.Foo, RDF.type, OWL.Class))
    g.add((EX.Foo, RDFS.label, Literal("Thing", lang="en")))
    g.add((EX.Bar, RDF.type, OWL.Class))
    g.add((EX.Bar, RDFS.label, Literal("Thing", lang="en")))

    linter = OntologyLinter(enabled_rules={"duplicate-label"})
    issues = await linter.lint(g, PROJECT_ID)

    matches = _results_with_rule(issues, "duplicate-label")
    # Both classes should be flagged
    assert len(matches) == 2
    flagged_iris = {m.subject_iri for m in matches}
    assert str(EX.Foo) in flagged_iris
    assert str(EX.Bar) in flagged_iris
    for m in matches:
        assert m.issue_type == "warning"


# ---------------------------------------------------------------------------
# 8. test_undefined_parent
# ---------------------------------------------------------------------------


async def test_undefined_parent() -> None:
    """A class referencing a parent not defined in the ontology generates an error."""
    g = Graph()
    g.add((EX.Child, RDF.type, OWL.Class))
    # Parent is NOT declared as an owl:Class in the graph
    g.add((EX.Child, RDFS.subClassOf, EX.Phantom))

    linter = OntologyLinter(enabled_rules={"undefined-parent"})
    issues = await linter.lint(g, PROJECT_ID)

    matches = _results_with_rule(issues, "undefined-parent")
    assert len(matches) == 1
    assert matches[0].issue_type == "error"
    assert matches[0].subject_iri == str(EX.Child)
    assert matches[0].details["undefined_parent"] == str(EX.Phantom)


async def test_no_undefined_parent_when_defined() -> None:
    """A parent that IS defined as owl:Class should not trigger the rule."""
    g = Graph()
    g.add((EX.Parent, RDF.type, OWL.Class))
    g.add((EX.Child, RDF.type, OWL.Class))
    g.add((EX.Child, RDFS.subClassOf, EX.Parent))

    linter = OntologyLinter(enabled_rules={"undefined-parent"})
    issues = await linter.lint(g, PROJECT_ID)

    matches = _results_with_rule(issues, "undefined-parent")
    assert len(matches) == 0


# ---------------------------------------------------------------------------
# 9. test_lint_all_rules — running lint on a valid ontology
# ---------------------------------------------------------------------------


async def test_lint_all_rules() -> None:
    """A well-formed ontology with two classes in a hierarchy returns expected results.

    The ontology has labels, comments, and a proper hierarchy, so most
    rules should produce no issues.  Only rules that require additional
    features (e.g. cardinality restrictions) may be silent simply because
    there is no data to check.
    """
    g = Graph()
    g.bind("ex", EX)

    # Two classes in a hierarchy, both well-annotated
    g.add((EX.Animal, RDF.type, OWL.Class))
    g.add((EX.Animal, RDFS.label, Literal("Animal", lang="en")))
    g.add((EX.Animal, RDFS.comment, Literal("A living organism", lang="en")))

    g.add((EX.Dog, RDF.type, OWL.Class))
    g.add((EX.Dog, RDFS.label, Literal("Dog", lang="en")))
    g.add((EX.Dog, RDFS.comment, Literal("A domesticated canine", lang="en")))
    g.add((EX.Dog, RDFS.subClassOf, EX.Animal))

    linter = OntologyLinter()  # all rules enabled
    issues = await linter.lint(g, PROJECT_ID)

    # No missing-label, missing-comment, orphan, circular, empty, duplicate,
    # or undefined-parent issues expected
    for rule_id in (
        "missing-label",
        "missing-comment",
        "circular-hierarchy",
        "empty-label",
        "duplicate-label",
        "undefined-parent",
    ):
        assert _results_with_rule(issues, rule_id) == [], (
            f"Unexpected issue for rule '{rule_id}'"
        )

    # Orphan should also be clear because Dog->Animal hierarchy exists
    assert _results_with_rule(issues, "orphan-class") == []


# ---------------------------------------------------------------------------
# 10. test_lint_enabled_rules_filter
# ---------------------------------------------------------------------------


async def test_lint_enabled_rules_filter() -> None:
    """Only rules in the enabled_rules set are actually executed."""
    g = Graph()
    g.add((EX.Unlabeled, RDF.type, OWL.Class))
    # This class has no label AND no comment, but we only enable missing-label

    linter = OntologyLinter(enabled_rules={"missing-label"})
    issues = await linter.lint(g, PROJECT_ID)

    # missing-label should fire
    assert len(_results_with_rule(issues, "missing-label")) == 1
    # missing-comment should NOT fire (not enabled)
    assert len(_results_with_rule(issues, "missing-comment")) == 0
    # orphan-class should NOT fire either
    assert len(_results_with_rule(issues, "orphan-class")) == 0


async def test_lint_no_enabled_rules() -> None:
    """When enabled_rules is empty, no issues are produced."""
    g = Graph()
    g.add((EX.Unlabeled, RDF.type, OWL.Class))

    linter = OntologyLinter(enabled_rules=set())
    issues = await linter.lint(g, PROJECT_ID)

    assert issues == []
