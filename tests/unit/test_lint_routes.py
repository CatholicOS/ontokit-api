"""Tests for lint routes."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

PROJECT_ID = "12345678-1234-5678-1234-567812345678"
RUN_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


class TestLintRules:
    """Tests for GET /api/v1/projects/lint/rules (no auth required)."""

    @patch("ontokit.api.routes.lint.get_available_rules")
    def test_get_lint_rules_returns_list(self, mock_rules: MagicMock, client: TestClient) -> None:
        """GET /api/v1/projects/lint/rules returns available rules."""
        mock_rules.return_value = [
            SimpleNamespace(
                rule_id="R001",
                name="Missing label",
                description="Class has no label",
                severity="warning",
            ),
            SimpleNamespace(
                rule_id="R002",
                name="Orphan class",
                description="Class has no parent",
                severity="info",
            ),
        ]

        response = client.get("/api/v1/projects/lint/rules")
        assert response.status_code == 200
        data = response.json()
        assert len(data["rules"]) == 2
        assert data["rules"][0]["rule_id"] == "R001"
        assert data["rules"][1]["severity"] == "info"

    @patch("ontokit.api.routes.lint.get_available_rules")
    def test_get_lint_rules_empty(self, mock_rules: MagicMock, client: TestClient) -> None:
        """Returns empty rules list when no rules are defined."""
        mock_rules.return_value = []

        response = client.get("/api/v1/projects/lint/rules")
        assert response.status_code == 200
        assert response.json()["rules"] == []


class TestTriggerLint:
    """Tests for POST /api/v1/projects/{id}/lint/run."""

    @patch("ontokit.api.routes.lint.get_arq_pool", new_callable=AsyncMock)
    @patch("ontokit.api.routes.lint.verify_project_access", new_callable=AsyncMock)
    def test_trigger_lint_success(
        self,
        mock_access: AsyncMock,
        mock_pool_fn: AsyncMock,
        authed_client: tuple[TestClient, AsyncMock],
    ) -> None:
        """Trigger lint returns 202 with job_id on success."""
        client, mock_session = authed_client

        mock_project = Mock()
        mock_project.source_file_path = "ontology.ttl"
        mock_access.return_value = mock_project

        # No existing running lint
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        mock_pool = AsyncMock()
        mock_pool.enqueue_job.return_value = Mock(job_id="job-42")
        mock_pool_fn.return_value = mock_pool

        response = client.post(f"/api/v1/projects/{PROJECT_ID}/lint/run")
        assert response.status_code == 202
        data = response.json()
        assert data["job_id"] == "job-42"
        assert data["status"] == "queued"

    @patch("ontokit.api.routes.lint.verify_project_access", new_callable=AsyncMock)
    def test_trigger_lint_no_ontology_file(
        self,
        mock_access: AsyncMock,
        authed_client: tuple[TestClient, AsyncMock],
    ) -> None:
        """Returns 400 when project has no source file."""
        client, _ = authed_client

        mock_project = Mock()
        mock_project.source_file_path = None
        mock_access.return_value = mock_project

        response = client.post(f"/api/v1/projects/{PROJECT_ID}/lint/run")
        assert response.status_code == 400
        assert "no ontology file" in response.json()["detail"].lower()

    @patch("ontokit.api.routes.lint.verify_project_access", new_callable=AsyncMock)
    def test_trigger_lint_already_running(
        self,
        mock_access: AsyncMock,
        authed_client: tuple[TestClient, AsyncMock],
    ) -> None:
        """Returns 409 when a lint run is already in progress."""
        client, mock_session = authed_client

        mock_project = Mock()
        mock_project.source_file_path = "ontology.ttl"
        mock_access.return_value = mock_project

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = Mock()  # existing run
        mock_session.execute.return_value = mock_result

        response = client.post(f"/api/v1/projects/{PROJECT_ID}/lint/run")
        assert response.status_code == 409
        assert "already in progress" in response.json()["detail"].lower()


class TestLintStatus:
    """Tests for GET /api/v1/projects/{id}/lint/status."""

    @patch("ontokit.api.routes.lint.verify_project_access", new_callable=AsyncMock)
    def test_lint_status_no_runs(
        self,
        mock_access: AsyncMock,
        authed_client: tuple[TestClient, AsyncMock],
    ) -> None:
        """Returns summary with no last_run when no runs exist."""
        client, mock_session = authed_client
        mock_access.return_value = Mock()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        response = client.get(f"/api/v1/projects/{PROJECT_ID}/lint/status")
        assert response.status_code == 200
        data = response.json()
        assert data["last_run"] is None
        assert data["total_issues"] == 0


class TestListLintRuns:
    """Tests for GET /api/v1/projects/{id}/lint/runs."""

    @patch("ontokit.api.routes.lint.verify_project_access", new_callable=AsyncMock)
    def test_list_lint_runs_empty(
        self,
        mock_access: AsyncMock,
        authed_client: tuple[TestClient, AsyncMock],
    ) -> None:
        """Returns empty list when no runs exist."""
        client, mock_session = authed_client
        mock_access.return_value = Mock()

        # First call: count query, second call: runs query
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 0

        mock_runs_result = MagicMock()
        mock_runs_result.scalars.return_value.all.return_value = []

        mock_session.execute.side_effect = [mock_count_result, mock_runs_result]

        response = client.get(f"/api/v1/projects/{PROJECT_ID}/lint/runs")
        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0


class TestGetLintRun:
    """Tests for GET /api/v1/projects/{id}/lint/runs/{run_id}."""

    @patch("ontokit.api.routes.lint.verify_project_access", new_callable=AsyncMock)
    def test_get_lint_run_not_found(
        self,
        mock_access: AsyncMock,
        authed_client: tuple[TestClient, AsyncMock],
    ) -> None:
        """Returns 404 when run does not exist."""
        client, mock_session = authed_client
        mock_access.return_value = Mock()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        response = client.get(f"/api/v1/projects/{PROJECT_ID}/lint/runs/{RUN_ID}")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @patch("ontokit.api.routes.lint.verify_project_access", new_callable=AsyncMock)
    def test_get_lint_run_with_issues(
        self,
        mock_access: AsyncMock,
        authed_client: tuple[TestClient, AsyncMock],
    ) -> None:
        """Returns run details with issues when run exists."""
        client, mock_session = authed_client
        mock_access.return_value = Mock()

        run_uuid = UUID(RUN_ID)
        project_uuid = UUID(PROJECT_ID)
        now = datetime.now(UTC)

        mock_run = Mock()
        mock_run.id = run_uuid
        mock_run.project_id = project_uuid
        mock_run.status = "completed"
        mock_run.started_at = now
        mock_run.completed_at = now
        mock_run.issues_found = 1
        mock_run.error_message = None

        mock_issue = Mock()
        mock_issue.id = uuid4()
        mock_issue.run_id = run_uuid
        mock_issue.project_id = project_uuid
        mock_issue.issue_type = "warning"
        mock_issue.rule_id = "R001"
        mock_issue.message = "Missing label"
        mock_issue.subject_iri = "http://example.org/Foo"
        mock_issue.details = None
        mock_issue.created_at = now
        mock_issue.resolved_at = None

        # First execute: get run, second: get issues
        mock_run_result = MagicMock()
        mock_run_result.scalar_one_or_none.return_value = mock_run

        mock_issues_result = MagicMock()
        mock_issues_result.scalars.return_value.all.return_value = [mock_issue]

        mock_session.execute.side_effect = [mock_run_result, mock_issues_result]

        response = client.get(f"/api/v1/projects/{PROJECT_ID}/lint/runs/{RUN_ID}")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert len(data["issues"]) == 1
        assert data["issues"][0]["rule_id"] == "R001"
