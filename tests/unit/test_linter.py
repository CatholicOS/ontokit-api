"""Tests for the ontology linter service (ontokit/services/linter.py)."""

from uuid import uuid4

from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS, SKOS, XSD

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
    assert matches[0].subject_type == "class"


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


async def test_label_per_language_case_insensitive_lang_tag() -> None:
    """BCP-47 says language tags are case-insensitive — @en-US and @en-us are the
    same language and conflicting labels under those tags must be flagged."""
    g = Graph()
    g.add((EX.Animal, RDF.type, OWL.Class))
    g.add((EX.Animal, RDFS.label, Literal("Apple", lang="en-US")))
    g.add((EX.Animal, RDFS.label, Literal("Banana", lang="en-us")))

    linter = OntologyLinter(enabled_rules={"label-per-language"})
    issues = await linter.lint(g, PROJECT_ID)

    matches = _results_with_rule(issues, "label-per-language")
    assert len(matches) == 1
    assert matches[0].subject_iri == str(EX.Animal)


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


# ---------------------------------------------------------------------------
# 18. missing-language-tag
# ---------------------------------------------------------------------------


async def test_missing_language_tag_plain_literal() -> None:
    """A plain literal without a language tag triggers missing-language-tag."""
    g = Graph()
    g.add((EX.Animal, RDF.type, OWL.Class))
    g.add((EX.Animal, RDFS.label, Literal("Animal")))  # no lang

    linter = OntologyLinter(enabled_rules={"missing-language-tag"})
    issues = await linter.lint(g, PROJECT_ID)

    matches = _results_with_rule(issues, "missing-language-tag")
    assert len(matches) == 1
    assert matches[0].issue_type == "warning"
    assert matches[0].subject_iri == str(EX.Animal)


async def test_missing_language_tag_xsd_string() -> None:
    """An xsd:string typed literal triggers missing-language-tag with datatype note."""
    g = Graph()
    g.add((EX.Animal, RDF.type, OWL.Class))
    g.add((EX.Animal, RDFS.label, Literal("Animal", datatype=XSD.string)))

    linter = OntologyLinter(enabled_rules={"missing-language-tag"})
    issues = await linter.lint(g, PROJECT_ID)

    matches = _results_with_rule(issues, "missing-language-tag")
    assert len(matches) == 1
    assert "xsd:string" in matches[0].message


async def test_no_missing_language_tag_when_present() -> None:
    """A literal with a language tag does not trigger missing-language-tag."""
    g = Graph()
    g.add((EX.Animal, RDF.type, OWL.Class))
    g.add((EX.Animal, RDFS.label, Literal("Animal", lang="en")))

    linter = OntologyLinter(enabled_rules={"missing-language-tag"})
    issues = await linter.lint(g, PROJECT_ID)

    matches = _results_with_rule(issues, "missing-language-tag")
    assert len(matches) == 0


async def test_missing_language_tag_non_literal_object_skipped() -> None:
    """A URIRef object on a label predicate is silently skipped."""
    g = Graph()
    g.add((EX.Animal, RDF.type, OWL.Class))
    g.add((EX.Animal, RDFS.label, EX.SomeURI))  # not a literal

    linter = OntologyLinter(enabled_rules={"missing-language-tag"})
    issues = await linter.lint(g, PROJECT_ID)

    matches = _results_with_rule(issues, "missing-language-tag")
    assert len(matches) == 0


# ---------------------------------------------------------------------------
# 19. BNode / OWL.Thing skip branches
# ---------------------------------------------------------------------------


async def test_bnode_subjects_skipped() -> None:
    """BNode subjects are skipped by all annotation lint rules."""
    g = Graph()
    bnode = BNode()
    g.add((bnode, RDF.type, OWL.Class))
    g.add((bnode, RDFS.label, Literal("Blank", lang="fr")))
    g.add((bnode, RDFS.label, Literal("Other", lang="fr")))

    rules = {
        "missing-label",
        "missing-comment",
        "empty-label",
        "duplicate-label",
        "label-per-language",
        "missing-english-label",
        "missing-language-tag",
        "redundant-regional-label",
    }
    linter = OntologyLinter(enabled_rules=rules)
    issues = await linter.lint(g, PROJECT_ID)

    # BNode is the only subject, so no issues should be produced at all
    assert len(issues) == 0


