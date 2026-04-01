"""Project management endpoints."""

import logging
from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from sqlalchemy import delete as sa_delete
from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ontokit.api.utils.redis import get_arq_pool
from ontokit.core.auth import OptionalUser, RequiredUser, RequiredUserWithToken
from ontokit.core.database import get_db
from ontokit.core.encryption import decrypt_token
from ontokit.git import GitRepositoryService, get_git_service
from ontokit.models.branch_metadata import BranchMetadata
from ontokit.models.pull_request import GitHubIntegration, PRStatus, PullRequest
from ontokit.models.user_github_token import UserGitHubToken
from ontokit.schemas.owl_class import EntitySearchResponse, OWLClassResponse, OWLClassTreeResponse
from ontokit.schemas.project import (
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
    TransferOwnership,
)
from ontokit.schemas.pull_request import (
    GitHubRepoFileInfo,
    GitHubRepoFilesResponse,
    ProjectCreateFromGitHub,
)
from ontokit.services.github_service import get_github_service
from ontokit.services.indexed_ontology import IndexedOntologyService
from ontokit.services.ontology import OntologyService, get_ontology_service
from ontokit.services.project_service import ProjectService, get_project_service
from ontokit.services.sitemap_notifier import notify_sitemap_add, notify_sitemap_remove
from ontokit.services.storage import StorageError, StorageService, get_storage_service

logger = logging.getLogger(__name__)

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


def get_indexed_ontology(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> IndexedOntologyService:
    """Dependency to get indexed ontology service (SQL index + RDFLib fallback)."""
    storage = get_storage_service()
    ontology = get_ontology_service(storage)
    return IndexedOntologyService(ontology, db)


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
    background_tasks: BackgroundTasks,
) -> ProjectResponse:
    """Create a new project. Requires authentication."""
    result = await service.create(project, user)
    if result.is_public:
        background_tasks.add_task(notify_sitemap_add, result.id, result.updated_at)
    return result


@router.post("/import", response_model=ProjectImportResponse, status_code=status.HTTP_201_CREATED)
async def import_project(
    file: UploadFile,
    is_public: Annotated[bool, Form()],
    service: Annotated[ProjectService, Depends(get_service)],
    storage: Annotated[StorageService, Depends(get_storage)],
    user: RequiredUser,
    background_tasks: BackgroundTasks,
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

    result = await service.create_from_import(
        file_content=content,
        filename=filename,
        is_public=is_public,
        owner=user,
        storage=storage,
        name_override=name,
        description_override=description,
    )
    if is_public:
        background_tasks.add_task(notify_sitemap_add, result.id, result.updated_at)

    # Trigger ontology index build for newly imported project
    try:
        pool = await get_arq_pool()
        if pool is not None:
            await pool.enqueue_job(
                "run_ontology_index_task",
                str(result.id),
                "main",
            )
    except Exception:
        logger.warning("Failed to queue ontology index for imported project", exc_info=True)

    return result


async def _resolve_github_pat(db: AsyncSession, user_id: str) -> str:
    """Resolve a user's GitHub PAT from the database.

    Raises HTTPException if no token is stored.
    """
    result = await db.execute(select(UserGitHubToken).where(UserGitHubToken.user_id == user_id))
    token_row = result.scalar_one_or_none()
    if not token_row:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No GitHub token found. Connect your GitHub account in Settings first.",
        )
    return decrypt_token(token_row.encrypted_token)


@router.get("/github/scan-files", response_model=GitHubRepoFilesResponse)
async def scan_github_repo_files(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: RequiredUser,
    owner: str = Query(..., description="GitHub repository owner"),
    repo: str = Query(..., description="GitHub repository name"),
    ref: str | None = Query(None, description="Git ref (branch/tag). Defaults to repo default."),
) -> GitHubRepoFilesResponse:
    """
    Scan a GitHub repository for ontology files.

    Returns a list of files with extensions: .ttl, .owl, .owx, .rdf, .n3, .jsonld
    """
    pat = await _resolve_github_pat(db, user.id)
    github = get_github_service()
    files = await github.scan_ontology_files(pat, owner, repo, ref)
    items = [GitHubRepoFileInfo(**f) for f in files]
    return GitHubRepoFilesResponse(items=items, total=len(items))


