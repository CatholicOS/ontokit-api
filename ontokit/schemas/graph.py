"""Pydantic models for the Entity Graph API."""

from __future__ import annotations

from pydantic import BaseModel


class GraphNode(BaseModel):
    """A node in the entity graph."""

    id: str
    label: str
    iri: str
    definition: str | None = None
    is_focus: bool = False
    is_root: bool = False
    depth: int = 0
    node_type: str = "class"
    child_count: int | None = None


class GraphEdge(BaseModel):
    """An edge in the entity graph."""

    id: str
    source: str
    target: str
    edge_type: str
    label: str | None = None


class EntityGraphResponse(BaseModel):
    """Complete graph response."""

    focus_iri: str
    focus_label: str
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    truncated: bool = False
    total_concept_count: int = 0