async def test_owl_thing_skipped() -> None:
    """OWL.Thing is skipped by all annotation lint rules."""
    g = Graph()
    g.add((OWL.Thing, RDF.type, OWL.Class))
    g.add((OWL.Thing, RDFS.label, Literal("Thing", lang="fr")))
    g.add((OWL.Thing, RDFS.label, Literal("Chose", lang="fr")))

    rules = {
        "missing-label",
        "missing-comment",
        "empty-label",
        "duplicate-label",
        "label-per-language",
        "missing-english-label",
        "missing-language-tag",
        "redundant-regional-label",
    }
    linter = OntologyLinter(enabled_rules=rules)
    issues = await linter.lint(g, PROJECT_ID)

    # OWL.Thing is the only subject, so no issues should be produced at all
    assert len(issues) == 0


# ---------------------------------------------------------------------------
# 20. missing-english-label with skos:prefLabel
# ---------------------------------------------------------------------------


async def test_missing_english_label_skos_preflabel() -> None:
    """A resource with only a non-English skos:prefLabel triggers the rule."""
    g = Graph()
    g.add((EX.Chose, RDF.type, OWL.Class))
    g.add((EX.Chose, SKOS.prefLabel, Literal("Chose", lang="fr")))

    linter = OntologyLinter(enabled_rules={"missing-english-label"})
    issues = await linter.lint(g, PROJECT_ID)

    matches = _results_with_rule(issues, "missing-english-label")
    assert len(matches) == 1


async def test_no_missing_english_label_skos_preflabel_en() -> None:
    """An English skos:prefLabel satisfies the rule even without rdfs:label."""
    g = Graph()
    g.add((EX.Thing, RDF.type, OWL.Class))
    g.add((EX.Thing, SKOS.prefLabel, Literal("Thing", lang="en")))

    linter = OntologyLinter(enabled_rules={"missing-english-label"})
    issues = await linter.lint(g, PROJECT_ID)

    matches = _results_with_rule(issues, "missing-english-label")
    assert len(matches) == 0


# ---------------------------------------------------------------------------
# 21. redundant-regional-label
# ---------------------------------------------------------------------------


async def test_redundant_regional_label() -> None:
    """Identical values across regional variants trigger redundant-regional-label."""
    g = Graph()
    g.add((EX.Thing, RDF.type, OWL.Class))
    g.add((EX.Thing, SKOS.altLabel, Literal("Asignación", lang="es-es")))
    g.add((EX.Thing, SKOS.altLabel, Literal("Asignación", lang="es-mx")))

    linter = OntologyLinter(enabled_rules={"redundant-regional-label"})
    issues = await linter.lint(g, PROJECT_ID)

    matches = _results_with_rule(issues, "redundant-regional-label")
    assert len(matches) == 1
    assert matches[0].issue_type == "info"
    assert matches[0].subject_iri == str(EX.Thing)
    assert matches[0].details is not None
    assert "@es-es" in matches[0].message
    assert "@es-mx" in matches[0].message
    assert matches[0].details["base_language"] == "es"
    assert sorted(matches[0].details["regional_tags"]) == ["es-es", "es-mx"]
    assert matches[0].subject_type == "class"


async def test_no_redundant_regional_when_values_differ() -> None:
    """Different values across regional variants do NOT trigger the rule."""
    g = Graph()
    g.add((EX.Thing, RDF.type, OWL.Class))
    g.add((EX.Thing, SKOS.altLabel, Literal("Color", lang="en-us")))
    g.add((EX.Thing, SKOS.altLabel, Literal("Colour", lang="en-gb")))

    linter = OntologyLinter(enabled_rules={"redundant-regional-label"})
    issues = await linter.lint(g, PROJECT_ID)

    matches = _results_with_rule(issues, "redundant-regional-label")
    assert len(matches) == 0


