"""Pydantic models for the Entity Graph API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

# Node type values produced by the BFS in `OntologyService.build_entity_graph`.
# Frontend mirror: `GraphNodeType` in `lib/graph/types.ts`.
GraphNodeType = Literal[
    "focus",
    "root",
    "secondary_root",
    "class",
    "individual",
    "property",
    "external",
]

# Edge type values produced by the BFS. Frontend mirror: `GraphEdgeType`.
GraphEdgeType = Literal[
    "subClassOf",
    "equivalentClass",
    "disjointWith",
    "seeAlso",
]


class GraphNode(BaseModel):
    """A node in the entity graph."""

    id: str
    label: str
    iri: str
    definition: str | None = None
    is_focus: bool = False
    is_root: bool = False
    depth: int = 0
    node_type: GraphNodeType = "class"
    child_count: int | None = None


class GraphEdge(BaseModel):
    """An edge in the entity graph."""

    id: str
    source: str
    target: str
    edge_type: GraphEdgeType
    label: str | None = None


class EntityGraphResponse(BaseModel):
    """Complete graph response."""

    focus_iri: str
    focus_label: str
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    truncated: bool = False
    total_concept_count: int = 0
