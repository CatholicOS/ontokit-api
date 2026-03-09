"""Shared RDF utility functions for entity type detection and deprecation checks."""

from rdflib import Graph, URIRef
from rdflib.namespace import OWL, RDF, RDFS

_TYPE_CHECKS: list[tuple[URIRef, str]] = [
    (OWL.Class, "class"),
    (RDFS.Class, "class"),
    (OWL.ObjectProperty, "property"),
    (OWL.DatatypeProperty, "property"),
    (OWL.AnnotationProperty, "property"),
    (RDF.Property, "property"),
    (OWL.NamedIndividual, "individual"),
]


def get_entity_type(graph: Graph, uri: URIRef) -> str:
    """Determine the entity type of a URI (OWL and RDFS)."""
    for rdf_type, label in _TYPE_CHECKS:
        if (uri, RDF.type, rdf_type) in graph:
            return label
    return "unknown"


def is_deprecated(graph: Graph, uri: URIRef) -> bool:
    """Check if an entity has owl:deprecated set to true."""
    return any(str(obj).lower() in ("true", "1") for obj in graph.objects(uri, OWL.deprecated))
