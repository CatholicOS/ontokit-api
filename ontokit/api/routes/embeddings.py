"""Embedding management API endpoints."""

import logging
import uuid
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ontokit.api.utils.redis import get_arq_pool
from ontokit.core.auth import CurrentUser, RequiredUser
from ontokit.core.database import get_db
from ontokit.git import get_git_service
from ontokit.models.embedding import EmbeddingJob
from ontokit.schemas.embeddings import (
    EmbeddingConfig,
    EmbeddingConfigUpdate,
    EmbeddingGenerateResponse,
    EmbeddingStatus,
)
from ontokit.services.embedding_service import EmbeddingService
from ontokit.services.project_service import get_project_service

logger = logging.getLogger(__name__)

router = APIRouter()


async def _verify_write_access(project_id: UUID, db: AsyncSession, user: CurrentUser) -> None:
    service = get_project_service(db)
    project_response = await service.get(project_id, user)
    if project_response.user_role not in ("owner", "admin", "editor"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Write access required",
        )


@router.get("/{project_id}/embeddings/config", response_model=EmbeddingConfig)
async def get_embedding_config(
    project_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: RequiredUser,
) -> EmbeddingConfig:
    """Get embedding configuration for a project."""
    service = get_project_service(db)
    await service.get(project_id, user)

    embed_service = EmbeddingService(db)
    config = await embed_service.get_config(project_id)
    if not config:
        return EmbeddingConfig(
            provider="local",
            model_name="all-MiniLM-L6-v2",
            api_key_set=False,
            dimensions=384,
            auto_embed_on_save=False,
        )
    return config


@router.put("/{project_id}/embeddings/config", response_model=EmbeddingConfig)
async def update_embedding_config(
    project_id: UUID,
    data: EmbeddingConfigUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: RequiredUser,
) -> EmbeddingConfig:
    """Update embedding configuration."""
    await _verify_write_access(project_id, db, user)
    embed_service = EmbeddingService(db)
    return await embed_service.update_config(project_id, data)


@router.post(
    "/{project_id}/embeddings/generate",
    response_model=EmbeddingGenerateResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def generate_embeddings(
    project_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: RequiredUser,
    branch: str | None = Query(default=None),
) -> EmbeddingGenerateResponse:
    """Trigger full project embedding generation (background job)."""
    await _verify_write_access(project_id, db, user)

    git = get_git_service()
    resolved_branch = branch or git.get_default_branch(project_id)

    # Check for an existing in-progress job for this project/branch
    active_q = (
        select(EmbeddingJob)
        .where(
            EmbeddingJob.project_id == project_id,
            EmbeddingJob.branch == resolved_branch,
            EmbeddingJob.status.in_(["pending", "running"]),
        )
        .limit(1)
    )
    active_result = await db.execute(active_q)
    active_job = active_result.scalar_one_or_none()
    if active_job:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Embedding generation already in progress (job {active_job.id})",
        )

    # Claim the work by inserting a pending job row before enqueuing,
    # so concurrent requests cannot both pass the SELECT check above.
    job_id = uuid.uuid4()
    pending_job = EmbeddingJob(
        id=job_id,
        project_id=project_id,
        branch=resolved_branch,
        status="pending",
    )
    try:
        db.add(pending_job)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Embedding generation already in progress",
        ) from None

    try:
        pool = await get_arq_pool()
        await pool.enqueue_job(
            "run_embedding_generation_task",
            str(project_id),
            resolved_branch,
            str(job_id),
        )
    except Exception:
        await db.execute(delete(EmbeddingJob).where(EmbeddingJob.id == job_id))
        await db.commit()
        raise
    return EmbeddingGenerateResponse(job_id=str(job_id))


@router.get("/{project_id}/embeddings/status", response_model=EmbeddingStatus)
async def get_embedding_status(
    project_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: RequiredUser,
    branch: str | None = Query(default=None),
) -> EmbeddingStatus:
    """Get embedding status and coverage."""
    service = get_project_service(db)
    await service.get(project_id, user)

    git = get_git_service()
    resolved_branch = branch or git.get_default_branch(project_id)

    embed_service = EmbeddingService(db)
    return await embed_service.get_status(project_id, resolved_branch)


@router.delete(
    "/{project_id}/embeddings",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def clear_embeddings(
    project_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: RequiredUser,
) -> None:
    """Clear all embeddings for a project."""
    await _verify_write_access(project_id, db, user)
    embed_service = EmbeddingService(db)
    await embed_service.clear_embeddings(project_id)
