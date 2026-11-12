# Issue #99 PR1 — Consolidate Consistency Rules into Linter (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 6 new rules to the linter and reconcile 3 partial-overlap rules so the lint system covers everything `consistency_service.py` checks, while leaving `consistency_service.py` and its routes in place for canary parity.

**Architecture:** All work lands in `ontokit/services/linter.py` (rule definitions + `OntologyLinter` check methods + level membership) and `tests/unit/test_linter.py`. The linter's existing dispatch convention turns a `rule_id` like `dangling-ref` into a method named `_check_dangling_ref` via `f"_check_{rule_id.replace('-', '_')}"` (linter.py:299). Each rule is a small `async` method that returns `list[LintResult]`. Helpers `_determine_entity_type`, `_get_local_name`, and `_get_label` are reused; `is_deprecated` is imported from `ontokit.services.rdf_utils`.

**Tech Stack:** Python 3.11+, RDFLib 7.1+, pytest with `asyncio_mode="auto"`, ruff (line length 100), mypy strict.

**Spec:** `docs/superpowers/specs/2026-05-03-issue-99-consolidate-consistency-into-lint-design.md`

**Branch:** `feat/issue-99-consolidate-consistency` (already created, spec already committed as `317981f`).

---

## File Structure

| File | Role | Change shape |
|------|------|--------------|
| `ontokit/services/linter.py` | Rule definitions, level sets, `OntologyLinter` check methods | Add 6 `LintRuleInfo` entries; add 6 `_check_*` methods; rename one method; modify two methods; update level membership and level descriptions |
| `tests/unit/test_linter.py` | Per-rule unit tests | Add ~14 new tests; rename ~3 existing; update one level-membership assertion |
| `ontokit/services/rdf_utils.py` | `is_deprecated` helper | Import only — no change to file |

`consistency_service.py`, route files, worker, schemas, and frontend are NOT touched in PR1.

---

## Task 1: Add `unused-property` rule (warning, L4)

**Files:**
- Modify: `ontokit/services/linter.py`
- Test: `tests/unit/test_linter.py`

- [ ] **Step 1: Write the failing tests**

Append at the end of `tests/unit/test_linter.py`:

```python
# ---------------------------------------------------------------------------
# unused-property
# ---------------------------------------------------------------------------


async def test_unused_property_flags_property_with_no_usage() -> None:
    """An ObjectProperty declared but never used as a predicate is flagged."""
    g = Graph()
    g.add((EX.knows, RDF.type, OWL.ObjectProperty))
    # No (?, EX.knows, ?) triples anywhere.

    linter = OntologyLinter(enabled_rules={"unused-property"})
    issues = await linter.lint(g, PROJECT_ID)

    matches = _results_with_rule(issues, "unused-property")
    assert len(matches) == 1
    assert matches[0].issue_type == "warning"
    assert matches[0].subject_iri == str(EX.knows)
    assert matches[0].subject_type == "property"


async def test_unused_property_does_not_flag_used_property() -> None:
    """A property used as a predicate at least once is not flagged."""
    g = Graph()
    g.add((EX.knows, RDF.type, OWL.ObjectProperty))
    g.add((EX.Alice, EX.knows, EX.Bob))

    linter = OntologyLinter(enabled_rules={"unused-property"})
    issues = await linter.lint(g, PROJECT_ID)

    assert _results_with_rule(issues, "unused-property") == []


async def test_unused_property_covers_datatype_and_annotation_properties() -> None:
    """DatatypeProperty and AnnotationProperty are also covered."""
    g = Graph()
    g.add((EX.age, RDF.type, OWL.DatatypeProperty))
    g.add((EX.note, RDF.type, OWL.AnnotationProperty))

    linter = OntologyLinter(enabled_rules={"unused-property"})
    issues = await linter.lint(g, PROJECT_ID)

    flagged_iris = {r.subject_iri for r in _results_with_rule(issues, "unused-property")}
    assert flagged_iris == {str(EX.age), str(EX.note)}
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/bin/pytest tests/unit/test_linter.py -k unused_property -v --no-cov
```

Expected: 3 failures, each because `OntologyLinter` produces no `unused-property` results (the rule does not exist yet).

- [ ] **Step 3: Add the `LintRuleInfo` entry and level membership**

In `ontokit/services/linter.py`, in the `LINT_RULES` list (currently ends ~line 184), append a new entry just before the closing `]`:

```python
    LintRuleInfo(
        rule_id="unused-property",
        name="Unused Property",
        description="Property is declared but never used as a predicate in any triple",
        severity=LintIssueType.WARNING.value,
        scope=["property"],
    ),
```

Then add `"unused-property"` to the L4 set at `_LEVEL_4_RULES` (~line 204):

```python
_LEVEL_4_RULES: set[str] = _LEVEL_3_RULES | {
    "missing-comment",
    "label-per-language",
    "redundant-regional-label",
    "unused-property",
}
```

- [ ] **Step 4: Implement the check method**

Add this method to `OntologyLinter` immediately after `_check_redundant_regional_label` (look for the comment `# Static helpers` or the `_determine_entity_type` static method around line 1297 — insert just before that line):

```python
    async def _check_unused_property(self, graph: Graph) -> list[LintResult]:
        """Find declared properties that are never used as a predicate."""
        issues: list[LintResult] = []
        property_types = (
            OWL.ObjectProperty,
            OWL.DatatypeProperty,
            OWL.AnnotationProperty,
            RDF.Property,
        )
        seen: set[URIRef] = set()
        for prop_type in property_types:
            for prop in graph.subjects(RDF.type, prop_type):
                if not isinstance(prop, URIRef) or prop in seen:
                    continue
                seen.add(prop)
                # `subjects(prop, None)` returns subjects of triples whose
                # predicate is `prop`. Excluding `prop` itself is necessary
                # because the rdf:type triple has the property as subject and
                # would otherwise count as self-usage.
                used = any(s != prop for s in graph.subjects(prop, None))
                if not used:
                    issues.append(
                        LintResult(
                            issue_type=LintIssueType.WARNING.value,
                            rule_id="unused-property",
                            message="Property is declared but never used as a predicate",
                            subject_iri=str(prop),
                            subject_type="property",
                            details={"local_name": self._get_local_name(prop)},
                        )
                    )
        return issues
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
.venv/bin/pytest tests/unit/test_linter.py -k unused_property -v --no-cov
```

Expected: 3 PASSED.

- [ ] **Step 6: Run ruff + mypy**

```bash
.venv/bin/ruff check ontokit/services/linter.py tests/unit/test_linter.py
.venv/bin/ruff format --check ontokit/services/linter.py tests/unit/test_linter.py
.venv/bin/mypy ontokit/services/linter.py
```

Expected: all clean.

- [ ] **Step 7: Commit**

```bash
git add ontokit/services/linter.py tests/unit/test_linter.py
git commit -m "feat(lint): add unused-property rule (#99)

Flags properties (ObjectProperty / DatatypeProperty / AnnotationProperty /
rdf:Property) declared in the ontology but never used as a predicate in
any triple. Mirrors consistency_service._check_unused_property; lives at
L4 (Quality)."
```

