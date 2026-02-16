"""Project service for managing projects and members."""

import json
import logging
from pathlib import Path
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import CurrentUser
from app.git import GitRepositoryService, get_git_service
from app.models.project import Project, ProjectMember
from app.schemas.project import (
    MemberCreate,
    MemberListResponse,
    MemberResponse,
    MemberUpdate,
    MemberUser,
    NormalizationReportResponse,
    ProjectCreate,
    ProjectImportResponse,
    ProjectListResponse,
    ProjectOwner,
    ProjectResponse,
    ProjectRole,
    ProjectUpdate,
)
from app.services.ontology_extractor import (
    OntologyMetadataExtractor,
    OntologyMetadataUpdater,
    OntologyParseError,
    UnsupportedFormatError,
)
from app.services.storage import StorageError, StorageService

logger = logging.getLogger(__name__)


class ProjectService:
    """Service for project CRUD operations and member management."""

    def __init__(self, db: AsyncSession, git_service: GitRepositoryService | None = None) -> None:
        self.db = db
        self.git_service = git_service or get_git_service()

    async def create(self, project: ProjectCreate, owner: CurrentUser) -> ProjectResponse:
        """Create a new project."""
        db_project = Project(
            name=project.name,
            description=project.description,
            is_public=project.is_public,
            owner_id=owner.id,
        )
        self.db.add(db_project)
        # Flush to get the project ID
        await self.db.flush()

        # Add owner as a member with owner role
        owner_member = ProjectMember(
            project_id=db_project.id,
            user_id=owner.id,
            role="owner",
        )
        self.db.add(owner_member)

        await self.db.commit()
        await self.db.refresh(db_project, ["members"])

        return self._to_response(db_project, owner)

    async def create_from_import(
        self,
        file_content: bytes,
        filename: str,
        is_public: bool,
        owner: CurrentUser,
        storage: StorageService,
        name_override: str | None = None,
        description_override: str | None = None,
    ) -> ProjectImportResponse:
        """
        Create a project by importing an ontology file.

        Args:
            file_content: The ontology file content as bytes
            filename: The original filename
            is_public: Whether the project should be public
            owner: The user creating the project
            storage: Storage service for file upload
            name_override: Optional name to use instead of extracted name
            description_override: Optional description to use instead of extracted

        Returns:
            ProjectImportResponse with project info and file path

        Raises:
            HTTPException: If file format is unsupported, parsing fails, or storage fails
        """
        extractor = OntologyMetadataExtractor()

        # Extract metadata from the ontology file
        try:
            metadata = extractor.extract_metadata(file_content, filename)
        except UnsupportedFormatError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            ) from e
        except OntologyParseError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(e),
            ) from e

        # Normalize to Turtle format for consistent representation
        # Skip canonical bnode IDs on import for speed - can be applied later via
        # the normalization feature if desired
        normalization_report_json: str | None = None
        try:
            normalized_content, normalization_report = extractor.normalize_to_turtle(
                file_content, filename, use_canonical=False
            )
            normalization_report_json = json.dumps(normalization_report.to_dict())
        except (UnsupportedFormatError, OntologyParseError) as e:
            # Should not happen since extract_metadata already succeeded, but handle gracefully
            logger.warning(f"Failed to normalize ontology to Turtle: {e}")
            normalized_content = file_content

        # Determine project name (priority: override > extracted > filename)
        project_name = name_override
        if not project_name:
            project_name = metadata.title
        if not project_name:
            # Derive from filename (strip extension)
            project_name = Path(filename).stem

        # Determine project description
        project_description = description_override or metadata.description

        # Create the project in the database
        db_project = Project(
            name=project_name,
            description=project_description,
            is_public=is_public,
            owner_id=owner.id,
            ontology_iri=metadata.ontology_iri,
            normalization_report=normalization_report_json,
        )
        self.db.add(db_project)
        await self.db.flush()

        # Add owner as a member with owner role
        owner_member = ProjectMember(
            project_id=db_project.id,
            user_id=owner.id,
            role="owner",
        )
        self.db.add(owner_member)

        # Always store as Turtle (.ttl) since we normalize to Turtle format
        object_name = f"projects/{db_project.id}/ontology.ttl"
        content_type = "text/turtle"

        # Upload normalized file to storage
        try:
            file_path = await storage.upload_file(object_name, normalized_content, content_type)
        except StorageError as e:
            # Rollback the database transaction
            await self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Failed to store file: {e}",
            ) from e

        # Update project with file path
        db_project.source_file_path = file_path

        await self.db.commit()
        # Refresh all attributes including updated_at and members relationship
        await self.db.refresh(db_project)
        # Explicitly load members relationship
        await self.db.refresh(db_project, ["members"])

        # Initialize git repository for version control
        try:
            self.git_service.initialize_repository(
                project_id=db_project.id,
                ontology_content=normalized_content,
                filename="ontology.ttl",
                author_name=owner.name,
                author_email=owner.email,
                project_name=project_name,
            )
            logger.info(f"Initialized git repository for project {db_project.id}")
        except Exception as e:
            # Log the error but don't fail the import - git is supplementary
            logger.warning(f"Failed to initialize git repository for project {db_project.id}: {e}")

        return self._to_import_response(db_project, owner, file_path)

    async def list_accessible(
        self,
        user: CurrentUser | None,
        skip: int = 0,
        limit: int = 20,
        filter_type: str | None = None,
    ) -> ProjectListResponse:
        """
        List projects accessible to the user.

        Args:
            user: Current user (None for anonymous)
            skip: Pagination offset
            limit: Maximum results to return
            filter_type: Filter by 'public', 'mine', or None for all accessible
        """
        # Build base query
        query = select(Project).options(selectinload(Project.members))

        if user is None:
            # Anonymous: only public projects
            query = query.where(Project.is_public == True)  # noqa: E712
        else:
            # Authenticated user
            if filter_type == "public":
                query = query.where(Project.is_public == True)  # noqa: E712
            elif filter_type == "mine":
                # Projects where user is a member
                subquery = select(ProjectMember.project_id).where(ProjectMember.user_id == user.id)
                query = query.where(Project.id.in_(subquery))
            else:
                # All accessible: public OR user is a member
                subquery = select(ProjectMember.project_id).where(ProjectMember.user_id == user.id)
                query = query.where(
                    or_(
                        Project.is_public == True,  # noqa: E712
                        Project.id.in_(subquery),
                    )
                )

        # Count total
        count_query = select(func.count()).select_from(query.subquery())
        total = await self.db.scalar(count_query) or 0

        # Apply pagination and ordering
        query = query.order_by(Project.created_at.desc()).offset(skip).limit(limit)

        result = await self.db.execute(query)
        projects = result.scalars().all()

        items = [self._to_response(p, user) for p in projects]

        return ProjectListResponse(items=items, total=total, skip=skip, limit=limit)

    async def get(self, project_id: UUID, user: CurrentUser | None) -> ProjectResponse:
        """
        Get a project by ID.

        Raises 404 if not found, 403 if user doesn't have access.
        """
        project = await self._get_project(project_id)

        if not self._can_view(project, user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have access to this project",
            )

        return self._to_response(project, user)

    async def update(
        self,
        project_id: UUID,
        project_update: ProjectUpdate,
        user: CurrentUser,
        storage: StorageService | None = None,
    ) -> ProjectResponse:
        """Update a project.

        Args:
            project_id: The project's UUID
            project_update: The update data
            user: The current user
            storage: Optional storage service for syncing metadata to RDF
        """
        project = await self._get_project(project_id)
        user_role = self._get_user_role(project, user)

        if user_role not in ("owner", "admin") and not user.is_superadmin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only owner or admin can update project settings",
            )

        # Track if name or description changed for RDF sync
        name_changed = project_update.name is not None and project_update.name != project.name
        description_changed = (
            project_update.description is not None
            and project_update.description != project.description
        )

        # Apply updates
        if project_update.name is not None:
            project.name = project_update.name
        if project_update.description is not None:
            project.description = project_update.description
        if project_update.is_public is not None:
            project.is_public = project_update.is_public
        if project_update.label_preferences is not None:
            # Store as JSON string
            project.label_preferences = json.dumps(project_update.label_preferences)

        await self.db.commit()
        await self.db.refresh(project)

        # Sync metadata to RDF if name or description changed
        if (name_changed or description_changed) and storage is not None:
            await self._sync_metadata_to_rdf(
                project=project,
                new_name=project_update.name if name_changed else None,
                new_description=project_update.description if description_changed else None,
                user=user,
                storage=storage,
            )

        return self._to_response(project, user)

    async def _sync_metadata_to_rdf(
        self,
        project: Project,
        new_name: str | None,
        new_description: str | None,
        user: CurrentUser,
        storage: StorageService,
    ) -> str | None:
        """
        Sync project metadata changes to the ontology RDF source.

        This method:
        1. Downloads the ontology content from storage
        2. Updates the appropriate metadata properties (dc:title, dcterms:title, etc.)
        3. Serializes back to Turtle
        4. Uploads to storage and commits to git

        Args:
            project: The project being updated
            new_name: New project name (None to skip)
            new_description: New project description (None to skip)
            user: The current user (for git commit author)
            storage: Storage service for file operations

        Returns:
            Commit hash if changes were committed, None otherwise
        """
        # Skip if no source file
        if not project.source_file_path:
            logger.debug(f"Project {project.id} has no source file, skipping RDF sync")
            return None

        try:
            # Extract object name from source_file_path (e.g., "projects/{id}/ontology.ttl")
            # The source_file_path is stored as "bucket/object_name", extract just the object part
            if "/" in project.source_file_path:
                # Remove bucket prefix if present
                parts = project.source_file_path.split("/", 1)
                object_name = parts[1] if len(parts) > 1 else project.source_file_path
            else:
                object_name = project.source_file_path

            # Download current ontology content
            content = await storage.download_file(object_name)

            # Get the filename from the path
            filename = Path(object_name).name

            # Update metadata in the RDF
            updater = OntologyMetadataUpdater()
            updated_content, changes = updater.update_metadata(
                content=content,
                filename=filename,
                new_title=new_name,
                new_description=new_description,
            )

            if not changes:
                logger.debug(f"No RDF changes needed for project {project.id}")
                return None

            # Upload updated content to storage
            await storage.upload_file(object_name, updated_content, "text/turtle")

            # Commit to git
            if self.git_service.repository_exists(project.id):
                # Build commit message
                change_lines = "\n".join(f"- {change}" for change in changes)
                commit_message = f"Update ontology metadata\n\n{change_lines}\n\nAutomated sync from project settings."

                commit_info = self.git_service.commit_changes(
                    project_id=project.id,
                    ontology_content=updated_content,
                    filename=filename,
                    message=commit_message,
                    author_name=user.name,
                    author_email=user.email,
                )
                logger.info(
                    f"Synced metadata to RDF for project {project.id}, "
                    f"commit {commit_info.short_hash}"
                )
                return commit_info.hash
            else:
                logger.debug(f"No git repository for project {project.id}, skipping commit")
                return None

        except StorageError as e:
            logger.warning(
                f"Failed to download ontology for project {project.id}: {e}. "
                "Database update succeeded, but RDF sync failed."
            )
            return None
        except Exception as e:
            logger.warning(
                f"Failed to sync metadata to RDF for project {project.id}: {e}. "
                "Database update succeeded, but RDF sync failed."
            )
            return None

    async def delete(self, project_id: UUID, user: CurrentUser) -> None:
        """Delete a project (owner or superadmin only)."""
        project = await self._get_project(project_id)

        if project.owner_id != user.id and not user.is_superadmin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the owner can delete a project",
            )

        await self.db.delete(project)
        await self.db.commit()

        # Clean up git repository
        try:
            self.git_service.delete_repository(project_id)
            logger.info(f"Deleted git repository for project {project_id}")
        except Exception as e:
            logger.warning(f"Failed to delete git repository for project {project_id}: {e}")

    # Branch preference

    async def get_branch_preference(self, project_id: UUID, user_id: str) -> str | None:
        """Get user's preferred branch for a project."""
        result = await self.db.execute(
            select(ProjectMember.preferred_branch).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def set_branch_preference(self, project_id: UUID, user_id: str, branch: str) -> None:
        """Save user's preferred branch for a project."""
        result = await self.db.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user_id,
            )
        )
        member = result.scalar_one_or_none()
        if member:
            member.preferred_branch = branch
            await self.db.commit()

    # Member management

    async def list_members(
        self, project_id: UUID, user: CurrentUser, access_token: str | None = None
    ) -> MemberListResponse:
        """List members of a project."""
        project = await self._get_project(project_id)

        if not self._can_view(project, user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have access to this project",
            )

        # Fetch user info for all members
        user_info_map: dict[str, MemberUser] = {}

        # Add current user's info from their token
        user_info_map[user.id] = MemberUser(
            id=user.id,
            name=user.name,
            email=user.email,
        )

        # Try to fetch other users' info from Zitadel if we have a token
        if access_token:
            from app.services.user_service import get_user_service

            user_service = get_user_service()
            other_user_ids = [m.user_id for m in project.members if m.user_id != user.id]

            if other_user_ids:
                fetched_users = await user_service.get_users_info(other_user_ids, access_token)
                for uid, info in fetched_users.items():
                    user_info_map[uid] = MemberUser(
                        id=info["id"],
                        name=info["name"],
                        email=info["email"],
                    )

        items = [self._member_to_response(m, user_info_map.get(m.user_id)) for m in project.members]

        return MemberListResponse(items=items, total=len(items))

    async def add_member(
        self, project_id: UUID, member: MemberCreate, user: CurrentUser
    ) -> MemberResponse:
        """Add a member to a project."""
        project = await self._get_project(project_id)
        user_role = self._get_user_role(project, user)

        if user_role not in ("owner", "admin") and not user.is_superadmin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only owner or admin can add members",
            )

        # Check if user is already a member
        existing = await self.db.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == member.user_id,
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User is already a member of this project",
            )

        # Cannot add someone as owner through this endpoint
        role = member.role
        if role == "owner":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot add a member as owner. Transfer ownership instead.",
            )

        db_member = ProjectMember(
            project_id=project_id,
            user_id=member.user_id,
            role=role,
        )
        self.db.add(db_member)
        await self.db.commit()
        await self.db.refresh(db_member)

        return self._member_to_response(db_member)

    async def update_member(
        self,
        project_id: UUID,
        member_user_id: str,
        member_update: MemberUpdate,
        user: CurrentUser,
    ) -> MemberResponse:
        """Update a member's role."""
        project = await self._get_project(project_id)
        user_role = self._get_user_role(project, user)

        if user_role not in ("owner", "admin") and not user.is_superadmin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only owner or admin can update member roles",
            )

        # Find the member
        result = await self.db.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == member_user_id,
            )
        )
        db_member = result.scalar_one_or_none()

        if db_member is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Member not found",
            )

        # Cannot change owner's role
        if db_member.role == "owner":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot change owner's role. Transfer ownership instead.",
            )

        # Cannot set role to owner through this endpoint
        if member_update.role == "owner":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot set role to owner. Use transfer ownership instead.",
            )

        # Admins cannot promote others to admin (unless superadmin)
        if user_role == "admin" and member_update.role == "admin" and not user.is_superadmin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only owner can promote members to admin",
            )

        db_member.role = member_update.role
        await self.db.commit()
        await self.db.refresh(db_member)

        return self._member_to_response(db_member)

    async def remove_member(self, project_id: UUID, member_user_id: str, user: CurrentUser) -> None:
        """Remove a member from a project."""
        project = await self._get_project(project_id)
        user_role = self._get_user_role(project, user)

        # Users can remove themselves
        is_self_removal = member_user_id == user.id

        if not is_self_removal and user_role not in ("owner", "admin") and not user.is_superadmin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only owner or admin can remove members",
            )

        # Find the member
        result = await self.db.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == member_user_id,
            )
        )
        db_member = result.scalar_one_or_none()

        if db_member is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Member not found",
            )

        # Cannot remove owner
        if db_member.role == "owner":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot remove project owner. Delete the project or transfer ownership.",
            )

        # Admins cannot remove other admins
        if user_role == "admin" and db_member.role == "admin" and not is_self_removal:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admins cannot remove other admins",
            )

        await self.db.delete(db_member)
        await self.db.commit()

    # Helper methods

    async def _get_project(self, project_id: UUID) -> Project:
        """Get a project by ID or raise 404."""
        result = await self.db.execute(
            select(Project).options(selectinload(Project.members)).where(Project.id == project_id)
        )
        project = result.scalar_one_or_none()

        if project is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )

        return project

    def _can_view(self, project: Project, user: CurrentUser | None) -> bool:
        """Check if user can view the project."""
        if project.is_public:
            return True

        if user is None:
            return False

        # Check if user is a member
        return any(m.user_id == user.id for m in project.members)

    def _get_user_role(self, project: Project, user: CurrentUser) -> ProjectRole | None:
        """Get user's role in the project."""
        for member in project.members:
            if member.user_id == user.id:
                return member.role  # type: ignore[return-value]
        return None

    def _to_response(self, project: Project, user: CurrentUser | None) -> ProjectResponse:
        """Convert Project model to response schema."""
        user_role = None
        if user:
            user_role = self._get_user_role(project, user)

        # For now, we just have the owner_id. In a real app, you'd fetch user info
        # from Zitadel or a user cache
        owner = ProjectOwner(id=project.owner_id)

        # Deserialize label_preferences from JSON string
        label_prefs = None
        if project.label_preferences:
            try:
                label_prefs = json.loads(project.label_preferences)
            except json.JSONDecodeError:
                label_prefs = None

        # Deserialize normalization_report from JSON string
        norm_report = None
        if project.normalization_report:
            try:
                report_data = json.loads(project.normalization_report)
                norm_report = NormalizationReportResponse(**report_data)
            except (json.JSONDecodeError, TypeError):
                norm_report = None

        return ProjectResponse(
            id=project.id,
            name=project.name,
            description=project.description,
            is_public=project.is_public,
            owner_id=project.owner_id,
            owner=owner,
            created_at=project.created_at,
            updated_at=project.updated_at,
            member_count=len(project.members),
            user_role=user_role,
            is_superadmin=user.is_superadmin if user else False,
            source_file_path=project.source_file_path,
            ontology_iri=project.ontology_iri,
            label_preferences=label_prefs,
            normalization_report=norm_report,
        )

    def _to_import_response(
        self, project: Project, user: CurrentUser, file_path: str
    ) -> ProjectImportResponse:
        """Convert Project model to import response schema."""
        user_role = self._get_user_role(project, user)
        owner = ProjectOwner(id=project.owner_id)

        return ProjectImportResponse(
            id=project.id,
            name=project.name,
            description=project.description,
            is_public=project.is_public,
            owner_id=project.owner_id,
            owner=owner,
            created_at=project.created_at,
            updated_at=project.updated_at,
            member_count=len(project.members),
            user_role=user_role,
            ontology_iri=project.ontology_iri,
            file_path=file_path,
        )

    def _member_to_response(
        self, member: ProjectMember, user_info: MemberUser | None = None
    ) -> MemberResponse:
        """Convert ProjectMember model to response schema."""
        return MemberResponse(
            id=member.id,
            project_id=member.project_id,
            user_id=member.user_id,
            role=member.role,  # type: ignore[arg-type]
            user=user_info,
            created_at=member.created_at,
        )


def get_project_service(db: AsyncSession) -> ProjectService:
    """Factory function for dependency injection."""
    return ProjectService(db)
