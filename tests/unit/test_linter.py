"""Tests for the ontology linter service (ontokit/services/linter.py)."""

from uuid import uuid4

from rdflib import Graph, Literal, Namespace
from rdflib.namespace import OWL, RDF, RDFS

from ontokit.services.linter import (
    LINT_RULES,
    LintResult,
    OntologyLinter,
    get_available_rules,
    get_linter,
)

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
    assert matches[0].details is not None
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
    assert matches[0].details is not None
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
        assert _results_with_rule(issues, rule_id) == [], f"Unexpected issue for rule '{rule_id}'"

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


# ---------------------------------------------------------------------------
# 11. get_available_rules / get_linter factory
# ---------------------------------------------------------------------------


def test_get_available_rules_returns_all() -> None:
    """get_available_rules returns a copy of all defined rules."""
    rules = get_available_rules()
    assert len(rules) == len(LINT_RULES)
    # Verify it is a copy, not the same object
    assert rules is not LINT_RULES


def test_get_linter_all_rules() -> None:
    """get_linter() with no args enables all rules."""
    linter = get_linter()
    assert linter.enabled_rules == {r.rule_id for r in LINT_RULES}


def test_get_linter_specific_rules() -> None:
    """get_linter(enabled_rules=...) enables only specified rules."""
    linter = get_linter(enabled_rules={"missing-label", "orphan-class"})
    assert linter.enabled_rules == {"missing-label", "orphan-class"}


def test_get_enabled_rules_method() -> None:
    """get_enabled_rules returns LintRuleInfo objects for enabled rules only."""
    linter = OntologyLinter(enabled_rules={"missing-label"})
    enabled = linter.get_enabled_rules()
    assert len(enabled) == 1
    assert enabled[0].rule_id == "missing-label"


# ---------------------------------------------------------------------------
# 12. label-per-language
# ---------------------------------------------------------------------------


async def test_label_per_language_multiple_labels() -> None:
    """Multiple different labels for the same language trigger label-per-language."""
    g = Graph()
    g.add((EX.Animal, RDF.type, OWL.Class))
    g.add((EX.Animal, RDFS.label, Literal("Animal", lang="en")))
    g.add((EX.Animal, RDFS.label, Literal("Beast", lang="en")))

    linter = OntologyLinter(enabled_rules={"label-per-language"})
    issues = await linter.lint(g, PROJECT_ID)

    matches = _results_with_rule(issues, "label-per-language")
    assert len(matches) == 1
    assert matches[0].issue_type == "error"
    assert matches[0].subject_iri == str(EX.Animal)


async def test_label_per_language_no_issue_when_same() -> None:
    """Identical labels for the same language do not trigger label-per-language."""
    g = Graph()
    g.add((EX.Animal, RDF.type, OWL.Class))
    g.add((EX.Animal, RDFS.label, Literal("Animal", lang="en")))

    linter = OntologyLinter(enabled_rules={"label-per-language"})
    issues = await linter.lint(g, PROJECT_ID)

    matches = _results_with_rule(issues, "label-per-language")
    assert len(matches) == 0


# ---------------------------------------------------------------------------
# 13. domain-violation
# ---------------------------------------------------------------------------


async def test_domain_violation() -> None:
    """Using a property on a subject outside its declared domain triggers a warning."""
    g = Graph()
    g.bind("ex", EX)

    g.add((EX.Person, RDF.type, OWL.Class))
    g.add((EX.Animal, RDF.type, OWL.Class))
    g.add((EX.worksFor, RDF.type, OWL.ObjectProperty))
    g.add((EX.worksFor, RDFS.domain, EX.Person))

    # Use worksFor on an Animal instance — domain violation
    g.add((EX.fido, RDF.type, EX.Animal))
    g.add((EX.fido, EX.worksFor, EX.someOrg))

    linter = OntologyLinter(enabled_rules={"domain-violation"})
    issues = await linter.lint(g, PROJECT_ID)

    matches = _results_with_rule(issues, "domain-violation")
    assert len(matches) >= 1
    assert matches[0].issue_type == "warning"


