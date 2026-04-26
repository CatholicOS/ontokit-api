"""Ontology linting service for checking ontology health."""

import contextlib
from collections import defaultdict
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, field
from typing import Any, NamedTuple
from uuid import UUID

from rdflib import Graph, Namespace, URIRef
from rdflib import Literal as RDFLiteral
from rdflib.namespace import OWL, RDF, RDFS, SKOS, XSD

from ontokit.models.lint import LintIssueType

DC = Namespace("http://purl.org/dc/elements/1.1/")
DCTERMS = Namespace("http://purl.org/dc/terms/")


@dataclass
class LintResult:
    """Result from a lint check."""

    issue_type: str  # error, warning, info
    rule_id: str
    message: str
    subject_iri: str | None = None
    subject_type: str | None = None  # "class", "property", "individual", "other"
    details: dict[str, Any] | None = None


@dataclass
class LintRuleInfo:
    """Information about a lint rule."""

    rule_id: str
    name: str
    description: str
    severity: str
    scope: list[str]


# Scope constants for rule applicability
_ALL = ["class", "property", "individual"]

# Available lint rules with their metadata
LINT_RULES: list[LintRuleInfo] = [
    LintRuleInfo(
        rule_id="missing-label",
        name="Missing Label",
        description="Resources should have at least one rdfs:label annotation",
        severity=LintIssueType.WARNING.value,
        scope=_ALL,
    ),
    LintRuleInfo(
        rule_id="missing-comment",
        name="Missing Comment",
        description="Resources should have a description via rdfs:comment",
        severity=LintIssueType.INFO.value,
        scope=_ALL,
    ),
    LintRuleInfo(
        rule_id="orphan-class",
        name="Orphan Class",
        description="Classes with no parent (other than owl:Thing) and no children may be misplaced",
        severity=LintIssueType.WARNING.value,
        scope=["class"],
    ),
    LintRuleInfo(
        rule_id="undefined-parent",
        name="Undefined Parent",
        description="Class references a parent that is not defined in the ontology",
        severity=LintIssueType.ERROR.value,
        scope=["class"],
    ),
    LintRuleInfo(
        rule_id="circular-hierarchy",
        name="Circular Hierarchy",
        description="Circular inheritance detected in class hierarchy",
        severity=LintIssueType.ERROR.value,
        scope=["class"],
    ),
    LintRuleInfo(
        rule_id="empty-label",
        name="Empty Label",
        description="Resource has a label that is an empty string",
        severity=LintIssueType.WARNING.value,
        scope=_ALL,
    ),
    LintRuleInfo(
        rule_id="duplicate-label",
        name="Duplicate Label",
        description="Multiple resources share the same label, which may cause confusion",
        severity=LintIssueType.WARNING.value,
        scope=_ALL,
    ),
    LintRuleInfo(
        rule_id="label-per-language",
        name="Duplicate Label Per Language",
        description="Resource has multiple different labels for the same language tag",
        severity=LintIssueType.ERROR.value,
        scope=_ALL,
    ),
    LintRuleInfo(
        rule_id="undefined-prefix",
        name="Undefined Prefix",
        description="IRI uses a prefix that is not defined in the namespace bindings",
        severity=LintIssueType.ERROR.value,
        scope=_ALL,
    ),
    LintRuleInfo(
        rule_id="duplicate-triple",
        name="Duplicate Triple",
        description="Same predicate-object pair appears multiple times for the same subject",
        severity=LintIssueType.INFO.value,
        scope=_ALL,
    ),
    LintRuleInfo(
        rule_id="domain-violation",
        name="Domain Violation",
        description="Property used on a subject that is not in its declared domain",
        severity=LintIssueType.WARNING.value,
        scope=_ALL,
    ),
    LintRuleInfo(
        rule_id="range-violation",
        name="Range Violation",
        description="Property value is not in the declared range",
        severity=LintIssueType.WARNING.value,
        scope=_ALL,
    ),
    LintRuleInfo(
        rule_id="cardinality-violation",
        name="Cardinality Violation",
        description="Property usage violates declared cardinality constraints",
        severity=LintIssueType.ERROR.value,
        scope=["individual"],
    ),
    LintRuleInfo(
        rule_id="disjoint-violation",
        name="Disjoint Class Violation",
        description="Resource is typed with classes declared as disjoint",
        severity=LintIssueType.ERROR.value,
        scope=["individual"],
    ),
    LintRuleInfo(
        rule_id="inverse-property-inconsistency",
        name="Inverse Property Inconsistency",
        description="Inverse property relationship is not symmetric",
        severity=LintIssueType.WARNING.value,
        scope=["property"],
    ),
    LintRuleInfo(
        rule_id="missing-english-label",
        name="Missing English Label",
        description="Resource has labels but none in English",
        severity=LintIssueType.WARNING.value,
        scope=_ALL,
    ),
    LintRuleInfo(
        rule_id="missing-language-tag",
        name="Missing Language Tag",
        description="Label or annotation has no language tag (plain literal or xsd:string)",
        severity=LintIssueType.WARNING.value,
        scope=_ALL,
    ),
    LintRuleInfo(
        rule_id="redundant-regional-label",
        name="Redundant Regional Label",
        description="Regional language variants have identical values and should use the base tag",
        severity=LintIssueType.INFO.value,
        scope=_ALL,
    ),
    LintRuleInfo(
        rule_id="missing-type-declaration",
        name="Missing Type Declaration",
        description="Resource has no rdf:type declaration (not declared as class, property, or individual)",
        severity=LintIssueType.WARNING.value,
        scope=_ALL,
    ),
]

