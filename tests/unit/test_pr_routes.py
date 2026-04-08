"""Tests for pull request routes."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock, patch
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from ontokit.api.routes.pull_requests import get_service
from ontokit.main import app
from ontokit.schemas.pull_request import (
    PRDiffResponse,
    PRFileChange,
    PRListResponse,
    PRMergeResponse,
    PRResponse,
)
from ontokit.services.pull_request_service import PullRequestService

PROJECT_ID = "12345678-1234-5678-1234-567812345678"


@pytest.fixture
def mock_pr_service() -> Generator[AsyncMock, None, None]:
    """Provide an AsyncMock PullRequestService and register it as a dependency override."""
    mock_svc = AsyncMock(spec=PullRequestService)
    app.dependency_overrides[get_service] = lambda: mock_svc
    try:
        yield mock_svc
    finally:
        app.dependency_overrides.pop(get_service, None)


def _make_pr_response(
    *,
    pr_number: int = 1,
    status: str = "open",
    title: str = "Add Person class",
) -> PRResponse:
    now = datetime.now(UTC)
    return PRResponse(
        id=uuid4(),
        project_id=UUID(PROJECT_ID),
        pr_number=pr_number,
        source_branch="feature/person",
        target_branch="main",
        status=status,  # type: ignore[arg-type]
        title=title,
        author_id="test-user-id",
        created_at=now,
    )


class TestListPullRequests:
    """Tests for GET /api/v1/projects/{id}/pull-requests."""

    def test_list_prs_empty(
        self,
        authed_client: tuple[TestClient, AsyncMock],
        mock_pr_service: AsyncMock,
    ) -> None:
        """Returns empty list when no PRs exist."""
        client, _ = authed_client

        mock_pr_service.list_pull_requests = AsyncMock(
            return_value=PRListResponse(items=[], total=0, skip=0, limit=20)
        )

        response = client.get(f"/api/v1/projects/{PROJECT_ID}/pull-requests")
        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0

    def test_list_prs_with_results(
        self,
        authed_client: tuple[TestClient, AsyncMock],
        mock_pr_service: AsyncMock,
    ) -> None:
        """Returns list of PRs with pagination info."""
        client, _ = authed_client

        pr = _make_pr_response()
        mock_pr_service.list_pull_requests = AsyncMock(
            return_value=PRListResponse(items=[pr], total=1, skip=0, limit=20)
        )

        response = client.get(f"/api/v1/projects/{PROJECT_ID}/pull-requests")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["title"] == "Add Person class"

    def test_list_prs_with_status_filter(
        self,
        authed_client: tuple[TestClient, AsyncMock],
        mock_pr_service: AsyncMock,
    ) -> None:
        """Passes status filter to service."""
        client, _ = authed_client

        mock_pr_service.list_pull_requests = AsyncMock(
            return_value=PRListResponse(items=[], total=0, skip=0, limit=20)
        )

        response = client.get(f"/api/v1/projects/{PROJECT_ID}/pull-requests?status=merged")
        assert response.status_code == 200
        mock_pr_service.list_pull_requests.assert_called_once()
        call_kwargs = mock_pr_service.list_pull_requests.call_args
        assert call_kwargs.kwargs.get("status_filter") == "merged"


class TestCreatePullRequest:
    """Tests for POST /api/v1/projects/{id}/pull-requests."""

    def test_create_pr_success(
        self,
        authed_client: tuple[TestClient, AsyncMock],
        mock_pr_service: AsyncMock,
    ) -> None:
        """Creates a PR and returns 201."""
        client, _ = authed_client

        pr = _make_pr_response()
        mock_pr_service.create_pull_request = AsyncMock(return_value=pr)

        response = client.post(
            f"/api/v1/projects/{PROJECT_ID}/pull-requests",
            json={
                "title": "Add Person class",
                "source_branch": "feature/person",
                "target_branch": "main",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["title"] == "Add Person class"
        assert data["source_branch"] == "feature/person"


class TestGetPullRequest:
    """Tests for GET /api/v1/projects/{id}/pull-requests/{number}."""

    def test_get_pr_by_number(
        self,
        authed_client: tuple[TestClient, AsyncMock],
        mock_pr_service: AsyncMock,
    ) -> None:
        """Returns PR details by number."""
        client, _ = authed_client

        pr = _make_pr_response(pr_number=42)
        mock_pr_service.get_pull_request = AsyncMock(return_value=pr)

        response = client.get(f"/api/v1/projects/{PROJECT_ID}/pull-requests/42")
        assert response.status_code == 200
        assert response.json()["pr_number"] == 42


class TestClosePullRequest:
    """Tests for POST /api/v1/projects/{id}/pull-requests/{number}/close."""

    def test_close_pr(
        self,
        authed_client: tuple[TestClient, AsyncMock],
        mock_pr_service: AsyncMock,
    ) -> None:
        """Closes a PR and returns updated status."""
        client, _ = authed_client

        pr = _make_pr_response(pr_number=1, status="closed")
        mock_pr_service.close_pull_request = AsyncMock(return_value=pr)

        response = client.post(f"/api/v1/projects/{PROJECT_ID}/pull-requests/1/close")
        assert response.status_code == 200
        assert response.json()["status"] == "closed"


class TestMergePullRequest:
    """Tests for POST /api/v1/projects/{id}/pull-requests/{number}/merge."""

    @patch("ontokit.api.routes.pull_requests.get_arq_pool", new_callable=AsyncMock)
    def test_merge_pr_success(
        self,
        mock_pool_fn: AsyncMock,
        authed_client: tuple[TestClient, AsyncMock],
        mock_pr_service: AsyncMock,
    ) -> None:
        """Merges a PR and triggers index rebuild."""
        client, _ = authed_client

        pr = _make_pr_response(pr_number=1)
        merge_result = PRMergeResponse(
            success=True,
            message="Merged successfully",
            merged_at=datetime.now(UTC),
            merge_commit_hash="abc123",
        )
        mock_pr_service.get_pull_request = AsyncMock(return_value=pr)
        mock_pr_service.merge_pull_request = AsyncMock(return_value=merge_result)

        mock_pool = AsyncMock()
        mock_pool.enqueue_job.return_value = Mock(job_id="idx-job")
        mock_pool_fn.return_value = mock_pool

        response = client.post(
            f"/api/v1/projects/{PROJECT_ID}/pull-requests/1/merge",
            json={"delete_source_branch": False},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["merge_commit_hash"] == "abc123"

    @patch("ontokit.api.routes.pull_requests.get_arq_pool", new_callable=AsyncMock)
    def test_merge_pr_failure_no_reindex(
        self,
        mock_pool_fn: AsyncMock,
        authed_client: tuple[TestClient, AsyncMock],
        mock_pr_service: AsyncMock,
    ) -> None:
        """When merge fails, no re-index job is queued."""
        client, _ = authed_client

        pr = _make_pr_response(pr_number=1)
        merge_result = PRMergeResponse(
            success=False,
            message="Merge conflicts detected",
        )
        mock_pr_service.get_pull_request = AsyncMock(return_value=pr)
        mock_pr_service.merge_pull_request = AsyncMock(return_value=merge_result)

        mock_pool = AsyncMock()
        mock_pool_fn.return_value = mock_pool

        response = client.post(
            f"/api/v1/projects/{PROJECT_ID}/pull-requests/1/merge",
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        mock_pool.enqueue_job.assert_not_called()


class TestGetPRDiff:
    """Tests for GET /api/v1/projects/{id}/pull-requests/{number}/diff."""

    def test_get_diff(
        self,
        authed_client: tuple[TestClient, AsyncMock],
        mock_pr_service: AsyncMock,
    ) -> None:
        """Returns diff for a pull request."""
        client, _ = authed_client

        diff = PRDiffResponse(
            files=[
                PRFileChange(
                    path="ontology.ttl",
                    change_type="modified",
                    additions=10,
                    deletions=2,
                ),
            ],
            total_additions=10,
            total_deletions=2,
            files_changed=1,
        )
        mock_pr_service.get_pr_diff = AsyncMock(return_value=diff)

        response = client.get(f"/api/v1/projects/{PROJECT_ID}/pull-requests/1/diff")
        assert response.status_code == 200
        data = response.json()
        assert data["files_changed"] == 1
        assert data["total_additions"] == 10
        assert data["files"][0]["path"] == "ontology.ttl"