async def test_no_redundant_regional_for_base_language() -> None:
    """A single regional tag or base-only tags do not trigger the rule."""
    g = Graph()
    g.add((EX.Thing, RDF.type, OWL.Class))
    g.add((EX.Thing, RDFS.label, Literal("Thing", lang="en")))
    g.add((EX.Thing, RDFS.label, Literal("Chose", lang="fr")))

    linter = OntologyLinter(enabled_rules={"redundant-regional-label"})
    issues = await linter.lint(g, PROJECT_ID)

    matches = _results_with_rule(issues, "redundant-regional-label")
    assert len(matches) == 0


async def test_redundant_regional_base_and_regional_same_value() -> None:
    """Base tag @es and regional @es-es with same value triggers the rule."""
    g = Graph()
    g.add((EX.Thing, RDF.type, OWL.Class))
    g.add((EX.Thing, SKOS.altLabel, Literal("Cosa", lang="es")))
    g.add((EX.Thing, SKOS.altLabel, Literal("Cosa", lang="es-es")))

    linter = OntologyLinter(enabled_rules={"redundant-regional-label"})
    issues = await linter.lint(g, PROJECT_ID)

    matches = _results_with_rule(issues, "redundant-regional-label")
    assert len(matches) == 1
    assert "@es" in matches[0].message
    assert "@es-es" in matches[0].message
    # Base tag is present, so message should suggest removing the regional variant
    assert "consider removing" in matches[0].message
    assert matches[0].subject_type == "class"


async def test_redundant_regional_skips_non_literal_and_untagged() -> None:
    """Non-literal objects and literals without language tags are skipped."""
    g = Graph()
    g.add((EX.Thing, RDF.type, OWL.Class))
    # URIRef as label value (not a literal)
    g.add((EX.Thing, RDFS.label, EX.SomeURI))
    # Plain literal without language tag
    g.add((EX.Thing, RDFS.label, Literal("plain")))

    linter = OntologyLinter(enabled_rules={"redundant-regional-label"})
    issues = await linter.lint(g, PROJECT_ID)

    matches = _results_with_rule(issues, "redundant-regional-label")
    assert len(matches) == 0


# ---------------------------------------------------------------------------
# 22. missing-type-declaration
# ---------------------------------------------------------------------------


async def test_missing_type_declaration_with_ontology_iri() -> None:
    """A subject in the ontology namespace with no rdf:type triggers the rule."""
    ONT = Namespace("http://example.org/ontology#")
    g = Graph()
    g.add((ONT[""], RDF.type, OWL.Ontology))
    g.add((ONT.Animal, RDF.type, OWL.Class))
    # Untyped resource in the same namespace
    g.add((ONT.mystery, RDFS.label, Literal("Mystery", lang="en")))

    linter = OntologyLinter(enabled_rules={"missing-type-declaration"})
    issues = await linter.lint(g, PROJECT_ID)

    matches = _results_with_rule(issues, "missing-type-declaration")
    assert len(matches) == 1
    assert matches[0].subject_iri == str(ONT.mystery)


async def test_missing_type_declaration_inferred_namespace() -> None:
    """Without owl:Ontology, infers namespace from most common prefix."""
    g = Graph()
    # No owl:Ontology declaration — must infer namespace
    g.add((EX.A, RDF.type, OWL.Class))
    g.add((EX.B, RDF.type, OWL.Class))
    g.add((EX.C, RDF.type, OWL.Class))
    # Untyped resource in the same namespace
    g.add((EX.orphan, RDFS.label, Literal("Orphan", lang="en")))

    linter = OntologyLinter(enabled_rules={"missing-type-declaration"})
    issues = await linter.lint(g, PROJECT_ID)

    matches = _results_with_rule(issues, "missing-type-declaration")
    assert len(matches) == 1
    assert matches[0].subject_iri == str(EX.orphan)


