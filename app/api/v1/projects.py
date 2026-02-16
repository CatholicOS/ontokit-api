"""Project management endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import OptionalUser, RequiredUser, RequiredUserWithToken
from app.core.database import get_db
from app.schemas.owl_class import OWLClassResponse, OWLClassTreeNode, OWLClassTreeResponse
from app.git import GitRepositoryService, get_git_service
from app.schemas.project import (
    BranchCreate,
    BranchInfo,
    BranchListResponse,
    MemberCreate,
    MemberListResponse,
    MemberResponse,
    MemberUpdate,
    ProjectCreate,
    ProjectImportResponse,
    ProjectListResponse,
    ProjectResponse,
    ProjectUpdate,
    RevisionCommit,
    RevisionDiffChange,
    RevisionDiffResponse,
    RevisionFileResponse,
    RevisionHistoryResponse,
    SourceContentSave,
    SourceContentSaveResponse,
)
from app.services.ontology import OntologyService, get_ontology_service
from app.services.project_service import ProjectService, get_project_service
from app.services.storage import StorageService, StorageError, get_storage_service

router = APIRouter()

# Maximum file size for import (50 MB)
MAX_IMPORT_FILE_SIZE = 50 * 1024 * 1024


def get_service(db: Annotated[AsyncSession, Depends(get_db)]) -> ProjectService:
    """Dependency to get project service with database session."""
    return get_project_service(db)


def get_storage() -> StorageService:
    """Dependency to get storage service."""
    return get_storage_service()


def get_ontology() -> OntologyService:
    """Dependency to get ontology service with storage."""
    storage = get_storage_service()
    return get_ontology_service(storage)


def get_git() -> GitRepositoryService:
    """Dependency to get git repository service."""
    return get_git_service()


@router.get("", response_model=ProjectListResponse)
async def list_projects(
    service: Annotated[ProjectService, Depends(get_service)],
    user: OptionalUser,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    filter: str | None = Query(
        default=None, description="Filter: 'public', 'mine', or null for all accessible"
    ),
) -> ProjectListResponse:
    """
    List projects accessible to the current user.

    For anonymous users, only public projects are returned.
    For authenticated users:
    - filter=public: Only public projects
    - filter=mine: Projects where user is a member
    - filter=null: All accessible (public + user's projects)
    """
    return await service.list_accessible(user, skip=skip, limit=limit, filter_type=filter)


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    project: ProjectCreate,
    service: Annotated[ProjectService, Depends(get_service)],
    user: RequiredUser,
) -> ProjectResponse:
    """Create a new project. Requires authentication."""
    return await service.create(project, user)


@router.post("/import", response_model=ProjectImportResponse, status_code=status.HTTP_201_CREATED)
async def import_project(
    file: UploadFile,
    is_public: Annotated[bool, Form()],
    service: Annotated[ProjectService, Depends(get_service)],
    storage: Annotated[StorageService, Depends(get_storage)],
    user: RequiredUser,
    name: Annotated[str | None, Form()] = None,
    description: Annotated[str | None, Form()] = None,
) -> ProjectImportResponse:
    """
    Create a project by importing an ontology file.

    Supported formats: OWL (.owl), RDF/XML (.rdf), Turtle (.ttl), N3 (.n3), JSON-LD (.jsonld)

    The project name and description will be extracted from the ontology metadata
    (dc:title, dcterms:title, rdfs:label for name; dc:description, dcterms:description,
    rdfs:comment for description). You can override these by providing the name and
    description form fields.

    Requires authentication.
    """
    # Check file size
    content = await file.read()
    if len(content) > MAX_IMPORT_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large. Maximum size is {MAX_IMPORT_FILE_SIZE // (1024 * 1024)} MB",
        )

    # Get filename
    filename = file.filename or "ontology.owl"

    return await service.create_from_import(
        file_content=content,
        filename=filename,
        is_public=is_public,
        owner=user,
        storage=storage,
        name_override=name,
        description_override=description,
    )


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: UUID,
    service: Annotated[ProjectService, Depends(get_service)],
    user: OptionalUser,
) -> ProjectResponse:
    """
    Get a project by ID.

    Returns 403 if the project is private and user doesn't have access.
    """
    return await service.get(project_id, user)


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: UUID,
    project: ProjectUpdate,
    service: Annotated[ProjectService, Depends(get_service)],
    storage: Annotated[StorageService, Depends(get_storage)],
    user: RequiredUser,
) -> ProjectResponse:
    """
    Update project settings.

    Only the owner or admin can update project settings.

    When name or description is updated, the corresponding metadata properties
    in the ontology RDF source are also updated and committed to git.
    """
    return await service.update(project_id, project, user, storage=storage)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: UUID,
    service: Annotated[ProjectService, Depends(get_service)],
    user: RequiredUser,
) -> None:
    """
    Delete a project.

    Only the owner can delete a project.
    """
    await service.delete(project_id, user)


# Member management endpoints


@router.get("/{project_id}/members", response_model=MemberListResponse)
async def list_members(
    project_id: UUID,
    service: Annotated[ProjectService, Depends(get_service)],
    user_with_token: RequiredUserWithToken,
) -> MemberListResponse:
    """
    List members of a project.

    Only members can see the member list.
    """
    user, access_token = user_with_token
    return await service.list_members(project_id, user, access_token)


@router.post(
    "/{project_id}/members",
    response_model=MemberResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_member(
    project_id: UUID,
    member: MemberCreate,
    service: Annotated[ProjectService, Depends(get_service)],
    user: RequiredUser,
) -> MemberResponse:
    """
    Add a member to a project.

    Only the owner or admin can add members.
    """
    return await service.add_member(project_id, member, user)


@router.patch("/{project_id}/members/{user_id}", response_model=MemberResponse)
async def update_member(
    project_id: UUID,
    user_id: str,
    member: MemberUpdate,
    service: Annotated[ProjectService, Depends(get_service)],
    user: RequiredUser,
) -> MemberResponse:
    """
    Update a member's role.

    Only the owner or admin can update member roles.
    Admins cannot promote others to admin.
    """
    return await service.update_member(project_id, user_id, member, user)


@router.delete(
    "/{project_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_member(
    project_id: UUID,
    user_id: str,
    service: Annotated[ProjectService, Depends(get_service)],
    user: RequiredUser,
) -> None:
    """
    Remove a member from a project.

    Owner and admin can remove members.
    Users can remove themselves from a project.
    Cannot remove the project owner.
    """
    await service.remove_member(project_id, user_id, user)


# Ontology tree navigation endpoints


async def _ensure_ontology_loaded(
    project_id: UUID,
    service: ProjectService,
    ontology: OntologyService,
    user: OptionalUser,
    branch: str = "main",
    git: GitRepositoryService | None = None,
) -> ProjectResponse:
    """
    Helper to ensure the ontology graph is loaded for a given branch.

    Returns the project response so callers can access label_preferences.
    """
    # Always get the project to check access and get preferences
    project = await service.get(project_id, user)

    if not project.source_file_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project does not have an ontology file",
        )

    # Load if not already loaded for this branch
    if not ontology.is_loaded(project_id, branch):
        import os

        filename = os.path.basename(project.source_file_path)

        # Prefer loading from git if available
        if git is not None and git.repository_exists(project_id):
            try:
                await ontology.load_from_git(project_id, branch, filename, git)
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=f"Failed to load ontology from git branch '{branch}': {e}",
                ) from e
        else:
            # Fall back to storage (e.g., for default branch when no git service)
            try:
                await ontology.load_from_storage(project_id, project.source_file_path, branch)
            except StorageError as e:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=f"Failed to load ontology from storage: {e}",
                ) from e
            except ValueError as e:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=str(e),
                ) from e

    return project


@router.get("/{project_id}/ontology/tree", response_model=OWLClassTreeResponse)
async def get_ontology_tree_root(
    project_id: UUID,
    service: Annotated[ProjectService, Depends(get_service)],
    ontology: Annotated[OntologyService, Depends(get_ontology)],
    git: Annotated[GitRepositoryService, Depends(get_git)],
    user: OptionalUser,
    branch: str | None = Query(default=None, description="Branch to read from"),
) -> OWLClassTreeResponse:
    """
    Get the root classes of the ontology tree.

    Returns the top-level classes (classes with no parent or only owl:Thing as parent)
    as tree nodes optimized for tree view rendering.
    """
    resolved_branch = branch or git.get_default_branch(project_id)
    project = await _ensure_ontology_loaded(
        project_id, service, ontology, user, resolved_branch, git
    )

    nodes = await ontology.get_root_tree_nodes(
        project_id, project.label_preferences, resolved_branch
    )
    total_classes = await ontology.get_class_count(project_id, resolved_branch)

    return OWLClassTreeResponse(nodes=nodes, total_classes=total_classes)


@router.get(
    "/{project_id}/ontology/tree/{class_iri:path}/children", response_model=OWLClassTreeResponse
)
async def get_ontology_tree_children(
    project_id: UUID,
    class_iri: str,
    service: Annotated[ProjectService, Depends(get_service)],
    ontology: Annotated[OntologyService, Depends(get_ontology)],
    git: Annotated[GitRepositoryService, Depends(get_git)],
    user: OptionalUser,
    branch: str | None = Query(default=None, description="Branch to read from"),
) -> OWLClassTreeResponse:
    """
    Get the children of a specific class.

    Returns direct subclasses as tree nodes for lazy-loading tree expansion.
    """
    resolved_branch = branch or git.get_default_branch(project_id)
    project = await _ensure_ontology_loaded(
        project_id, service, ontology, user, resolved_branch, git
    )

    nodes = await ontology.get_children_tree_nodes(
        project_id, class_iri, project.label_preferences, resolved_branch
    )
    total_classes = await ontology.get_class_count(project_id, resolved_branch)

    return OWLClassTreeResponse(nodes=nodes, total_classes=total_classes)


@router.get("/{project_id}/ontology/classes/{class_iri:path}", response_model=OWLClassResponse)
async def get_ontology_class(
    project_id: UUID,
    class_iri: str,
    service: Annotated[ProjectService, Depends(get_service)],
    ontology: Annotated[OntologyService, Depends(get_ontology)],
    git: Annotated[GitRepositoryService, Depends(get_git)],
    user: OptionalUser,
    branch: str | None = Query(default=None, description="Branch to read from"),
) -> OWLClassResponse:
    """
    Get details of a specific class.

    Returns full class information including labels, comments, parents, etc.
    """
    resolved_branch = branch or git.get_default_branch(project_id)
    project = await _ensure_ontology_loaded(
        project_id, service, ontology, user, resolved_branch, git
    )

    result = await ontology.get_class(
        project_id, class_iri, project.label_preferences, resolved_branch
    )
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Class not found: {class_iri}",
        )
    return result


@router.get(
    "/{project_id}/ontology/tree/{class_iri:path}/ancestors", response_model=OWLClassTreeResponse
)
async def get_ontology_class_ancestors(
    project_id: UUID,
    class_iri: str,
    service: Annotated[ProjectService, Depends(get_service)],
    ontology: Annotated[OntologyService, Depends(get_ontology)],
    git: Annotated[GitRepositoryService, Depends(get_git)],
    user: OptionalUser,
    branch: str | None = Query(default=None, description="Branch to read from"),
) -> OWLClassTreeResponse:
    """
    Get the ancestor path from root to a specific class.

    Returns a list of tree nodes representing the path from the root
    down to (but not including) the target class. This is useful for
    expanding the tree view to reveal a specific class.
    """
    resolved_branch = branch or git.get_default_branch(project_id)
    project = await _ensure_ontology_loaded(
        project_id, service, ontology, user, resolved_branch, git
    )

    nodes = await ontology.get_ancestor_path(
        project_id, class_iri, project.label_preferences, resolved_branch
    )
    total_classes = await ontology.get_class_count(project_id, resolved_branch)

    return OWLClassTreeResponse(nodes=nodes, total_classes=total_classes)


# Revision history endpoints


@router.get("/{project_id}/revisions", response_model=RevisionHistoryResponse)
async def get_revision_history(
    project_id: UUID,
    service: Annotated[ProjectService, Depends(get_service)],
    git: Annotated[GitRepositoryService, Depends(get_git)],
    user: OptionalUser,
    limit: int = Query(default=50, ge=1, le=200),
) -> RevisionHistoryResponse:
    """
    Get the revision history for a project.

    Returns a list of commits showing changes to the ontology over time.
    Each commit includes the author, timestamp, and commit message.
    """
    # Check project access
    await service.get(project_id, user)

    # Check if repository exists
    if not git.repository_exists(project_id):
        return RevisionHistoryResponse(
            project_id=project_id,
            commits=[],
            total=0,
        )

    # Get commit history
    commits = git.get_history(project_id, limit=limit)

    return RevisionHistoryResponse(
        project_id=project_id,
        commits=[
            RevisionCommit(
                hash=c.hash,
                short_hash=c.short_hash,
                message=c.message,
                author_name=c.author_name,
                author_email=c.author_email,
                timestamp=c.timestamp,
                is_merge=c.is_merge,
                merged_branch=c.merged_branch,
                parent_hashes=c.parent_hashes,
            )
            for c in commits
        ],
        total=len(commits),
    )


@router.get("/{project_id}/revisions/{version}/file", response_model=RevisionFileResponse)
async def get_file_at_revision(
    project_id: UUID,
    version: str,
    service: Annotated[ProjectService, Depends(get_service)],
    git: Annotated[GitRepositoryService, Depends(get_git)],
    user: OptionalUser,
    filename: str = Query(default="ontology.ttl", description="Filename to retrieve"),
) -> RevisionFileResponse:
    """
    Get the ontology file content at a specific revision.

    Use this to view the ontology as it existed at a particular point in time.
    """
    # Check project access
    project = await service.get(project_id, user)

    # Check if repository exists
    if not git.repository_exists(project_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No revision history found for this project",
        )

    # Try to determine the filename from the project's source_file_path
    if project.source_file_path and filename == "ontology.ttl":
        # Extract the actual filename
        import os

        actual_filename = os.path.basename(project.source_file_path)
        # Use the stored filename pattern (e.g., ontology.ttl)
        if actual_filename.startswith("ontology."):
            filename = actual_filename

    try:
        content = git.get_file_at_version(project_id, filename, version)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Could not retrieve file at revision: {e}",
        )

    return RevisionFileResponse(
        project_id=project_id,
        version=version,
        filename=filename,
        content=content,
    )


@router.get("/{project_id}/revisions/diff", response_model=RevisionDiffResponse)
async def get_revision_diff(
    project_id: UUID,
    service: Annotated[ProjectService, Depends(get_service)],
    git: Annotated[GitRepositoryService, Depends(get_git)],
    user: OptionalUser,
    from_version: str = Query(..., description="Starting revision (commit hash)"),
    to_version: str = Query(default="HEAD", description="Ending revision (commit hash or HEAD)"),
) -> RevisionDiffResponse:
    """
    Get the diff between two revisions.

    Shows which files changed between the two specified commits.
    """
    # Check project access
    await service.get(project_id, user)

    # Check if repository exists
    if not git.repository_exists(project_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No revision history found for this project",
        )

    try:
        diff = git.diff_versions(project_id, from_version, to_version)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not compute diff: {e}",
        )

    return RevisionDiffResponse(
        project_id=project_id,
        from_version=diff.from_version,
        to_version=diff.to_version,
        files_changed=diff.files_changed,
        changes=[
            RevisionDiffChange(
                path=c.path,
                change_type=c.change_type,
                old_path=c.old_path,
                additions=c.additions,
                deletions=c.deletions,
                patch=c.patch,
            )
            for c in diff.changes
        ],
    )


# Branch endpoints


@router.get("/{project_id}/branches", response_model=BranchListResponse)
async def list_branches(
    project_id: UUID,
    service: Annotated[ProjectService, Depends(get_service)],
    git: Annotated[GitRepositoryService, Depends(get_git)],
    user: OptionalUser,
) -> BranchListResponse:
    """
    List all branches for a project.

    Returns a list of branches with their metadata including commits ahead/behind.
    Includes the user's preferred branch if authenticated.
    """
    # Check project access
    await service.get(project_id, user)

    preferred = None
    if user:
        preferred = await service.get_branch_preference(project_id, user.id)

    # Check if repository exists
    if not git.repository_exists(project_id):
        return BranchListResponse(
            items=[],
            current_branch="main",
            default_branch="main",
            preferred_branch=preferred,
        )

    branches = git.list_branches(project_id)

    return BranchListResponse(
        items=[
            BranchInfo(
                name=b.name,
                is_current=b.is_current,
                is_default=b.is_default,
                commit_hash=b.commit_hash,
                commit_message=b.commit_message,
                commit_date=b.commit_date,
                commits_ahead=b.commits_ahead,
                commits_behind=b.commits_behind,
            )
            for b in branches
        ],
        current_branch=git.get_default_branch(project_id),
        default_branch=git.get_default_branch(project_id),
        preferred_branch=preferred,
    )


@router.put(
    "/{project_id}/branch-preference",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def save_branch_preference(
    project_id: UUID,
    service: Annotated[ProjectService, Depends(get_service)],
    user: RequiredUser,
    branch: str = Query(..., description="Branch name to save as preference"),
) -> None:
    """Save the user's preferred branch for a project."""
    await service.set_branch_preference(project_id, user.id, branch)


@router.post(
    "/{project_id}/branches", response_model=BranchInfo, status_code=status.HTTP_201_CREATED
)
async def create_branch(
    project_id: UUID,
    branch: BranchCreate,
    service: Annotated[ProjectService, Depends(get_service)],
    git: Annotated[GitRepositoryService, Depends(get_git)],
    user: RequiredUser,
) -> BranchInfo:
    """
    Create a new branch.

    Requires authentication and editor or higher role.
    """
    # Check project access (will raise 403 if user doesn't have access)
    project = await service.get(project_id, user)

    # Check if user has at least editor role
    if project.user_role not in ("owner", "admin", "editor"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Must be an editor or higher to create branches",
        )

    # Check if repository exists
    if not git.repository_exists(project_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No repository found for this project",
        )

    try:
        from_ref = branch.from_branch or "HEAD"
        result = git.create_branch(project_id, branch.name, from_ref)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not create branch: {e}",
        )

    return BranchInfo(
        name=result.name,
        is_current=result.is_current,
        is_default=result.is_default,
        commit_hash=result.commit_hash,
        commit_message=result.commit_message,
        commit_date=result.commit_date,
        commits_ahead=result.commits_ahead,
        commits_behind=result.commits_behind,
    )


