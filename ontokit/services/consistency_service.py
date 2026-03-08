"""Consistency checking service — 12 rules for ontology quality."""

import time
from datetime import UTC, datetime

from rdflib import Graph, URIRef
from rdflib import Literal as RDFLiteral
from rdflib.namespace import DCTERMS, OWL, RDF, RDFS, SKOS, XSD

from ontokit.schemas.quality import ConsistencyCheckResult, ConsistencyIssue

# Entity type detection helpers
_CLASS_TYPES = {OWL.Class}
_PROPERTY_TYPES = {OWL.ObjectProperty, OWL.DatatypeProperty, OWL.AnnotationProperty}
_INDIVIDUAL_TYPES = {OWL.NamedIndividual}


def _get_entity_type(graph: Graph, uri: URIRef) -> str:
    for t in graph.objects(uri, RDF.type):
        if t in _CLASS_TYPES:
            return "class"
        if t in _PROPERTY_TYPES:
            return "property"
        if t in _INDIVIDUAL_TYPES:
            return "individual"
    return "unknown"


def _has_label(graph: Graph, uri: URIRef) -> bool:
    return any(isinstance(o, RDFLiteral) for o in graph.objects(uri, RDFS.label))


def _has_comment(graph: Graph, uri: URIRef) -> bool:
    return any(isinstance(o, RDFLiteral) for o in graph.objects(uri, RDFS.comment))


def _all_declared_uris(graph: Graph) -> set[URIRef]:
    """Get all URIs that appear as subjects of rdf:type triples."""
    return {s for s in graph.subjects(RDF.type, None) if isinstance(s, URIRef)}


def _is_deprecated(graph: Graph, uri: URIRef) -> bool:
    for obj in graph.objects(uri, OWL.deprecated):
        if str(obj).lower() in ("true", "1"):
            return True
    return False


def _check_orphan_class(graph: Graph) -> list[ConsistencyIssue]:
    """Class with no parent (except owl:Thing), no children, no instances."""
    issues = []
    owl_thing = OWL.Thing
    for cls in graph.subjects(RDF.type, OWL.Class):
        if not isinstance(cls, URIRef) or cls == owl_thing:
            continue
        parents = [p for p in graph.objects(cls, RDFS.subClassOf) if isinstance(p, URIRef) and p != owl_thing]
        children = list(graph.subjects(RDFS.subClassOf, cls))
        instances = list(graph.subjects(RDF.type, cls))
        if not parents and not children and not instances:
            issues.append(ConsistencyIssue(
                rule_id="orphan_class",
                severity="warning",
                entity_iri=str(cls),
                entity_type="class",
                message="Orphan class: no parent, no children, no instances",
            ))
    return issues


def _check_cycle_detect(graph: Graph) -> list[ConsistencyIssue]:
    """Detect cycles in rdfs:subClassOf chains."""
    issues = []
    reported: set[str] = set()

    for cls in graph.subjects(RDF.type, OWL.Class):
        if not isinstance(cls, URIRef):
            continue
        visited: set[URIRef] = set()
        current = cls
        while True:
            if current in visited:
                iri = str(cls)
                if iri not in reported:
                    issues.append(ConsistencyIssue(
                        rule_id="cycle_detect",
                        severity="error",
                        entity_iri=iri,
                        entity_type="class",
                        message="Cycle detected in subClassOf hierarchy",
                    ))
                    reported.add(iri)
                break
            visited.add(current)
            parents = [p for p in graph.objects(current, RDFS.subClassOf) if isinstance(p, URIRef)]
            if not parents:
                break
            current = parents[0]
    return issues


def _check_unused_property(graph: Graph) -> list[ConsistencyIssue]:
    """Property not used as predicate in any triple (excluding own declaration)."""
    issues = []
    for prop_type in _PROPERTY_TYPES:
        for prop in graph.subjects(RDF.type, prop_type):
            if not isinstance(prop, URIRef):
                continue
            # Check if this property is used as a predicate anywhere
            used = any(
                s != prop
                for s in graph.subjects(prop, None)
            )
            if not used:
                issues.append(ConsistencyIssue(
                    rule_id="unused_property",
                    severity="warning",
                    entity_iri=str(prop),
                    entity_type="property",
                    message="Property is declared but never used as a predicate",
                ))
    return issues


