"""Quality API endpoints — cross-references, consistency checks, duplicate detection."""

import logging
import uuid
from typing import Annotated
from urllib.parse import unquote
from uuid import UUID

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from ontokit.api.dependencies import load_project_graph, verify_project_access
from ontokit.core.auth import OptionalUser, RequiredUser
from ontokit.core.database import get_db
from ontokit.schemas.quality import (
    ConsistencyCheckResult,
    ConsistencyCheckTriggerResponse,
    CrossReferencesResponse,
    DuplicateDetectionResult,
)
from ontokit.services.consistency_service import run_consistency_check
from ontokit.services.cross_reference_service import get_cross_references
from ontokit.services.duplicate_detection_service import find_duplicates

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_redis() -> aioredis.Redis:
    """Get the shared Redis connection pool from the application lifespan."""
    from ontokit.main import redis_pool

    if redis_pool is None:
        raise RuntimeError("Redis pool is not available")
    return redis_pool


@router.get(
    "/{project_id}/entities/{iri:path}/references",
    response_model=CrossReferencesResponse,
)
async def get_entity_references(
    project_id: UUID,
    iri: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: OptionalUser,
    branch: str | None = Query(default=None, description="Branch name"),
) -> CrossReferencesResponse:
    """Get all cross-references to a specific entity."""
    await verify_project_access(project_id, db, user)
    decoded_iri = unquote(iri)
    graph, _ = await load_project_graph(project_id, branch, db)
    return get_cross_references(graph, decoded_iri)


@router.post(
    "/{project_id}/quality/check",
    response_model=ConsistencyCheckTriggerResponse,
)
async def trigger_consistency_check(
    project_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: RequiredUser,
    branch: str | None = Query(default=None, description="Branch name"),
) -> ConsistencyCheckTriggerResponse:
    """Run consistency checks and cache the result."""
    await verify_project_access(project_id, db, user)
    graph, resolved_branch = await load_project_graph(project_id, branch, db)

    result = run_consistency_check(graph, str(project_id), resolved_branch)

    # Cache in Redis with 10-min TTL
    job_id = str(uuid.uuid4())
    try:
        redis = _get_redis()
        result_json = result.model_dump_json()
        cache_key = f"quality:{project_id}:{resolved_branch}"
        job_key = f"quality_job:{project_id}:{job_id}"
        await redis.set(cache_key, result_json, ex=600)
        await redis.set(job_key, result_json, ex=600)
    except Exception:
        logger.warning("Failed to cache consistency result in Redis", exc_info=True)

    return ConsistencyCheckTriggerResponse(job_id=job_id)


@router.get(
    "/{project_id}/quality/jobs/{job_id}",
    response_model=ConsistencyCheckResult,
)
async def get_quality_job_result(
    project_id: UUID,
    job_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: OptionalUser,
) -> ConsistencyCheckResult:
    """Get consistency check results by job ID."""
    await verify_project_access(project_id, db, user)

    try:
        redis = _get_redis()
        cached = await redis.get(f"quality_job:{project_id}:{job_id}")
        if cached:
            return ConsistencyCheckResult.model_validate_json(cached)
    except Exception:
        logger.warning("Failed to read quality job from Redis", exc_info=True)

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Job result not found or expired",
    )


@router.get(
    "/{project_id}/quality/issues",
    response_model=ConsistencyCheckResult,
)
async def get_consistency_issues(
    project_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: OptionalUser,
    branch: str | None = Query(default=None, description="Branch name"),
) -> ConsistencyCheckResult:
    """Get cached consistency check results."""
    await verify_project_access(project_id, db, user)

    # Resolve the branch so cache keys match what trigger_consistency_check stored
    from ontokit.git.bare_repository import BareGitRepositoryService

    resolved_branch = branch or BareGitRepositoryService().get_default_branch(project_id)

    try:
        redis = _get_redis()
        cache_key = f"quality:{project_id}:{resolved_branch}"
        cached = await redis.get(cache_key)
        if cached:
            return ConsistencyCheckResult.model_validate_json(cached)
    except Exception:
        logger.warning("Failed to read consistency cache from Redis", exc_info=True)

    # No cached result — return empty
    from datetime import UTC, datetime

    return ConsistencyCheckResult(
        project_id=str(project_id),
        branch=resolved_branch,
        issues=[],
        checked_at=datetime.now(UTC).isoformat(),
        duration_ms=0,
    )


@router.post(
    "/{project_id}/quality/duplicates",
    response_model=DuplicateDetectionResult,
)
async def detect_duplicates(
    project_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: RequiredUser,
    branch: str | None = Query(default=None, description="Branch name"),
    threshold: float = Query(default=0.85, ge=0.5, le=1.0),
) -> DuplicateDetectionResult:
    """Detect duplicate entities based on label similarity."""
    await verify_project_access(project_id, db, user)
    graph, _ = await load_project_graph(project_id, branch, db)
    return find_duplicates(graph, threshold)
