"""Search-related schemas."""

from typing import Literal

from pydantic import BaseModel, Field


class SearchQuery(BaseModel):
    """Search query parameters."""

    query: str = Field(..., min_length=1)
    ontology_ids: list[str] | None = None
    entity_types: list[str] | None = None
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class SearchResult(BaseModel):
    """A single search result."""

    iri: str
    entity_type: Literal["class", "property", "individual"]
    label: str | None = None
    description: str | None = None
    ontology_id: str
    ontology_title: str
    score: float = 1.0


class SearchResponse(BaseModel):
    """Search response with results."""

    results: list[SearchResult]
    total: int
    query: str
    took_ms: float


class SPARQLQuery(BaseModel):
    """SPARQL query request."""

    query: str = Field(..., min_length=1)
    ontology_id: str | None = None
    default_graph: str | None = None
    timeout: int = Field(default=30, ge=1, le=300)


class SPARQLBinding(BaseModel):
    """A single SPARQL binding."""

    type: str
    value: str
    datatype: str | None = None
    lang: str | None = None


class SPARQLResponse(BaseModel):
    """SPARQL query response."""

    query_type: Literal["SELECT", "ASK", "CONSTRUCT"]
    variables: list[str] | None = None
    bindings: list[dict[str, SPARQLBinding]] | None = None
    boolean: bool | None = None
    graph: str | None = None  # For CONSTRUCT, serialized graph
    took_ms: float