# ---------------------------------------------------------------------------
# 14. range-violation
# ---------------------------------------------------------------------------


async def test_range_violation() -> None:
    """Using an object property with an object outside declared range triggers a warning."""
    g = Graph()
    g.bind("ex", EX)

    g.add((EX.Organization, RDF.type, OWL.Class))
    g.add((EX.Person, RDF.type, OWL.Class))
    g.add((EX.worksFor, RDF.type, OWL.ObjectProperty))
    g.add((EX.worksFor, RDFS.range, EX.Organization))

    # fido worksFor another Person — range violation
    g.add((EX.fido, EX.worksFor, EX.alice))
    g.add((EX.alice, RDF.type, EX.Person))

    linter = OntologyLinter(enabled_rules={"range-violation"})
    issues = await linter.lint(g, PROJECT_ID)

    matches = _results_with_rule(issues, "range-violation")
    assert len(matches) >= 1
    assert matches[0].issue_type == "warning"


# ---------------------------------------------------------------------------
# 15. disjoint-violation
# ---------------------------------------------------------------------------


async def test_disjoint_violation() -> None:
    """An instance typed with two disjoint classes triggers a disjoint-violation error."""
    g = Graph()
    g.bind("ex", EX)

    g.add((EX.Cat, RDF.type, OWL.Class))
    g.add((EX.Dog, RDF.type, OWL.Class))
    g.add((EX.Cat, OWL.disjointWith, EX.Dog))

    # Instance is both Cat and Dog
    g.add((EX.pet, RDF.type, EX.Cat))
    g.add((EX.pet, RDF.type, EX.Dog))

    linter = OntologyLinter(enabled_rules={"disjoint-violation"})
    issues = await linter.lint(g, PROJECT_ID)

    matches = _results_with_rule(issues, "disjoint-violation")
    assert len(matches) == 1
    assert matches[0].issue_type == "error"
    assert matches[0].subject_iri == str(EX.pet)


# ---------------------------------------------------------------------------
# 16. inverse-property-inconsistency
# ---------------------------------------------------------------------------


async def test_inverse_property_inconsistency() -> None:
    """Missing inverse assertion triggers inverse-property-inconsistency."""
    g = Graph()
    g.bind("ex", EX)

    g.add((EX.hasPart, RDF.type, OWL.ObjectProperty))
    g.add((EX.partOf, RDF.type, OWL.ObjectProperty))
    g.add((EX.hasPart, OWL.inverseOf, EX.partOf))

    # Forward assertion without inverse
    g.add((EX.car, EX.hasPart, EX.engine))
    # Missing: EX.engine EX.partOf EX.car

    linter = OntologyLinter(enabled_rules={"inverse-property-inconsistency"})
    issues = await linter.lint(g, PROJECT_ID)

    matches = _results_with_rule(issues, "inverse-property-inconsistency")
    assert len(matches) >= 1
    assert matches[0].issue_type == "warning"


# ---------------------------------------------------------------------------
# 17. missing-english-label
# ---------------------------------------------------------------------------


async def test_missing_english_label() -> None:
    """A class with labels only in non-English languages triggers missing-english-label."""
    g = Graph()
    g.add((EX.Chose, RDF.type, OWL.Class))
    g.add((EX.Chose, RDFS.label, Literal("Chose", lang="fr")))

    linter = OntologyLinter(enabled_rules={"missing-english-label"})
    issues = await linter.lint(g, PROJECT_ID)

    matches = _results_with_rule(issues, "missing-english-label")
    assert len(matches) == 1
    assert matches[0].issue_type == "warning"


async def test_no_missing_english_label_when_present() -> None:
    """A class with an English label does not trigger missing-english-label."""
    g = Graph()
    g.add((EX.Thing, RDF.type, OWL.Class))
    g.add((EX.Thing, RDFS.label, Literal("Thing", lang="en")))
    g.add((EX.Thing, RDFS.label, Literal("Chose", lang="fr")))

    linter = OntologyLinter(enabled_rules={"missing-english-label"})
    issues = await linter.lint(g, PROJECT_ID)

    matches = _results_with_rule(issues, "missing-english-label")
    assert len(matches) == 0