# Map rule IDs to their info
LINT_RULES_MAP: dict[str, LintRuleInfo] = {rule.rule_id: rule for rule in LINT_RULES}

# Progressive lint levels — each level cumulatively includes the previous
_LEVEL_1_RULES: set[str] = {"undefined-parent", "circular-hierarchy", "undefined-prefix"}
_LEVEL_2_RULES: set[str] = _LEVEL_1_RULES | {
    "orphan-class",
    "duplicate-triple",
    "disjoint-violation",
    "missing-type-declaration",
}
_LEVEL_3_RULES: set[str] = _LEVEL_2_RULES | {
    "missing-label",
    "empty-label",
    "duplicate-label",
    "missing-english-label",
    "missing-language-tag",
}
_LEVEL_4_RULES: set[str] = _LEVEL_3_RULES | {
    "missing-comment",
    "label-per-language",
    "redundant-regional-label",
}
_LEVEL_5_RULES: set[str] = {r.rule_id for r in LINT_RULES}

LINT_LEVELS: dict[int, frozenset[str]] = {
    1: frozenset(_LEVEL_1_RULES),
    2: frozenset(_LEVEL_2_RULES),
    3: frozenset(_LEVEL_3_RULES),
    4: frozenset(_LEVEL_4_RULES),
    5: frozenset(_LEVEL_5_RULES),
}

ALL_RULE_IDS: frozenset[str] = LINT_LEVELS[5]


class LintLevelDefinition(NamedTuple):
    """Metadata for a progressive lint level."""

    name: str
    description: str
    rules: frozenset[str]


LINT_LEVEL_DEFINITIONS: dict[int, LintLevelDefinition] = {
    1: LintLevelDefinition(
        "Critical",
        "Undefined parents, circular hierarchies, undefined prefixes",
        LINT_LEVELS[1],
    ),
    2: LintLevelDefinition(
        "Consistency",
        "Orphan classes, duplicate triples, and disjointness violations",
        LINT_LEVELS[2],
    ),
    3: LintLevelDefinition(
        "Labels",
        "Missing, empty, and duplicate label checks",
        LINT_LEVELS[3],
    ),
    4: LintLevelDefinition(
        "Quality",
        "Comments, per-language label checks, and redundant regional variants",
        LINT_LEVELS[4],
    ),
    5: LintLevelDefinition(
        "All",
        "All available rules including domain/range and cardinality",
        LINT_LEVELS[5],
    ),
}


def get_rules_for_level(level: int) -> frozenset[str]:
    """Return the immutable set of rule IDs enabled at a given lint level (1-5)."""
    if level < 1 or level > 5:
        raise ValueError(f"Lint level must be between 1 and 5, got {level}")
    return LINT_LEVELS[level]


