"""Normalization API endpoints."""

import json
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import OptionalUser, RequiredUser
from app.core.database import get_db
from app.schemas.project import NormalizationReportResponse
from app.services.normalization_service import NormalizationService, get_normalization_service
from app.services.project_service import ProjectService, get_project_service
from app.services.storage import StorageService, get_storage_service

router = APIRouter()


# Response schemas
class NormalizationStatusResponse(BaseModel):
    """Status of normalization for a project."""

    needs_normalization: bool
    last_run: datetime | None = None
    last_run_id: str | None = None
    preview_report: NormalizationReportResponse | None = None
    error: str | None = None


class NormalizationRunResponse(BaseModel):
    """Response for a normalization run."""

    id: str
    project_id: str
    created_at: datetime
    triggered_by: str | None = None
    trigger_type: str
    report: NormalizationReportResponse
    is_dry_run: bool
    commit_hash: str | None = None
    # For dry runs, include content for diff preview
    original_content: str | None = None
    normalized_content: str | None = None


class NormalizationHistoryResponse(BaseModel):
    """List of normalization runs."""

    items: list[NormalizationRunResponse]
    total: int


class NormalizationTriggerRequest(BaseModel):
    """Request to trigger normalization."""

    dry_run: bool = False


# Dependencies
def get_storage() -> StorageService:
    """Dependency to get storage service."""
    return get_storage_service()


def get_service(db: Annotated[AsyncSession, Depends(get_db)]) -> ProjectService:
    """Dependency to get project service."""
    return get_project_service(db)


def get_norm_service(
    db: Annotated[AsyncSession, Depends(get_db)],
    storage: Annotated[StorageService, Depends(get_storage)],
) -> NormalizationService:
    """Dependency to get normalization service."""
    return get_normalization_service(db, storage)


# Endpoints
@router.get("/{project_id}/normalization/status", response_model=NormalizationStatusResponse)
async def get_normalization_status(
    project_id: UUID,
    project_service: Annotated[ProjectService, Depends(get_service)],
    norm_service: Annotated[NormalizationService, Depends(get_norm_service)],
    user: OptionalUser,
) -> NormalizationStatusResponse:
    """
    Check if a project's ontology needs normalization.

    Returns the current normalization status including:
    - Whether normalization is needed
    - When the last normalization ran
    - A preview of what would change if normalized
    """
    # Check access (validates user has permission to view this project)
    await project_service.get(project_id, user)

    # Get project model for the service
    db_project = await project_service._get_project(project_id)

    status_data = await norm_service.check_normalization_status(db_project)

    return NormalizationStatusResponse(
        needs_normalization=status_data["needs_normalization"],
        last_run=status_data["last_run"],
        last_run_id=status_data.get("last_run_id"),
        preview_report=(
            NormalizationReportResponse(**status_data["report"])
            if status_data["report"]
            else None
        ),
        error=status_data.get("error"),
    )


@router.post("/{project_id}/normalization", response_model=NormalizationRunResponse)
async def run_normalization(
    project_id: UUID,
    request: NormalizationTriggerRequest,
    project_service: Annotated[ProjectService, Depends(get_service)],
    norm_service: Annotated[NormalizationService, Depends(get_norm_service)],
    user: RequiredUser,
) -> NormalizationRunResponse:
    """
    Trigger normalization of a project's ontology.

    Normalizes the ontology to canonical Turtle format and commits the changes.
    Use dry_run=true to preview changes without committing.

    Requires editor role or higher.
    """
    # Check access
    project = await project_service.get(project_id, user)

    if project.user_role not in ("owner", "admin", "editor"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Must be an editor or higher to run normalization",
        )

    if not project.source_file_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Project has no ontology file",
        )

    # Get project model for the service
    db_project = await project_service._get_project(project_id)

    try:
        run, original_content, normalized_content = await norm_service.run_normalization(
            project=db_project,
            user=user,
            trigger_type="manual",
            dry_run=request.dry_run,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Normalization failed: {e}",
        ) from e

    report_data = json.loads(run.report_json)

    return NormalizationRunResponse(
        id=str(run.id),
        project_id=str(run.project_id),
        created_at=run.created_at,
        triggered_by=run.triggered_by,
        trigger_type=run.trigger_type,
        report=NormalizationReportResponse(**report_data),
        is_dry_run=run.is_dry_run,
        commit_hash=run.commit_hash,
        original_content=original_content,
        normalized_content=normalized_content,
    )


@router.get("/{project_id}/normalization/history", response_model=NormalizationHistoryResponse)
async def get_normalization_history(
    project_id: UUID,
    project_service: Annotated[ProjectService, Depends(get_service)],
    norm_service: Annotated[NormalizationService, Depends(get_norm_service)],
    user: OptionalUser,
    limit: int = Query(default=10, ge=1, le=50),
    include_dry_runs: bool = Query(default=False),
) -> NormalizationHistoryResponse:
    """
    Get the normalization run history for a project.

    Returns a list of past normalization runs with their reports.
    """
    # Check access
    await project_service.get(project_id, user)

    runs = await norm_service.get_normalization_history(
        project_id, limit=limit, include_dry_runs=include_dry_runs
    )

    items = []
    for run in runs:
        report_data = json.loads(run.report_json)
        items.append(
            NormalizationRunResponse(
                id=str(run.id),
                project_id=str(run.project_id),
                created_at=run.created_at,
                triggered_by=run.triggered_by,
                trigger_type=run.trigger_type,
                report=NormalizationReportResponse(**report_data),
                is_dry_run=run.is_dry_run,
                commit_hash=run.commit_hash,
            )
        )

    return NormalizationHistoryResponse(items=items, total=len(items))


@router.get(
    "/{project_id}/normalization/runs/{run_id}",
    response_model=NormalizationRunResponse,
)
async def get_normalization_run(
    project_id: UUID,
    run_id: UUID,
    project_service: Annotated[ProjectService, Depends(get_service)],
    norm_service: Annotated[NormalizationService, Depends(get_norm_service)],
    user: OptionalUser,
) -> NormalizationRunResponse:
    """Get details of a specific normalization run."""
    # Check access
    await project_service.get(project_id, user)

    run = await norm_service.get_normalization_run(project_id, run_id)
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Normalization run not found",
        )

    report_data = json.loads(run.report_json)

    return NormalizationRunResponse(
        id=str(run.id),
        project_id=str(run.project_id),
        created_at=run.created_at,
        triggered_by=run.triggered_by,
        trigger_type=run.trigger_type,
        report=NormalizationReportResponse(**report_data),
        is_dry_run=run.is_dry_run,
        commit_hash=run.commit_hash,
    )
