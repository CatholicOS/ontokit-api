"""Tests for normalization routes."""

from __future__ import annotations

import json
from collections.abc import Generator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from uuid import UUID, uuid4

import pytest
from arq.jobs import JobStatus
from fastapi.testclient import TestClient

from ontokit.api.routes.normalization import get_norm_service, get_service
from ontokit.main import app
from ontokit.services.normalization_service import NormalizationService
from ontokit.services.project_service import ProjectService


def _get_job_status(name: str) -> JobStatus:
    """Map a string name to an arq JobStatus enum value."""
    return {
        "not_found": JobStatus.not_found,
        "complete": JobStatus.complete,
        "queued": JobStatus.queued,
        "in_progress": JobStatus.in_progress,
        "deferred": JobStatus.deferred,
    }[name]


PROJECT_ID = "12345678-1234-5678-1234-567812345678"
RUN_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def _make_project_response(user_role: str = "owner") -> MagicMock:
    resp = MagicMock()
    resp.user_role = user_role
    resp.source_file_path = "ontology.ttl"
    return resp


def _setup_project_mock(mock_svc: AsyncMock, user_role: str = "owner") -> None:
    """Configure mock_project_service.get and ._get_project for route tests."""
    mock_svc.get = AsyncMock(return_value=_make_project_response(user_role))
    mock_svc._get_project = AsyncMock(return_value=Mock())


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

        _setup_project_mock(mock_project_service)

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

        _setup_project_mock(mock_project_service)

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


class TestGetJobStatus:
    """Tests for GET /api/v1/projects/{id}/normalization/jobs/{job_id} (lines 253-292)."""

    @patch("ontokit.api.routes.normalization.get_arq_pool", new_callable=AsyncMock)
    def test_job_status_not_found(
        self,
        mock_pool_fn: AsyncMock,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,
    ) -> None:
        """Returns not_found status when job doesn't exist."""
        client, _ = authed_client
        mock_project_service.get = AsyncMock(return_value=_make_project_response())

        mock_pool = AsyncMock()
        mock_pool_fn.return_value = mock_pool

        # Mock Job class to return not_found status
        with patch("ontokit.api.routes.normalization.Job") as MockJob:
            mock_job_instance = AsyncMock()
            mock_job_instance.status.return_value = _get_job_status("not_found")
            MockJob.return_value = mock_job_instance

            response = client.get(f"/api/v1/projects/{PROJECT_ID}/normalization/jobs/missing-job")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "not_found"
        assert data["error"] is not None

    @patch("ontokit.api.routes.normalization.get_arq_pool", new_callable=AsyncMock)
    def test_job_status_complete(
        self,
        mock_pool_fn: AsyncMock,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,
    ) -> None:
        """Returns complete status with result when job is done."""
        client, _ = authed_client
        mock_project_service.get = AsyncMock(return_value=_make_project_response())

        mock_pool = AsyncMock()
        mock_pool_fn.return_value = mock_pool

        with patch("ontokit.api.routes.normalization.Job") as MockJob:
            mock_job_instance = AsyncMock()
            mock_job_instance.status.return_value = _get_job_status("complete")
            mock_job_instance.result.return_value = {"changes": 5}
            MockJob.return_value = mock_job_instance

            response = client.get(f"/api/v1/projects/{PROJECT_ID}/normalization/jobs/done-job")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "complete"
        assert data["result"] == {"changes": 5}

    @patch("ontokit.api.routes.normalization.get_arq_pool", new_callable=AsyncMock)
    def test_job_status_pending(
        self,
        mock_pool_fn: AsyncMock,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,
    ) -> None:
        """Returns pending status for queued jobs."""
        client, _ = authed_client
        mock_project_service.get = AsyncMock(return_value=_make_project_response())

        mock_pool = AsyncMock()
        mock_pool_fn.return_value = mock_pool

        with patch("ontokit.api.routes.normalization.Job") as MockJob:
            mock_job_instance = AsyncMock()
            mock_job_instance.status.return_value = _get_job_status("queued")
            MockJob.return_value = mock_job_instance

            response = client.get(f"/api/v1/projects/{PROJECT_ID}/normalization/jobs/queued-job")

        assert response.status_code == 200
        assert response.json()["status"] == "pending"