---

## Task 2: Add `orphan-individual` rule (warning, L2)

**Files:**
- Modify: `ontokit/services/linter.py`
- Test: `tests/unit/test_linter.py`

- [ ] **Step 1: Write the failing tests**

Append at the end of `tests/unit/test_linter.py`:

```python
# ---------------------------------------------------------------------------
# orphan-individual
# ---------------------------------------------------------------------------


async def test_orphan_individual_flags_undeclared_type() -> None:
    """Individual whose rdf:type target is not declared as owl:Class is flagged."""
    g = Graph()
    g.add((EX.Alice, RDF.type, OWL.NamedIndividual))
    g.add((EX.Alice, RDF.type, EX.Person))  # EX.Person is NOT declared as a class

    linter = OntologyLinter(enabled_rules={"orphan-individual"})
    issues = await linter.lint(g, PROJECT_ID)

    matches = _results_with_rule(issues, "orphan-individual")
    assert len(matches) == 1
    assert matches[0].issue_type == "warning"
    assert matches[0].subject_iri == str(EX.Alice)
    assert matches[0].subject_type == "individual"
    assert matches[0].details is not None
    assert matches[0].details["undeclared_type"] == str(EX.Person)


async def test_orphan_individual_does_not_flag_declared_type() -> None:
    """Individual whose rdf:type target is a declared class is not flagged."""
    g = Graph()
    g.add((EX.Person, RDF.type, OWL.Class))
    g.add((EX.Alice, RDF.type, OWL.NamedIndividual))
    g.add((EX.Alice, RDF.type, EX.Person))

    linter = OntologyLinter(enabled_rules={"orphan-individual"})
    issues = await linter.lint(g, PROJECT_ID)

    assert _results_with_rule(issues, "orphan-individual") == []


async def test_orphan_individual_emits_one_finding_per_undeclared_type() -> None:
    """An individual with two undeclared types yields two findings."""
    g = Graph()
    g.add((EX.Alice, RDF.type, OWL.NamedIndividual))
    g.add((EX.Alice, RDF.type, EX.Person))
    g.add((EX.Alice, RDF.type, EX.Employee))

    linter = OntologyLinter(enabled_rules={"orphan-individual"})
    issues = await linter.lint(g, PROJECT_ID)

    matches = _results_with_rule(issues, "orphan-individual")
    flagged = {(m.subject_iri, m.details["undeclared_type"]) for m in matches if m.details}
    assert flagged == {
        (str(EX.Alice), str(EX.Person)),
        (str(EX.Alice), str(EX.Employee)),
    }
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/bin/pytest tests/unit/test_linter.py -k orphan_individual -v --no-cov
```

Expected: 3 failures.

- [ ] **Step 3: Add the `LintRuleInfo` entry and level membership**

In `ontokit/services/linter.py`, append to `LINT_RULES`:

```python
    LintRuleInfo(
        rule_id="orphan-individual",
        name="Orphan Individual",
        description="Individual's rdf:type target is not declared as owl:Class in this ontology",
        severity=LintIssueType.WARNING.value,
        scope=["individual"],
    ),
```

Then add `"orphan-individual"` to `_LEVEL_2_RULES`:

```python
_LEVEL_2_RULES: set[str] = _LEVEL_1_RULES | {
    "orphan-class",
    "duplicate-triple",
    "disjoint-violation",
    "missing-type-declaration",
    "orphan-individual",
}
```

- [ ] **Step 4: Implement the check method**

Add this method to `OntologyLinter` (insert before `_determine_entity_type`):

```python
    async def _check_orphan_individual(self, graph: Graph) -> list[LintResult]:
        """Flag individuals whose rdf:type target is not declared as owl:Class."""
        issues: list[LintResult] = []
        declared_classes = {
            c
            for c in graph.subjects(RDF.type, OWL.Class)
            if isinstance(c, URIRef)
        }
        # owl:Thing is implicitly a class even if not declared.
        declared_classes.add(OWL.Thing)

        for ind in graph.subjects(RDF.type, OWL.NamedIndividual):
            if not isinstance(ind, URIRef):
                continue
            for type_target in graph.objects(ind, RDF.type):
                if not isinstance(type_target, URIRef):
                    continue
                if type_target == OWL.NamedIndividual:
                    continue
                if type_target in declared_classes:
                    continue
                issues.append(
                    LintResult(
                        issue_type=LintIssueType.WARNING.value,
                        rule_id="orphan-individual",
                        message=f"Individual's type {type_target} is not declared as owl:Class",
                        subject_iri=str(ind),
                        subject_type="individual",
                        details={
                            "local_name": self._get_local_name(ind),
                            "undeclared_type": str(type_target),
                            "undeclared_type_local": self._get_local_name(type_target),
                        },
                    )
                )
        return issues
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
.venv/bin/pytest tests/unit/test_linter.py -k orphan_individual -v --no-cov
```

Expected: 3 PASSED.

- [ ] **Step 6: Commit**

```bash
git add ontokit/services/linter.py tests/unit/test_linter.py
git commit -m "feat(lint): add orphan-individual rule (#99)

Flags individuals whose rdf:type target is not declared as owl:Class
in this ontology. Mirrors consistency_service._check_orphan_individual;
lives at L2 (Consistency)."
```

---

## Task 3: Add `empty-domain` rule (info, L4)

**Files:**
- Modify: `ontokit/services/linter.py`
- Test: `tests/unit/test_linter.py`

- [ ] **Step 1: Write the failing tests**

Append at the end of `tests/unit/test_linter.py`:

```python
# ---------------------------------------------------------------------------
# empty-domain
# ---------------------------------------------------------------------------


async def test_empty_domain_flags_object_property_without_domain() -> None:
    g = Graph()
    g.add((EX.knows, RDF.type, OWL.ObjectProperty))

    linter = OntologyLinter(enabled_rules={"empty-domain"})
    issues = await linter.lint(g, PROJECT_ID)

    matches = _results_with_rule(issues, "empty-domain")
    assert len(matches) == 1
    assert matches[0].issue_type == "info"
    assert matches[0].subject_iri == str(EX.knows)
    assert matches[0].subject_type == "property"


async def test_empty_domain_flags_datatype_property_without_domain() -> None:
    g = Graph()
    g.add((EX.age, RDF.type, OWL.DatatypeProperty))

    linter = OntologyLinter(enabled_rules={"empty-domain"})
    issues = await linter.lint(g, PROJECT_ID)

    matches = _results_with_rule(issues, "empty-domain")
    assert len(matches) == 1
    assert matches[0].subject_iri == str(EX.age)


async def test_empty_domain_does_not_flag_property_with_domain() -> None:
    g = Graph()
    g.add((EX.knows, RDF.type, OWL.ObjectProperty))
    g.add((EX.knows, RDFS.domain, EX.Person))

    linter = OntologyLinter(enabled_rules={"empty-domain"})
    issues = await linter.lint(g, PROJECT_ID)

    assert _results_with_rule(issues, "empty-domain") == []


async def test_empty_domain_does_not_flag_annotation_property() -> None:
    """AnnotationProperty is excluded from the empty-domain check."""
    g = Graph()
    g.add((EX.note, RDF.type, OWL.AnnotationProperty))

    linter = OntologyLinter(enabled_rules={"empty-domain"})
    issues = await linter.lint(g, PROJECT_ID)

    assert _results_with_rule(issues, "empty-domain") == []
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/bin/pytest tests/unit/test_linter.py -k empty_domain -v --no-cov
```