def _check_missing_label(graph: Graph) -> list[ConsistencyIssue]:
    """Entity with no rdfs:label."""
    issues = []
    declared = _all_declared_uris(graph)
    for uri in declared:
        if uri == OWL.Thing:
            continue
        etype = _get_entity_type(graph, uri)
        if etype == "unknown":
            continue
        if not _has_label(graph, uri):
            issues.append(ConsistencyIssue(
                rule_id="missing_label",
                severity="warning",
                entity_iri=str(uri),
                entity_type=etype,
                message="Entity has no rdfs:label",
            ))
    return issues


def _check_missing_comment(graph: Graph) -> list[ConsistencyIssue]:
    """Entity with no rdfs:comment."""
    issues = []
    declared = _all_declared_uris(graph)
    for uri in declared:
        if uri == OWL.Thing:
            continue
        etype = _get_entity_type(graph, uri)
        if etype == "unknown":
            continue
        if not _has_comment(graph, uri):
            issues.append(ConsistencyIssue(
                rule_id="missing_comment",
                severity="info",
                entity_iri=str(uri),
                entity_type=etype,
                message="Entity has no rdfs:comment",
            ))
    return issues


def _check_orphan_individual(graph: Graph) -> list[ConsistencyIssue]:
    """Individual whose rdf:type class is not declared as owl:Class."""
    issues = []
    declared_classes = {s for s in graph.subjects(RDF.type, OWL.Class) if isinstance(s, URIRef)}
    for ind in graph.subjects(RDF.type, OWL.NamedIndividual):
        if not isinstance(ind, URIRef):
            continue
        types = [t for t in graph.objects(ind, RDF.type) if isinstance(t, URIRef) and t != OWL.NamedIndividual]
        for t in types:
            if t not in declared_classes:
                issues.append(ConsistencyIssue(
                    rule_id="orphan_individual",
                    severity="warning",
                    entity_iri=str(ind),
                    entity_type="individual",
                    message=f"Individual's type {t} is not declared as owl:Class",
                    details={"undeclared_type": str(t)},
                ))
    return issues


def _check_empty_domain(graph: Graph) -> list[ConsistencyIssue]:
    """ObjectProperty or DatatypeProperty with no rdfs:domain."""
    issues = []
    for prop_type in (OWL.ObjectProperty, OWL.DatatypeProperty):
        for prop in graph.subjects(RDF.type, prop_type):
            if not isinstance(prop, URIRef):
                continue
            domains = list(graph.objects(prop, RDFS.domain))
            if not domains:
                issues.append(ConsistencyIssue(
                    rule_id="empty_domain",
                    severity="info",
                    entity_iri=str(prop),
                    entity_type="property",
                    message="Property has no rdfs:domain",
                ))
    return issues


def _check_empty_range(graph: Graph) -> list[ConsistencyIssue]:
    """ObjectProperty or DatatypeProperty with no rdfs:range."""
    issues = []
    for prop_type in (OWL.ObjectProperty, OWL.DatatypeProperty):
        for prop in graph.subjects(RDF.type, prop_type):
            if not isinstance(prop, URIRef):
                continue
            ranges = list(graph.objects(prop, RDFS.range))
            if not ranges:
                issues.append(ConsistencyIssue(
                    rule_id="empty_range",
                    severity="info",
                    entity_iri=str(prop),
                    entity_type="property",
                    message="Property has no rdfs:range",
                ))
    return issues


def _check_duplicate_label(graph: Graph) -> list[ConsistencyIssue]:
    """Two+ same-type entities sharing exact same rdfs:label value+lang."""
    issues = []
    # Map (entity_type, label_value, lang) -> list of IRIs
    label_map: dict[tuple[str, str, str | None], list[str]] = {}

    declared = _all_declared_uris(graph)
    for uri in declared:
        if uri == OWL.Thing:
            continue
        etype = _get_entity_type(graph, uri)
        if etype == "unknown":
            continue
        for obj in graph.objects(uri, RDFS.label):
            if isinstance(obj, RDFLiteral):
                key = (etype, str(obj), obj.language)
                label_map.setdefault(key, []).append(str(uri))

    reported: set[str] = set()
    for (etype, label_val, lang), iris in label_map.items():
        if len(iris) < 2:
            continue
        for iri in iris:
            if iri in reported:
                continue
            reported.add(iri)
            lang_str = f"@{lang}" if lang else ""
            issues.append(ConsistencyIssue(
                rule_id="duplicate_label",
                severity="warning",
                entity_iri=iri,
                entity_type=etype,
                message=f'Duplicate label "{label_val}"{lang_str} shared with {len(iris) - 1} other {etype}(s)',
                details={"duplicates": [i for i in iris if i != iri]},
            ))
    return issues


