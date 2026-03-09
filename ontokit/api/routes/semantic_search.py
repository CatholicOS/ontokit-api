"""Semantic search and similarity API endpoints."""

import logging
from typing import Annotated
from urllib.parse import unquote
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ontokit.core.auth import CurrentUser, OptionalUser, RequiredUser
from ontokit.core.database import get_db
from ontokit.schemas.embeddings import (
    RankedCandidate,
    RankSuggestionRequest,
    SemanticSearchResponse,
    SimilarEntity,
)
from ontokit.services.embedding_service import EmbeddingService
from ontokit.services.project_service import get_project_service

logger = logging.getLogger(__name__)

router = APIRouter()


async def _verify_access(project_id: UUID, db: AsyncSession, user: CurrentUser | None) -> None:
    from fastapi import HTTPException

    service = get_project_service(db)
    try:
        await service.get(project_id, user)
    except HTTPException:
        raise


@router.get(
    "/{project_id}/search/semantic",
    response_model=SemanticSearchResponse,
)
async def semantic_search(
    project_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: OptionalUser,
    q: str = Query(..., min_length=1, description="Search query"),
    branch: str = Query(default="main"),
    limit: int = Query(default=20, ge=1, le=100),
    threshold: float = Query(default=0.3, ge=0.0, le=1.0),
) -> SemanticSearchResponse:
    """Search entities using semantic similarity."""
    await _verify_access(project_id, db, user)
    service = EmbeddingService(db)
    return await service.semantic_search(project_id, branch, q, limit, threshold)


@router.get(
    "/{project_id}/entities/{iri:path}/similar",
    response_model=list[SimilarEntity],
)
async def find_similar_entities(
    project_id: UUID,
    iri: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: OptionalUser,
    branch: str = Query(default="main"),
    limit: int = Query(default=10, ge=1, le=50),
    threshold: float = Query(default=0.5, ge=0.0, le=1.0),
) -> list[SimilarEntity]:
    """Find entities similar to a given entity."""
    await _verify_access(project_id, db, user)
    decoded_iri = unquote(iri)
    service = EmbeddingService(db)
    return await service.find_similar(project_id, branch, decoded_iri, limit, threshold)


@router.post(
    "/{project_id}/entities/rank-suggestions",
    response_model=list[RankedCandidate],
)
async def rank_suggestions(
    project_id: UUID,
    body: RankSuggestionRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: RequiredUser,
) -> list[RankedCandidate]:
    """Rank candidate entities by similarity to a context entity."""
    await _verify_access(project_id, db, user)
    if not body.branch:
        from ontokit.git import get_git_service

        body.branch = get_git_service().get_default_branch(project_id)
    service = EmbeddingService(db)
    return await service.rank_suggestions(project_id, body)