class TestListJobs:
    """Tests for GET /api/v1/projects/{id}/normalization/jobs (lines 313-317)."""

    def test_list_jobs_returns_empty(
        self,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,
    ) -> None:
        """Returns empty list (ARQ doesn't support job listing)."""
        client, _ = authed_client
        mock_project_service.get = AsyncMock(return_value=_make_project_response())

        response = client.get(f"/api/v1/projects/{PROJECT_ID}/normalization/jobs")
        assert response.status_code == 200
        assert response.json() == []


class TestRunNormalization:
    """Tests for POST /api/v1/projects/{id}/normalization (lines 337-374)."""

    def test_run_normalization_success(
        self,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,
        mock_norm_service: AsyncMock,
    ) -> None:
        """Successfully runs normalization and returns response."""
        client, _ = authed_client
        _setup_project_mock(mock_project_service)

        run = _make_norm_run()
        mock_norm_service.run_normalization = AsyncMock(return_value=(run, None, None))

        response = client.post(
            f"/api/v1/projects/{PROJECT_ID}/normalization",
            json={"dry_run": False},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == RUN_ID
        assert data["commit_hash"] == "abc123"

    def test_run_normalization_forbidden_for_viewer(
        self,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,
    ) -> None:
        """Viewer gets 403 when trying to run normalization."""
        client, _ = authed_client
        _setup_project_mock(mock_project_service, user_role="viewer")

        response = client.post(
            f"/api/v1/projects/{PROJECT_ID}/normalization",
            json={"dry_run": False},
        )
        assert response.status_code == 403

    def test_run_normalization_no_source_file(
        self,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,
    ) -> None:
        """Returns 400 when project has no ontology file."""
        client, _ = authed_client
        resp = _make_project_response()
        resp.source_file_path = None
        mock_project_service.get = AsyncMock(return_value=resp)
        mock_project_service._get_project = AsyncMock(return_value=Mock())

        response = client.post(
            f"/api/v1/projects/{PROJECT_ID}/normalization",
            json={"dry_run": False},
        )
        assert response.status_code == 400

    def test_run_normalization_value_error(
        self,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,
        mock_norm_service: AsyncMock,
    ) -> None:
        """Returns 400 when normalization raises ValueError."""
        client, _ = authed_client
        _setup_project_mock(mock_project_service)

        mock_norm_service.run_normalization = AsyncMock(side_effect=ValueError("Cannot normalize"))

        response = client.post(
            f"/api/v1/projects/{PROJECT_ID}/normalization",
            json={"dry_run": False},
        )
        assert response.status_code == 400

    def test_run_normalization_internal_error(
        self,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,
        mock_norm_service: AsyncMock,
    ) -> None:
        """Returns 500 when normalization raises unexpected exception."""
        client, _ = authed_client
        _setup_project_mock(mock_project_service)

        mock_norm_service.run_normalization = AsyncMock(side_effect=RuntimeError("Storage down"))

        response = client.post(
            f"/api/v1/projects/{PROJECT_ID}/normalization",
            json={"dry_run": False},
        )
        assert response.status_code == 500

    def test_run_normalization_dry_run_with_content(
        self,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,
        mock_norm_service: AsyncMock,
    ) -> None:
        """Dry run returns original and normalized content."""
        client, _ = authed_client
        _setup_project_mock(mock_project_service)

        run = _make_norm_run(is_dry_run=True)
        mock_norm_service.run_normalization = AsyncMock(
            return_value=(run, "original ttl", "normalized ttl")
        )

        response = client.post(
            f"/api/v1/projects/{PROJECT_ID}/normalization",
            json={"dry_run": True},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["original_content"] == "original ttl"
        assert data["normalized_content"] == "normalized ttl"