@router.post("/{project_id}/branches/{branch_name:path}/checkout", response_model=BranchInfo)
async def checkout_branch(
    project_id: UUID,
    branch_name: str,
    service: Annotated[ProjectService, Depends(get_service)],
    git: Annotated[GitRepositoryService, Depends(get_git)],
    user: RequiredUser,
) -> BranchInfo:
    """
    Switch to a different branch.

    Requires authentication and editor or higher role.
    """
    # Check project access
    project = await service.get(project_id, user)

    # Check if user has at least editor role
    if project.user_role not in ("owner", "admin", "editor"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Must be an editor or higher to switch branches",
        )

    # Check if repository exists
    if not git.repository_exists(project_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No repository found for this project",
        )

    try:
        result = git.switch_branch(project_id, branch_name)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Branch not found: {branch_name}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not switch to branch: {e}",
        )

    return BranchInfo(
        name=result.name,
        is_current=result.is_current,
        is_default=result.is_default,
        commit_hash=result.commit_hash,
        commit_message=result.commit_message,
        commit_date=result.commit_date,
        commits_ahead=result.commits_ahead,
        commits_behind=result.commits_behind,
    )


@router.delete("/{project_id}/branches/{branch_name:path}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_branch(
    project_id: UUID,
    branch_name: str,
    service: Annotated[ProjectService, Depends(get_service)],
    git: Annotated[GitRepositoryService, Depends(get_git)],
    user: RequiredUser,
    force: bool = Query(
        default=False, description="Force delete even if branch has unmerged changes"
    ),
) -> None:
    """
    Delete a branch.

    Cannot delete the current branch or the default branch.
    Requires authentication and editor or higher role.
    """
    # Check project access
    project = await service.get(project_id, user)

    # Check if user has at least editor role
    if project.user_role not in ("owner", "admin", "editor"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Must be an editor or higher to delete branches",
        )

    # Check if repository exists
    if not git.repository_exists(project_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No repository found for this project",
        )

    try:
        git.delete_branch(project_id, branch_name, force=force)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Branch not found: {branch_name}",
        )


