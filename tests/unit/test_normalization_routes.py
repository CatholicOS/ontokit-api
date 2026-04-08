"""Tests for normalization routes."""

from __future__ import annotations

import json
from collections.abc import Generator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from ontokit.api.routes.normalization import get_norm_service, get_service
from ontokit.main import app
from ontokit.services.normalization_service import NormalizationService
from ontokit.services.project_service import ProjectService

PROJECT_ID = "12345678-1234-5678-1234-567812345678"
RUN_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def _make_project_response(user_role: str = "owner") -> MagicMock:
    resp = MagicMock()
    resp.user_role = user_role
    resp.source_file_path = "ontology.ttl"
    return resp


def _make_norm_run(
    *,
    run_id: UUID | None = None,
    project_id: UUID | None = None,
    is_dry_run: bool = False,
) -> Mock:
    run = Mock()
    run.id = run_id or UUID(RUN_ID)
    run.project_id = project_id or UUID(PROJECT_ID)
    run.created_at = datetime.now(UTC)
    run.triggered_by = "Test User"
    run.trigger_type = "manual"
    run.report_json = json.dumps(
        {
            "original_format": "turtle",
            "original_filename": "ontology.ttl",
            "original_size_bytes": 1024,
            "normalized_size_bytes": 1100,
            "triple_count": 50,
            "prefixes_before": ["owl", "rdf", "rdfs"],
            "prefixes_after": ["owl", "rdf", "rdfs"],
            "prefixes_removed": [],
            "prefixes_added": [],
            "format_converted": False,
            "notes": ["Blank nodes renamed: 2", "Prefixes reordered"],
        }
    )
    run.is_dry_run = is_dry_run
    run.commit_hash = "abc123" if not is_dry_run else None
    return run


@pytest.fixture
def mock_project_service() -> Generator[AsyncMock, None, None]:
    """Provide an AsyncMock ProjectService and register it as a dependency override."""
    mock_svc = AsyncMock(spec=ProjectService)
    app.dependency_overrides[get_service] = lambda: mock_svc
    try:
        yield mock_svc
    finally:
        app.dependency_overrides.pop(get_service, None)


@pytest.fixture
def mock_norm_service() -> Generator[AsyncMock, None, None]:
    """Provide an AsyncMock NormalizationService and register it as a dependency override."""
    mock_svc = AsyncMock(spec=NormalizationService)
    app.dependency_overrides[get_norm_service] = lambda: mock_svc
    try:
        yield mock_svc
    finally:
        app.dependency_overrides.pop(get_norm_service, None)


class TestGetNormalizationStatus:
    """Tests for GET /api/v1/projects/{id}/normalization/status."""

    def test_get_status_returns_cached(
        self,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,
        mock_norm_service: AsyncMock,
    ) -> None:
        """Returns cached normalization status."""
        client, _ = authed_client

        mock_project_service.get = AsyncMock(return_value=_make_project_response())
        mock_project_service._get_project = AsyncMock(return_value=Mock())

        mock_norm_service.get_cached_status = AsyncMock(
            return_value={
                "needs_normalization": True,
                "last_run": None,
                "last_run_id": None,
                "last_check": None,
                "preview_report": None,
                "checking": False,
                "error": None,
            }
        )

        response = client.get(f"/api/v1/projects/{PROJECT_ID}/normalization/status")
        assert response.status_code == 200
        data = response.json()
        assert data["needs_normalization"] is True
        assert data["checking"] is False

    def test_get_status_unknown(
        self,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,
        mock_norm_service: AsyncMock,
    ) -> None:
        """Returns None for needs_normalization when never checked."""
        client, _ = authed_client

        mock_project_service.get = AsyncMock(return_value=_make_project_response())
        mock_project_service._get_project = AsyncMock(return_value=Mock())

        mock_norm_service.get_cached_status = AsyncMock(
            return_value={
                "needs_normalization": None,
                "last_run": None,
            }
        )

        response = client.get(f"/api/v1/projects/{PROJECT_ID}/normalization/status")
        assert response.status_code == 200
        assert response.json()["needs_normalization"] is None


class TestRefreshNormalizationStatus:
    """Tests for POST /api/v1/projects/{id}/normalization/refresh."""

    @patch("ontokit.api.routes.normalization.get_arq_pool", new_callable=AsyncMock)
    def test_refresh_queues_job(
        self,
        mock_pool_fn: AsyncMock,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,
    ) -> None:
        """Refresh triggers a background check and returns job_id."""
        client, _ = authed_client

        mock_project_service.get = AsyncMock(return_value=_make_project_response())

        mock_pool = AsyncMock()
        mock_pool.enqueue_job.return_value = Mock(job_id="refresh-job-1")
        mock_pool_fn.return_value = mock_pool

        response = client.post(f"/api/v1/projects/{PROJECT_ID}/normalization/refresh")
        assert response.status_code == 200
        data = response.json()
        assert data["job_id"] == "refresh-job-1"
        assert "queued" in data["message"].lower()

    @patch("ontokit.api.routes.normalization.get_arq_pool", new_callable=AsyncMock)
    def test_refresh_returns_null_job_id_when_enqueue_returns_none(
        self,
        mock_pool_fn: AsyncMock,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,
    ) -> None:
        """Returns null job_id when pool.enqueue_job returns None."""
        client, _ = authed_client

        mock_project_service.get = AsyncMock(return_value=_make_project_response())

        mock_pool = AsyncMock()
        mock_pool.enqueue_job.return_value = None
        mock_pool_fn.return_value = mock_pool

        response = client.post(f"/api/v1/projects/{PROJECT_ID}/normalization/refresh")
        assert response.status_code == 200
        assert response.json()["job_id"] is None


