"""Cross-reference service — find all entities that reference a target IRI."""

from rdflib import BNode, Graph, URIRef
from rdflib import Literal as RDFLiteral
from rdflib.namespace import OWL, RDF, RDFS

from ontokit.schemas.quality import (
    CONTEXT_LABELS,
    CrossReference,
    CrossReferenceGroup,
    CrossReferencesResponse,
    ReferenceContext,
)

# Map predicates to reference contexts
_PREDICATE_CONTEXT: dict[URIRef, ReferenceContext] = {
    RDFS.subClassOf: "parent_iris",
    RDFS.domain: "domain_iris",
    RDFS.range: "range_iris",
    RDF.type: "type_iris",
    OWL.equivalentClass: "equivalent_iris",
    OWL.disjointWith: "disjoint_iris",
    OWL.someValuesFrom: "some_values_from",
    RDFS.seeAlso: "see_also",
    OWL.inverseOf: "inverse_of",
}

# Entity type detection in order of precedence
_TYPE_CHECKS: list[tuple[URIRef, str]] = [
    (OWL.Class, "class"),
    (OWL.ObjectProperty, "property"),
    (OWL.DatatypeProperty, "property"),
    (OWL.AnnotationProperty, "property"),
    (OWL.NamedIndividual, "individual"),
]


def _resolve_entity_type(graph: Graph, subject: URIRef) -> str:
    """Determine the entity type of a subject."""
    for rdf_type, label in _TYPE_CHECKS:
        if (subject, RDF.type, rdf_type) in graph:
            return label
    return "unknown"


def _resolve_label(graph: Graph, subject: URIRef) -> str | None:
    """Get first rdfs:label for a subject."""
    for obj in graph.objects(subject, RDFS.label):
        if isinstance(obj, RDFLiteral):
            return str(obj)
    return None


def _resolve_bnode_owners(graph: Graph, bnode: BNode) -> list[URIRef]:
    """Walk up from a blank node to find the named entities that own it."""
    owners: list[URIRef] = []
    visited: set[BNode] = set()
    stack = [bnode]
    while stack:
        node = stack.pop()
        if node in visited:
            continue
        visited.add(node)
        for owner in graph.subjects(None, node):
            if isinstance(owner, URIRef):
                owners.append(owner)
            elif isinstance(owner, BNode):
                stack.append(owner)
    return owners


def get_cross_references(graph: Graph, target_iri: str) -> CrossReferencesResponse:
    """Find all entities that reference the target IRI and group by context."""
    target = URIRef(target_iri)

    # Collect unique references grouped by context (one per source IRI per context)
    refs_by_context: dict[ReferenceContext, dict[str, CrossReference]] = {}

    for s, p, _o in graph.triples((None, None, target)):
        # Resolve the referencing subjects to named entities (URIRefs).
        # Blank-node subjects (e.g. OWL restrictions) are traced back to
        # the named entities that own them.
        if isinstance(s, URIRef):
            source_iris = [s]
        elif isinstance(s, BNode):
            source_iris = _resolve_bnode_owners(graph, s)
            if not source_iris:
                continue
        else:
            continue

        # Determine context from predicate
        context = _PREDICATE_CONTEXT.get(p)
        if context is None:
            # Only classify as annotation_value if the predicate is declared
            # as an owl:AnnotationProperty in the graph; skip other unknown
            # structural predicates to avoid misclassification.
            if isinstance(p, URIRef) and (p, RDF.type, OWL.AnnotationProperty) in graph:
                context = "annotation_value"
            else:
                continue

        seen = refs_by_context.setdefault(context, {})
        for source in source_iris:
            source_str = str(source)
            if source_str in seen:
                continue
            seen[source_str] = CrossReference(
                source_iri=source_str,
                source_type=_resolve_entity_type(graph, source),
                source_label=_resolve_label(graph, source),
                reference_context=context,
            )

    # Build groups
    groups = []
    total = 0
    for context, refs_dict in refs_by_context.items():
        refs = list(refs_dict.values())
        groups.append(
            CrossReferenceGroup(
                context=context,
                context_label=CONTEXT_LABELS.get(context, context),
                references=refs,
            )
        )
        total += len(refs)

    return CrossReferencesResponse(
        target_iri=target_iri,
        total=total,
        groups=groups,
    )
