"""Shared dependencies for API route handlers."""

import asyncio
import os
from uuid import UUID

from fastapi import HTTPException, status
from rdflib import Graph
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ontokit.core.auth import CurrentUser
from ontokit.models.project import Project


async def load_project_graph(
    project_id: UUID, branch: str | None, db: AsyncSession
) -> tuple[Graph, str]:
    """Load the ontology graph for a project, returning (graph, resolved_branch).

    Resolves the branch to the repository default when not specified,
    loads the ontology from git (falling back to storage), and returns
    the in-memory RDFLib graph.
    """
    from ontokit.git.bare_repository import get_bare_git_service
    from ontokit.services.ontology import get_ontology_service
    from ontokit.services.storage import get_storage_service

    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    if not project.source_file_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Project does not have an ontology file",
        )

    storage = get_storage_service()
    ontology = get_ontology_service(storage)
    git = get_bare_git_service()

    resolved_branch: str = (
        branch if branch else await asyncio.to_thread(git.get_default_branch, project_id)
    )

    if not ontology.is_loaded(project_id, resolved_branch):
        filename = getattr(project, "git_ontology_path", None) or os.path.basename(
            project.source_file_path
        )
        try:
            await ontology.load_from_git(project_id, resolved_branch, filename, git)
        except (FileNotFoundError, KeyError, ValueError):
            await ontology.load_from_storage(project_id, project.source_file_path, resolved_branch)

    graph = await ontology._get_graph(project_id, resolved_branch)
    return graph, resolved_branch


async def verify_project_access(
    project_id: UUID, db: AsyncSession, user: CurrentUser | None
) -> None:
    """Verify the user has access to the project.

    For public projects, unauthenticated users are allowed.
    For private projects, the user must be a member.
    """
    from ontokit.services.project_service import get_project_service

    service = get_project_service(db)
    await service.get(project_id, user)