@dataclass
class OntologyLinter:
    """Service for checking ontology health and finding issues."""

    enabled_rules: AbstractSet[str] = field(
        default_factory=lambda: frozenset(r.rule_id for r in LINT_RULES)
    )
    _uri_subjects: set[URIRef] = field(default_factory=set, init=False, repr=False)

    def get_enabled_rules(self) -> list[LintRuleInfo]:
        """Get list of enabled lint rules."""
        return [r for r in LINT_RULES if r.rule_id in self.enabled_rules]

    async def lint(self, graph: Graph, project_id: UUID) -> list[LintResult]:  # noqa: ARG002
        """
        Run all enabled lint rules on the ontology graph.

        Args:
            graph: The RDF graph to lint
            project_id: The project ID (for context)

        Returns:
            List of lint results (issues found)
        """
        issues: list[LintResult] = []

        # Pre-compute subjects once for all checkers
        self._uri_subjects: set[URIRef] = {
            s for s in graph.subjects() if isinstance(s, URIRef) and s != OWL.Thing
        }

        # Run each enabled rule
        for rule_id in self.enabled_rules:
            checker_name = f"_check_{rule_id.replace('-', '_')}"
            checker = getattr(self, checker_name, None)
            if checker:
                rule_issues = await checker(graph)
                issues.extend(rule_issues)

        return issues

    async def _check_missing_label(self, graph: Graph) -> list[LintResult]:
        """Find resources without rdfs:label."""
        issues = []

        for subject in self._uri_subjects:
            # Check for any rdfs:label
            labels = list(graph.objects(subject, RDFS.label))
            if not labels:
                issues.append(
                    LintResult(
                        issue_type=LintIssueType.WARNING.value,
                        rule_id="missing-label",
                        message="Resource has no rdfs:label annotation",
                        subject_iri=str(subject),
                        subject_type=self._determine_entity_type(graph, subject),
                        details={"local_name": self._get_local_name(subject)},
                    )
                )

        return issues

    async def _check_missing_comment(self, graph: Graph) -> list[LintResult]:
        """Find resources without rdfs:comment."""
        issues = []

        for subject in self._uri_subjects:
            # Check for any rdfs:comment
            comments = list(graph.objects(subject, RDFS.comment))
            if not comments:
                # Get label for better context
                label = self._get_label(graph, subject)
                issues.append(
                    LintResult(
                        issue_type=LintIssueType.INFO.value,
                        rule_id="missing-comment",
                        message="Resource has no rdfs:comment description",
                        subject_iri=str(subject),
                        subject_type=self._determine_entity_type(graph, subject),
                        details={
                            "local_name": self._get_local_name(subject),
                            "label": label,
                        },
                    )
                )

        return issues

    async def _check_orphan_class(self, graph: Graph) -> list[LintResult]:
        """Find classes with no parent (other than owl:Thing) and no children."""
        issues = []

        owl_thing = OWL.Thing

        for class_uri in graph.subjects(RDF.type, OWL.Class):
            if not isinstance(class_uri, URIRef):
                continue
            if class_uri == owl_thing:
                continue

            # Get parents (excluding owl:Thing)
            parents = [
                p
                for p in graph.objects(class_uri, RDFS.subClassOf)
                if isinstance(p, URIRef) and p != owl_thing
            ]

            # Get children
            children = list(graph.subjects(RDFS.subClassOf, class_uri))

            # Orphan if no meaningful parents and no children
            if not parents and not children:
                label = self._get_label(graph, class_uri)
                issues.append(
                    LintResult(
                        issue_type=LintIssueType.WARNING.value,
                        rule_id="orphan-class",
                        message="Class has no parent classes and no children",
                        subject_iri=str(class_uri),
                        subject_type="class",
                        details={
                            "local_name": self._get_local_name(class_uri),
                            "label": label,
                        },
                    )
                )

        return issues

    async def _check_undefined_parent(self, graph: Graph) -> list[LintResult]:
        """Find classes that reference undefined parent classes."""
        issues = []

        # Build set of all defined classes
        defined_classes = {
            str(c) for c in graph.subjects(RDF.type, OWL.Class) if isinstance(c, URIRef)
        }
        # Add owl:Thing as it's always implicitly defined
        defined_classes.add(str(OWL.Thing))

        for class_uri in graph.subjects(RDF.type, OWL.Class):
            if not isinstance(class_uri, URIRef):
                continue

            # Check each parent
            for parent_uri in graph.objects(class_uri, RDFS.subClassOf):
                if not isinstance(parent_uri, URIRef):
                    continue

                parent_str = str(parent_uri)
                if parent_str not in defined_classes:
                    label = self._get_label(graph, class_uri)
                    issues.append(
                        LintResult(
                            issue_type=LintIssueType.ERROR.value,
                            rule_id="undefined-parent",
                            message="References undefined parent class",
                            subject_iri=str(class_uri),
                            subject_type="class",
                            details={
                                "local_name": self._get_local_name(class_uri),
                                "label": label,
                                "undefined_parent": parent_str,
                                "undefined_parent_local": self._get_local_name(parent_uri),
                            },
                        )
                    )

        return issues

    async def _check_circular_hierarchy(self, graph: Graph) -> list[LintResult]:
        """Find circular inheritance in class hierarchy."""
        issues = []
        reported_cycles: set[frozenset[str]] = set()

        # Build adjacency list for subClassOf relationships
        subclass_of: dict[str, list[str]] = defaultdict(list)
        for class_uri in graph.subjects(RDF.type, OWL.Class):
            if isinstance(class_uri, URIRef):
                for parent in graph.objects(class_uri, RDFS.subClassOf):
                    if isinstance(parent, URIRef) and parent != OWL.Thing:
                        subclass_of[str(class_uri)].append(str(parent))

        def find_cycle(
            start: str, current: str, visited: set[str], path: list[str]
        ) -> list[str] | None:
            """DFS to find cycle starting from 'start'."""
            if current in visited:
                if current == start:
                    return path
                return None

            visited.add(current)
            path.append(current)

            for parent in subclass_of.get(current, []):
                cycle = find_cycle(start, parent, visited, path)
                if cycle is not None:
                    return cycle

            path.pop()
            return None

        # Check each class for cycles
        for class_str in subclass_of:
            cycle = find_cycle(class_str, class_str, set(), [])
            if cycle:
                # Create a frozenset to avoid reporting the same cycle multiple times
                cycle_set = frozenset(cycle)
                if cycle_set not in reported_cycles:
                    reported_cycles.add(cycle_set)
                    # Get labels for cycle classes
                    cycle_labels = [
                        self._get_label(graph, URIRef(c)) or self._get_local_name(URIRef(c))
                        for c in cycle
                    ]
                    issues.append(
                        LintResult(
                            issue_type=LintIssueType.ERROR.value,
                            rule_id="circular-hierarchy",
                            message=f"Circular inheritance: {' → '.join(cycle_labels)} → {cycle_labels[0]}",
                            subject_iri=cycle[0],
                            subject_type="class",
                            details={
                                "cycle_iris": cycle,
                                "cycle_labels": cycle_labels,
                            },
                        )
                    )

        return issues

    async def _check_empty_label(self, graph: Graph) -> list[LintResult]:
        """Find resources with empty string labels."""
        issues = []

        for subject in self._uri_subjects:
            # Check each label
            for label in graph.objects(subject, RDFS.label):
                if isinstance(label, RDFLiteral):
                    label_str = str(label).strip()
                    if not label_str:
                        issues.append(
                            LintResult(
                                issue_type=LintIssueType.WARNING.value,
                                rule_id="empty-label",
                                message="Resource has an empty rdfs:label",
                                subject_iri=str(subject),
                                subject_type=self._determine_entity_type(graph, subject),
                                details={
                                    "local_name": self._get_local_name(subject),
                                    "language": label.language,
                                },
                            )
                        )

        return issues

    async def _check_duplicate_label(self, graph: Graph) -> list[LintResult]:
        """Find resources that share the same label."""
        issues = []

        # Build map of label → list of resource IRIs
        label_to_resources: dict[str, list[str]] = defaultdict(list)

        for subject in self._uri_subjects:
            for label in graph.objects(subject, RDFS.label):
                if isinstance(label, RDFLiteral):
                    label_str = str(label).strip().lower()
                    if label_str:  # Skip empty labels
                        label_to_resources[label_str].append(str(subject))

        # Report duplicates
        reported_iris: set[str] = set()
        for _label_str, resource_iris in label_to_resources.items():
            if len(resource_iris) > 1:
                for resource_iri in resource_iris:
                    if resource_iri not in reported_iris:
                        reported_iris.add(resource_iri)
                        # Get original (non-lowercased) label
                        original_label = self._get_label(graph, URIRef(resource_iri))
                        other_resources = [c for c in resource_iris if c != resource_iri]
                        issues.append(
                            LintResult(
                                issue_type=LintIssueType.WARNING.value,
                                rule_id="duplicate-label",
                                message=f"Label '{original_label}' is shared with {len(other_resources)} other resource(s)",
                                subject_iri=resource_iri,
                                subject_type=self._determine_entity_type(
                                    graph, URIRef(resource_iri)
                                ),
                                details={
                                    "local_name": self._get_local_name(URIRef(resource_iri)),
                                    "label": original_label,
                                    "duplicate_iris": other_resources[:5],  # Limit to 5
                                    "total_duplicates": len(other_resources),
                                },
                            )
                        )

        return issues

    async def _check_label_per_language(self, graph: Graph) -> list[LintResult]:
        """
        Find resources with multiple different labels for the same predicate and language.

        Only checks predicates with cardinality constraints:
        - rdfs:label: conventionally one per language
        - skos:prefLabel: at most one per language (SKOS integrity condition S14)

        skos:altLabel and skos:hiddenLabel are explicitly unconstrained —
        multiple values per language is their intended usage (synonyms, variants).
        """
        issues = []

        label_predicates = [
            (RDFS.label, "rdfs:label"),
            (SKOS.prefLabel, "skos:prefLabel"),
        ]

        for subject in self._uri_subjects:
            for predicate, pred_name in label_predicates:
                # Collect labels by language for this specific predicate
                labels_by_lang: dict[str | None, list[str]] = defaultdict(list)

                for label in graph.objects(subject, predicate):
                    if isinstance(label, RDFLiteral):
                        # Normalize language tag to lowercase for case-insensitive
                        # comparison (BCP-47: tags are case-insensitive). Matches the
                        # normalization used by `redundant-regional-label`.
                        lang_key = label.language.lower() if label.language else None
                        labels_by_lang[lang_key].append(str(label))

                # Check for multiple different labels per language within this predicate
                for lang, label_values in labels_by_lang.items():
                    unique_values = list(set(label_values))
                    if len(unique_values) > 1:
                        lang_str = lang or "no language tag"
                        issues.append(
                            LintResult(
                                issue_type=LintIssueType.ERROR.value,
                                rule_id="label-per-language",
                                message=(
                                    f"Multiple different {pred_name} values "
                                    f"for language '{lang_str}'"
                                ),
                                subject_iri=str(subject),
                                subject_type=self._determine_entity_type(graph, subject),
                                details={
                                    "local_name": self._get_local_name(subject),
                                    "predicate": pred_name,
                                    "language": lang_str,
                                    "labels": unique_values,
                                },
                            )
                        )

        return issues

    async def _check_undefined_prefix(self, graph: Graph) -> list[LintResult]:
        """
        Find IRIs that use undefined prefixes.

        Adapted from skos-ttl-editor's prefixCheck.
        """
        issues = []

        # Get all defined namespace prefixes
        defined_prefixes = dict(graph.namespaces())
        defined_namespaces = {str(ns) for ns in defined_prefixes.values()}

        # Check all subjects, predicates, and objects
        checked_iris: set[str] = set()

        for s, p, o in graph:
            for term in [s, p, o]:
                if isinstance(term, URIRef):
                    iri = str(term)
                    if iri in checked_iris:
                        continue
                    checked_iris.add(iri)

                    # Check if IRI starts with any known namespace
                    has_known_prefix = any(iri.startswith(ns) for ns in defined_namespaces)

                    # If it looks like a prefixed name but doesn't resolve
                    if not has_known_prefix and ":" in iri and not iri.startswith("http"):
                        prefix = iri.split(":")[0]
                        issues.append(
                            LintResult(
                                issue_type=LintIssueType.ERROR.value,
                                rule_id="undefined-prefix",
                                message=f"Prefix '{prefix}' is not defined",
                                subject_iri=iri,
                                subject_type=self._determine_entity_type(graph, term),
                                details={
                                    "prefix": prefix,
                                    "iri": iri,
                                },
                            )
                        )

        return issues

    async def _check_duplicate_triple(self, graph: Graph) -> list[LintResult]:
        """
        Find duplicate predicate-object pairs for the same subject.

        Adapted from skos-ttl-editor's duplicateCheck.
        """
        issues = []

        # Group triples by subject
        # Use o.n3() to preserve language tags and datatypes in comparisons
        subject_triples: dict[str, list[tuple[str, str]]] = defaultdict(list)

        for s, p, o in graph:
            if isinstance(s, URIRef):
                po_key = (str(p), o.n3())
                subject_triples[str(s)].append(po_key)

        # Find duplicates within each subject
        for subject_iri, po_list in subject_triples.items():
            seen: dict[tuple[str, str], int] = defaultdict(int)
            for po in po_list:
                seen[po] += 1

            for po, count in seen.items():
                if count > 1:
                    issues.append(
                        LintResult(
                            issue_type=LintIssueType.INFO.value,
                            rule_id="duplicate-triple",
                            message=f"Duplicate triple: predicate-object pair appears {count} times",
                            subject_iri=subject_iri,
                            subject_type=self._determine_entity_type(graph, URIRef(subject_iri)),
                            details={
                                "predicate": po[0],
                                "object": po[1],
                                "count": count,
                            },
                        )
                    )

        return issues

    async def _check_domain_violation(self, graph: Graph) -> list[LintResult]:
        """Find property usages where subject is not in the declared domain."""
        issues = []

        # Build domain map for properties
        property_domains: dict[str, set[str]] = defaultdict(set)
        for prop in graph.subjects(RDF.type, OWL.ObjectProperty):
            if isinstance(prop, URIRef):
                for domain in graph.objects(prop, RDFS.domain):
                    if isinstance(domain, URIRef):
                        property_domains[str(prop)].add(str(domain))

        for prop in graph.subjects(RDF.type, OWL.DatatypeProperty):
            if isinstance(prop, URIRef):
                for domain in graph.objects(prop, RDFS.domain):
                    if isinstance(domain, URIRef):
                        property_domains[str(prop)].add(str(domain))

        # Check property usage
        for s, p, _o in graph:
            prop_str = str(p)
            if prop_str in property_domains and isinstance(s, URIRef):
                domains = property_domains[prop_str]

                # Get types of subject
                subject_types = {
                    str(t) for t in graph.objects(s, RDF.type) if isinstance(t, URIRef)
                }

                # Check if any subject type is in domain (or subclass of domain)
                valid_domain = False
                for subject_type in subject_types:
                    if subject_type in domains:
                        valid_domain = True
                        break
                    # Check superclasses
                    for superclass in graph.transitive_objects(
                        URIRef(subject_type), RDFS.subClassOf
                    ):
                        if str(superclass) in domains:
                            valid_domain = True
                            break
                    if valid_domain:
                        break

                if not valid_domain and subject_types:
                    issues.append(
                        LintResult(
                            issue_type=LintIssueType.WARNING.value,
                            rule_id="domain-violation",
                            message="Property used on subject not in declared domain",
                            subject_iri=str(s),
                            subject_type=self._determine_entity_type(graph, URIRef(str(s))),
                            details={
                                "property": prop_str,
                                "expected_domains": list(domains),
                                "actual_types": list(subject_types),
                            },
                        )
                    )

        return issues

    async def _check_range_violation(self, graph: Graph) -> list[LintResult]:
        """Find property usages where object is not in the declared range."""
        issues = []

        # Build range map for object properties
        property_ranges: dict[str, set[str]] = defaultdict(set)
        for prop in graph.subjects(RDF.type, OWL.ObjectProperty):
            if isinstance(prop, URIRef):
                for range_class in graph.objects(prop, RDFS.range):
                    if isinstance(range_class, URIRef):
                        property_ranges[str(prop)].add(str(range_class))

        # Check property usage
        for s, p, o in graph:
            prop_str = str(p)
            if prop_str in property_ranges and isinstance(o, URIRef):
                ranges = property_ranges[prop_str]

                # Get types of object
                object_types = {str(t) for t in graph.objects(o, RDF.type) if isinstance(t, URIRef)}

                # Check if any object type is in range (or subclass of range)
                valid_range = False
                for object_type in object_types:
                    if object_type in ranges:
                        valid_range = True
                        break
                    # Check superclasses
                    for superclass in graph.transitive_objects(
                        URIRef(object_type), RDFS.subClassOf
                    ):
                        if str(superclass) in ranges:
                            valid_range = True
                            break
                    if valid_range:
                        break

                if not valid_range and object_types:
                    issues.append(
                        LintResult(
                            issue_type=LintIssueType.WARNING.value,
                            rule_id="range-violation",
                            message="Property value not in declared range",
                            subject_iri=str(s),
                            subject_type=self._determine_entity_type(graph, URIRef(str(s))),
                            details={
                                "property": prop_str,
                                "object": str(o),
                                "expected_ranges": list(ranges),
                                "actual_types": list(object_types),
                            },
                        )
                    )

        return issues

    async def _check_cardinality_violation(self, graph: Graph) -> list[LintResult]:
        """Find cardinality constraint violations."""
        issues = []

        # Find cardinality restrictions
        for restriction in graph.subjects(RDF.type, OWL.Restriction):
            on_property = None
            max_cardinality = None
            min_cardinality = None
            exact_cardinality = None

            for prop in graph.objects(restriction, OWL.onProperty):
                on_property = prop
                break

            for val in graph.objects(restriction, OWL.maxCardinality):
                with contextlib.suppress(ValueError, TypeError):
                    max_cardinality = int(str(val))

            for val in graph.objects(restriction, OWL.minCardinality):
                with contextlib.suppress(ValueError, TypeError):
                    min_cardinality = int(str(val))

            for val in graph.objects(restriction, OWL.cardinality):
                with contextlib.suppress(ValueError, TypeError):
                    exact_cardinality = int(str(val))

            if on_property is None:
                continue

            # Find classes with this restriction
            for cls in graph.subjects(RDFS.subClassOf, restriction):
                if not isinstance(cls, URIRef):
                    continue

                # Find instances of this class
                for instance in graph.subjects(RDF.type, cls):
                    if not isinstance(instance, URIRef):
                        continue

                    # Count property values
                    value_count = sum(1 for _ in graph.objects(instance, on_property))

                    # Check constraints
                    if exact_cardinality is not None and value_count != exact_cardinality:
                        issues.append(
                            LintResult(
                                issue_type=LintIssueType.ERROR.value,
                                rule_id="cardinality-violation",
                                message=f"Cardinality violation: expected exactly {exact_cardinality}, found {value_count}",
                                subject_iri=str(instance),
                                subject_type="individual",
                                details={
                                    "property": str(on_property),
                                    "expected": exact_cardinality,
                                    "actual": value_count,
                                    "constraint_type": "exact",
                                },
                            )
                        )
                    elif max_cardinality is not None and value_count > max_cardinality:
                        issues.append(
                            LintResult(
                                issue_type=LintIssueType.ERROR.value,
                                rule_id="cardinality-violation",
                                message=f"Cardinality violation: max {max_cardinality}, found {value_count}",
                                subject_iri=str(instance),
                                subject_type="individual",
                                details={
                                    "property": str(on_property),
                                    "max": max_cardinality,
                                    "actual": value_count,
                                    "constraint_type": "max",
                                },
                            )
                        )
                    elif min_cardinality is not None and value_count < min_cardinality:
                        issues.append(
                            LintResult(
                                issue_type=LintIssueType.ERROR.value,
                                rule_id="cardinality-violation",
                                message=f"Cardinality violation: min {min_cardinality}, found {value_count}",
                                subject_iri=str(instance),
                                subject_type="individual",
                                details={
                                    "property": str(on_property),
                                    "min": min_cardinality,
                                    "actual": value_count,
                                    "constraint_type": "min",
                                },
                            )
                        )

        return issues

    async def _check_disjoint_violation(self, graph: Graph) -> list[LintResult]:
        """Find resources typed with classes declared as disjoint."""
        issues = []
        reported: set[str] = set()

        # Build disjoint pairs
        disjoint_pairs: set[frozenset[str]] = set()

        for s in graph.subjects(RDF.type, OWL.AllDisjointClasses):
            members = list(graph.objects(s, OWL.members))
            # Handle RDF collection
            for member_list in members:
                classes = list(graph.items(member_list))
                for i, c1 in enumerate(classes):
                    for c2 in classes[i + 1 :]:
                        if isinstance(c1, URIRef) and isinstance(c2, URIRef):
                            disjoint_pairs.add(frozenset([str(c1), str(c2)]))

        # Also check pairwise owl:disjointWith
        for c1 in graph.subjects(OWL.disjointWith, None):
            for c2 in graph.objects(c1, OWL.disjointWith):
                if isinstance(c1, URIRef) and isinstance(c2, URIRef):
                    disjoint_pairs.add(frozenset([str(c1), str(c2)]))

        # Check instances
        for instance in graph.subjects(RDF.type, None):
            if not isinstance(instance, URIRef):
                continue
            if str(instance) in reported:
                continue

            types = [str(t) for t in graph.objects(instance, RDF.type) if isinstance(t, URIRef)]

            # Check all pairs of types
            for i, t1 in enumerate(types):
                for t2 in types[i + 1 :]:
                    pair = frozenset([t1, t2])
                    if pair in disjoint_pairs:
                        reported.add(str(instance))
                        issues.append(
                            LintResult(
                                issue_type=LintIssueType.ERROR.value,
                                rule_id="disjoint-violation",
                                message="Resource is typed with disjoint classes",
                                subject_iri=str(instance),
                                subject_type="individual",
                                details={
                                    "class1": t1,
                                    "class2": t2,
                                    "all_types": types,
                                },
                            )
                        )
                        break
                else:
                    continue
                break

        return issues

    async def _check_inverse_property_inconsistency(self, graph: Graph) -> list[LintResult]:
        """Find inverse property relationships that are not symmetric."""
        issues = []
        reported: set[str] = set()

        # Build inverse property map
        inverse_map: dict[str, str] = {}
        for p1 in graph.subjects(OWL.inverseOf, None):
            for p2 in graph.objects(p1, OWL.inverseOf):
                if isinstance(p1, URIRef) and isinstance(p2, URIRef):
                    inverse_map[str(p1)] = str(p2)
                    inverse_map[str(p2)] = str(p1)

        # Check property usage
        for s, p, o in graph:
            if not isinstance(s, URIRef) or not isinstance(o, URIRef):
                continue

            prop_str = str(p)
            if prop_str in inverse_map:
                inverse_prop = inverse_map[prop_str]

                # Check if inverse relationship exists
                has_inverse = (o, URIRef(inverse_prop), s) in graph

                if not has_inverse:
                    key = f"{s}|{p}|{o}"
                    if key not in reported:
                        reported.add(key)
                        issues.append(
                            LintResult(
                                issue_type=LintIssueType.WARNING.value,
                                rule_id="inverse-property-inconsistency",
                                message="Missing inverse property assertion",
                                subject_iri=str(s),
                                subject_type="property",
                                details={
                                    "property": prop_str,
                                    "object": str(o),
                                    "inverse_property": inverse_prop,
                                    "expected_triple": f"{o} {inverse_prop} {s}",
                                },
                            )
                        )

        return issues

    async def _check_missing_english_label(self, graph: Graph) -> list[LintResult]:
        """
        Find resources with labels but none in English.

        Adapted from skos-ttl-editor's labelCheck warning.
        """
        issues = []

        for subject in self._uri_subjects:
            # Collect all labels
            all_labels = []
            has_english = False

            for label in graph.objects(subject, RDFS.label):
                if isinstance(label, RDFLiteral):
                    all_labels.append(label)
                    if label.language and label.language.lower().startswith("en"):
                        has_english = True

            for label in graph.objects(subject, SKOS.prefLabel):
                if isinstance(label, RDFLiteral):
                    all_labels.append(label)
                    if label.language and label.language.lower().startswith("en"):
                        has_english = True

            # Only warn if there are labels but none in English
            if all_labels and not has_english:
                languages = list({label.language or "none" for label in all_labels})
                issues.append(
                    LintResult(
                        issue_type=LintIssueType.WARNING.value,
                        rule_id="missing-english-label",
                        message=f"No English label defined (has labels in: {', '.join(languages)})",
                        subject_iri=str(subject),
                        subject_type=self._determine_entity_type(graph, subject),
                        details={
                            "local_name": self._get_local_name(subject),
                            "available_languages": languages,
                        },
                    )
                )

        return issues

    async def _check_missing_language_tag(self, graph: Graph) -> list[LintResult]:
        """
        Find label/annotation predicates with plain literals or xsd:string
        instead of language-tagged literals.
        """
        issues = []

        # Predicates that should typically have language tags
        lang_predicates = [
            (RDFS.label, "rdfs:label"),
            (RDFS.comment, "rdfs:comment"),
            (SKOS.prefLabel, "skos:prefLabel"),
            (SKOS.altLabel, "skos:altLabel"),
            (SKOS.hiddenLabel, "skos:hiddenLabel"),
            (SKOS.definition, "skos:definition"),
            (SKOS.note, "skos:note"),
            (SKOS.scopeNote, "skos:scopeNote"),
            (SKOS.historyNote, "skos:historyNote"),
            (SKOS.editorialNote, "skos:editorialNote"),
            (SKOS.changeNote, "skos:changeNote"),
            (SKOS.example, "skos:example"),
            (DC.title, "dc:title"),
            (DC.description, "dc:description"),
            (DCTERMS.title, "dcterms:title"),
            (DCTERMS.description, "dcterms:description"),
        ]

        for subject in self._uri_subjects:
            for predicate, pred_name in lang_predicates:
                for obj in graph.objects(subject, predicate):
                    if not isinstance(obj, RDFLiteral):
                        continue
                    # Flag if no language tag: plain literal or explicit xsd:string
                    if obj.language is None:
                        datatype_note = ""
                        if obj.datatype == XSD.string:
                            datatype_note = " (typed as xsd:string)"
                        issues.append(
                            LintResult(
                                issue_type=LintIssueType.WARNING.value,
                                rule_id="missing-language-tag",
                                message=(f"{pred_name} has no language tag{datatype_note}"),
                                subject_iri=str(subject),
                                subject_type=self._determine_entity_type(graph, subject),
                                details={
                                    "local_name": self._get_local_name(subject),
                                    "predicate": pred_name,
                                    "value": str(obj)[:100],
                                },
                            )
                        )

        return issues

    async def _check_redundant_regional_label(self, graph: Graph) -> list[LintResult]:
        """
        Find annotations where regional language variants have identical values.

        When e.g. @es-es and @es-mx carry the same text, the regional qualifier
        adds no value and the base tag (@es) should be used instead.
        """
        issues = []

        predicates = [
            (RDFS.label, "rdfs:label"),
            (RDFS.comment, "rdfs:comment"),
            (SKOS.prefLabel, "skos:prefLabel"),
            (SKOS.altLabel, "skos:altLabel"),
            (SKOS.hiddenLabel, "skos:hiddenLabel"),
            (SKOS.definition, "skos:definition"),
            (SKOS.note, "skos:note"),
            (SKOS.scopeNote, "skos:scopeNote"),
            (SKOS.historyNote, "skos:historyNote"),
            (SKOS.editorialNote, "skos:editorialNote"),
            (SKOS.changeNote, "skos:changeNote"),
            (SKOS.example, "skos:example"),
            (DC.title, "dc:title"),
            (DC.description, "dc:description"),
            (DCTERMS.title, "dcterms:title"),
            (DCTERMS.description, "dcterms:description"),
        ]

        for subject in self._uri_subjects:
            for predicate, pred_name in predicates:
                # Group literals by (base_language, value)
                regional_groups: dict[tuple[str, str], list[str]] = defaultdict(list)

                for obj in graph.objects(subject, predicate):
                    if not isinstance(obj, RDFLiteral) or obj.language is None:
                        continue
                    lang = obj.language.lower()
                    base_lang = lang.split("-")[0]
                    regional_groups[(base_lang, str(obj))].append(lang)

                for (base_lang, value), tags in regional_groups.items():
                    if len(tags) < 2:
                        continue
                    sorted_tags = sorted(tags)
                    tag_list = ", ".join(f"@{t}" for t in sorted_tags)
                    if base_lang in sorted_tags:
                        # Base tag already present — suggest removing regional variants
                        regional_only = [t for t in sorted_tags if t != base_lang]
                        drop_list = ", ".join(f"@{t}" for t in regional_only)
                        action = f"consider removing {drop_list}"
                    else:
                        action = f"consider using @{base_lang} instead"
                    issues.append(
                        LintResult(
                            issue_type=LintIssueType.INFO.value,
                            rule_id="redundant-regional-label",
                            message=(
                                f"Redundant regional variants: {pred_name} "
                                f'"{value[:80]}" has identical values for '
                                f"{tag_list} — {action}"
                            ),
                            subject_iri=str(subject),
                            subject_type=self._determine_entity_type(graph, subject),
                            details={
                                "local_name": self._get_local_name(subject),
                                "predicate": pred_name,
                                "value": value[:100],
                                "regional_tags": sorted_tags,
                                "base_language": base_lang,
                            },
                        )
                    )

        return issues

    async def _check_missing_type_declaration(self, graph: Graph) -> list[LintResult]:
        """
        Find resources that appear as subjects but have no rdf:type declaration.

        Only checks IRIs in the ontology's own namespace — external vocabulary
        terms (OWL, RDF, RDFS, XSD, SKOS, DC, etc.) are skipped.
        """
        issues: list[LintResult] = []

        # Determine the ontology's base namespace from the graph
        base_ns_candidates: set[str] = set()
        for s in graph.subjects(RDF.type, OWL.Ontology):
            if isinstance(s, URIRef):
                stripped = str(s).rstrip("/#")
                base_ns_candidates.add(stripped + "#")
                base_ns_candidates.add(stripped + "/")
                break

        base_ns = None
        if base_ns_candidates:
            # Pick the candidate that actually contains subjects
            for candidate in base_ns_candidates:
                if any(str(subj).startswith(candidate) for subj in self._uri_subjects):
                    base_ns = candidate
                    break
            # Fallback to first candidate if neither matches
            if not base_ns:
                base_ns = next(iter(base_ns_candidates))

        # Well-known vocabulary namespaces to skip
        skip_prefixes = {
            str(OWL),
            str(RDF),
            str(RDFS),
            str(XSD),
            str(SKOS),
            "http://purl.org/dc/elements/1.1/",
            "http://purl.org/dc/terms/",
            "http://www.w3.org/ns/prov#",
            "http://www.w3.org/2006/time#",
            "http://xmlns.com/foaf/0.1/",
        }

        # If no owl:Ontology found, infer from most common namespace
        if not base_ns:
            from collections import Counter

            ns_counts: Counter[str] = Counter()
            for s in self._uri_subjects:
                iri = str(s)
                if any(iri.startswith(p) for p in skip_prefixes):
                    continue
                if "#" in iri:
                    ns_counts[iri[: iri.rindex("#") + 1]] += 1
                elif "/" in iri:
                    ns_counts[iri[: iri.rindex("/") + 1]] += 1
            if ns_counts:
                base_ns = ns_counts.most_common(1)[0][0]

        if not base_ns:
            return issues

        for subject in self._uri_subjects:
            iri = str(subject)

            # Only check IRIs in the ontology's own namespace
            if not iri.startswith(base_ns):
                continue

            # Skip if it's a well-known vocabulary term
            if any(iri.startswith(prefix) for prefix in skip_prefixes):
                continue

            # Check for rdf:type
            types = list(graph.objects(subject, RDF.type))
            if not types:
                issues.append(
                    LintResult(
                        issue_type=LintIssueType.WARNING.value,
                        rule_id="missing-type-declaration",
                        message="Resource has no rdf:type declaration",
                        subject_iri=iri,
                        subject_type="other",
                        details={
                            "local_name": self._get_local_name(subject),
                        },
                    )
                )

        return issues

    @staticmethod
    def _determine_entity_type(graph: Graph, uri: URIRef) -> str:
        """Return 'class', 'property', 'individual', or 'other' for a URI."""
        types = set(graph.objects(uri, RDF.type))
        if OWL.Class in types or RDFS.Class in types:
            return "class"
        if any(
            t in types
            for t in (
                OWL.ObjectProperty,
                OWL.DatatypeProperty,
                OWL.AnnotationProperty,
                RDF.Property,
            )
        ):
            return "property"
        if types:
            return "individual"
        return "other"

    @staticmethod
    def _get_local_name(uri: URIRef) -> str:
        """Extract local name from IRI (after # or last /)."""
        iri = str(uri)
        if "#" in iri:
            return iri.split("#")[-1]
        return iri.rsplit("/", 1)[-1]

    @staticmethod
    def _get_label(graph: Graph, uri: URIRef) -> str | None:
        """Get the first rdfs:label for a URI."""
        for label in graph.objects(uri, RDFS.label):
            if isinstance(label, RDFLiteral):
                return str(label)
        return None


def get_linter(enabled_rules: AbstractSet[str] | None = None) -> OntologyLinter:
    """
    Get an ontology linter instance.

    Args:
        enabled_rules: Set of rule IDs to enable. If None, all rules are enabled.

    Returns:
        Configured OntologyLinter instance
    """
    if enabled_rules is None:
        return OntologyLinter()
    return OntologyLinter(enabled_rules=enabled_rules)


def get_available_rules() -> list[LintRuleInfo]:
    """Get list of all available lint rules."""
    return LINT_RULES.copy()