Expected: 4 failures.

- [ ] **Step 3: Add the `LintRuleInfo` entry and level membership**

Append to `LINT_RULES`:

```python
    LintRuleInfo(
        rule_id="empty-domain",
        name="Empty Domain",
        description="ObjectProperty or DatatypeProperty has no rdfs:domain",
        severity=LintIssueType.INFO.value,
        scope=["property"],
    ),
```

Add `"empty-domain"` to `_LEVEL_4_RULES`.

- [ ] **Step 4: Implement the check method**

Add to `OntologyLinter` before `_determine_entity_type`:

```python
    async def _check_empty_domain(self, graph: Graph) -> list[LintResult]:
        """Flag ObjectProperty/DatatypeProperty declarations with no rdfs:domain."""
        issues: list[LintResult] = []
        for prop_type in (OWL.ObjectProperty, OWL.DatatypeProperty):
            for prop in graph.subjects(RDF.type, prop_type):
                if not isinstance(prop, URIRef):
                    continue
                if any(graph.objects(prop, RDFS.domain)):
                    continue
                issues.append(
                    LintResult(
                        issue_type=LintIssueType.INFO.value,
                        rule_id="empty-domain",
                        message="Property has no rdfs:domain",
                        subject_iri=str(prop),
                        subject_type="property",
                        details={"local_name": self._get_local_name(prop)},
                    )
                )
        return issues
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
.venv/bin/pytest tests/unit/test_linter.py -k empty_domain -v --no-cov
```

Expected: 4 PASSED.

- [ ] **Step 6: Commit**

```bash
git add ontokit/services/linter.py tests/unit/test_linter.py
git commit -m "feat(lint): add empty-domain rule (#99)

Flags ObjectProperty and DatatypeProperty declarations with no
rdfs:domain. AnnotationProperty is intentionally excluded (annotations
are by convention domain-agnostic). L4 (Quality)."
```

---

## Task 4: Add `empty-range` rule (info, L4)

**Files:**
- Modify: `ontokit/services/linter.py`
- Test: `tests/unit/test_linter.py`

- [ ] **Step 1: Write the failing tests**

Append at the end of `tests/unit/test_linter.py`:

```python
# ---------------------------------------------------------------------------
# empty-range
# ---------------------------------------------------------------------------


async def test_empty_range_flags_object_property_without_range() -> None:
    g = Graph()
    g.add((EX.knows, RDF.type, OWL.ObjectProperty))

    linter = OntologyLinter(enabled_rules={"empty-range"})
    issues = await linter.lint(g, PROJECT_ID)

    matches = _results_with_rule(issues, "empty-range")
    assert len(matches) == 1
    assert matches[0].issue_type == "info"
    assert matches[0].subject_iri == str(EX.knows)


async def test_empty_range_does_not_flag_property_with_range() -> None:
    g = Graph()
    g.add((EX.age, RDF.type, OWL.DatatypeProperty))
    g.add((EX.age, RDFS.range, XSD.integer))

    linter = OntologyLinter(enabled_rules={"empty-range"})
    issues = await linter.lint(g, PROJECT_ID)

    assert _results_with_rule(issues, "empty-range") == []
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/bin/pytest tests/unit/test_linter.py -k empty_range -v --no-cov
```

Expected: 2 failures.

- [ ] **Step 3: Add the `LintRuleInfo` entry and level membership**

Append to `LINT_RULES`:

```python
    LintRuleInfo(
        rule_id="empty-range",
        name="Empty Range",
        description="ObjectProperty or DatatypeProperty has no rdfs:range",
        severity=LintIssueType.INFO.value,
        scope=["property"],
    ),
```

Add `"empty-range"` to `_LEVEL_4_RULES`.

- [ ] **Step 4: Implement the check method**

```python
    async def _check_empty_range(self, graph: Graph) -> list[LintResult]:
        """Flag ObjectProperty/DatatypeProperty declarations with no rdfs:range."""
        issues: list[LintResult] = []
        for prop_type in (OWL.ObjectProperty, OWL.DatatypeProperty):
            for prop in graph.subjects(RDF.type, prop_type):
                if not isinstance(prop, URIRef):
                    continue
                if any(graph.objects(prop, RDFS.range)):
                    continue
                issues.append(
                    LintResult(
                        issue_type=LintIssueType.INFO.value,
                        rule_id="empty-range",
                        message="Property has no rdfs:range",
                        subject_iri=str(prop),
                        subject_type="property",
                        details={"local_name": self._get_local_name(prop)},
                    )
                )
        return issues
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
.venv/bin/pytest tests/unit/test_linter.py -k empty_range -v --no-cov
```

Expected: 2 PASSED.

- [ ] **Step 6: Commit**

```bash
git add ontokit/services/linter.py tests/unit/test_linter.py
git commit -m "feat(lint): add empty-range rule (#99)

Flags ObjectProperty and DatatypeProperty declarations with no
rdfs:range. AnnotationProperty intentionally excluded. L4 (Quality)."
```

---

## Task 5: Add `deprecated-parent` rule (warning, L2)

**Files:**
- Modify: `ontokit/services/linter.py` (also adds an `is_deprecated` import)
- Test: `tests/unit/test_linter.py`

- [ ] **Step 1: Write the failing tests**

Append at the end of `tests/unit/test_linter.py`:

