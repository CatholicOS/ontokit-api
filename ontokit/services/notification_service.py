"""Notification service for creating and managing user notifications."""

import logging
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ontokit.models.notification import Notification
from ontokit.models.project import ProjectMember
from ontokit.schemas.notification import NotificationListResponse, NotificationResponse

logger = logging.getLogger(__name__)


class NotificationService:
    """Service for notification CRUD operations."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_notification(
        self,
        *,
        user_id: str,
        notification_type: str,
        title: str,
        project_id: UUID,
        project_name: str,
        body: str | None = None,
        target_id: str | None = None,
        target_url: str | None = None,
    ) -> Notification:
        """Create a single notification for a user."""
        notification = Notification(
            user_id=user_id,
            type=notification_type,
            title=title,
            body=body,
            project_id=project_id,
            project_name=project_name,
            target_id=target_id,
            target_url=target_url,
        )
        self.db.add(notification)
        return notification

    async def notify_project_roles(
        self,
        *,
        project_id: UUID,
        project_name: str,
        roles: list[str],
        notification_type: str,
        title: str,
        body: str | None = None,
        target_id: str | None = None,
        target_url: str | None = None,
        exclude_user_id: str | None = None,
    ) -> None:
        """Create notifications for all project members with the given roles.

        Args:
            exclude_user_id: Skip this user (e.g. the actor who triggered the event).
        """
        result = await self.db.execute(
            select(ProjectMember.user_id).where(
                ProjectMember.project_id == project_id,
                ProjectMember.role.in_(roles),
            )
        )
        user_ids = [row[0] for row in result.all()]

        for uid in user_ids:
            if uid == exclude_user_id:
                continue
            await self.create_notification(
                user_id=uid,
                notification_type=notification_type,
                title=title,
                body=body,
                project_id=project_id,
                project_name=project_name,
                target_id=target_id,
                target_url=target_url,
            )

    async def list_notifications(
        self,
        user_id: str,
        *,
        unread_only: bool = False,
    ) -> NotificationListResponse:
        """List notifications for a user."""
        base_filter = Notification.user_id == user_id

        query = select(Notification).where(base_filter)
        if unread_only:
            query = query.where(Notification.is_read.is_(False))
        query = query.order_by(Notification.created_at.desc()).limit(100)

        result = await self.db.execute(query)
        notifications = list(result.scalars().all())

        # Total count (respecting unread_only filter)
        count_query = select(func.count()).select_from(Notification).where(base_filter)
        if unread_only:
            count_query = count_query.where(Notification.is_read.is_(False))
        total = (await self.db.execute(count_query)).scalar() or 0

        # Unread count (always computed)
        unread_count_result = await self.db.execute(
            select(func.count())
            .select_from(Notification)
            .where(base_filter, Notification.is_read.is_(False))
        )
        unread_count = unread_count_result.scalar() or 0

        return NotificationListResponse(
            items=[NotificationResponse.model_validate(n) for n in notifications],
            total=total,
            unread_count=unread_count,
        )

    async def mark_read(self, notification_id: UUID, user_id: str) -> bool:
        """Mark a single notification as read. Returns True if found and updated."""
        result = await self.db.execute(
            update(Notification)
            .where(Notification.id == notification_id, Notification.user_id == user_id)
            .values(is_read=True)
        )
        await self.db.commit()
        return result.rowcount > 0  # type: ignore[attr-defined, no-any-return]

    async def mark_all_read(self, user_id: str) -> int:
        """Mark all notifications as read for a user. Returns count updated."""
        result = await self.db.execute(
            update(Notification)
            .where(Notification.user_id == user_id, Notification.is_read.is_(False))
            .values(is_read=True)
        )
        await self.db.commit()
        return result.rowcount  # type: ignore[attr-defined, no-any-return]


def get_notification_service(db: AsyncSession) -> NotificationService:
    """Factory function for dependency injection."""
    return NotificationService(db)
