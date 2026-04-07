"""Tests for quality routes (cross-references, consistency, duplicates)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
from rdflib import Graph

PROJECT_ID = "12345678-1234-5678-1234-567812345678"
JOB_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


class TestGetEntityReferences:
    """Tests for GET /api/v1/projects/{id}/entities/{iri}/references."""

    @patch("ontokit.api.routes.quality.get_cross_references")
    @patch("ontokit.api.routes.quality.load_project_graph", new_callable=AsyncMock)
    @patch("ontokit.api.routes.quality.verify_project_access", new_callable=AsyncMock)
    def test_get_references_success(
        self,
        mock_access: AsyncMock,  # noqa: ARG002
        mock_load: AsyncMock,
        mock_xrefs: MagicMock,
        authed_client: tuple[TestClient, AsyncMock],
    ) -> None:
        """Returns cross-references for an entity IRI."""
        client, _ = authed_client

        mock_graph = MagicMock(spec=Graph)
        mock_load.return_value = (mock_graph, "main")
        mock_xrefs.return_value = {
            "target_iri": "http://example.org/Person",
            "total": 0,
            "groups": [],
        }

        iri = "http://example.org/Person"
        response = client.get(f"/api/v1/projects/{PROJECT_ID}/entities/{iri}/references")
        assert response.status_code == 200
        data = response.json()
        assert data["target_iri"] == "http://example.org/Person"
        assert data["total"] == 0

    @patch("ontokit.api.routes.quality.get_cross_references")
    @patch("ontokit.api.routes.quality.load_project_graph", new_callable=AsyncMock)
    @patch("ontokit.api.routes.quality.verify_project_access", new_callable=AsyncMock)
    def test_get_references_with_branch(
        self,
        mock_access: AsyncMock,  # noqa: ARG002
        mock_load: AsyncMock,
        mock_xrefs: MagicMock,
        authed_client: tuple[TestClient, AsyncMock],
    ) -> None:
        """Branch query param is forwarded to load_project_graph."""
        client, _ = authed_client

        mock_graph = MagicMock(spec=Graph)
        mock_load.return_value = (mock_graph, "dev")
        mock_xrefs.return_value = {
            "target_iri": "http://example.org/Foo",
            "total": 0,
            "groups": [],
        }

        response = client.get(
            f"/api/v1/projects/{PROJECT_ID}/entities/http://example.org/Foo/references",
            params={"branch": "dev"},
        )
        assert response.status_code == 200
        # Verify branch was passed through
        mock_load.assert_called_once()
        call_args = mock_load.call_args
        assert call_args[0][1] == "dev"


class TestTriggerConsistencyCheck:
    """Tests for POST /api/v1/projects/{id}/quality/check."""

    @patch("ontokit.api.routes.quality._get_redis")
    @patch("ontokit.api.routes.quality.run_consistency_check")
    @patch("ontokit.api.routes.quality.load_project_graph", new_callable=AsyncMock)
    @patch("ontokit.api.routes.quality.verify_project_access", new_callable=AsyncMock)
    def test_trigger_check_success(
        self,
        mock_access: AsyncMock,  # noqa: ARG002
        mock_load: AsyncMock,
        mock_check: MagicMock,
        mock_redis_fn: MagicMock,
        authed_client: tuple[TestClient, AsyncMock],
    ) -> None:
        """Consistency check returns job_id on success."""
        client, _ = authed_client

        mock_graph = MagicMock(spec=Graph)
        mock_load.return_value = (mock_graph, "main")

        mock_result = MagicMock()
        mock_result.model_dump_json.return_value = '{"issues": []}'
        mock_check.return_value = mock_result

        mock_redis = AsyncMock()
        mock_redis_fn.return_value = mock_redis

        response = client.post(f"/api/v1/projects/{PROJECT_ID}/quality/check")
        assert response.status_code == 200
        data = response.json()
        assert "job_id" in data
        assert len(data["job_id"]) > 0

    @patch("ontokit.api.routes.quality._get_redis")
    @patch("ontokit.api.routes.quality.run_consistency_check")
    @patch("ontokit.api.routes.quality.load_project_graph", new_callable=AsyncMock)
    @patch("ontokit.api.routes.quality.verify_project_access", new_callable=AsyncMock)
    def test_trigger_check_redis_failure_still_succeeds(
        self,
        mock_access: AsyncMock,  # noqa: ARG002
        mock_load: AsyncMock,
        mock_check: MagicMock,
        mock_redis_fn: MagicMock,
        authed_client: tuple[TestClient, AsyncMock],
    ) -> None:
        """Consistency check succeeds even when Redis caching fails."""
        client, _ = authed_client

        mock_graph = MagicMock(spec=Graph)
        mock_load.return_value = (mock_graph, "main")

        mock_result = MagicMock()
        mock_result.model_dump_json.return_value = '{"issues": []}'
        mock_check.return_value = mock_result

        mock_redis_fn.side_effect = RuntimeError("Redis unavailable")

        response = client.post(f"/api/v1/projects/{PROJECT_ID}/quality/check")
        # Should still return 200 since Redis failure is caught with warning
        assert response.status_code == 200


class TestGetQualityJobResult:
    """Tests for GET /api/v1/projects/{id}/quality/jobs/{job_id}."""

    @patch("ontokit.api.routes.quality._get_redis")
    @patch("ontokit.api.routes.quality.verify_project_access", new_callable=AsyncMock)
    def test_get_job_result_cached(
        self,
        mock_access: AsyncMock,  # noqa: ARG002
        mock_redis_fn: MagicMock,
        authed_client: tuple[TestClient, AsyncMock],
    ) -> None:
        """Returns cached result when available in Redis."""
        client, _ = authed_client

        cached_data = json.dumps(
            {
                "project_id": PROJECT_ID,
                "branch": "main",
                "issues": [],
                "checked_at": datetime.now(UTC).isoformat(),
                "duration_ms": 42.5,
            }
        )

        mock_redis = AsyncMock()
        mock_redis.get.return_value = cached_data
        mock_redis_fn.return_value = mock_redis

        response = client.get(f"/api/v1/projects/{PROJECT_ID}/quality/jobs/{JOB_ID}")
        assert response.status_code == 200
        data = response.json()
        assert data["project_id"] == PROJECT_ID
        assert data["issues"] == []

    @patch("ontokit.api.routes.quality._get_redis")
    @patch("ontokit.api.routes.quality.verify_project_access", new_callable=AsyncMock)
    def test_get_job_result_not_found(
        self,
        mock_access: AsyncMock,  # noqa: ARG002
        mock_redis_fn: MagicMock,
        authed_client: tuple[TestClient, AsyncMock],
    ) -> None:
        """Returns 404 when job result is not cached."""
        client, _ = authed_client

        mock_redis = AsyncMock()
        mock_redis.get.return_value = None
        mock_redis_fn.return_value = mock_redis

        response = client.get(f"/api/v1/projects/{PROJECT_ID}/quality/jobs/{JOB_ID}")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()


class TestDetectDuplicates:
    """Tests for POST /api/v1/projects/{id}/quality/duplicates."""

    @patch("ontokit.api.routes.quality.find_duplicates")
    @patch("ontokit.api.routes.quality.load_project_graph", new_callable=AsyncMock)
    @patch("ontokit.api.routes.quality.verify_project_access", new_callable=AsyncMock)
    def test_detect_duplicates_success(
        self,
        mock_access: AsyncMock,  # noqa: ARG002
        mock_load: AsyncMock,
        mock_find: MagicMock,
        authed_client: tuple[TestClient, AsyncMock],
    ) -> None:
        """Returns duplicate detection results."""
        client, _ = authed_client

        mock_graph = MagicMock(spec=Graph)
        mock_load.return_value = (mock_graph, "main")
        mock_find.return_value = {
            "clusters": [],
            "threshold": 0.85,
            "checked_at": datetime.now(UTC).isoformat(),
        }

        response = client.post(f"/api/v1/projects/{PROJECT_ID}/quality/duplicates")
        assert response.status_code == 200
        data = response.json()
        assert data["clusters"] == []
        assert data["threshold"] == 0.85

    @patch("ontokit.api.routes.quality.find_duplicates")
    @patch("ontokit.api.routes.quality.load_project_graph", new_callable=AsyncMock)
    @patch("ontokit.api.routes.quality.verify_project_access", new_callable=AsyncMock)
    def test_detect_duplicates_custom_threshold(
        self,
        mock_access: AsyncMock,  # noqa: ARG002
        mock_load: AsyncMock,
        mock_find: MagicMock,
        authed_client: tuple[TestClient, AsyncMock],
    ) -> None:
        """Custom threshold parameter is forwarded to find_duplicates."""
        client, _ = authed_client

        mock_graph = MagicMock(spec=Graph)
        mock_load.return_value = (mock_graph, "main")
        mock_find.return_value = {
            "clusters": [],
            "threshold": 0.9,
            "checked_at": datetime.now(UTC).isoformat(),
        }

        response = client.post(
            f"/api/v1/projects/{PROJECT_ID}/quality/duplicates",
            params={"threshold": 0.9},
        )
        assert response.status_code == 200
        mock_find.assert_called_once_with(mock_graph, 0.9)
