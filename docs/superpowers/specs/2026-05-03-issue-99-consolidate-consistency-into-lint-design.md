# Issue #99 — Consolidate Consistency Checks into the Lint Rule System

**Status:** Design approved (2026-05-03), pending @damienriehl input on `orphan-class` and `dangling-ref` reconciliation choices (logged in [issue #99 comment](https://github.com/CatholicOS/ontokit-api/issues/99#issuecomment-4364982879)).

**Issue:** [#99](https://github.com/CatholicOS/ontokit-api/issues/99) — milestone v0.4.0
**Related:** [Discussion #87](https://github.com/CatholicOS/ontokit-api/discussions/87) (rdflib-vs-SQL — out of scope here)
**Prerequisite:** [PR #94](https://github.com/CatholicOS/ontokit-api/pull/94) per-project lint config — merged ✓

## Problem

`ontokit/services/consistency_service.py` (12 rules, ephemeral Redis cache, all-or-nothing runner) and `ontokit/services/linter.py` (19 rules, progressive levels, per-project config, persisted in PostgreSQL, entity-type-aware) both check ontology quality with significant overlap:

- 3 fully redundant rules (`cycle-detect`, `missing-label`, `missing-comment`)
- 3 partially overlapping rules with diverging semantics (`orphan-class`, `undefined-parent` ↔ `dangling-ref`, `duplicate-label`)
- 6 rules unique to consistency that don't exist in lint

The lint system is the more capable of the two and is where new work should land. Consistency_service should go away; its remaining behaviors should move into the linter.

## Scope

In: backend rule consolidation, route + worker + service deletion, frontend Consistency-tab removal.

Out (explicitly): the broader rdflib-graph-vs-SQL question raised in discussion #87, the duplicate-detection (`pg_trgm`) pipeline, the cross-references endpoint.

## Approach

Two PRs, in order:

1. **PR1 — `feat(lint): consolidate consistency rules into linter`.** Adds 6 new rules and reconciles 3 partial-overlap rules in `linter.py`. `consistency_service.py` and its routes are left untouched, so both pipelines run side by side and we can validate parity in production before tearing the old one down.
2. **PR2 — `chore: remove consistency_service in favor of linter`.** Hard-removes the service, its routes, the worker task, and the frontend Consistency tab. Depends on PR1 being merged.

## PR1 — Rule Consolidation

### 6 new rules added to `LINT_RULES`

| `rule_id` | Name | Severity | Scope | Level | Notes |
|-----------|------|----------|-------|-------|-------|
| `unused-property` | Unused Property | warning | `["property"]` | L4 (Quality) | Declared property never used as predicate (excluding own declaration triple) |
| `orphan-individual` | Orphan Individual | warning | `["individual"]` | L2 (Consistency) | Individual's `rdf:type` target is not declared as `owl:Class` in this ontology; one finding per (individual, undeclared-type) pair |
| `empty-domain` | Empty Domain | info | `["property"]` | L4 (Quality) | `owl:ObjectProperty` or `owl:DatatypeProperty` with no `rdfs:domain` |
| `empty-range` | Empty Range | info | `["property"]` | L4 (Quality) | Same for `rdfs:range` |
| `deprecated-parent` | Deprecated Parent | warning | `["class"]` | L2 (Consistency) | Class `subClassOf` a class with `owl:deprecated true` |
| `multi-root` | Multiple Root Classes | info | `[]` (ontology-scope) | L4 (Quality) | Fires once if >5 root classes; uses `subject_iri=None`, `subject_type="other"` |

Severities are taken verbatim from the originals in `consistency_service.py` so canary parity holds. Level placements match the issue body's recommendations: `orphan-individual` and `deprecated-parent` are TBox-correctness issues (the ontology is meaningfully wrong) so they belong at L2; the other four are quality/style concerns that don't break the ontology, so they stay at L4.

`LINT_LEVEL_DEFINITIONS` descriptions get updated:
- L2 description gains "deprecated parent classes, orphan individuals"
- L4 description gains "unused properties, empty domain/range, multi-root warnings"

### 3 partial-overlap rules — reconciliation

**`orphan-class`** — no code change. Keep the existing lint behavior (no parent + no children). The stricter "no instances" variant from `consistency_service.py` simply disappears with PR2's removal. Stays at L2.

> Rationale: "instance" here means individuals declared with `rdf:type Class`, and a class without individuals isn't necessarily orphan-worthy. TBox-only ontologies, abstract classes, and taxonomies declared before being populated all legitimately have classes with no individuals. Flagging those would produce false positives.

**`undefined-parent` → `dangling-ref`** — rename and expand.

- Rename `rule_id` from `undefined-parent` to `dangling-ref` in `LINT_RULES`, `LINT_RULES_MAP`, all level sets, and all callsites.
- `name` becomes "Dangling Reference"; description becomes "Reference to a URI not defined in the ontology (in `subClassOf`, `rdfs:domain`, or `rdfs:range`)".
- The check scans all three predicates. The well-known-namespace + `owl:imports`-derived skiplist is ported over from `consistency_service._check_dangling_ref`.
- `details` payload gains a `predicate` field so the UI can show *which* axis triggered the dangling reference.
- Stays at L1 (Critical) — domain/range dangling refs are equally fatal to reasoning as subclass dangling refs.
- **Historical data**: existing `LintIssue` rows with `rule_id="undefined-parent"` are left in place (they are snapshots of past runs and lint results are regenerable). Documenting this in the PR description is sufficient. UI filters by `rule_id` will not find the old name; users can re-run lint to refresh.

**`duplicate-label`** — broaden semantics.

- `scope`: `["class"]` → `_ALL` (now applies to classes, properties, and individuals).
- Matching key: `label_lower` → `(entity_type, label_lower, lang)` — group case-insensitively, per entity type, per language.
- A finding is emitted for each member of any group of size ≥ 2; `details.duplicates` lists the other IRIs in the group; `subject_type` is set to the entity type of the duplicate.
- Stays at L3 (Labels).

### Files touched in PR1

- `ontokit/services/linter.py` — add 6 rule definitions to `LINT_RULES`, add 6 check methods to `OntologyLinter`, rename `undefined-parent` → `dangling-ref`, update `_check_duplicate_label` matching, update `LINT_LEVELS` membership and `LINT_LEVEL_DEFINITIONS` descriptions.
- `tests/unit/test_linter.py` — add per-rule test classes for new rules, extend `duplicate-label` and `dangling-ref` tests, update level-membership assertions.

`consistency_service.py`, `ontokit/api/routes/quality.py`, `ontokit/worker.py`, and the frontend are NOT touched in PR1.

## PR2 — Removal and Cutover

### Backend deletions

- **Files:** `ontokit/services/consistency_service.py`, `tests/unit/test_consistency_service.py`. The `tests/unit/test_quality_worker.py` file stays — only the `run_consistency_check_task` test class (line 59 onward) is deleted; `run_duplicate_detection_task` tests remain.
- **Routes in `ontokit/api/routes/quality.py`:**
  - `POST /{project_id}/quality/check` → `trigger_consistency_check` (lines 64–109)
  - `GET /{project_id}/quality/jobs/{job_id}` → `get_quality_job_result` (lines 112–165) — currently consistency-only despite the generic-looking path
  - `GET /{project_id}/quality/issues` → `get_consistency_issues` (lines 167–204)
  - **Kept**: `/entities/{iri}/references` (cross-refs, unrelated), all `/quality/duplicates/*` routes, the `/quality/ws` WebSocket — only its docstring drops the "Consistency check starts / completes / fails" line; the WS itself is a generic pubsub forwarder.
- **Worker (`ontokit/worker.py`):** delete `_parse_and_run_consistency_check` (line 65), `run_consistency_check_task` (line 643), and the `func(run_consistency_check_task, timeout=900)` entry from the ARQ task list (line 1287).
- **Schemas (`ontokit/schemas/quality.py`):** delete `ConsistencyCheckResult` and `ConsistencyIssue` (used exclusively by the consistency pipeline; verified by `grep`).
- **Route tests:** the consistency-route assertions in `tests/unit/test_quality_routes.py` (line 114 area) are deleted; duplicate-detection route tests stay.

### Frontend deletions (`ontokit-web/`)

- `components/editor/HealthCheckPanel.tsx`: remove the Consistency tab entirely.
- `lib/api/quality.ts`: remove the consistency-check client methods (precise names verified at implementation time).
- `lib/ontology/qualityTypes.ts`: remove `ConsistencyCheckResult` / `ConsistencyIssue` types (keep duplicate-detection types).
- `__tests__/lib/api/quality.test.ts`: remove tests for the deleted client methods.
- `__tests__/components/editor/HealthCheckPanel.test.tsx`: drop tab-switching tests for the Consistency tab.

### External API

No external consumers of the `/quality/check`, `/quality/jobs/{job_id}`, or `/quality/issues` endpoints are known, so all three are hard-removed in PR2 (no `410 Gone` shim, no alias-redirect).

### Cache cleanup

Existing `consistency_check:*` Redis keys have a TTL and will expire naturally. No explicit eviction needed.

## Testing Strategy

### PR1

- **Per-rule unit tests** for each of the 6 new rules in `tests/unit/test_linter.py`, each with at least:
  - A "should flag" case (minimal in-memory rdflib graph that triggers the rule)
  - A "should not flag" case (minimal graph that doesn't)
  - Where applicable, a `details`-shape assertion (e.g., `details.predicate` for `dangling-ref`, `details.duplicates` for `duplicate-label`, `details.root_count` for `multi-root`).
- **Reconciled rules:**
  - `dangling-ref`: rename existing `undefined-parent` tests (lines 224, 242, 286) to use the new `rule_id`; add tests for `rdfs:domain` and `rdfs:range` dangling refs; assert `details.predicate` is set per axis.
  - `duplicate-label`: extend existing test (line 192) with property and individual cases; add a same-label-different-type test that asserts NO finding (same-type constraint); add a case-insensitivity test.
  - `orphan-class`: no test changes (behavior unchanged).
- **Level coverage:** add `test_lint_levels_include_new_rules` that asserts each new `rule_id` is in the expected level set, and `dangling-ref` is in L1 (replacing `undefined-parent`).
- **No separate parity-vs-`consistency_service` test harness** — each new rule's own unit tests effectively replicate what the corresponding `consistency_service.py` test covers.

### PR2

- Delete `tests/unit/test_consistency_service.py` whole file.
- Delete consistency-route tests in `tests/unit/test_quality_routes.py` (the `run_consistency_check_task` assertion area, plus the consistency-endpoint tests around it).
- Delete the `run_consistency_check_task` test class in `tests/unit/test_quality_worker.py`; keep `run_duplicate_detection_task` tests.
- Frontend: update `__tests__/components/editor/HealthCheckPanel.test.tsx` to drop Consistency-tab navigation tests; update `__tests__/lib/api/quality.test.ts` to remove tests for the deleted client methods.

### Regression

Full `pytest tests/ -k linter` must stay green after PR1. Same for the frontend's Vitest suite after PR2.

## Risks and Open Questions

- **Existing baselines containing `undefined-parent` issues.** When the rule is renamed, those rows will not appear under the new `dangling-ref` filter. Mitigation: lint runs are user-triggered and regenerable — re-running lint produces fresh issues with the new `rule_id`. Documenting the rename in the PR description and changelog is sufficient.
- **The two unresolved reconciliation choices** (logged in the issue comment, awaiting @damienriehl input):
  - `orphan-class`: keep loose definition vs adopt strict "no instances".
  - `undefined-parent` → `dangling-ref`: rename + expand vs keep separate rules.
  This document reflects the working decision (keep loose `orphan-class`, rename + expand to `dangling-ref`); it will be revised if those decisions change.
- **`multi-root`'s ontology-scope shape.** The lint schema's `subject_iri` is `str | None` and `subject_type` already accepts `"other"`, so this fits without schema changes. If a future use case wants to distinguish ontology-scope findings from class-scope findings in the UI, a dedicated `subject_type="ontology"` value can be added then.