async def test_no_missing_type_declaration_when_typed() -> None:
    """A fully typed ontology should not trigger the rule."""
    g = Graph()
    g.add((EX.Animal, RDF.type, OWL.Class))
    g.add((EX.Dog, RDF.type, OWL.Class))
    g.add((EX.Dog, RDFS.subClassOf, EX.Animal))

    linter = OntologyLinter(enabled_rules={"missing-type-declaration"})
    issues = await linter.lint(g, PROJECT_ID)

    matches = _results_with_rule(issues, "missing-type-declaration")
    assert len(matches) == 0


async def test_missing_type_declaration_slash_namespace_ontology() -> None:
    """Ontology IRI without a trailing separator and slash-style subjects.

    Exercises the candidate-namespace branch that picks ``base + "/"`` over
    ``base + "#"`` when the actual subjects use slashes.
    """
    g = Graph()
    onto = "http://example.org/myonto"
    g.add((URIRef(onto), RDF.type, OWL.Ontology))
    g.add((URIRef(f"{onto}/Animal"), RDF.type, OWL.Class))
    # Untyped resource in the same slash-namespace
    g.add((URIRef(f"{onto}/mystery"), RDFS.label, Literal("Mystery", lang="en")))

    linter = OntologyLinter(enabled_rules={"missing-type-declaration"})
    issues = await linter.lint(g, PROJECT_ID)

    matches = _results_with_rule(issues, "missing-type-declaration")
    assert len(matches) == 1
    assert matches[0].subject_iri == f"{onto}/mystery"


async def test_missing_type_declaration_inferred_hash_namespace() -> None:
    """Inferred-namespace branch should pick the ``#``-prefix when subjects use it."""
    HASH = Namespace("http://example.org/onto#")
    g = Graph()
    # No owl:Ontology declaration — namespace must be inferred
    g.add((HASH.A, RDF.type, OWL.Class))
    g.add((HASH.B, RDF.type, OWL.Class))
    # Untyped resource sharing the inferred hash namespace
    g.add((HASH.orphan, RDFS.label, Literal("Orphan", lang="en")))

    linter = OntologyLinter(enabled_rules={"missing-type-declaration"})
    issues = await linter.lint(g, PROJECT_ID)

    matches = _results_with_rule(issues, "missing-type-declaration")
    assert len(matches) == 1
    assert matches[0].subject_iri == str(HASH.orphan)


async def test_missing_type_declaration_inferred_deep_slash_namespace() -> None:
    """Inferred-namespace branch should pick the deepest ``/``-prefix when no ``#``."""
    base = "http://example.org/vocab/v1/"
    g = Graph()
    g.add((URIRef(f"{base}A"), RDF.type, OWL.Class))
    g.add((URIRef(f"{base}B"), RDF.type, OWL.Class))
    g.add((URIRef(f"{base}orphan"), RDFS.label, Literal("Orphan", lang="en")))

    linter = OntologyLinter(enabled_rules={"missing-type-declaration"})
    issues = await linter.lint(g, PROJECT_ID)

    matches = _results_with_rule(issues, "missing-type-declaration")
    assert len(matches) == 1
    assert matches[0].subject_iri == f"{base}orphan"


# ---------------------------------------------------------------------------
# 23. undefined-prefix subject_type
# ---------------------------------------------------------------------------


async def test_undefined_prefix_subject_type_reflects_entity() -> None:
    """undefined-prefix issues classify the offending term so the frontend
    can navigate to the right entity panel."""
    g = Graph()
    # A class typed via rdf:type but referencing an undefined prefix in its IRI.
    bad_class = URIRef("undefined:BadClass")
    g.add((bad_class, RDF.type, OWL.Class))

    linter = OntologyLinter(enabled_rules={"undefined-prefix"})
    issues = await linter.lint(g, PROJECT_ID)

    matches = [
        i for i in _results_with_rule(issues, "undefined-prefix") if i.subject_iri == str(bad_class)
    ]
    assert matches, "expected an undefined-prefix issue for the bad class IRI"
    assert matches[0].subject_type == "class"
