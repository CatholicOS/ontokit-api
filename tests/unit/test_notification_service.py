"""Tests for NotificationService (ontokit/services/notification_service.py)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from ontokit.services.notification_service import NotificationService, get_notification_service

PROJECT_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
PROJECT_NAME = "Test Project"
USER_ID = "user-123"
ACTOR_ID = "actor-456"


def _make_notification_obj(
    *,
    user_id: str = USER_ID,
    notification_type: str = "pr_created",
    title: str = "New PR",
    is_read: bool = False,
) -> MagicMock:
    """Create a mock Notification ORM object."""
    notif = MagicMock()
    notif.id = uuid.uuid4()
    notif.user_id = user_id
    notif.type = notification_type
    notif.title = title
    notif.body = None
    notif.project_id = PROJECT_ID
    notif.project_name = PROJECT_NAME
    notif.target_id = None
    notif.target_url = None
    notif.is_read = is_read
    notif.created_at = datetime.now(UTC)
    return notif


@pytest.fixture
def mock_db() -> AsyncMock:
    """Create an async mock of AsyncSession."""
    session = AsyncMock()
    session.commit = AsyncMock()
    session.add = Mock()
    session.execute = AsyncMock()
    return session


@pytest.fixture
def service(mock_db: AsyncMock) -> NotificationService:
    """Create a NotificationService with mocked DB."""
    return NotificationService(mock_db)


class TestCreateNotification:
    """Tests for create_notification()."""

    @pytest.mark.asyncio
    async def test_creates_and_adds_to_session(
        self, service: NotificationService, mock_db: AsyncMock
    ) -> None:
        """create_notification adds a Notification to the session and returns it."""
        result = await service.create_notification(
            user_id=USER_ID,
            notification_type="pr_created",
            title="New PR opened",
            project_id=PROJECT_ID,
            project_name=PROJECT_NAME,
            body="PR #1 description",
            target_id="pr-1",
            target_url="/projects/test/prs/1",
        )
        mock_db.add.assert_called_once()
        added_obj = mock_db.add.call_args[0][0]
        assert added_obj.user_id == USER_ID
        assert added_obj.type == "pr_created"
        assert added_obj.title == "New PR opened"
        assert added_obj.body == "PR #1 description"
        assert added_obj.project_id == PROJECT_ID
        assert result is added_obj

    @pytest.mark.asyncio
    async def test_optional_fields_default_to_none(
        self, service: NotificationService, mock_db: AsyncMock
    ) -> None:
        """Optional fields (body, target_id, target_url) default to None."""
        await service.create_notification(
            user_id=USER_ID,
            notification_type="member_added",
            title="You were added",
            project_id=PROJECT_ID,
            project_name=PROJECT_NAME,
        )
        added_obj = mock_db.add.call_args[0][0]
        assert added_obj.body is None
        assert added_obj.target_id is None
        assert added_obj.target_url is None


class TestNotifyProjectRoles:
    """Tests for notify_project_roles()."""

    @pytest.mark.asyncio
    async def test_creates_notifications_for_matching_members(
        self, service: NotificationService, mock_db: AsyncMock
    ) -> None:
        """Notifications are created for all members with matching roles."""
        # Mock DB to return two user IDs
        mock_result = MagicMock()
        mock_result.all.return_value = [("user-a",), ("user-b",)]
        mock_db.execute.return_value = mock_result

        await service.notify_project_roles(
            project_id=PROJECT_ID,
            project_name=PROJECT_NAME,
            roles=["owner", "admin"],
            notification_type="lint_complete",
            title="Lint finished",
        )

        # Two notifications should have been added (one per user)
        assert mock_db.add.call_count == 2
        user_ids = [call[0][0].user_id for call in mock_db.add.call_args_list]
        assert set(user_ids) == {"user-a", "user-b"}

    @pytest.mark.asyncio
    async def test_excludes_actor(self, service: NotificationService, mock_db: AsyncMock) -> None:
        """The exclude_user_id (actor) does not receive a notification."""
        mock_result = MagicMock()
        mock_result.all.return_value = [("user-a",), (ACTOR_ID,), ("user-c",)]
        mock_db.execute.return_value = mock_result

        await service.notify_project_roles(
            project_id=PROJECT_ID,
            project_name=PROJECT_NAME,
            roles=["owner"],
            notification_type="pr_merged",
            title="PR merged",
            exclude_user_id=ACTOR_ID,
        )

        assert mock_db.add.call_count == 2
        user_ids = [call[0][0].user_id for call in mock_db.add.call_args_list]
        assert ACTOR_ID not in user_ids

    @pytest.mark.asyncio
    async def test_no_matching_members(
        self, service: NotificationService, mock_db: AsyncMock
    ) -> None:
        """No notifications created when no members match the roles."""
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_db.execute.return_value = mock_result

        await service.notify_project_roles(
            project_id=PROJECT_ID,
            project_name=PROJECT_NAME,
            roles=["admin"],
            notification_type="test",
            title="Test",
        )

        mock_db.add.assert_not_called()


class TestListNotifications:
    """Tests for list_notifications()."""

    @pytest.mark.asyncio
    async def test_returns_items_with_unread_count(
        self, service: NotificationService, mock_db: AsyncMock
    ) -> None:
        """list_notifications returns items, total, and unread_count."""
        notif1 = _make_notification_obj(is_read=False)
        notif2 = _make_notification_obj(is_read=True)

        # First execute: items query
        items_result = MagicMock()
        items_result.scalars.return_value.all.return_value = [notif1, notif2]

        # Second execute: total count
        total_result = MagicMock()
        total_result.scalar.return_value = 2

        # Third execute: unread count
        unread_result = MagicMock()
        unread_result.scalar.return_value = 1

        mock_db.execute.side_effect = [items_result, total_result, unread_result]

        response = await service.list_notifications(USER_ID)
        assert response.total == 2
        assert response.unread_count == 1
        assert len(response.items) == 2

    @pytest.mark.asyncio
    async def test_empty_results(self, service: NotificationService, mock_db: AsyncMock) -> None:
        """list_notifications returns zeroes for empty results."""
        items_result = MagicMock()
        items_result.scalars.return_value.all.return_value = []

        total_result = MagicMock()
        total_result.scalar.return_value = 0

        unread_result = MagicMock()
        unread_result.scalar.return_value = 0

        mock_db.execute.side_effect = [items_result, total_result, unread_result]

        response = await service.list_notifications(USER_ID, unread_only=True)
        assert response.total == 0
        assert response.unread_count == 0
        assert response.items == []


class TestMarkRead:
    """Tests for mark_read()."""

    @pytest.mark.asyncio
    async def test_mark_read_returns_true_when_updated(
        self, service: NotificationService, mock_db: AsyncMock
    ) -> None:
        """mark_read returns True when a notification was found and updated."""
        result_mock = MagicMock()
        result_mock.rowcount = 1
        mock_db.execute.return_value = result_mock

        notif_id = uuid.uuid4()
        result = await service.mark_read(notif_id, USER_ID)
        assert result is True
        mock_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_mark_read_returns_false_when_not_found(
        self, service: NotificationService, mock_db: AsyncMock
    ) -> None:
        """mark_read returns False when notification not found."""
        result_mock = MagicMock()
        result_mock.rowcount = 0
        mock_db.execute.return_value = result_mock

        notif_id = uuid.uuid4()
        result = await service.mark_read(notif_id, USER_ID)
        assert result is False


class TestMarkAllRead:
    """Tests for mark_all_read()."""

    @pytest.mark.asyncio
    async def test_mark_all_read_returns_count(
        self, service: NotificationService, mock_db: AsyncMock
    ) -> None:
        """mark_all_read returns the number of notifications updated."""
        result_mock = MagicMock()
        result_mock.rowcount = 5
        mock_db.execute.return_value = result_mock

        count = await service.mark_all_read(USER_ID)
        assert count == 5
        mock_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_mark_all_read_returns_zero_when_none_unread(
        self, service: NotificationService, mock_db: AsyncMock
    ) -> None:
        """mark_all_read returns 0 when no unread notifications exist."""
        result_mock = MagicMock()
        result_mock.rowcount = 0
        mock_db.execute.return_value = result_mock

        count = await service.mark_all_read(USER_ID)
        assert count == 0


class TestGetNotificationService:
    """Tests for the factory function."""

    def test_returns_service_instance(self, mock_db: AsyncMock) -> None:
        """get_notification_service returns a NotificationService."""
        svc = get_notification_service(mock_db)
        assert isinstance(svc, NotificationService)
        assert svc.db is mock_db