@router.post(
    "/from-github",
    response_model=ProjectImportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_project_from_github(
    data: ProjectCreateFromGitHub,
    service: Annotated[ProjectService, Depends(get_service)],
    storage: Annotated[StorageService, Depends(get_storage)],
    db: Annotated[AsyncSession, Depends(get_db)],
    user: RequiredUser,
    background_tasks: BackgroundTasks,
) -> ProjectImportResponse:
    """
    Create a project by cloning a GitHub repository.

    The user selects a repository and an ontology file within it.
    The file is downloaded, parsed, and the entire repo is cloned as a bare git repo.
    """
    pat = await _resolve_github_pat(db, user.id)
    github = get_github_service()

    # Auto-detect default branch if not provided
    default_branch = data.default_branch
    if not default_branch:
        repo_info = await github.get_repo_info(pat, data.repo_owner, data.repo_name)
        default_branch = repo_info.get("default_branch") or "main"

    # Download the ontology file from GitHub
    try:
        file_content = await github.get_file_content(
            pat, data.repo_owner, data.repo_name, data.ontology_file_path, default_branch
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to download ontology file from GitHub: {e}",
        ) from e

    filename = data.ontology_file_path.rsplit("/", 1)[-1]

    # Resolve turtle_file_path:
    # - If source is already .ttl, turtle output goes to the same file
    # - If source is non-.ttl, the client must specify where to write .ttl output
    if data.ontology_file_path.lower().endswith(".ttl"):
        turtle_file_path = data.ontology_file_path
    elif data.turtle_file_path:
        if not data.turtle_file_path.lower().endswith(".ttl"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="turtle_file_path must end with .ttl",
            )
        turtle_file_path = data.turtle_file_path
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="turtle_file_path is required when source file is not .ttl",
        )

    result = await service.create_from_github(
        file_content=file_content,
        filename=filename,
        repo_owner=data.repo_owner,
        repo_name=data.repo_name,
        ontology_file_path=data.ontology_file_path,
        default_branch=default_branch,
        is_public=data.is_public,
        owner=user,
        storage=storage,
        github_token=pat,
        name_override=data.name,
        description_override=data.description,
        turtle_file_path=turtle_file_path,
    )
    if data.is_public:
        background_tasks.add_task(notify_sitemap_add, result.id, result.updated_at)

    # Trigger ontology index build for GitHub-imported project
    try:
        pool = await get_arq_pool()
        if pool is not None:
            await pool.enqueue_job(
                "run_ontology_index_task",
                str(result.id),
                default_branch or "main",
            )
    except Exception:
        logger.warning("Failed to queue ontology index for GitHub project", exc_info=True)

    return result


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
    background_tasks: BackgroundTasks,
) -> ProjectResponse:
    """
    Update project settings.

    Only the owner or admin can update project settings.

    When name or description is updated, the corresponding metadata properties
    in the ontology RDF source are also updated and committed to git.
    """
    # Fetch old state to detect is_public changes
    old_project = await service.get(project_id, user)
    was_public = old_project.is_public

    result = await service.update(project_id, project, user, storage=storage)

    # Determine sitemap action based on visibility change
    if result.is_public and not was_public:
        # Became public — add to sitemap
        background_tasks.add_task(notify_sitemap_add, result.id, result.updated_at)
    elif not result.is_public and was_public:
        # Became private — remove from sitemap
        background_tasks.add_task(notify_sitemap_remove, result.id)
    elif result.is_public and was_public:
        # Still public but name may have changed — update entry
        background_tasks.add_task(notify_sitemap_add, result.id, result.updated_at)

    return result


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: UUID,
    service: Annotated[ProjectService, Depends(get_service)],
    user: RequiredUser,
    background_tasks: BackgroundTasks,
) -> None:
    """
    Delete a project.

    Only the owner can delete a project.
    """
    # Check if project was public before deleting
    project = await service.get(project_id, user)
    was_public = project.is_public

    await service.delete(project_id, user)

    if was_public:
        background_tasks.add_task(notify_sitemap_remove, project_id)


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


