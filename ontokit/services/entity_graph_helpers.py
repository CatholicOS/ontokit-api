"""Helpers for entity-graph BFS — extracted from `OntologyService.build_entity_graph`.

These functions live at module scope so they can be unit-tested directly without
constructing an `OntologyService` and a loaded ontology graph.
"""

from __future__ import annotations

from rdflib import Graph, URIRef
from rdflib.namespace import OWL, RDF, RDFS


def get_see_also_targets(graph: Graph, uri: URIRef) -> list[URIRef]:
    """Extract seeAlso targets from both direct triples and OWL restrictions.

    FOLIO encodes seeAlso as ``owl:Restriction`` with ``owl:someValuesFrom``
    inside ``rdfs:subClassOf``, not as direct ``rdfs:seeAlso`` triples — both
    forms are returned, deduplicated, in discovery order.
    """
    seen: set[URIRef] = set()
    targets: list[URIRef] = []

    def _add(ref: URIRef) -> None:
        if ref not in seen:
            seen.add(ref)
            targets.append(ref)

    # Direct rdfs:seeAlso triples
    for obj in graph.objects(uri, RDFS.seeAlso):
        if isinstance(obj, URIRef):
            _add(obj)

    # OWL restrictions: subClassOf -> Restriction(onProperty=seeAlso, someValuesFrom=X)
    for sc in graph.objects(uri, RDFS.subClassOf):
        if isinstance(sc, URIRef):
            continue  # Named superclass, not a restriction
        # sc is a blank node (restriction)
        on_prop = next(graph.objects(sc, OWL.onProperty), None)
        if on_prop == RDFS.seeAlso:
            for predicate in (OWL.someValuesFrom, OWL.allValuesFrom, OWL.hasValue):
                for val in graph.objects(sc, predicate):
                    if isinstance(val, URIRef):
                        _add(val)

    return targets


def get_see_also_referrers(graph: Graph, uri: URIRef) -> list[URIRef]:
    """Find classes that reference ``uri`` via seeAlso (direct or restriction).

    Reverse of :func:`get_see_also_targets`. Only returns classes (subjects with
    ``rdf:type owl:Class``) so callers don't surface arbitrary blank nodes.
    """
    seen: set[URIRef] = set()
    referrers: list[URIRef] = []

    def _add(ref: URIRef) -> None:
        if ref not in seen:
            seen.add(ref)
            referrers.append(ref)

    # Direct reverse rdfs:seeAlso
    for subj in graph.subjects(RDFS.seeAlso, uri):
        if isinstance(subj, URIRef):
            _add(subj)

    # Find restrictions that reference uri via someValuesFrom/allValuesFrom/hasValue
    for predicate in (OWL.someValuesFrom, OWL.allValuesFrom, OWL.hasValue):
        for restriction in graph.subjects(predicate, uri):
            on_prop = next(graph.objects(restriction, OWL.onProperty), None)
            if on_prop == RDFS.seeAlso:
                for cls in graph.subjects(RDFS.subClassOf, restriction):
                    if isinstance(cls, URIRef) and (cls, RDF.type, OWL.Class) in graph:
                        _add(cls)

    return referrers