```python
# ---------------------------------------------------------------------------
# deprecated-parent
# ---------------------------------------------------------------------------


async def test_deprecated_parent_flags_subclass_of_deprecated_class() -> None:
    g = Graph()
    g.add((EX.OldThing, RDF.type, OWL.Class))
    g.add((EX.OldThing, OWL.deprecated, Literal(True)))
    g.add((EX.NewThing, RDF.type, OWL.Class))
    g.add((EX.NewThing, RDFS.subClassOf, EX.OldThing))

    linter = OntologyLinter(enabled_rules={"deprecated-parent"})
    issues = await linter.lint(g, PROJECT_ID)

    matches = _results_with_rule(issues, "deprecated-parent")
    assert len(matches) == 1
    assert matches[0].issue_type == "warning"
    assert matches[0].subject_iri == str(EX.NewThing)
    assert matches[0].subject_type == "class"
    assert matches[0].details is not None
    assert matches[0].details["deprecated_parent"] == str(EX.OldThing)


async def test_deprecated_parent_does_not_flag_non_deprecated_parent() -> None:
    g = Graph()
    g.add((EX.Animal, RDF.type, OWL.Class))
    g.add((EX.Dog, RDF.type, OWL.Class))
    g.add((EX.Dog, RDFS.subClassOf, EX.Animal))

    linter = OntologyLinter(enabled_rules={"deprecated-parent"})
    issues = await linter.lint(g, PROJECT_ID)

    assert _results_with_rule(issues, "deprecated-parent") == []


async def test_deprecated_parent_recognizes_string_true() -> None:
    """is_deprecated accepts case-insensitive 'true' / '1' literals."""
    g = Graph()
    g.add((EX.OldThing, RDF.type, OWL.Class))
    g.add((EX.OldThing, OWL.deprecated, Literal("true")))
    g.add((EX.NewThing, RDF.type, OWL.Class))
    g.add((EX.NewThing, RDFS.subClassOf, EX.OldThing))

    linter = OntologyLinter(enabled_rules={"deprecated-parent"})
    issues = await linter.lint(g, PROJECT_ID)

    assert len(_results_with_rule(issues, "deprecated-parent")) == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/bin/pytest tests/unit/test_linter.py -k deprecated_parent -v --no-cov
```

Expected: 3 failures.

- [ ] **Step 3: Add the import, `LintRuleInfo` entry, and level membership**

In `ontokit/services/linter.py`, add the import near the other internal imports (line 14 area):

```python
from ontokit.models.lint import LintIssueType
from ontokit.services.rdf_utils import is_deprecated
```

Append to `LINT_RULES`:

```python
    LintRuleInfo(
        rule_id="deprecated-parent",
        name="Deprecated Parent",
        description="Class subclasses a class marked owl:deprecated",
        severity=LintIssueType.WARNING.value,
        scope=["class"],
    ),
```

Add `"deprecated-parent"` to `_LEVEL_2_RULES`.

- [ ] **Step 4: Implement the check method**

```python
    async def _check_deprecated_parent(self, graph: Graph) -> list[LintResult]:
        """Flag classes that subclass an owl:deprecated class."""
        issues: list[LintResult] = []
        for cls in graph.subjects(RDF.type, OWL.Class):
            if not isinstance(cls, URIRef):
                continue
            for parent in graph.objects(cls, RDFS.subClassOf):
                if not isinstance(parent, URIRef):
                    continue
                if not is_deprecated(graph, parent):
                    continue
                issues.append(
                    LintResult(
                        issue_type=LintIssueType.WARNING.value,
                        rule_id="deprecated-parent",
                        message=f"Parent class {parent} is deprecated",
                        subject_iri=str(cls),
                        subject_type="class",
                        details={
                            "local_name": self._get_local_name(cls),
                            "deprecated_parent": str(parent),
                            "deprecated_parent_local": self._get_local_name(parent),
                        },
                    )
                )
        return issues
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
.venv/bin/pytest tests/unit/test_linter.py -k deprecated_parent -v --no-cov
```

Expected: 3 PASSED.

- [ ] **Step 6: Commit**

```bash
git add ontokit/services/linter.py tests/unit/test_linter.py
git commit -m "feat(lint): add deprecated-parent rule (#99)

Flags classes that subclass an owl:deprecated class. Reuses the
shared is_deprecated helper from rdf_utils which accepts both boolean
and string literal forms. L2 (Consistency)."
```

---

## Task 6: Add `multi-root` rule (info, L4)

**Files:**
- Modify: `ontokit/services/linter.py`
- Test: `tests/unit/test_linter.py`

- [ ] **Step 1: Write the failing tests**

Append at the end of `tests/unit/test_linter.py`:

```python
# ---------------------------------------------------------------------------
# multi-root
# ---------------------------------------------------------------------------


async def test_multi_root_does_not_fire_below_threshold() -> None:
    """Five or fewer root classes does NOT fire."""
    g = Graph()
    for i in range(5):
        g.add((URIRef(f"http://example.org/Root{i}"), RDF.type, OWL.Class))

    linter = OntologyLinter(enabled_rules={"multi-root"})
    issues = await linter.lint(g, PROJECT_ID)

    assert _results_with_rule(issues, "multi-root") == []


async def test_multi_root_fires_above_threshold() -> None:
    """Six root classes triggers a single ontology-scope finding."""
    g = Graph()
    for i in range(6):
        g.add((URIRef(f"http://example.org/Root{i}"), RDF.type, OWL.Class))

    linter = OntologyLinter(enabled_rules={"multi-root"})
    issues = await linter.lint(g, PROJECT_ID)

    matches = _results_with_rule(issues, "multi-root")
    assert len(matches) == 1
    assert matches[0].issue_type == "info"
    assert matches[0].subject_iri is None
    assert matches[0].subject_type == "other"
    assert matches[0].details is not None
    assert matches[0].details["root_count"] == 6


async def test_multi_root_excludes_classes_with_explicit_parent() -> None:
    """Classes with a non-owl:Thing parent don't count as roots."""
    g = Graph()
    g.add((EX.Animal, RDF.type, OWL.Class))
    # 5 roots + 1 non-root subclass = 5 roots total, no finding expected.
    for i in range(5):
        g.add((URIRef(f"http://example.org/Root{i}"), RDF.type, OWL.Class))
    g.add((EX.Dog, RDF.type, OWL.Class))
    g.add((EX.Dog, RDFS.subClassOf, EX.Animal))
    # EX.Animal itself is a root, so we have 6 roots when including it
    # → fires. Verify the count excludes EX.Dog.

    linter = OntologyLinter(enabled_rules={"multi-root"})
    issues = await linter.lint(g, PROJECT_ID)

    matches = _results_with_rule(issues, "multi-root")
    assert len(matches) == 1
    assert matches[0].details is not None
    assert matches[0].details["root_count"] == 6
    assert str(EX.Dog) not in matches[0].details["root_iris"]
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/bin/pytest tests/unit/test_linter.py -k multi_root -v --no-cov
```

Expected: 3 failures.

- [ ] **Step 3: Add the `LintRuleInfo` entry and level membership**

Append to `LINT_RULES`:

```python
    LintRuleInfo(
        rule_id="multi-root",
        name="Multiple Root Classes",
        description="Ontology has more than 5 root classes (classes with no parent except owl:Thing)",
        severity=LintIssueType.INFO.value,
        scope=[],
    ),
```

Add `"multi-root"` to `_LEVEL_4_RULES`.

- [ ] **Step 4: Implement the check method**