@router.post("/{project_id}/transfer-ownership", response_model=MemberListResponse)
async def transfer_ownership(
    project_id: UUID,
    data: TransferOwnership,
    service: Annotated[ProjectService, Depends(get_service)],
    user_with_token: RequiredUserWithToken,
    force: bool = Query(
        default=False,
        description="Force transfer even if GitHub integration will be disconnected",
    ),
) -> MemberListResponse:
    """
    Transfer project ownership to an existing admin member.

    Only the current project owner (or superadmin) can transfer ownership.
    The target user must be an admin member of the project.
    The current owner is demoted to admin.

    If the project has a GitHub integration and the new owner does not have a
    GitHub token, returns 409 unless force=true, in which case the integration
    is removed.
    """
    user, access_token = user_with_token
    return await service.transfer_ownership(project_id, data, user, access_token, force=force)


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

        filename = project.git_ontology_path or os.path.basename(project.source_file_path)

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
    indexed: Annotated[IndexedOntologyService, Depends(get_indexed_ontology)],
    git: Annotated[GitRepositoryService, Depends(get_git)],
    user: OptionalUser,
    branch: str | None = Query(default=None, description="Branch to read from"),
) -> OWLClassTreeResponse:
    """
    Get the root classes of the ontology tree.

    Returns the top-level classes (classes with no parent or only owl:Thing as parent)
    as tree nodes optimized for tree view rendering.
    Uses PostgreSQL index when available, falls back to RDFLib.
    """
    resolved_branch = branch or git.get_default_branch(project_id)
    project = await _ensure_ontology_loaded(
        project_id, service, ontology, user, resolved_branch, git
    )

    nodes = await indexed.get_root_tree_nodes(
        project_id, project.label_preferences, resolved_branch
    )
    total_classes = await indexed.get_class_count(project_id, resolved_branch)

    return OWLClassTreeResponse(nodes=nodes, total_classes=total_classes)


