"""Build embeddable text from entity RDF triples."""

from rdflib import Graph, URIRef
from rdflib import Literal as RDFLiteral
from rdflib.namespace import OWL, RDFS, SKOS


def build_embedding_text(graph: Graph, entity_uri: URIRef, entity_type: str) -> str:
    """Build a text representation of an entity for embedding.

    Format: "{type}: {label}. {comment}. Parents: {parents}. Also known as: {alt_labels}"
    """
    parts: list[str] = []

    # Primary label
    labels = [str(o) for o in graph.objects(entity_uri, RDFS.label) if isinstance(o, RDFLiteral)]
    primary_label = labels[0] if labels else _local_name(str(entity_uri))
    parts.append(f"{entity_type}: {primary_label}")

    # Comments/definitions
    comments = [
        str(o) for o in graph.objects(entity_uri, RDFS.comment) if isinstance(o, RDFLiteral)
    ]
    definitions = [
        str(o) for o in graph.objects(entity_uri, SKOS.definition) if isinstance(o, RDFLiteral)
    ]
    desc = comments or definitions
    if desc:
        parts.append(desc[0])

    # Parents (use subPropertyOf for properties, subClassOf for classes)
    parent_pred = RDFS.subPropertyOf if entity_type == "property" else RDFS.subClassOf
    parent_labels = []
    for p in graph.objects(entity_uri, parent_pred):
        if isinstance(p, URIRef) and p != OWL.Thing:
            plabel = next(
                (str(o) for o in graph.objects(p, RDFS.label) if isinstance(o, RDFLiteral)),
                _local_name(str(p)),
            )
            parent_labels.append(plabel)
    if parent_labels:
        parts.append(f"Parents: {', '.join(parent_labels)}")

    # Alternative labels
    alt_labels = [
        str(o) for o in graph.objects(entity_uri, SKOS.altLabel) if isinstance(o, RDFLiteral)
    ]
    extra_labels = [lbl for lbl in labels[1:] if lbl != primary_label]
    all_alt = alt_labels + extra_labels
    if all_alt:
        parts.append(f"Also known as: {', '.join(all_alt)}")

    return ". ".join(parts)


def _local_name(iri: str) -> str:
    """Extract local name from IRI."""
    if "#" in iri:
        return iri.split("#")[-1]
    return iri.rsplit("/", 1)[-1]