class TestQueueNormalization:
    """Tests for POST /api/v1/projects/{id}/normalization/queue."""

    @patch("ontokit.api.routes.normalization.get_arq_pool", new_callable=AsyncMock)
    def test_queue_success(
        self,
        mock_pool_fn: AsyncMock,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,
    ) -> None:
        """Queues normalization job and returns job_id."""
        client, _ = authed_client

        mock_project_service.get = AsyncMock(return_value=_make_project_response("editor"))

        mock_pool = AsyncMock()
        mock_pool.enqueue_job.return_value = Mock(job_id="norm-job-1")
        mock_pool_fn.return_value = mock_pool

        response = client.post(
            f"/api/v1/projects/{PROJECT_ID}/normalization/queue",
            json={"dry_run": False},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["job_id"] == "norm-job-1"
        assert data["status"] == "queued"

    def test_queue_forbidden_for_viewer(
        self,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,
    ) -> None:
        """Viewer role gets 403 when trying to queue normalization."""
        client, _ = authed_client

        mock_project_service.get = AsyncMock(return_value=_make_project_response("viewer"))

        response = client.post(
            f"/api/v1/projects/{PROJECT_ID}/normalization/queue",
            json={"dry_run": False},
        )
        assert response.status_code == 403

    @patch("ontokit.api.routes.normalization.get_arq_pool", new_callable=AsyncMock)
    def test_queue_enqueue_returns_none(
        self,
        mock_pool_fn: AsyncMock,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,
    ) -> None:
        """Returns 500 when enqueue_job returns None."""
        client, _ = authed_client

        mock_project_service.get = AsyncMock(return_value=_make_project_response("owner"))

        mock_pool = AsyncMock()
        mock_pool.enqueue_job.return_value = None
        mock_pool_fn.return_value = mock_pool

        response = client.post(
            f"/api/v1/projects/{PROJECT_ID}/normalization/queue",
            json={"dry_run": True},
        )
        assert response.status_code == 500


class TestGetNormalizationHistory:
    """Tests for GET /api/v1/projects/{id}/normalization/history."""

    def test_history_returns_runs(
        self,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,
        mock_norm_service: AsyncMock,
    ) -> None:
        """Returns normalization history with run details."""
        client, _ = authed_client

        mock_project_service.get = AsyncMock(return_value=_make_project_response())

        run = _make_norm_run()
        mock_norm_service.get_normalization_history = AsyncMock(return_value=[run])

        response = client.get(f"/api/v1/projects/{PROJECT_ID}/normalization/history")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["trigger_type"] == "manual"

    def test_history_empty(
        self,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,
        mock_norm_service: AsyncMock,
    ) -> None:
        """Returns empty history when no runs exist."""
        client, _ = authed_client

        mock_project_service.get = AsyncMock(return_value=_make_project_response())

        mock_norm_service.get_normalization_history = AsyncMock(return_value=[])

        response = client.get(f"/api/v1/projects/{PROJECT_ID}/normalization/history")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["items"] == []


class TestGetNormalizationRun:
    """Tests for GET /api/v1/projects/{id}/normalization/runs/{run_id}."""

    def test_get_run_detail(
        self,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,
        mock_norm_service: AsyncMock,
    ) -> None:
        """Returns normalization run details."""
        client, _ = authed_client

        mock_project_service.get = AsyncMock(return_value=_make_project_response())

        run = _make_norm_run()
        mock_norm_service.get_normalization_run = AsyncMock(return_value=run)

        response = client.get(f"/api/v1/projects/{PROJECT_ID}/normalization/runs/{RUN_ID}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == RUN_ID
        assert data["commit_hash"] == "abc123"

    def test_get_run_not_found(
        self,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,
        mock_norm_service: AsyncMock,
    ) -> None:
        """Returns 404 when run does not exist."""
        client, _ = authed_client

        mock_project_service.get = AsyncMock(return_value=_make_project_response())

        mock_norm_service.get_normalization_run = AsyncMock(return_value=None)

        run_id = str(uuid4())
        response = client.get(f"/api/v1/projects/{PROJECT_ID}/normalization/runs/{run_id}")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()