```python
    async def _check_multi_root(self, graph: Graph) -> list[LintResult]:
        """Fire once if the ontology has more than 5 root classes."""
        root_iris: list[str] = []
        for cls in graph.subjects(RDF.type, OWL.Class):
            if not isinstance(cls, URIRef) or cls == OWL.Thing:
                continue
            has_real_parent = any(
                isinstance(p, URIRef) and p != OWL.Thing
                for p in graph.objects(cls, RDFS.subClassOf)
            )
            if not has_real_parent:
                root_iris.append(str(cls))

        if len(root_iris) <= 5:
            return []

        return [
            LintResult(
                issue_type=LintIssueType.INFO.value,
                rule_id="multi-root",
                message=f"Ontology has {len(root_iris)} root classes (classes with no parent)",
                subject_iri=None,
                subject_type="other",
                details={
                    "root_count": len(root_iris),
                    # Cap at 20 to keep the payload small even on huge ontologies.
                    "root_iris": sorted(root_iris)[:20],
                },
            )
        ]
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
.venv/bin/pytest tests/unit/test_linter.py -k multi_root -v --no-cov
```

Expected: 3 PASSED.

- [ ] **Step 6: Commit**

```bash
git add ontokit/services/linter.py tests/unit/test_linter.py
git commit -m "feat(lint): add multi-root rule (#99)

Fires once when an ontology has more than 5 root classes (classes with
no parent except owl:Thing). Ontology-scope finding: subject_iri=None,
subject_type='other'. L4 (Quality)."
```

---

## Task 7: Rename `undefined-parent` → `dangling-ref` (no behavior change)

**Files:**
- Modify: `ontokit/services/linter.py`
- Test: `tests/unit/test_linter.py`

- [ ] **Step 1: Update the existing tests to expect the new rule_id**

In `tests/unit/test_linter.py`, find the three callsites referencing `"undefined-parent"`:
- Line 224 (`enabled_rules={"undefined-parent"}`)
- Line 227 (`_results_with_rule(issues, "undefined-parent")`)
- Line 242 (`enabled_rules={"undefined-parent"}`)
- Line 245 (`_results_with_rule(issues, "undefined-parent")`)
- Line 286 (inside an `enabled_rules={...}` set literal)

Replace every occurrence of the string `"undefined-parent"` in this file with `"dangling-ref"`.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/bin/pytest tests/unit/test_linter.py -k undefined_parent -v --no-cov
.venv/bin/pytest tests/unit/test_linter.py -k dangling_ref -v --no-cov
```

Expected: the tests now collect under `dangling_ref` and FAIL because the rule_id `dangling-ref` does not exist yet (linter still emits `undefined-parent`).

- [ ] **Step 3: Rename the rule in `linter.py`**

In `ontokit/services/linter.py`:

a. In `LINT_RULES` (~line 70), change the existing entry:

```python
    LintRuleInfo(
        rule_id="dangling-ref",
        name="Dangling Reference",
        description="Reference to a URI not defined in the ontology (in subClassOf, rdfs:domain, or rdfs:range)",
        severity=LintIssueType.ERROR.value,
        scope=["class", "property"],
    ),
```

b. In `_LEVEL_1_RULES` (~line 190), replace `"undefined-parent"` with `"dangling-ref"`:

```python
_LEVEL_1_RULES: set[str] = {"dangling-ref", "circular-hierarchy", "undefined-prefix"}
```

c. Rename the method `_check_undefined_parent` to `_check_dangling_ref` (line 395). Inside the method, change the `rule_id="undefined-parent"` literal to `rule_id="dangling-ref"`. **Do not yet expand it to cover domain/range** — that's Task 8.

d. Update the L1 description in `LINT_LEVEL_DEFINITIONS` (~line 233) to reference dangling references instead of undefined parents:

```python
    1: LintLevelDefinition(
        "Critical",
        "Dangling references, circular hierarchies, undefined prefixes",
        LINT_LEVELS[1],
    ),
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
.venv/bin/pytest tests/unit/test_linter.py -k dangling_ref -v --no-cov
```

Expected: the renamed tests PASS.

- [ ] **Step 5: Commit**

```bash
git add ontokit/services/linter.py tests/unit/test_linter.py
git commit -m "refactor(lint): rename undefined-parent to dangling-ref (#99)

Pure rename. Behavior unchanged — the rule still only checks
subClassOf targets. Predicate-axis expansion comes in the next
commit. Existing LintIssue rows with rule_id='undefined-parent' are
left in place; they're snapshots of past runs and lint results are
regenerable."
```

---

## Task 8: Expand `dangling-ref` to cover `rdfs:domain` and `rdfs:range`

**Files:**
- Modify: `ontokit/services/linter.py`
- Test: `tests/unit/test_linter.py`

- [ ] **Step 1: Write the failing tests**

Append at the end of `tests/unit/test_linter.py`:

```python
# ---------------------------------------------------------------------------
# dangling-ref (domain/range expansion)
# ---------------------------------------------------------------------------


async def test_dangling_ref_flags_undefined_domain() -> None:
    """Property whose rdfs:domain points to an undeclared URI is flagged."""
    g = Graph()
    g.add((EX.knows, RDF.type, OWL.ObjectProperty))
    g.add((EX.knows, RDFS.domain, EX.UndeclaredClass))

    linter = OntologyLinter(enabled_rules={"dangling-ref"})
    issues = await linter.lint(g, PROJECT_ID)

    matches = _results_with_rule(issues, "dangling-ref")
    assert len(matches) == 1
    assert matches[0].subject_iri == str(EX.knows)
    assert matches[0].details is not None
    assert matches[0].details["predicate"] == str(RDFS.domain)
    assert matches[0].details["dangling_target"] == str(EX.UndeclaredClass)


async def test_dangling_ref_flags_undefined_range() -> None:
    g = Graph()
    g.add((EX.age, RDF.type, OWL.DatatypeProperty))
    g.add((EX.age, RDFS.range, EX.UndeclaredDatatype))

    linter = OntologyLinter(enabled_rules={"dangling-ref"})
    issues = await linter.lint(g, PROJECT_ID)

    matches = _results_with_rule(issues, "dangling-ref")
    assert len(matches) == 1
    assert matches[0].subject_iri == str(EX.age)
    assert matches[0].details is not None
    assert matches[0].details["predicate"] == str(RDFS.range)


async def test_dangling_ref_subclassof_includes_predicate_detail() -> None:
    """The existing subClassOf path now also reports details.predicate."""
    g = Graph()
    g.add((EX.Dog, RDF.type, OWL.Class))
    g.add((EX.Dog, RDFS.subClassOf, EX.UndeclaredAnimal))

    linter = OntologyLinter(enabled_rules={"dangling-ref"})
    issues = await linter.lint(g, PROJECT_ID)

    matches = _results_with_rule(issues, "dangling-ref")
    assert len(matches) == 1
    assert matches[0].details is not None
    assert matches[0].details["predicate"] == str(RDFS.subClassOf)


async def test_dangling_ref_skips_well_known_namespaces() -> None:
    """References into rdf/rdfs/owl/xsd/skos/dcterms must not be flagged."""
    g = Graph()
    g.add((EX.knows, RDF.type, OWL.ObjectProperty))
    g.add((EX.knows, RDFS.range, XSD.string))
    g.add((EX.related, RDF.type, OWL.ObjectProperty))
    g.add((EX.related, RDFS.range, SKOS.Concept))

    linter = OntologyLinter(enabled_rules={"dangling-ref"})
    issues = await linter.lint(g, PROJECT_ID)

    assert _results_with_rule(issues, "dangling-ref") == []


