"""Join request service for managing project join requests."""

import logging
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ontokit.core.auth import CurrentUser
from ontokit.models.join_request import JoinRequest, JoinRequestStatus
from ontokit.models.project import Project, ProjectMember
from ontokit.schemas.join_request import (
    JoinRequestAction,
    JoinRequestCreate,
    JoinRequestListResponse,
    JoinRequestResponse,
    JoinRequestUser,
    MyJoinRequestResponse,
    PendingJoinRequestsSummary,
    ProjectPendingCount,
)
from ontokit.services.user_service import UserService, get_user_service

logger = logging.getLogger(__name__)


class JoinRequestService:
    """Service for join request operations."""

    def __init__(
        self,
        db: AsyncSession,
        user_service: UserService | None = None,
    ) -> None:
        self.db = db
        self.user_service = user_service or get_user_service()

    async def _get_project(self, project_id: UUID) -> Project:
        """Get a project by ID or raise 404."""
        result = await self.db.execute(select(Project).where(Project.id == project_id))
        project = result.scalar_one_or_none()
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )
        return project

    async def _get_user_role(self, project_id: UUID, user_id: str) -> str | None:
        """Get a user's role in a project, or None if not a member."""
        result = await self.db.execute(
            select(ProjectMember.role).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def _check_admin_access(self, project_id: UUID, user: CurrentUser) -> None:
        """Check that the user is an owner or admin of the project."""
        if user.is_superadmin:
            return
        role = await self._get_user_role(project_id, user.id)
        if role not in ("owner", "admin"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only project owners and admins can manage join requests",
            )

    def _to_response(
        self,
        jr: JoinRequest,
        user_info: dict[str, dict[str, str | None]] | None = None,
    ) -> JoinRequestResponse:
        """Convert a JoinRequest model to a response schema."""
        user = JoinRequestUser(
            id=jr.user_id,
            name=jr.user_name,
            email=jr.user_email,
        )

        responder = None
        if jr.responded_by and user_info and jr.responded_by in user_info:
            info = user_info[jr.responded_by]
            responder = JoinRequestUser(
                id=jr.responded_by,
                name=info.get("name"),
                email=info.get("email"),
            )

        return JoinRequestResponse(
            id=jr.id,
            project_id=jr.project_id,
            user_id=jr.user_id,
            user=user,
            message=jr.message,
            status=jr.status,
            responded_by=jr.responded_by,
            responder=responder,
            responded_at=jr.responded_at,
            response_message=jr.response_message,
            created_at=jr.created_at,
            updated_at=jr.updated_at,
        )

    async def create_request(
        self,
        project_id: UUID,
        data: JoinRequestCreate,
        user: CurrentUser,
    ) -> JoinRequestResponse:
        """Submit a join request for a public project."""
        project = await self._get_project(project_id)

        if not project.is_public:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Join requests are only available for public projects",
            )

        # Check if user is already a member
        existing_role = await self._get_user_role(project_id, user.id)
        if existing_role:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You are already a member of this project",
            )

        # Create the join request (partial unique index will catch duplicates)
        jr = JoinRequest(
            project_id=project_id,
            user_id=user.id,
            user_name=user.name,
            user_email=user.email,
            message=data.message,
            status=JoinRequestStatus.PENDING,
        )
        self.db.add(jr)

        try:
            await self.db.commit()
            await self.db.refresh(jr)
        except IntegrityError as exc:
            await self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="You already have a pending join request for this project",
            ) from exc

        return self._to_response(jr)

    async def list_requests(
        self,
        project_id: UUID,
        user: CurrentUser,
        status_filter: str | None = None,
    ) -> JoinRequestListResponse:
        """List join requests for a project (admin only)."""
        await self._check_admin_access(project_id, user)

        query = select(JoinRequest).where(JoinRequest.project_id == project_id)
        count_query = (
            select(func.count())
            .select_from(JoinRequest)
            .where(JoinRequest.project_id == project_id)
        )

        if status_filter:
            query = query.where(JoinRequest.status == status_filter)
            count_query = count_query.where(JoinRequest.status == status_filter)
        else:
            # Default to pending
            query = query.where(JoinRequest.status == JoinRequestStatus.PENDING)
            count_query = count_query.where(JoinRequest.status == JoinRequestStatus.PENDING)

        query = query.order_by(JoinRequest.created_at.desc())

        result = await self.db.execute(query)
        requests = list(result.scalars().all())
        total_result = await self.db.execute(count_query)
        total = total_result.scalar() or 0

        # Collect responder IDs for batch lookup
        responder_ids = [jr.responded_by for jr in requests if jr.responded_by]
        user_info: dict[str, dict[str, str | None]] = {}
        if responder_ids:
            info = await self.user_service.get_users_info(responder_ids)
            user_info = {uid: dict(uinfo) for uid, uinfo in info.items()}

        return JoinRequestListResponse(
            items=[self._to_response(jr, user_info) for jr in requests],
            total=total,
        )

    async def approve_request(
        self,
        project_id: UUID,
        request_id: UUID,
        action: JoinRequestAction,
        user: CurrentUser,
    ) -> JoinRequestResponse:
        """Approve a join request and add the user with the suggester role."""
        await self._check_admin_access(project_id, user)

        result = await self.db.execute(
            select(JoinRequest).where(
                JoinRequest.id == request_id,
                JoinRequest.project_id == project_id,
            )
        )
        jr = result.scalar_one_or_none()
        if not jr:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Join request not found",
            )

        if jr.status != JoinRequestStatus.PENDING:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Join request is already {jr.status}",
            )

        # Update the join request
        jr.status = JoinRequestStatus.APPROVED
        jr.responded_by = user.id
        jr.responded_at = datetime.now(UTC)
        jr.response_message = action.response_message

        # Add user as suggester
        member = ProjectMember(
            project_id=project_id,
            user_id=jr.user_id,
            role="suggester",
        )
        self.db.add(member)

        try:
            await self.db.commit()
            await self.db.refresh(jr)
        except IntegrityError:
            await self.db.rollback()
            # User was already added as a member (race condition)
            # Still mark as approved
            jr.status = JoinRequestStatus.APPROVED
            jr.responded_by = user.id
            jr.responded_at = datetime.now(UTC)
            jr.response_message = action.response_message
            await self.db.commit()
            await self.db.refresh(jr)

        return self._to_response(jr)

    async def decline_request(
        self,
        project_id: UUID,
        request_id: UUID,
        action: JoinRequestAction,
        user: CurrentUser,
    ) -> JoinRequestResponse:
        """Decline a join request."""
        await self._check_admin_access(project_id, user)

        result = await self.db.execute(
            select(JoinRequest).where(
                JoinRequest.id == request_id,
                JoinRequest.project_id == project_id,
            )
        )
        jr = result.scalar_one_or_none()
        if not jr:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Join request not found",
            )

        if jr.status != JoinRequestStatus.PENDING:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Join request is already {jr.status}",
            )

        jr.status = JoinRequestStatus.DECLINED
        jr.responded_by = user.id
        jr.responded_at = datetime.now(UTC)
        jr.response_message = action.response_message

        await self.db.commit()
        await self.db.refresh(jr)

        return self._to_response(jr)

    async def withdraw_request(
        self,
        project_id: UUID,
        request_id: UUID,
        user: CurrentUser,
    ) -> None:
        """Withdraw a pending join request (requester only)."""
        result = await self.db.execute(
            select(JoinRequest).where(
                JoinRequest.id == request_id,
                JoinRequest.project_id == project_id,
            )
        )
        jr = result.scalar_one_or_none()
        if not jr:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Join request not found",
            )

        if jr.user_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only withdraw your own join requests",
            )

        if jr.status != JoinRequestStatus.PENDING:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Join request is already {jr.status}",
            )

        jr.status = JoinRequestStatus.WITHDRAWN

        await self.db.commit()

    async def get_my_request(
        self,
        project_id: UUID,
        user: CurrentUser,
    ) -> MyJoinRequestResponse:
        """Get the current user's join request status for a project."""
        # First check for a pending request
        result = await self.db.execute(
            select(JoinRequest).where(
                JoinRequest.project_id == project_id,
                JoinRequest.user_id == user.id,
                JoinRequest.status == JoinRequestStatus.PENDING,
            )
        )
        pending = result.scalar_one_or_none()

        if pending:
            return MyJoinRequestResponse(
                has_pending_request=True,
                request=self._to_response(pending),
            )

        # If no pending, return the most recent request
        result = await self.db.execute(
            select(JoinRequest)
            .where(
                JoinRequest.project_id == project_id,
                JoinRequest.user_id == user.id,
            )
            .order_by(JoinRequest.created_at.desc())
            .limit(1)
        )
        most_recent = result.scalar_one_or_none()

        if most_recent:
            return MyJoinRequestResponse(
                has_pending_request=False,
                request=self._to_response(most_recent),
            )

        return MyJoinRequestResponse(
            has_pending_request=False,
            request=None,
        )

    async def get_pending_summary(self, user: CurrentUser) -> PendingJoinRequestsSummary:
        """Get a summary of pending join requests across projects the user manages."""
        if user.is_superadmin:
            # Superadmins see all pending requests across all public projects
            query = (
                select(
                    JoinRequest.project_id,
                    Project.name.label("project_name"),
                    func.count().label("pending_count"),
                )
                .join(Project, JoinRequest.project_id == Project.id)
                .where(
                    JoinRequest.status == JoinRequestStatus.PENDING,
                    Project.is_public.is_(True),
                )
                .group_by(JoinRequest.project_id, Project.name)
            )
        else:
            # Regular admins/owners see pending requests for projects they manage
            query = (
                select(
                    JoinRequest.project_id,
                    Project.name.label("project_name"),
                    func.count().label("pending_count"),
                )
                .join(Project, JoinRequest.project_id == Project.id)
                .join(
                    ProjectMember,
                    (ProjectMember.project_id == JoinRequest.project_id)
                    & (ProjectMember.user_id == user.id)
                    & (ProjectMember.role.in_(["owner", "admin"])),
                )
                .where(
                    JoinRequest.status == JoinRequestStatus.PENDING,
                    Project.is_public.is_(True),
                )
                .group_by(JoinRequest.project_id, Project.name)
            )

        result = await self.db.execute(query)
        rows = result.all()

        by_project = [
            ProjectPendingCount(
                project_id=row.project_id,
                project_name=row.project_name,
                pending_count=row.pending_count,
            )
            for row in rows
        ]

        total_pending = sum(p.pending_count for p in by_project)

        return PendingJoinRequestsSummary(
            total_pending=total_pending,
            by_project=by_project,
        )


def get_join_request_service(db: AsyncSession) -> JoinRequestService:
    """Create a JoinRequestService instance."""
    return JoinRequestService(db)
