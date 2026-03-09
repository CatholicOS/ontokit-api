"""Duplicate detection service — find entities with similar labels."""

import difflib
from collections import defaultdict
from datetime import UTC, datetime

from rdflib import Graph, URIRef
from rdflib import Literal as RDFLiteral
from rdflib.namespace import OWL, RDF, RDFS

from ontokit.schemas.quality import DuplicateCluster, DuplicateDetectionResult, DuplicateEntity
from ontokit.services.rdf_utils import get_entity_type as _get_entity_type


def _extract_entities(graph: Graph) -> list[tuple[str, str, str]]:
    """Extract (iri, label, entity_type) for all labelled entities."""
    entities = []
    for s in graph.subjects(RDF.type, None):
        if not isinstance(s, URIRef) or s == OWL.Thing:
            continue
        etype = _get_entity_type(graph, s)
        if etype == "unknown":
            continue
        for obj in graph.objects(s, RDFS.label):
            if isinstance(obj, RDFLiteral):
                entities.append((str(s), str(obj), etype))
                break  # Use first label
    return entities


def find_duplicates(graph: Graph, threshold: float = 0.85) -> DuplicateDetectionResult:
    """Find entities with similar labels using string similarity."""
    entities = _extract_entities(graph)

    # Group by entity type for comparison (only compare within same type)
    by_type: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for iri, label, etype in entities:
        by_type[etype].append((iri, label))

    # Union-find for clustering
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])
            x = parent[x]
        return x

    def union(x: str, y: str) -> None:
        px, py = find(x), find(y)
        if px != py:
            parent[px] = py

    # Track pairwise similarities
    pair_sim: dict[tuple[str, str], float] = {}

    for _etype, etype_entities in by_type.items():
        n = len(etype_entities)
        for i in range(n):
            iri_a, label_a = etype_entities[i]
            norm_a = label_a.lower().strip()
            for j in range(i + 1, n):
                iri_b, label_b = etype_entities[j]
                norm_b = label_b.lower().strip()
                sim = difflib.SequenceMatcher(None, norm_a, norm_b).ratio()
                pair_sim[(iri_a, iri_b)] = sim
                if sim >= threshold:
                    union(iri_a, iri_b)

    # Build clusters
    clusters_map: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    entity_lookup = {iri: (label, etype) for iri, label, etype in entities}
    for iri, (label, etype) in entity_lookup.items():
        root = find(iri)
        clusters_map[root].append((iri, label, etype))

    # Build response clusters
    clusters = []
    for _root, members in clusters_map.items():
        if len(members) < 2:
            continue
        # Average similarity between all pairs in cluster
        sims = []
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                key = (members[i][0], members[j][0])
                rev_key = (members[j][0], members[i][0])
                if key in pair_sim:
                    sim = pair_sim[key]
                elif rev_key in pair_sim:
                    sim = pair_sim[rev_key]
                else:
                    continue
                if sim is not None:
                    sims.append(sim)
        avg_sim = sum(sims) / len(sims) if sims else threshold

        clusters.append(
            DuplicateCluster(
                entities=[
                    DuplicateEntity(iri=iri, label=label, entity_type=etype)
                    for iri, label, etype in members
                ],
                similarity=round(avg_sim, 3),
            )
        )

    return DuplicateDetectionResult(
        clusters=clusters,
        threshold=threshold,
        checked_at=datetime.now(UTC).isoformat(),
    )