async def test_dangling_ref_skips_imported_namespaces() -> None:
    """References into namespaces declared via owl:imports must not be flagged."""
    g = Graph()
    imported_ns = URIRef("http://other.org/onto")
    g.add((URIRef("http://example.org/myonto"), OWL.imports, imported_ns))
    g.add((EX.knows, RDF.type, OWL.ObjectProperty))
    g.add((EX.knows, RDFS.range, URIRef("http://other.org/onto/Person")))

    linter = OntologyLinter(enabled_rules={"dangling-ref"})
    issues = await linter.lint(g, PROJECT_ID)

    assert _results_with_rule(issues, "dangling-ref") == []
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/bin/pytest tests/unit/test_linter.py -k dangling_ref -v --no-cov
```

Expected: the 5 new tests fail (existing dangling-ref tests still pass). The new failures are because the rule still only inspects subClassOf and has no `details.predicate` field.

- [ ] **Step 3: Replace `_check_dangling_ref` with the expanded version**

In `ontokit/services/linter.py`, replace the entire `_check_dangling_ref` method (lines roughly 395–434) with:

```python
    async def _check_dangling_ref(self, graph: Graph) -> list[LintResult]:
        """Find references to URIs that aren't declared in this ontology.

        Scans rdfs:subClassOf, rdfs:domain, and rdfs:range. References into
        well-known vocabularies (rdf/rdfs/owl/xsd/skos/dcterms/dc) and into
        namespaces brought in via owl:imports are not flagged.
        """
        issues: list[LintResult] = []

        # A URI is "known" if it appears as a subject of any rdf:type triple
        # OR as a subject of any triple at all (covers blank-node-free uses).
        declared_subjects: set[URIRef] = {
            s for s in graph.subjects(RDF.type, None) if isinstance(s, URIRef)
        }
        all_subjects: set[URIRef] = {
            s for s in graph.subjects() if isinstance(s, URIRef)
        }
        known: set[URIRef] = declared_subjects | all_subjects | {OWL.Thing}

        well_known_ns = {
            str(RDF),
            str(RDFS),
            str(OWL),
            str(XSD),
            str(SKOS),
            str(DC),
            str(DCTERMS),
        }
        imported_ns: set[str] = set()
        for _ontology, _pred, imported in graph.triples((None, OWL.imports, None)):
            if isinstance(imported, URIRef):
                imp_str = str(imported)
                if not imp_str.endswith(("/", "#")):
                    imp_str += "/"
                imported_ns.add(imp_str)
        external_ns = well_known_ns | imported_ns

        # (subject_iri, predicate, target) keyed reporting to deduplicate
        # when the same triple would be reported by multiple iterations.
        reported: set[tuple[str, str, str]] = set()

        for predicate in (RDFS.subClassOf, RDFS.domain, RDFS.range):
            for subj, _p, obj in graph.triples((None, predicate, None)):
                if not isinstance(obj, URIRef) or not isinstance(subj, URIRef):
                    continue
                if obj == OWL.Thing or obj in known:
                    continue
                obj_str = str(obj)
                if any(obj_str.startswith(ns) for ns in external_ns):
                    continue
                key = (str(subj), str(predicate), obj_str)
                if key in reported:
                    continue
                reported.add(key)
                issues.append(
                    LintResult(
                        issue_type=LintIssueType.ERROR.value,
                        rule_id="dangling-ref",
                        message=f"References undeclared entity {obj}",
                        subject_iri=str(subj),
                        subject_type=self._determine_entity_type(graph, subj),
                        details={
                            "local_name": self._get_local_name(subj),
                            "predicate": str(predicate),
                            "dangling_target": obj_str,
                            "dangling_target_local": self._get_local_name(obj),
                        },
                    )
                )
        return issues
```

- [ ] **Step 4: Run all dangling-ref tests to verify they pass**

```bash
.venv/bin/pytest tests/unit/test_linter.py -k dangling_ref -v --no-cov
```

Expected: every test passes (the renamed ones from Task 7 plus the 5 new ones).

- [ ] **Step 5: Commit**

```bash
git add ontokit/services/linter.py tests/unit/test_linter.py
git commit -m "feat(lint): expand dangling-ref to cover domain and range (#99)

The rule now inspects rdfs:subClassOf, rdfs:domain, and rdfs:range
targets uniformly. Each finding carries details.predicate so the UI
can show which axis triggered the dangling reference. References into
well-known namespaces (rdf/rdfs/owl/xsd/skos/dc/dcterms) and into
namespaces declared via owl:imports are skipped, mirroring
consistency_service._check_dangling_ref."
```

---

## Task 9: Broaden `duplicate-label` semantics (case-insensitive + same-type + all entity types)

**Files:**
- Modify: `ontokit/services/linter.py`
- Test: `tests/unit/test_linter.py`

- [ ] **Step 1: Write the failing tests**

Append at the end of `tests/unit/test_linter.py`:

```python
# ---------------------------------------------------------------------------
# duplicate-label (broader semantics)
# ---------------------------------------------------------------------------


async def test_duplicate_label_case_insensitive_within_classes() -> None:
    """Existing behavior preserved: classes with same label (any case) flagged."""
    g = Graph()
    g.add((EX.A, RDF.type, OWL.Class))
    g.add((EX.A, RDFS.label, Literal("Animal", lang="en")))
    g.add((EX.B, RDF.type, OWL.Class))
    g.add((EX.B, RDFS.label, Literal("ANIMAL", lang="en")))

    linter = OntologyLinter(enabled_rules={"duplicate-label"})
    issues = await linter.lint(g, PROJECT_ID)

    matches = _results_with_rule(issues, "duplicate-label")
    assert {m.subject_iri for m in matches} == {str(EX.A), str(EX.B)}


async def test_duplicate_label_flags_property_duplicates() -> None:
    """Two ObjectProperties sharing a label (case-insensitive) are flagged."""
    g = Graph()
    g.add((EX.knows, RDF.type, OWL.ObjectProperty))
    g.add((EX.knows, RDFS.label, Literal("knows", lang="en")))
    g.add((EX.acquaintedWith, RDF.type, OWL.ObjectProperty))
    g.add((EX.acquaintedWith, RDFS.label, Literal("Knows", lang="en")))

    linter = OntologyLinter(enabled_rules={"duplicate-label"})
    issues = await linter.lint(g, PROJECT_ID)

    matches = _results_with_rule(issues, "duplicate-label")
    assert {m.subject_iri for m in matches} == {str(EX.knows), str(EX.acquaintedWith)}
    for m in matches:
        assert m.subject_type == "property"


