"""Pydantic schemas for quality checks (cross-references, consistency, duplicates)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

# --- Cross-References ---

ReferenceContext = Literal[
    "parent_iris",
    "domain_iris",
    "range_iris",
    "type_iris",
    "equivalent_iris",
    "disjoint_iris",
    "some_values_from",
    "annotation_value",
    "see_also",
    "inverse_of",
]

CONTEXT_LABELS: dict[str, str] = {
    "parent_iris": "As parent class",
    "domain_iris": "As property domain",
    "range_iris": "As property range",
    "type_iris": "As instance type",
    "equivalent_iris": "As equivalent class",
    "disjoint_iris": "As disjoint class",
    "some_values_from": "In restriction (someValuesFrom)",
    "annotation_value": "As annotation value",
    "see_also": "Referenced via seeAlso",
    "inverse_of": "As inverse property",
}


class CrossReference(BaseModel):
    source_iri: str
    source_type: str
    source_label: str | None = None
    reference_context: ReferenceContext


class CrossReferenceGroup(BaseModel):
    context: ReferenceContext
    context_label: str
    references: list[CrossReference]


class CrossReferencesResponse(BaseModel):
    target_iri: str
    total: int
    groups: list[CrossReferenceGroup]


# --- Consistency ---

ConsistencyRuleId = Literal[
    "orphan_class",
    "cycle_detect",
    "unused_property",
    "missing_label",
    "missing_comment",
    "orphan_individual",
    "empty_domain",
    "empty_range",
    "duplicate_label",
    "deprecated_parent",
    "dangling_ref",
    "multi_root",
]


class ConsistencyIssue(BaseModel):
    rule_id: ConsistencyRuleId
    severity: Literal["error", "warning", "info"]
    entity_iri: str
    entity_type: str
    message: str
    details: dict[str, Any] | None = None


class ConsistencyCheckResult(BaseModel):
    project_id: str
    branch: str
    issues: list[ConsistencyIssue]
    checked_at: str
    duration_ms: float


class ConsistencyCheckTriggerResponse(BaseModel):
    job_id: str


# --- Duplicate Detection ---


class DuplicateEntity(BaseModel):
    iri: str
    label: str
    entity_type: str


class DuplicateCluster(BaseModel):
    entities: list[DuplicateEntity]
    similarity: float


class DuplicateDetectionResult(BaseModel):
    clusters: list[DuplicateCluster]
    threshold: float
    checked_at: str
