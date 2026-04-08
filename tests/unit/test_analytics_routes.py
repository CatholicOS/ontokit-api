"""Tests for analytics routes."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from ontokit.schemas.analytics import (
    ActivityDay,
    ContributorStats,
    EntityHistoryResponse,
    HotEntity,
    ProjectActivity,
    TopEditor,
)

PROJECT_ID = "12345678-1234-5678-1234-567812345678"


def _make_project_response(user_role: str = "owner") -> MagicMock:
    resp = MagicMock()
    resp.user_role = user_role
    return resp


class TestGetProjectActivity:
    """Tests for GET /api/v1/projects/{id}/analytics/activity."""

    @patch("ontokit.api.routes.analytics.ChangeEventService")
    @patch("ontokit.api.routes.analytics.get_project_service")
    def test_get_activity(
        self,
        mock_get_ps: MagicMock,
        mock_ces_cls: MagicMock,
        authed_client: tuple[TestClient, AsyncMock],
    ) -> None:  # noqa: ARG002
        """Returns project activity with daily counts."""
        client, _ = authed_client

        mock_ps = MagicMock()
        mock_ps.get = AsyncMock(return_value=_make_project_response())
        mock_get_ps.return_value = mock_ps

        activity = ProjectActivity(
            daily_counts=[ActivityDay(date="2026-04-01", count=5)],
            total_events=5,
            top_editors=[TopEditor(user_id="u1", user_name="Alice", edit_count=5)],
        )
        mock_ces = MagicMock()
        mock_ces.get_activity = AsyncMock(return_value=activity)
        mock_ces_cls.return_value = mock_ces

        response = client.get(f"/api/v1/projects/{PROJECT_ID}/analytics/activity")
        assert response.status_code == 200
        data = response.json()
        assert data["total_events"] == 5
        assert len(data["daily_counts"]) == 1

    @patch("ontokit.api.routes.analytics.ChangeEventService")
    @patch("ontokit.api.routes.analytics.get_project_service")
    def test_get_activity_with_custom_days(
        self,
        mock_get_ps: MagicMock,
        mock_ces_cls: MagicMock,
        authed_client: tuple[TestClient, AsyncMock],
    ) -> None:  # noqa: ARG002
        """Accepts custom days query param."""
        client, _ = authed_client

        mock_ps = MagicMock()
        mock_ps.get = AsyncMock(return_value=_make_project_response())
        mock_get_ps.return_value = mock_ps

        activity = ProjectActivity(daily_counts=[], total_events=0, top_editors=[])
        mock_ces = MagicMock()
        mock_ces.get_activity = AsyncMock(return_value=activity)
        mock_ces_cls.return_value = mock_ces

        response = client.get(f"/api/v1/projects/{PROJECT_ID}/analytics/activity?days=7")
        assert response.status_code == 200
        mock_ces.get_activity.assert_called_once()


class TestGetEntityHistory:
    """Tests for GET /api/v1/projects/{id}/analytics/entity/{iri}/history."""

    @patch("ontokit.api.routes.analytics.ChangeEventService")
    @patch("ontokit.api.routes.analytics.get_project_service")
    def test_get_entity_history(
        self,
        mock_get_ps: MagicMock,
        mock_ces_cls: MagicMock,
        authed_client: tuple[TestClient, AsyncMock],
    ) -> None:  # noqa: ARG002
        """Returns entity change history."""
        client, _ = authed_client

        mock_ps = MagicMock()
        mock_ps.get = AsyncMock(return_value=_make_project_response())
        mock_get_ps.return_value = mock_ps

        history = EntityHistoryResponse(
            entity_iri="http://example.org/Foo",
            events=[],
            total=0,
        )
        mock_ces = MagicMock()
        mock_ces.get_entity_history = AsyncMock(return_value=history)
        mock_ces_cls.return_value = mock_ces

        iri = "http%3A%2F%2Fexample.org%2FFoo"
        response = client.get(f"/api/v1/projects/{PROJECT_ID}/analytics/entity/{iri}/history")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0


class TestGetHotEntities:
    """Tests for GET /api/v1/projects/{id}/analytics/hot-entities."""

    @patch("ontokit.api.routes.analytics.ChangeEventService")
    @patch("ontokit.api.routes.analytics.get_project_service")
    def test_get_hot_entities(
        self,
        mock_get_ps: MagicMock,
        mock_ces_cls: MagicMock,
        authed_client: tuple[TestClient, AsyncMock],
    ) -> None:  # noqa: ARG002
        """Returns most frequently edited entities."""
        client, _ = authed_client

        mock_ps = MagicMock()
        mock_ps.get = AsyncMock(return_value=_make_project_response())
        mock_get_ps.return_value = mock_ps

        hot = [
            HotEntity(
                entity_iri="http://example.org/Person",
                entity_type="owl:Class",
                label="Person",
                edit_count=15,
                editor_count=3,
                last_edited_at="2026-04-05T12:00:00Z",
            ),
        ]
        mock_ces = MagicMock()
        mock_ces.get_hot_entities = AsyncMock(return_value=hot)
        mock_ces_cls.return_value = mock_ces

        response = client.get(f"/api/v1/projects/{PROJECT_ID}/analytics/hot-entities")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["edit_count"] == 15


class TestGetContributors:
    """Tests for GET /api/v1/projects/{id}/analytics/contributors."""

    @patch("ontokit.api.routes.analytics.ChangeEventService")
    @patch("ontokit.api.routes.analytics.get_project_service")
    def test_get_contributors(
        self,
        mock_get_ps: MagicMock,
        mock_ces_cls: MagicMock,
        authed_client: tuple[TestClient, AsyncMock],
    ) -> None:  # noqa: ARG002
        """Returns contributor statistics."""
        client, _ = authed_client

        mock_ps = MagicMock()
        mock_ps.get = AsyncMock(return_value=_make_project_response())
        mock_get_ps.return_value = mock_ps

        contributors = [
            ContributorStats(
                user_id="u1",
                user_name="Alice",
                create_count=10,
                update_count=20,
                delete_count=2,
                total_count=32,
                last_active_at="2026-04-05T12:00:00Z",
            ),
        ]
        mock_ces = MagicMock()
        mock_ces.get_contributors = AsyncMock(return_value=contributors)
        mock_ces_cls.return_value = mock_ces

        response = client.get(f"/api/v1/projects/{PROJECT_ID}/analytics/contributors")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["total_count"] == 32
        assert data[0]["user_name"] == "Alice"