async def test_duplicate_label_flags_individual_duplicates() -> None:
    g = Graph()
    g.add((EX.Person, RDF.type, OWL.Class))
    g.add((EX.alice1, RDF.type, EX.Person))
    g.add((EX.alice1, RDFS.label, Literal("Alice", lang="en")))
    g.add((EX.alice2, RDF.type, EX.Person))
    g.add((EX.alice2, RDFS.label, Literal("alice", lang="en")))

    linter = OntologyLinter(enabled_rules={"duplicate-label"})
    issues = await linter.lint(g, PROJECT_ID)

    matches = _results_with_rule(issues, "duplicate-label")
    assert {m.subject_iri for m in matches} == {str(EX.alice1), str(EX.alice2)}


async def test_duplicate_label_does_not_flag_across_entity_types() -> None:
    """A class and a property sharing a label are NOT cross-flagged."""
    g = Graph()
    g.add((EX.Knows, RDF.type, OWL.Class))
    g.add((EX.Knows, RDFS.label, Literal("knows", lang="en")))
    g.add((EX.knows, RDF.type, OWL.ObjectProperty))
    g.add((EX.knows, RDFS.label, Literal("Knows", lang="en")))

    linter = OntologyLinter(enabled_rules={"duplicate-label"})
    issues = await linter.lint(g, PROJECT_ID)

    assert _results_with_rule(issues, "duplicate-label") == []


async def test_duplicate_label_separates_languages() -> None:
    """Same label string in different languages is not a duplicate."""
    g = Graph()
    g.add((EX.A, RDF.type, OWL.Class))
    g.add((EX.A, RDFS.label, Literal("Hund", lang="de")))
    g.add((EX.B, RDF.type, OWL.Class))
    g.add((EX.B, RDFS.label, Literal("Hund", lang="en")))  # English happens to coincide

    linter = OntologyLinter(enabled_rules={"duplicate-label"})
    issues = await linter.lint(g, PROJECT_ID)

    assert _results_with_rule(issues, "duplicate-label") == []
```

- [ ] **Step 2: Update the existing duplicate-label tests if needed**

Look at the existing `test_duplicate_label` test (around line 192). Currently both classes share a label and are flagged. Verify this still passes after the implementation change — no test edits expected, but if the existing test asserted `subject_type == "class"` exactly, that should still hold.

- [ ] **Step 3: Run the tests to verify they fail**

```bash
.venv/bin/pytest tests/unit/test_linter.py -k duplicate_label -v --no-cov
```

Expected: the 5 new tests fail because the current implementation either misses non-class entity types (`flags_property_duplicates`, `flags_individual_duplicates`) or cross-flags across types (`does_not_flag_across_entity_types`) or ignores language tags (`separates_languages`).

- [ ] **Step 4: Replace `_check_duplicate_label` with the broadened version**

In `ontokit/services/linter.py`, also update the rule's `LintRuleInfo.scope` from `_ALL` (it's already `_ALL` per the spec? — verify by reading line 91-95; if scope is currently `_ALL` no change is needed; if it is `["class"]` change it to `_ALL`):

```python
    LintRuleInfo(
        rule_id="duplicate-label",
        name="Duplicate Label",
        description="Multiple resources of the same entity type share the same label (case-insensitive, per language)",
        severity=LintIssueType.WARNING.value,
        scope=_ALL,
    ),
```

Replace the entire `_check_duplicate_label` method (line 524 area):

```python
    async def _check_duplicate_label(self, graph: Graph) -> list[LintResult]:
        """Find resources of the same entity type sharing a label (case-insensitive, per language)."""
        issues: list[LintResult] = []

        # Group by (entity_type, label_lower, lang) → list of resource IRIs.
        # Skip resources whose entity_type is "other" — we only group concrete
        # types that the schema knows how to navigate.
        groups: dict[tuple[str, str, str | None], list[str]] = defaultdict(list)
        original_label_for: dict[str, str] = {}

        for subject in self._uri_subjects:
            etype = self._determine_entity_type(graph, subject)
            if etype == "other":
                continue
            for label in graph.objects(subject, RDFS.label):
                if not isinstance(label, RDFLiteral):
                    continue
                label_str = str(label).strip()
                if not label_str:
                    continue
                key = (etype, label_str.lower(), label.language)
                groups[key].append(str(subject))
                original_label_for.setdefault(str(subject), label_str)

        reported_iris: set[str] = set()
        for (_etype, _lower, lang), iris in groups.items():
            if len(iris) < 2:
                continue
            for iri in iris:
                if iri in reported_iris:
                    continue
                reported_iris.add(iri)
                others = [o for o in iris if o != iri]
                lang_str = f"@{lang}" if lang else ""
                shown_label = original_label_for[iri]
                issues.append(
                    LintResult(
                        issue_type=LintIssueType.WARNING.value,
                        rule_id="duplicate-label",
                        message=(
                            f'Label "{shown_label}"{lang_str} is shared with '
                            f"{len(others)} other resource(s) of the same type"
                        ),
                        subject_iri=iri,
                        subject_type=self._determine_entity_type(graph, URIRef(iri)),
                        details={
                            "local_name": self._get_local_name(URIRef(iri)),
                            "label": shown_label,
                            "language": lang,
                            "duplicate_iris": others[:5],
                            "total_duplicates": len(others),
                        },
                    )
                )
        return issues
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
.venv/bin/pytest tests/unit/test_linter.py -k duplicate_label -v --no-cov
```

Expected: all duplicate-label tests pass (existing + 5 new).

- [ ] **Step 6: Commit**

```bash
git add ontokit/services/linter.py tests/unit/test_linter.py
git commit -m "feat(lint): broaden duplicate-label to all entity types, same-type only (#99)

Matching is now case-insensitive, per language, and grouped by entity
type — so a class and a property sharing 'knows' is no longer a false
positive, but two ObjectProperties with the same label still are.
Scope expanded from class-only to all entity types. Mirrors the per-
type semantics from consistency_service._check_duplicate_label while
keeping the lint rule's case-insensitive matching."
```

---

## Task 10: Update `LINT_LEVEL_DEFINITIONS` descriptions

**Files:**
- Modify: `ontokit/services/linter.py`

- [ ] **Step 1: Edit the L2 and L4 descriptions**

In `ontokit/services/linter.py`, find `LINT_LEVEL_DEFINITIONS` (around line 230) and update:

```python
LINT_LEVEL_DEFINITIONS: dict[int, LintLevelDefinition] = {
    1: LintLevelDefinition(
        "Critical",
        "Dangling references, circular hierarchies, undefined prefixes",
        LINT_LEVELS[1],
    ),
    2: LintLevelDefinition(
        "Consistency",
        (
            "Orphan classes, duplicate triples, disjointness violations, "
            "orphan individuals, deprecated parent classes"
        ),
        LINT_LEVELS[2],
    ),
    3: LintLevelDefinition(
        "Labels",
        "Missing, empty, and duplicate label checks",
        LINT_LEVELS[3],
    ),
    4: LintLevelDefinition(
        "Quality",
        (
            "Comments, per-language label checks, redundant regional variants, "
            "unused properties, empty domain/range, multi-root warnings"
        ),
        LINT_LEVELS[4],
    ),
    5: LintLevelDefinition(
        "All",
        "All available rules including domain/range and cardinality",
        LINT_LEVELS[5],
    ),
}
```

(Task 7 already updated L1's description, so it's listed here only for reference; do not edit it again if it's already correct.)

- [ ] **Step 2: Verify ruff + mypy clean**

```bash
.venv/bin/ruff check ontokit/services/linter.py
.venv/bin/ruff format --check ontokit/services/linter.py
.venv/bin/mypy ontokit/services/linter.py
```

Expected: all clean.

- [ ] **Step 3: Commit**

```bash
git add ontokit/services/linter.py
git commit -m "feat(lint): refresh L2 and L4 descriptions for new rules (#99)