# Source content endpoints


@router.put("/{project_id}/source", response_model=SourceContentSaveResponse)
async def save_source_content(
    project_id: UUID,
    data: SourceContentSave,
    service: Annotated[ProjectService, Depends(get_service)],
    storage: Annotated[StorageService, Depends(get_storage)],
    ontology: Annotated[OntologyService, Depends(get_ontology)],
    git: Annotated[GitRepositoryService, Depends(get_git)],
    user: RequiredUser,
    branch: str | None = Query(default=None, description="Branch to commit to"),
) -> SourceContentSaveResponse:
    """
    Save ontology source content to storage and create a git commit.

    Requires authentication and editor or higher role.
    """
    # Check project access
    project = await service.get(project_id, user)

    # Check if user has at least editor role
    if project.user_role not in ("owner", "admin", "editor"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Must be an editor or higher to save changes",
        )

    if not project.source_file_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Project does not have an ontology file",
        )

    # Validate the content is valid Turtle
    try:
        from rdflib import Graph

        g = Graph()
        g.parse(data=data.content, format="turtle")
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid Turtle syntax: {e}",
        )

    # Check if repository exists
    if not git.repository_exists(project_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No repository found for this project",
        )

    # Resolve branch from query param or default
    current_branch = branch or git.get_default_branch(project_id)

    # Extract filename from source_file_path
    import os

    filename = os.path.basename(project.source_file_path)

    # Convert content to bytes
    content_bytes = data.content.encode("utf-8")

    # Save to storage
    try:
        await storage.upload_file(project.source_file_path, content_bytes, "text/turtle")
    except StorageError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to save to storage: {e}",
        )

    # Commit to git on the specified branch
    try:
        commit_info = git.commit_changes(
            project_id=project_id,
            ontology_content=content_bytes,
            filename=filename,
            message=data.commit_message,
            author_name=user.name,
            author_email=user.email,
            branch_name=current_branch,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to commit changes: {e}",
        )

    # Reload the ontology in memory to reflect changes
    try:
        ontology.unload(project_id, current_branch)
        await ontology.load_from_git(project_id, current_branch, filename, git)
    except Exception as e:
        # Log but don't fail - the commit succeeded
        import logging

        logging.warning(f"Failed to reload ontology after save: {e}")

    return SourceContentSaveResponse(
        success=True,
        commit_hash=commit_info.hash,
        commit_message=commit_info.message,
        branch=current_branch,
    )
