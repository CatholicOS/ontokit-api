"""Tests for notification routes."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from ontokit.api.routes.notifications import get_service
from ontokit.main import app
from ontokit.schemas.notification import NotificationListResponse, NotificationResponse
from ontokit.services.notification_service import NotificationService

PROJECT_ID = UUID("12345678-1234-5678-1234-567812345678")
NOTIF_ID = uuid4()


def _make_notification_response(**overrides: object) -> NotificationResponse:
    """Build a NotificationResponse with sensible defaults."""
    defaults = {
        "id": NOTIF_ID,
        "type": "pr_created",
        "title": "New pull request",
        "body": "PR #1 opened",
        "project_id": PROJECT_ID,
        "project_name": "Test Project",
        "target_id": None,
        "target_url": None,
        "is_read": False,
        "created_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    return NotificationResponse(**defaults)  # type: ignore[arg-type]


class TestListNotifications:
    """Tests for GET /api/v1/notifications."""

    def test_list_notifications_success(self, authed_client: tuple[TestClient, AsyncMock]) -> None:
        """Returns notification list for authenticated user."""
        client, _ = authed_client

        mock_service = AsyncMock(spec=NotificationService)
        mock_service.list_notifications.return_value = NotificationListResponse(
            items=[_make_notification_response()],
            total=1,
            unread_count=1,
        )
        app.dependency_overrides[get_service] = lambda: mock_service

        response = client.get("/api/v1/notifications")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["unread_count"] == 1
        assert len(data["items"]) == 1

        app.dependency_overrides.pop(get_service, None)

    def test_list_notifications_empty(self, authed_client: tuple[TestClient, AsyncMock]) -> None:
        """Returns empty list when user has no notifications."""
        client, _ = authed_client

        mock_service = AsyncMock(spec=NotificationService)
        mock_service.list_notifications.return_value = NotificationListResponse(
            items=[], total=0, unread_count=0
        )
        app.dependency_overrides[get_service] = lambda: mock_service

        response = client.get("/api/v1/notifications")
        assert response.status_code == 200
        assert response.json()["items"] == []

        app.dependency_overrides.pop(get_service, None)

    def test_list_notifications_unread_only(
        self, authed_client: tuple[TestClient, AsyncMock]
    ) -> None:
        """Passing unread_only=true filters notifications."""
        client, _ = authed_client

        mock_service = AsyncMock(spec=NotificationService)
        mock_service.list_notifications.return_value = NotificationListResponse(
            items=[], total=0, unread_count=0
        )
        app.dependency_overrides[get_service] = lambda: mock_service

        response = client.get("/api/v1/notifications", params={"unread_only": "true"})
        assert response.status_code == 200
        mock_service.list_notifications.assert_called_once_with("test-user-id", unread_only=True)

        app.dependency_overrides.pop(get_service, None)


class TestMarkNotificationRead:
    """Tests for POST /api/v1/notifications/{id}/read."""

    def test_mark_read_success(self, authed_client: tuple[TestClient, AsyncMock]) -> None:
        """Returns 204 when notification is successfully marked as read."""
        client, _ = authed_client

        mock_service = AsyncMock(spec=NotificationService)
        mock_service.mark_read.return_value = True
        app.dependency_overrides[get_service] = lambda: mock_service

        response = client.post(f"/api/v1/notifications/{NOTIF_ID}/read")
        assert response.status_code == 204

        app.dependency_overrides.pop(get_service, None)

    def test_mark_read_not_found(self, authed_client: tuple[TestClient, AsyncMock]) -> None:
        """Returns 404 when notification does not exist."""
        client, _ = authed_client

        mock_service = AsyncMock(spec=NotificationService)
        mock_service.mark_read.return_value = False
        app.dependency_overrides[get_service] = lambda: mock_service

        response = client.post(f"/api/v1/notifications/{uuid4()}/read")
        assert response.status_code == 404

        app.dependency_overrides.pop(get_service, None)


class TestMarkAllNotificationsRead:
    """Tests for POST /api/v1/notifications/read-all."""

    def test_mark_all_read_success(self, authed_client: tuple[TestClient, AsyncMock]) -> None:
        """Returns 204 when all notifications are marked read."""
        client, _ = authed_client

        mock_service = AsyncMock(spec=NotificationService)
        mock_service.mark_all_read.return_value = 5
        app.dependency_overrides[get_service] = lambda: mock_service

        response = client.post("/api/v1/notifications/read-all")
        assert response.status_code == 204

        app.dependency_overrides.pop(get_service, None)