L2 now mentions orphan-individual and deprecated-parent. L4 now
mentions unused-property, empty-domain/range, and multi-root."
```

---

## Task 11: Add level-membership coverage test

**Files:**
- Test: `tests/unit/test_linter.py`

- [ ] **Step 1: Write the failing test**

Append at the end of `tests/unit/test_linter.py`:

```python
# ---------------------------------------------------------------------------
# Level membership for new and renamed rules (#99)
# ---------------------------------------------------------------------------


def test_lint_levels_include_new_and_renamed_rules() -> None:
    """Each rule introduced or renamed in #99 is in the expected lint level."""
    from ontokit.services.linter import LINT_LEVELS

    # L1 — dangling-ref replaces undefined-parent.
    assert "dangling-ref" in LINT_LEVELS[1]
    assert "undefined-parent" not in LINT_LEVELS[1]
    assert "undefined-parent" not in LINT_LEVELS[5]

    # L2 — orphan-individual and deprecated-parent join existing consistency rules.
    assert "orphan-individual" in LINT_LEVELS[2]
    assert "deprecated-parent" in LINT_LEVELS[2]

    # L4 — quality-style additions.
    assert "unused-property" in LINT_LEVELS[4]
    assert "empty-domain" in LINT_LEVELS[4]
    assert "empty-range" in LINT_LEVELS[4]
    assert "multi-root" in LINT_LEVELS[4]
```

- [ ] **Step 2: Run the test to verify it passes**

```bash
.venv/bin/pytest tests/unit/test_linter.py -k lint_levels_include_new -v --no-cov
```

Expected: PASS (all level memberships were established by Tasks 1–7).

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_linter.py
git commit -m "test(lint): assert level membership for new/renamed rules (#99)

Locks in the level placements from the design doc so a future
accidental edit to LINT_LEVELS gets caught at test time."
```

---

## Task 12: Final regression — full linter test suite + open the PR

**Files:** none

- [ ] **Step 1: Run the full linter test suite**

```bash
.venv/bin/pytest tests/unit/test_linter.py -v --no-cov
```

Expected: every test passes. Verify the test count grew by approximately the number of new tests added across Tasks 1–11.

- [ ] **Step 2: Run the full backend test suite**

```bash
.venv/bin/pytest tests/ -q --no-cov
```

Expected: green. Any failure outside `tests/unit/test_linter.py` indicates a regression — investigate before opening the PR.

- [ ] **Step 3: Final ruff + mypy + format pass**

```bash
.venv/bin/ruff check ontokit/services/linter.py tests/unit/test_linter.py
.venv/bin/ruff format --check ontokit/services/linter.py tests/unit/test_linter.py
.venv/bin/mypy ontokit/services/linter.py
```

Expected: all clean.

- [ ] **Step 4: Push the branch**

```bash
git push -u origin feat/issue-99-consolidate-consistency
```

- [ ] **Step 5: Open the PR**

```bash
gh pr create --base dev \
  --title "feat(lint): consolidate consistency rules into linter (#99 part 1)" \
  --body "$(cat <<'EOF'
## Summary

PR1 of two for issue #99. Adds 6 new rules to the linter and reconciles 3 partial-overlap rules so the lint system covers everything `consistency_service.py` checks. `consistency_service.py`, its routes, the worker task, and the frontend Consistency tab are all left in place; PR2 will remove them once we have confidence the lint pipeline produces equivalent findings.

### New rules

| `rule_id` | Severity | Level | Notes |
|-----------|----------|-------|-------|
| `unused-property` | warning | L4 | Property declared but never used as predicate |
| `orphan-individual` | warning | L2 | Individual's `rdf:type` not declared as `owl:Class` |
| `empty-domain` | info | L4 | Object/Datatype property with no `rdfs:domain` |
| `empty-range` | info | L4 | Same for `rdfs:range` |
| `deprecated-parent` | warning | L2 | Class subclasses an `owl:deprecated` class |
| `multi-root` | info | L4 | Fires once if >5 root classes; ontology-scope finding |

### Reconciled rules

- **`undefined-parent` → `dangling-ref`** (rename + expand). Now scans `rdfs:subClassOf`, `rdfs:domain`, and `rdfs:range`. Each finding carries `details.predicate`. Stays at L1 (Critical). Existing `LintIssue` rows with the old `rule_id` are left in place; lint runs are user-triggered and regenerable.
- **`duplicate-label`** (broaden). Scope expanded from class-only to all entity types; matching key is now `(entity_type, label_lower, lang)` so cross-type collisions and language overlaps are no longer false positives. Stays at L3.
- **`orphan-class`** — no code change. The "no instances" variant from consistency simply disappears with PR2.

### Out of scope

- Removal of `consistency_service.py` and its routes (PR2)
- Discussion #87's broader rdflib-vs-SQL question
- Frontend Consistency tab (PR2)

## Design

`docs/superpowers/specs/2026-05-03-issue-99-consolidate-consistency-into-lint-design.md`

## Test plan

- [x] Per-rule unit tests for every new and reconciled rule
- [x] Level-membership coverage test
- [x] Full `pytest tests/` regression green
- [x] ruff + mypy clean

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-Review Checklist (run before declaring the plan done)

1. **Spec coverage:**
   - 6 new rules → Tasks 1–6 ✓
   - `orphan-class` no change → noted in PR description, no task needed ✓
   - `undefined-parent` → `dangling-ref` rename → Task 7 ✓
   - `dangling-ref` domain/range expansion → Task 8 ✓
   - `duplicate-label` broadening → Task 9 ✓
   - `LINT_LEVEL_DEFINITIONS` description updates → Task 10 ✓
   - Level-membership coverage test → Task 11 ✓
   - Full regression + PR open → Task 12 ✓

2. **Placeholder scan:** every step contains either concrete code, a concrete command, or a concrete file edit. No "TBD" / "implement appropriate" / "similar to above" placeholders.

3. **Type consistency:** every test uses `OntologyLinter(enabled_rules={...})` and `_results_with_rule(issues, rule_id)`; every rule's `LintRuleInfo` matches the method name (kebab → snake) and the `LintResult.rule_id` literal. `is_deprecated` import added in Task 5 is used in the same task; `defaultdict` is already imported in `linter.py` at line 4 (used by Task 9).

4. **Out-of-scope creep check:** no task touches `consistency_service.py`, `quality.py`, `worker.py`, schemas, or the frontend.