@router.get(
    "/{project_id}/ontology/tree/{class_iri:path}/children", response_model=OWLClassTreeResponse
)
async def get_ontology_tree_children(
    project_id: UUID,
    class_iri: str,
    service: Annotated[ProjectService, Depends(get_service)],
    ontology: Annotated[OntologyService, Depends(get_ontology)],
    indexed: Annotated[IndexedOntologyService, Depends(get_indexed_ontology)],
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

    nodes = await indexed.get_children_tree_nodes(
        project_id, class_iri, project.label_preferences, resolved_branch
    )
    total_classes = await indexed.get_class_count(project_id, resolved_branch)

    return OWLClassTreeResponse(nodes=nodes, total_classes=total_classes)


@router.get("/{project_id}/ontology/classes/{class_iri:path}", response_model=OWLClassResponse)
async def get_ontology_class(
    project_id: UUID,
    class_iri: str,
    service: Annotated[ProjectService, Depends(get_service)],
    ontology: Annotated[OntologyService, Depends(get_ontology)],
    indexed: Annotated[IndexedOntologyService, Depends(get_indexed_ontology)],
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

    result = await indexed.get_class(
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
    indexed: Annotated[IndexedOntologyService, Depends(get_indexed_ontology)],
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

    nodes = await indexed.get_ancestor_path(
        project_id, class_iri, project.label_preferences, resolved_branch
    )
    total_classes = await indexed.get_class_count(project_id, resolved_branch)

    return OWLClassTreeResponse(nodes=nodes, total_classes=total_classes)


@router.get("/{project_id}/ontology/search", response_model=EntitySearchResponse)
async def search_ontology_entities(
    project_id: UUID,
    service: Annotated[ProjectService, Depends(get_service)],
    ontology: Annotated[OntologyService, Depends(get_ontology)],
    indexed: Annotated[IndexedOntologyService, Depends(get_indexed_ontology)],
    git: Annotated[GitRepositoryService, Depends(get_git)],
    user: OptionalUser,
    q: str = Query(..., min_length=1, max_length=200, description="Search query"),
    entity_types: str | None = Query(
        default=None,
        description="Comma-separated entity types: class,property,individual",
    ),
    branch: str | None = Query(default=None, description="Branch to read from"),
) -> EntitySearchResponse:
    """
    Search for entities in the ontology by name.

    Matches against labels, local names, and full IRIs (case-insensitive substring).
    Returns up to 50 results sorted by relevance (prefix matches first).
    """
    resolved_branch = branch or git.get_default_branch(project_id)
    project = await _ensure_ontology_loaded(
        project_id, service, ontology, user, resolved_branch, git
    )

    parsed_types = None
    if entity_types:
        parsed_types = [t.strip() for t in entity_types.split(",") if t.strip()]

    return await indexed.search_entities(
        project_id,
        query=q,
        entity_types=parsed_types,
        label_preferences=project.label_preferences,
        branch=resolved_branch,
    )


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


@router.get("/{project_id}/revisions/file", response_model=RevisionFileResponse)
async def get_file_at_revision(
    project_id: UUID,
    service: Annotated[ProjectService, Depends(get_service)],
    git: Annotated[GitRepositoryService, Depends(get_git)],
    user: OptionalUser,
    version: str = Query(description="Branch name or commit hash"),
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

    # Map the default filename to the actual path in the git repo
    if project.git_ontology_path and filename == "ontology.ttl":
        filename = project.git_ontology_path

    try:
        content = git.get_file_at_version(project_id, filename, version)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Could not retrieve file at revision: {e}",
        ) from e

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
        ) from e

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
    db: Annotated[AsyncSession, Depends(get_db)],
    user: OptionalUser,
) -> BranchListResponse:
    """
    List all branches for a project.

    Returns a list of branches with their metadata including commits ahead/behind.
    Includes the user's preferred branch if authenticated.
    Permission fields control delete button visibility/state in the UI.
    """
    # Check project access — save role info for permission computation
    project = await service.get(project_id, user)

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

    # Query GitHub integration for remote sync metadata
    gh_result = await db.execute(
        select(GitHubIntegration).where(GitHubIntegration.project_id == project_id)
    )
    gh_integration = gh_result.scalar_one_or_none()
    has_github_remote = gh_integration is not None
    last_sync_at = gh_integration.last_sync_at if gh_integration else None
    sync_status = gh_integration.sync_status if gh_integration else None

    # Build metadata map: branch_name → BranchMetadata
    meta_result = await db.execute(
        select(BranchMetadata).where(BranchMetadata.project_id == project_id)
    )
    meta_map = {m.branch_name: m for m in meta_result.scalars().all()}

    # Build set of branch names that are source of an open PR
    pr_result = await db.execute(
        select(PullRequest.source_branch).where(
            PullRequest.project_id == project_id,
            PullRequest.status == PRStatus.OPEN,
        )
    )
    open_pr_branches = {row[0] for row in pr_result.all()}

    # Determine user's role for permission computation
    user_role = project.user_role
    is_superadmin = project.is_superadmin
    is_privileged = is_superadmin or user_role in ("owner", "admin")

    items = []
    for b in branches:
        meta = meta_map.get(b.name)
        has_open_pr = b.name in open_pr_branches

        # Permission logic
        has_delete_permission = is_privileged or (
            user_role == "editor"
            and user is not None
            and meta is not None
            and meta.created_by_id == user.id
        )

        can_delete = has_delete_permission and not has_open_pr and not b.is_default

        items.append(
            BranchInfo(
                name=b.name,
                is_current=b.is_current,
                is_default=b.is_default,
                commit_hash=b.commit_hash,
                commit_message=b.commit_message,
                commit_date=b.commit_date,
                commits_ahead=b.commits_ahead,
                commits_behind=b.commits_behind,
                remote_commits_ahead=b.remote_commits_ahead,
                remote_commits_behind=b.remote_commits_behind,
                created_by_id=meta.created_by_id if meta else None,
                created_by_name=meta.created_by_name if meta else None,
                has_open_pr=has_open_pr,
                has_delete_permission=has_delete_permission,
                can_delete=can_delete,
            )
        )

    return BranchListResponse(
        items=items,
        current_branch=git.get_default_branch(project_id),
        default_branch=git.get_default_branch(project_id),
        preferred_branch=preferred,
        has_github_remote=has_github_remote,
        last_sync_at=last_sync_at,
        sync_status=sync_status,
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
    db: Annotated[AsyncSession, Depends(get_db)],
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
        ) from e

    # Record branch metadata (who created this branch)
    metadata = BranchMetadata(
        project_id=project_id,
        branch_name=result.name,
        created_by_id=user.id,
        created_by_name=user.name,
    )
    db.add(metadata)
    await db.commit()

    return BranchInfo(
        name=result.name,
        is_current=result.is_current,
        is_default=result.is_default,
        commit_hash=result.commit_hash,
        commit_message=result.commit_message,
        commit_date=result.commit_date,
        commits_ahead=result.commits_ahead,
        commits_behind=result.commits_behind,
        created_by_id=user.id,
        created_by_name=user.name,
        can_delete=True,
        has_open_pr=False,
        has_delete_permission=True,
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
    except KeyError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Branch not found: {branch_name}",
        ) from e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not switch to branch: {e}",
        ) from e

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
    db: Annotated[AsyncSession, Depends(get_db)],
    user: RequiredUser,
    force: bool = Query(
        default=False, description="Force delete even if branch has unmerged changes"
    ),
) -> None:
    """
    Delete a branch.

    Cannot delete the current branch or the default branch.
    Owner/admin/superadmin can delete any branch; editors can only delete
    branches they created. Branches with open pull requests cannot be deleted.
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

    # Block deletion if branch has an open pull request
    open_pr_count = await db.scalar(
        select(sa_func.count()).where(
            PullRequest.project_id == project_id,
            PullRequest.source_branch == branch_name,
            PullRequest.status == PRStatus.OPEN,
        )
    )
    if open_pr_count and open_pr_count > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete branch: it has an open pull request",
        )

    # Author check for editors (non-admin/non-owner)
    is_privileged = project.is_superadmin or project.user_role in ("owner", "admin")
    if not is_privileged:
        meta = await db.scalar(
            select(BranchMetadata).where(
                BranchMetadata.project_id == project_id,
                BranchMetadata.branch_name == branch_name,
            )
        )
        if not meta or meta.created_by_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only delete branches you created",
            )

    try:
        git.delete_branch(project_id, branch_name, force=force)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except KeyError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Branch not found: {branch_name}",
        ) from e

    # Clean up branch metadata
    await db.execute(
        sa_delete(BranchMetadata).where(
            BranchMetadata.project_id == project_id,
            BranchMetadata.branch_name == branch_name,
        )
    )

    # Clean up ontology index for deleted branch
    try:
        from ontokit.services.ontology_index import OntologyIndexService

        index_service = OntologyIndexService(db)
        await index_service.delete_branch_index(project_id, branch_name, auto_commit=False)
    except Exception:
        logger.warning("Failed to clean up ontology index for deleted branch", exc_info=True)

    await db.commit()


# Source content endpoints


@router.put("/{project_id}/source", response_model=SourceContentSaveResponse)
async def save_source_content(
    project_id: UUID,
    data: SourceContentSave,
    service: Annotated[ProjectService, Depends(get_service)],
    storage: Annotated[StorageService, Depends(get_storage)],
    ontology: Annotated[OntologyService, Depends(get_ontology)],
    git: Annotated[GitRepositoryService, Depends(get_git)],
    db: Annotated[AsyncSession, Depends(get_db)],
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
        ) from e

    # Check if repository exists
    if not git.repository_exists(project_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No repository found for this project",
        )

    # Resolve branch from query param or default
    current_branch = branch or git.get_default_branch(project_id)

    # Extract filename from git_ontology_path or source_file_path
    import os

    filename = project.git_ontology_path or os.path.basename(project.source_file_path)

    # Convert content to bytes
    content_bytes = data.content.encode("utf-8")

    # Save to storage
    try:
        await storage.upload_file(project.source_file_path, content_bytes, "text/turtle")
    except StorageError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to save to storage: {e}",
        ) from e

    # Capture old graph for change event diffing (before the commit)
    old_graph = None
    was_loaded = ontology.is_loaded(project_id, current_branch)
    try:
        if not was_loaded:
            await ontology.load_from_git(project_id, current_branch, filename, git)
        old_graph = await ontology._get_graph(project_id, current_branch)
    except Exception:
        logger.debug("Could not capture pre-commit graph for diff", exc_info=True)

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
        ) from e

    # Reload the ontology in memory to reflect changes
    try:
        ontology.unload(project_id, current_branch)
        await ontology.load_from_git(project_id, current_branch, filename, git)
    except Exception as e:
        # Log but don't fail - the commit succeeded
        logger.warning("Failed to reload ontology after save: %s", e)

    # Record change events (analytics)
    change_events = []
    try:
        new_graph = await ontology._get_graph(project_id, current_branch)
        from ontokit.services.change_event_service import ChangeEventService

        change_service = ChangeEventService(db)
        change_events = await change_service.record_events_from_diff(
            project_id,
            current_branch,
            old_graph,
            new_graph,
            user.id,
            user.name,
            commit_info.hash,
        )
    except Exception:
        logger.warning("Failed to record change events", exc_info=True)

    # Auto-embed changed entities if configured
    if change_events:
        try:
            from ontokit.models.change_event import ChangeEventType
            from ontokit.services.embedding_service import EmbeddingService

            embed_config = await EmbeddingService(db).get_config(project_id)
            if embed_config and embed_config.auto_embed_on_save:
                pool = await get_arq_pool()
                if pool is None:
                    logger.warning(
                        "Cannot auto-embed for project %s: ARQ/Redis pool unavailable",
                        project_id,
                    )
                else:
                    entity_iris = [
                        event.entity_iri
                        for event in change_events
                        if event.event_type != ChangeEventType.DELETE
                    ]
                    if entity_iris:
                        await pool.enqueue_job(
                            "run_batch_entity_embed_task",
                            str(project_id),
                            current_branch,
                            entity_iris,
                        )
        except Exception:
            logger.warning("Failed to queue auto-embed", exc_info=True)

    # Trigger ontology index rebuild
    try:
        pool = await get_arq_pool()
        if pool is not None:
            await pool.enqueue_job(
                "run_ontology_index_task",
                str(project_id),
                current_branch,
                commit_info.hash,
            )
    except Exception:
        logger.warning("Failed to queue ontology re-index", exc_info=True)

    return SourceContentSaveResponse(
        success=True,
        commit_hash=commit_info.hash,
        commit_message=commit_info.message,
        branch=current_branch,
    )


@router.post("/{project_id}/ontology/reindex", status_code=status.HTTP_202_ACCEPTED)
async def trigger_ontology_reindex(
    project_id: UUID,
    service: Annotated[ProjectService, Depends(get_service)],
    git: Annotated[GitRepositoryService, Depends(get_git)],
    user: RequiredUser,
    branch: str | None = Query(default=None, description="Branch to reindex"),
) -> dict[str, str]:
    """
    Manually trigger an ontology index rebuild (admin only).

    Enqueues a background job to re-parse the Turtle file and rebuild
    the PostgreSQL index tables for faster queries.
    """
    project = await service.get(project_id, user)

    if project.user_role not in ("owner", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Must be an admin or owner to trigger reindexing",
        )

    resolved_branch = branch or git.get_default_branch(project_id)

    pool = await get_arq_pool()
    if pool is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Background job queue unavailable",
        )

    await pool.enqueue_job(
        "run_ontology_index_task",
        str(project_id),
        resolved_branch,
    )

    return {"status": "accepted", "branch": resolved_branch}
