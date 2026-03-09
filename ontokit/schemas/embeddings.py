"""Pydantic schemas for embedding management and semantic search."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

EmbeddingProvider = Literal["local", "openai", "voyage"]


class EmbeddingConfig(BaseModel):
    provider: EmbeddingProvider
    model_name: str
    api_key_set: bool
    dimensions: int
    auto_embed_on_save: bool
    last_full_embed_at: str | None = None


class EmbeddingConfigUpdate(BaseModel):
    provider: EmbeddingProvider | None = None
    model_name: str | None = None
    api_key: str | None = None  # write-only
    auto_embed_on_save: bool | None = None


class EmbeddingStatus(BaseModel):
    total_entities: int
    embedded_entities: int
    coverage_percent: float
    provider: str
    model_name: str
    job_in_progress: bool
    job_progress_percent: float | None = None
    last_full_embed_at: str | None = None


class EmbeddingGenerateResponse(BaseModel):
    job_id: str


class SemanticSearchResult(BaseModel):
    iri: str
    label: str
    entity_type: str
    score: float
    deprecated: bool = False


class SemanticSearchResponse(BaseModel):
    results: list[SemanticSearchResult]
    search_mode: Literal["semantic", "hybrid", "text_fallback"]


class SimilarEntity(BaseModel):
    iri: str
    label: str
    entity_type: str
    score: float
    deprecated: bool = False


class RankSuggestionRequest(BaseModel):
    context_iri: str
    candidates: list[str]
    relationship: Literal["parent", "equivalent", "domain", "range"]
    branch: str | None = None


class RankedCandidate(BaseModel):
    iri: str
    label: str
    score: float