def _check_deprecated_parent(graph: Graph) -> list[ConsistencyIssue]:
    """Class whose rdfs:subClassOf target has owl:deprecated=true."""
    issues = []
    for cls in graph.subjects(RDF.type, OWL.Class):
        if not isinstance(cls, URIRef):
            continue
        for parent in graph.objects(cls, RDFS.subClassOf):
            if isinstance(parent, URIRef) and _is_deprecated(graph, parent):
                issues.append(ConsistencyIssue(
                    rule_id="deprecated_parent",
                    severity="warning",
                    entity_iri=str(cls),
                    entity_type="class",
                    message=f"Parent class {parent} is deprecated",
                    details={"deprecated_parent": str(parent)},
                ))
    return issues


def _check_dangling_ref(graph: Graph) -> list[ConsistencyIssue]:
    """rdfs:subClassOf, rdfs:domain, rdfs:range pointing to URI not declared in ontology."""
    issues = []
    declared = _all_declared_uris(graph)
    # Also consider URIs that appear as subjects of any triple
    all_subjects = {s for s in graph.subjects(None, None) if isinstance(s, URIRef)}
    known = declared | all_subjects

    # Collect namespace prefixes from the graph and standard vocabularies
    # so that external/imported vocabulary terms are not flagged as dangling.
    well_known_ns = {
        str(RDF), str(RDFS), str(OWL), str(XSD), str(SKOS), str(DCTERMS),
    }
    graph_ns = {str(uri) for _prefix, uri in graph.namespace_manager.namespaces()}
    external_ns = well_known_ns | graph_ns

    predicates = [RDFS.subClassOf, RDFS.domain, RDFS.range]
    reported: set[tuple[str, str]] = set()

    for pred in predicates:
        for s, _p, o in graph.triples((None, pred, None)):
            if not isinstance(o, URIRef):
                continue
            if o == OWL.Thing:
                continue
            if o in known:
                continue
            # Skip URIs whose namespace matches a registered or well-known vocab
            o_str = str(o)
            if any(o_str.startswith(ns) for ns in external_ns):
                continue
            key = (str(s), str(o))
            if key in reported:
                continue
            reported.add(key)
            if isinstance(s, URIRef):
                issues.append(ConsistencyIssue(
                    rule_id="dangling_ref",
                    severity="error",
                    entity_iri=str(s),
                    entity_type=_get_entity_type(graph, s) if isinstance(s, URIRef) else "unknown",
                    message=f"References undeclared entity {o}",
                    details={"predicate": str(pred), "dangling_target": str(o)},
                ))
    return issues


def _check_multi_root(graph: Graph) -> list[ConsistencyIssue]:
    """More than 5 root classes (classes with no parent except owl:Thing)."""
    owl_thing = OWL.Thing
    root_iris: list[str] = []
    for cls in graph.subjects(RDF.type, OWL.Class):
        if not isinstance(cls, URIRef) or cls == owl_thing:
            continue
        parents = [p for p in graph.objects(cls, RDFS.subClassOf) if isinstance(p, URIRef) and p != owl_thing]
        if not parents:
            root_iris.append(str(cls))

    if len(root_iris) > 5:
        return [ConsistencyIssue(
            rule_id="multi_root",
            severity="info",
            entity_iri="",
            entity_type="ontology",
            message=f"Ontology has {len(root_iris)} root classes (classes with no parent)",
            details={"root_count": len(root_iris), "root_iris": root_iris[:20]},
        )]
    return []


# All check functions
_ALL_CHECKS = [
    _check_orphan_class,
    _check_cycle_detect,
    _check_unused_property,
    _check_missing_label,
    _check_missing_comment,
    _check_orphan_individual,
    _check_empty_domain,
    _check_empty_range,
    _check_duplicate_label,
    _check_deprecated_parent,
    _check_dangling_ref,
    _check_multi_root,
]


def run_consistency_check(graph: Graph, project_id: str, branch: str) -> ConsistencyCheckResult:
    """Run all 12 consistency rules against the graph."""
    start = time.monotonic()
    issues: list[ConsistencyIssue] = []

    for check_fn in _ALL_CHECKS:
        issues.extend(check_fn(graph))

    duration_ms = (time.monotonic() - start) * 1000

    return ConsistencyCheckResult(
        project_id=project_id,
        branch=branch,
        issues=issues,
        checked_at=datetime.now(UTC).isoformat(),
        duration_ms=round(duration_ms, 2),
    )
