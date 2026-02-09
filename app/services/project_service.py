"""Project service for managing projects and members."""

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import CurrentUser
from app.models.project import Project, ProjectMember
from app.schemas.project import (
    MemberCreate,
    MemberListResponse,
    MemberResponse,
    MemberUpdate,
    ProjectCreate,
    ProjectListResponse,
    ProjectOwner,
    ProjectResponse,
    ProjectRole,
    ProjectUpdate,
)


class ProjectService:
    """Service for project CRUD operations and member management."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

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
                subquery = select(ProjectMember.project_id).where(
                    ProjectMember.user_id == user.id
                )
                query = query.where(Project.id.in_(subquery))
            else:
                # All accessible: public OR user is a member
                subquery = select(ProjectMember.project_id).where(
                    ProjectMember.user_id == user.id
                )
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
        self, project_id: UUID, project_update: ProjectUpdate, user: CurrentUser
    ) -> ProjectResponse:
        """Update a project."""
        project = await self._get_project(project_id)
        user_role = self._get_user_role(project, user)

        if user_role not in ("owner", "admin"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only owner or admin can update project settings",
            )

        # Apply updates
        if project_update.name is not None:
            project.name = project_update.name
        if project_update.description is not None:
            project.description = project_update.description
        if project_update.is_public is not None:
            project.is_public = project_update.is_public

        await self.db.commit()
        await self.db.refresh(project)

        return self._to_response(project, user)

    async def delete(self, project_id: UUID, user: CurrentUser) -> None:
        """Delete a project (owner only)."""
        project = await self._get_project(project_id)

        if project.owner_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the owner can delete a project",
            )

        await self.db.delete(project)
        await self.db.commit()

    # Member management

    async def list_members(
        self, project_id: UUID, user: CurrentUser
    ) -> MemberListResponse:
        """List members of a project."""
        project = await self._get_project(project_id)

        if not self._can_view(project, user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have access to this project",
            )

        items = [self._member_to_response(m) for m in project.members]

        return MemberListResponse(items=items, total=len(items))

    async def add_member(
        self, project_id: UUID, member: MemberCreate, user: CurrentUser
    ) -> MemberResponse:
        """Add a member to a project."""
        project = await self._get_project(project_id)
        user_role = self._get_user_role(project, user)

        if user_role not in ("owner", "admin"):
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

        if user_role not in ("owner", "admin"):
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

        # Admins cannot promote others to admin
        if user_role == "admin" and member_update.role == "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only owner can promote members to admin",
            )

        db_member.role = member_update.role
        await self.db.commit()
        await self.db.refresh(db_member)

        return self._member_to_response(db_member)

    async def remove_member(
        self, project_id: UUID, member_user_id: str, user: CurrentUser
    ) -> None:
        """Remove a member from a project."""
        project = await self._get_project(project_id)
        user_role = self._get_user_role(project, user)

        # Users can remove themselves
        is_self_removal = member_user_id == user.id

        if not is_self_removal and user_role not in ("owner", "admin"):
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
            select(Project)
            .options(selectinload(Project.members))
            .where(Project.id == project_id)
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

    def _to_response(
        self, project: Project, user: CurrentUser | None
    ) -> ProjectResponse:
        """Convert Project model to response schema."""
        user_role = None
        if user:
            user_role = self._get_user_role(project, user)

        # For now, we just have the owner_id. In a real app, you'd fetch user info
        # from Zitadel or a user cache
        owner = ProjectOwner(id=project.owner_id)

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
        )

    def _member_to_response(self, member: ProjectMember) -> MemberResponse:
        """Convert ProjectMember model to response schema."""
        return MemberResponse(
            id=member.id,
            project_id=member.project_id,
            user_id=member.user_id,
            role=member.role,  # type: ignore[arg-type]
            user=None,  # Would be populated from user service
            created_at=member.created_at,
        )


def get_project_service(db: AsyncSession) -> ProjectService:
    """Factory function for dependency injection."""
    return ProjectService(db)
