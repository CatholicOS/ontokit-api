"""Extended tests for lint routes – covers uncovered paths."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from uuid import UUID, uuid4

import pytest
from fastapi import WebSocket
from fastapi.testclient import TestClient

from ontokit.api.routes.lint import LintConnectionManager

PROJECT_ID = "12345678-1234-5678-1234-567812345678"
RUN_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
ISSUE_ID = "cccccccc-dddd-eeee-ffff-111111111111"


class TestVerifyProjectAccessErrors:
    """Tests for verify_project_access error paths (lines 63-85)."""

    @patch("ontokit.api.routes.lint.get_project_service")
    def test_project_not_found_returns_404(
        self,
        mock_get_svc: MagicMock,
        authed_client: tuple[TestClient, AsyncMock],
    ) -> None:
        """Returns 404 when DB query finds no project after service.get succeeds."""
        client, mock_session = authed_client

        # service.get returns successfully (a project response)
        mock_svc = AsyncMock()
        mock_svc.get.return_value = SimpleNamespace(user_role="owner")
        mock_get_svc.return_value = mock_svc

        # But the DB query for the Project model returns None
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        # Use dismiss_issue endpoint since it calls verify_project_access
        response = client.delete(f"/api/v1/projects/{PROJECT_ID}/lint/issues/{ISSUE_ID}")
        assert response.status_code == 404
        assert "project not found" in response.json()["detail"].lower()

    @patch("ontokit.api.routes.lint.get_project_service")
    def test_write_access_forbidden_for_viewer(
        self,
        mock_get_svc: MagicMock,
        authed_client: tuple[TestClient, AsyncMock],
    ) -> None:
        """Returns 403 when user has viewer role and write access is required."""
        client, mock_session = authed_client

        # service.get returns with viewer role
        mock_svc = AsyncMock()
        mock_svc.get.return_value = SimpleNamespace(user_role="viewer")
        mock_get_svc.return_value = mock_svc

        # DB query returns a project
        mock_project = Mock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_project
        mock_session.execute.return_value = mock_result

        # dismiss_issue requires write access
        response = client.delete(f"/api/v1/projects/{PROJECT_ID}/lint/issues/{ISSUE_ID}")
        assert response.status_code == 403
        assert "write access required" in response.json()["detail"].lower()


class TestLintStatusWithCompletedRun:
    """Tests for get_lint_status with a completed run (lines 180-204)."""

    @patch("ontokit.api.routes.lint.verify_project_access", new_callable=AsyncMock)
    def test_lint_status_with_completed_run(
        self,
        mock_access: AsyncMock,
        authed_client: tuple[TestClient, AsyncMock],
    ) -> None:
        """Returns summary with issue counts when a completed run exists."""
        client, mock_session = authed_client
        mock_access.return_value = Mock()

        now = datetime.now(UTC)
        run_uuid = UUID(RUN_ID)
        project_uuid = UUID(PROJECT_ID)

        mock_run = Mock()
        mock_run.id = run_uuid
        mock_run.project_id = project_uuid
        mock_run.status = "completed"
        mock_run.started_at = now
        mock_run.completed_at = now
        mock_run.issues_found = 5
        mock_run.error_message = None

        # First execute: get most recent run
        mock_run_result = MagicMock()
        mock_run_result.scalar_one_or_none.return_value = mock_run

        # Second execute: count issues by type
        mock_count_result = MagicMock()
        mock_count_result.all.return_value = [
            ("error", 2),
            ("warning", 2),
            ("info", 1),
        ]

        mock_session.execute.side_effect = [mock_run_result, mock_count_result]

        response = client.get(f"/api/v1/projects/{PROJECT_ID}/lint/status")
        assert response.status_code == 200
        data = response.json()
        assert data["error_count"] == 2
        assert data["warning_count"] == 2
        assert data["info_count"] == 1
        assert data["total_issues"] == 5
        assert data["last_run"] is not None
        assert data["last_run"]["status"] == "completed"
        assert data["last_run"]["issues_found"] == 5


class TestGetLintIssuesFilters:
    """Tests for get_lint_issues with rule_id and subject_iri filters (lines 374, 377)."""

    @patch("ontokit.api.routes.lint.verify_project_access", new_callable=AsyncMock)
    def test_get_issues_with_rule_id_filter(
        self,
        mock_access: AsyncMock,
        authed_client: tuple[TestClient, AsyncMock],
    ) -> None:
        """Returns filtered issues when rule_id query param is provided."""
        client, mock_session = authed_client
        mock_access.return_value = Mock()

        now = datetime.now(UTC)
        project_uuid = UUID(PROJECT_ID)
        run_uuid = UUID(RUN_ID)

        mock_run = Mock()
        mock_run.id = run_uuid
        mock_run.status = "completed"

        mock_issue = Mock()
        mock_issue.id = uuid4()
        mock_issue.run_id = run_uuid
        mock_issue.project_id = project_uuid
        mock_issue.issue_type = "warning"
        mock_issue.rule_id = "R005"
        mock_issue.message = "Missing comment"
        mock_issue.subject_iri = "http://example.org/Foo"
        mock_issue.details = None
        mock_issue.created_at = now
        mock_issue.resolved_at = None

        # 1st: find last completed run, 2nd: count, 3rd: issues
        mock_run_result = MagicMock()
        mock_run_result.scalar_one_or_none.return_value = mock_run

        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 1

        mock_issues_result = MagicMock()
        mock_issues_result.scalars.return_value.all.return_value = [mock_issue]

        mock_session.execute.side_effect = [
            mock_run_result,
            mock_count_result,
            mock_issues_result,
        ]

        response = client.get(f"/api/v1/projects/{PROJECT_ID}/lint/issues?rule_id=R005")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["rule_id"] == "R005"

    @patch("ontokit.api.routes.lint.verify_project_access", new_callable=AsyncMock)
    def test_get_issues_with_subject_iri_filter(
        self,
        mock_access: AsyncMock,
        authed_client: tuple[TestClient, AsyncMock],
    ) -> None:
        """Returns filtered issues when subject_iri query param is provided."""
        client, mock_session = authed_client
        mock_access.return_value = Mock()

        now = datetime.now(UTC)
        project_uuid = UUID(PROJECT_ID)
        run_uuid = UUID(RUN_ID)

        mock_run = Mock()
        mock_run.id = run_uuid
        mock_run.status = "completed"

        mock_issue = Mock()
        mock_issue.id = uuid4()
        mock_issue.run_id = run_uuid
        mock_issue.project_id = project_uuid
        mock_issue.issue_type = "error"
        mock_issue.rule_id = "R010"
        mock_issue.message = "Cyclic dependency"
        mock_issue.subject_iri = "http://example.org/SpecificClass"
        mock_issue.details = None
        mock_issue.created_at = now
        mock_issue.resolved_at = None

        mock_run_result = MagicMock()
        mock_run_result.scalar_one_or_none.return_value = mock_run

        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 1

        mock_issues_result = MagicMock()
        mock_issues_result.scalars.return_value.all.return_value = [mock_issue]

        mock_session.execute.side_effect = [
            mock_run_result,
            mock_count_result,
            mock_issues_result,
        ]

        response = client.get(
            f"/api/v1/projects/{PROJECT_ID}/lint/issues"
            "?subject_iri=http%3A%2F%2Fexample.org%2FSpecificClass"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["subject_iri"] == "http://example.org/SpecificClass"


class TestDismissIssue:
    """Tests for DELETE /{project_id}/lint/issues/{issue_id} (lines 444-466)."""

    @patch("ontokit.api.routes.lint.verify_project_access", new_callable=AsyncMock)
    def test_dismiss_issue_success(
        self,
        mock_access: AsyncMock,
        authed_client: tuple[TestClient, AsyncMock],
    ) -> None:
        """Returns 204 when issue is successfully dismissed."""
        client, mock_session = authed_client
        mock_access.return_value = Mock()

        mock_issue = Mock()
        mock_issue.resolved_at = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_issue
        mock_session.execute.return_value = mock_result

        response = client.delete(f"/api/v1/projects/{PROJECT_ID}/lint/issues/{ISSUE_ID}")
        assert response.status_code == 204
        # Verify resolved_at was set
        assert mock_issue.resolved_at is not None
        mock_session.commit.assert_awaited_once()

    @patch("ontokit.api.routes.lint.verify_project_access", new_callable=AsyncMock)
    def test_dismiss_issue_not_found(
        self,
        mock_access: AsyncMock,
        authed_client: tuple[TestClient, AsyncMock],
    ) -> None:
        """Returns 404 when issue does not exist."""
        client, mock_session = authed_client
        mock_access.return_value = Mock()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        response = client.delete(f"/api/v1/projects/{PROJECT_ID}/lint/issues/{ISSUE_ID}")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @patch("ontokit.api.routes.lint.verify_project_access", new_callable=AsyncMock)
    def test_dismiss_issue_already_resolved(
        self,
        mock_access: AsyncMock,
        authed_client: tuple[TestClient, AsyncMock],
    ) -> None:
        """Returns 400 when issue is already resolved."""
        client, mock_session = authed_client
        mock_access.return_value = Mock()

        mock_issue = Mock()
        mock_issue.resolved_at = datetime.now(UTC)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_issue
        mock_session.execute.return_value = mock_result

        response = client.delete(f"/api/v1/projects/{PROJECT_ID}/lint/issues/{ISSUE_ID}")
        assert response.status_code == 400
        assert "already resolved" in response.json()["detail"].lower()


class TestLintConnectionManager:
    """Tests for LintConnectionManager disconnect() and broadcast() (lines 500-527)."""

    def test_disconnect_removes_websocket(self) -> None:
        """disconnect() removes the websocket from active connections."""
        mgr = LintConnectionManager()
        ws = Mock(spec=WebSocket)
        project_id = "test-project"

        # Manually add the connection (bypassing accept)
        mgr.active_connections[project_id] = [ws]

        mgr.disconnect(ws, project_id)
        assert project_id not in mgr.active_connections

    def test_disconnect_keeps_other_connections(self) -> None:
        """disconnect() only removes the specific websocket, keeps others."""
        mgr = LintConnectionManager()
        ws1 = Mock(spec=WebSocket)
        ws2 = Mock(spec=WebSocket)
        project_id = "test-project"

        mgr.active_connections[project_id] = [ws1, ws2]

        mgr.disconnect(ws1, project_id)
        assert mgr.active_connections[project_id] == [ws2]

    def test_disconnect_nonexistent_project(self) -> None:
        """disconnect() is a no-op if the project has no connections."""
        mgr = LintConnectionManager()
        ws = Mock(spec=WebSocket)

        # Should not raise
        mgr.disconnect(ws, "nonexistent")
        assert "nonexistent" not in mgr.active_connections

    @pytest.mark.asyncio
    async def test_broadcast_sends_to_connected(self) -> None:
        """broadcast() sends message to all connected websockets for a project."""
        mgr = LintConnectionManager()
        ws1 = AsyncMock(spec=WebSocket)
        ws2 = AsyncMock(spec=WebSocket)
        project_id = "test-project"

        mgr.active_connections[project_id] = [ws1, ws2]

        message: dict[str, object] = {"type": "lint_complete", "issues": 3}
        await mgr.broadcast(project_id, message)

        ws1.send_json.assert_awaited_once_with(message)
        ws2.send_json.assert_awaited_once_with(message)

    @pytest.mark.asyncio
    async def test_broadcast_cleans_up_disconnected(self) -> None:
        """broadcast() removes websockets that raise on send."""
        mgr = LintConnectionManager()
        good_ws = AsyncMock(spec=WebSocket)
        bad_ws = AsyncMock(spec=WebSocket)
        bad_ws.send_json.side_effect = RuntimeError("Connection closed")
        project_id = "test-project"

        mgr.active_connections[project_id] = [good_ws, bad_ws]

        message: dict[str, object] = {"type": "lint_update"}
        await mgr.broadcast(project_id, message)

        good_ws.send_json.assert_awaited_once_with(message)
        # bad_ws should have been cleaned up
        assert bad_ws not in mgr.active_connections.get(project_id, [])

    @pytest.mark.asyncio
    async def test_broadcast_no_connections(self) -> None:
        """broadcast() is a no-op when no connections exist for the project."""
        mgr = LintConnectionManager()
        message: dict[str, object] = {"type": "lint_complete"}
        # Should not raise
        await mgr.broadcast("nonexistent", message)

    @pytest.mark.asyncio
    async def test_connect_adds_websocket(self) -> None:
        """connect() accepts the websocket and adds it to active_connections."""
        mgr = LintConnectionManager()
        ws = AsyncMock(spec=WebSocket)
        project_id = "test-project"

        await mgr.connect(ws, project_id)

        ws.accept.assert_awaited_once()
        assert ws in mgr.active_connections[project_id]

    @pytest.mark.asyncio
    async def test_connect_multiple_to_same_project(self) -> None:
        """connect() adds multiple websockets to the same project."""
        mgr = LintConnectionManager()
        ws1 = AsyncMock(spec=WebSocket)
        ws2 = AsyncMock(spec=WebSocket)
        project_id = "test-project"

        await mgr.connect(ws1, project_id)
        await mgr.connect(ws2, project_id)

        assert len(mgr.active_connections[project_id]) == 2

    def test_disconnect_websocket_not_in_list(self) -> None:
        """disconnect() is a no-op when websocket is not in the connection list."""
        mgr = LintConnectionManager()
        ws1 = Mock(spec=WebSocket)
        ws2 = Mock(spec=WebSocket)
        project_id = "test-project"

        mgr.active_connections[project_id] = [ws1]
        # Disconnect ws2 which is not in the list - should not raise
        mgr.disconnect(ws2, project_id)
        assert mgr.active_connections[project_id] == [ws1]
