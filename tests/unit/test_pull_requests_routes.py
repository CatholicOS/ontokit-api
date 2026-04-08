"""Tests for pull request route endpoints."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Generator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from ontokit.api.routes.pull_requests import get_service
from ontokit.main import app
from ontokit.schemas.pull_request import (
    CommentListResponse,
    CommentResponse,
    GitHubIntegrationResponse,
    OpenPRsSummary,
    PRCommitListResponse,
    PRDiffResponse,
    PRListResponse,
    PRMergeResponse,
    PRResponse,
    PRSettingsResponse,
    ReviewListResponse,
    ReviewResponse,
)

PROJECT_ID = "12345678-1234-5678-1234-567812345678"
PROJECT_UUID = UUID(PROJECT_ID)
COMMENT_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
BASE = "/api/v1/projects"
NOW = datetime.now(tz=UTC)

# Reusable response fixtures
_PR_RESP = PRResponse(
    id=PROJECT_UUID,
    project_id=PROJECT_UUID,
    pr_number=1,
    title="Test",
    source_branch="feature",
    target_branch="main",
    status="open",
    author_id="test-user-id",
    created_at=NOW,
)

_MERGE_SUCCESS = PRMergeResponse(
    success=True,
    message="Merged",
    merged_at=NOW,
    merge_commit_hash="abc123",
)

_MERGE_FAILURE = PRMergeResponse(
    success=False,
    message="Cannot merge",
)

_REVIEW_RESP = ReviewResponse(
    id=PROJECT_UUID,
    pull_request_id=PROJECT_UUID,
    reviewer_id="test-user-id",
    status="approved",
    body="LGTM",
    created_at=NOW,
)

_COMMENT_RESP = CommentResponse(
    id=UUID(COMMENT_ID),
    pull_request_id=PROJECT_UUID,
    author_id="test-user-id",
    body="Nice",
    created_at=NOW,
)

_INTEGRATION_RESP = GitHubIntegrationResponse(
    id=PROJECT_UUID,
    project_id=PROJECT_UUID,
    repo_owner="owner",
    repo_name="repo",
    default_branch="main",
    sync_enabled=False,
    created_at=NOW,
)

_PR_SETTINGS_RESP = PRSettingsResponse(pr_approval_required=1)


@pytest.fixture
def svc_client(
    authed_client: tuple[TestClient, AsyncMock],
) -> Generator[tuple[TestClient, AsyncMock], None, None]:
    """Inject a mocked PullRequestService into the app."""
    client, _mock_session = authed_client
    mock_svc = AsyncMock()
    mock_svc.db = AsyncMock()
    app.dependency_overrides[get_service] = lambda: mock_svc
    yield client, mock_svc
    app.dependency_overrides.pop(get_service, None)


# ---------------------------------------------------------------------------
# Delegation endpoint tests
# ---------------------------------------------------------------------------


class TestOpenPRSummary:
    def test_returns_200(self, svc_client: tuple[TestClient, AsyncMock]) -> None:
        client, svc = svc_client
        svc.get_open_pr_summary.return_value = OpenPRsSummary(total_open=0, by_project=[])
        resp = client.get(f"{BASE}/pull-requests/open-summary")
        assert resp.status_code == 200
        svc.get_open_pr_summary.assert_awaited_once()


class TestListPullRequests:
    def test_returns_200(self, svc_client: tuple[TestClient, AsyncMock]) -> None:
        client, svc = svc_client
        svc.list_pull_requests.return_value = PRListResponse(items=[], total=0, skip=0, limit=20)
        resp = client.get(f"{BASE}/{PROJECT_ID}/pull-requests")
        assert resp.status_code == 200
        svc.list_pull_requests.assert_awaited_once()


class TestCreatePullRequest:
    def test_returns_201(self, svc_client: tuple[TestClient, AsyncMock]) -> None:
        client, svc = svc_client
        svc.create_pull_request.return_value = _PR_RESP
        resp = client.post(
            f"{BASE}/{PROJECT_ID}/pull-requests",
            json={
                "title": "Test PR",
                "source_branch": "feature",
                "target_branch": "main",
            },
        )
        assert resp.status_code == 201
        svc.create_pull_request.assert_awaited_once()


class TestGetPullRequest:
    def test_returns_200(self, svc_client: tuple[TestClient, AsyncMock]) -> None:
        client, svc = svc_client
        svc.get_pull_request.return_value = _PR_RESP
        resp = client.get(f"{BASE}/{PROJECT_ID}/pull-requests/1")
        assert resp.status_code == 200
        svc.get_pull_request.assert_awaited_once()


class TestUpdatePullRequest:
    def test_returns_200(self, svc_client: tuple[TestClient, AsyncMock]) -> None:
        client, svc = svc_client
        svc.update_pull_request.return_value = _PR_RESP
        resp = client.patch(
            f"{BASE}/{PROJECT_ID}/pull-requests/1",
            json={"title": "Updated"},
        )
        assert resp.status_code == 200
        svc.update_pull_request.assert_awaited_once()


class TestClosePullRequest:
    def test_returns_200(self, svc_client: tuple[TestClient, AsyncMock]) -> None:
        client, svc = svc_client
        svc.close_pull_request.return_value = _PR_RESP
        resp = client.post(f"{BASE}/{PROJECT_ID}/pull-requests/1/close")
        assert resp.status_code == 200
        svc.close_pull_request.assert_awaited_once()


class TestReopenPullRequest:
    def test_returns_200(self, svc_client: tuple[TestClient, AsyncMock]) -> None:
        client, svc = svc_client
        svc.reopen_pull_request.return_value = _PR_RESP
        resp = client.post(f"{BASE}/{PROJECT_ID}/pull-requests/1/reopen")
        assert resp.status_code == 200
        svc.reopen_pull_request.assert_awaited_once()


class TestMergePullRequest:
    @patch("ontokit.api.routes.pull_requests.get_arq_pool", new_callable=AsyncMock)
    def test_merge_success_enqueues_reindex(
        self,
        mock_pool_fn: AsyncMock,
        svc_client: tuple[TestClient, AsyncMock],
    ) -> None:
        client, svc = svc_client
        svc.get_pull_request.return_value = _PR_RESP
        svc.merge_pull_request.return_value = _MERGE_SUCCESS

        mock_pool = AsyncMock()
        mock_pool_fn.return_value = mock_pool

        resp = client.post(f"{BASE}/{PROJECT_ID}/pull-requests/1/merge")
        assert resp.status_code == 200
        svc.get_pull_request.assert_awaited_once()
        svc.merge_pull_request.assert_awaited_once()
        mock_pool.enqueue_job.assert_awaited_once()

    @patch("ontokit.api.routes.pull_requests.get_arq_pool", new_callable=AsyncMock)
    def test_merge_failure_skips_reindex(
        self,
        mock_pool_fn: AsyncMock,
        svc_client: tuple[TestClient, AsyncMock],
    ) -> None:
        client, svc = svc_client
        svc.get_pull_request.return_value = _PR_RESP
        svc.merge_pull_request.return_value = _MERGE_FAILURE

        resp = client.post(f"{BASE}/{PROJECT_ID}/pull-requests/1/merge")
        assert resp.status_code == 200
        mock_pool_fn.assert_not_awaited()


class TestReviews:
    def test_list_reviews(self, svc_client: tuple[TestClient, AsyncMock]) -> None:
        client, svc = svc_client
        svc.list_reviews.return_value = ReviewListResponse(items=[], total=0)
        resp = client.get(f"{BASE}/{PROJECT_ID}/pull-requests/1/reviews")
        assert resp.status_code == 200
        svc.list_reviews.assert_awaited_once()

    def test_create_review(self, svc_client: tuple[TestClient, AsyncMock]) -> None:
        client, svc = svc_client
        svc.create_review.return_value = _REVIEW_RESP
        resp = client.post(
            f"{BASE}/{PROJECT_ID}/pull-requests/1/reviews",
            json={"body": "LGTM", "status": "approved"},
        )
        assert resp.status_code == 201
        svc.create_review.assert_awaited_once()


class TestComments:
    def test_list_comments(self, svc_client: tuple[TestClient, AsyncMock]) -> None:
        client, svc = svc_client
        svc.list_comments.return_value = CommentListResponse(items=[], total=0)
        resp = client.get(f"{BASE}/{PROJECT_ID}/pull-requests/1/comments")
        assert resp.status_code == 200
        svc.list_comments.assert_awaited_once()

    def test_create_comment(self, svc_client: tuple[TestClient, AsyncMock]) -> None:
        client, svc = svc_client
        svc.create_comment.return_value = _COMMENT_RESP
        resp = client.post(
            f"{BASE}/{PROJECT_ID}/pull-requests/1/comments",
            json={"body": "Nice work"},
        )
        assert resp.status_code == 201
        svc.create_comment.assert_awaited_once()

    def test_update_comment(self, svc_client: tuple[TestClient, AsyncMock]) -> None:
        client, svc = svc_client
        svc.update_comment.return_value = _COMMENT_RESP
        resp = client.patch(
            f"{BASE}/{PROJECT_ID}/pull-requests/1/comments/{COMMENT_ID}",
            json={"body": "Updated comment"},
        )
        assert resp.status_code == 200
        svc.update_comment.assert_awaited_once()

    def test_delete_comment(self, svc_client: tuple[TestClient, AsyncMock]) -> None:
        client, svc = svc_client
        svc.delete_comment.return_value = None
        resp = client.delete(
            f"{BASE}/{PROJECT_ID}/pull-requests/1/comments/{COMMENT_ID}",
        )
        assert resp.status_code == 204
        svc.delete_comment.assert_awaited_once()


class TestCommitsAndDiff:
    def test_get_pr_commits(self, svc_client: tuple[TestClient, AsyncMock]) -> None:
        client, svc = svc_client
        svc.get_pr_commits.return_value = PRCommitListResponse(items=[], total=0)
        resp = client.get(f"{BASE}/{PROJECT_ID}/pull-requests/1/commits")
        assert resp.status_code == 200
        svc.get_pr_commits.assert_awaited_once()

    def test_get_pr_diff(self, svc_client: tuple[TestClient, AsyncMock]) -> None:
        client, svc = svc_client
        svc.get_pr_diff.return_value = PRDiffResponse(
            files=[], total_additions=0, total_deletions=0, files_changed=0
        )
        resp = client.get(f"{BASE}/{PROJECT_ID}/pull-requests/1/diff")
        assert resp.status_code == 200
        svc.get_pr_diff.assert_awaited_once()


# NOTE: Branch routes (list_branches, create_branch, switch_branch) are defined
# in both pull_requests.py and projects.py with the same URL prefix "/projects".
# Since projects.py is registered first, its routes take precedence. Those
# routes are tested in test_projects_routes.py instead.


class TestGitHubIntegration:
    def test_get_integration(self, svc_client: tuple[TestClient, AsyncMock]) -> None:
        client, svc = svc_client
        svc.get_github_integration.return_value = _INTEGRATION_RESP
        resp = client.get(f"{BASE}/{PROJECT_ID}/github-integration")
        assert resp.status_code == 200
        svc.get_github_integration.assert_awaited_once()

    def test_create_integration(self, svc_client: tuple[TestClient, AsyncMock]) -> None:
        client, svc = svc_client
        svc.create_github_integration.return_value = _INTEGRATION_RESP
        resp = client.post(
            f"{BASE}/{PROJECT_ID}/github-integration",
            json={
                "repo_owner": "owner",
                "repo_name": "repo",
            },
        )
        assert resp.status_code == 201
        svc.create_github_integration.assert_awaited_once()

    def test_update_integration(self, svc_client: tuple[TestClient, AsyncMock]) -> None:
        client, svc = svc_client
        svc.update_github_integration.return_value = _INTEGRATION_RESP
        resp = client.patch(
            f"{BASE}/{PROJECT_ID}/github-integration",
            json={"sync_enabled": True},
        )
        assert resp.status_code == 200
        svc.update_github_integration.assert_awaited_once()

    def test_get_webhook_secret(self, svc_client: tuple[TestClient, AsyncMock]) -> None:
        client, svc = svc_client
        svc.get_webhook_secret.return_value = {"webhook_secret": "s3cr3t"}
        resp = client.get(f"{BASE}/{PROJECT_ID}/github-integration/webhook-secret")
        assert resp.status_code == 200
        assert resp.json()["webhook_secret"] == "s3cr3t"

    def test_setup_webhook(self, svc_client: tuple[TestClient, AsyncMock]) -> None:
        client, svc = svc_client
        svc.setup_or_detect_webhook.return_value = {"status": "created", "hook_id": 42}
        resp = client.post(f"{BASE}/{PROJECT_ID}/github-integration/webhook-setup")
        assert resp.status_code == 200
        svc.setup_or_detect_webhook.assert_awaited_once()

    def test_delete_integration(self, svc_client: tuple[TestClient, AsyncMock]) -> None:
        client, svc = svc_client
        svc.delete_github_integration.return_value = None
        resp = client.delete(f"{BASE}/{PROJECT_ID}/github-integration")
        assert resp.status_code == 204
        svc.delete_github_integration.assert_awaited_once()


class TestPRSettings:
    def test_get_settings(self, svc_client: tuple[TestClient, AsyncMock]) -> None:
        client, svc = svc_client
        svc.get_pr_settings.return_value = _PR_SETTINGS_RESP
        resp = client.get(f"{BASE}/{PROJECT_ID}/pr-settings")
        assert resp.status_code == 200
        svc.get_pr_settings.assert_awaited_once()

    def test_update_settings(self, svc_client: tuple[TestClient, AsyncMock]) -> None:
        client, svc = svc_client
        svc.update_pr_settings.return_value = _PR_SETTINGS_RESP
        resp = client.patch(
            f"{BASE}/{PROJECT_ID}/pr-settings",
            json={"pr_approval_required": 1},
        )
        assert resp.status_code == 200
        svc.update_pr_settings.assert_awaited_once()


# ---------------------------------------------------------------------------
# GitHub Webhook endpoint tests
# ---------------------------------------------------------------------------


def _sign(secret: str, body: bytes) -> str:
    """Compute the GitHub webhook signature."""
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _make_integration(
    *,
    webhooks_enabled: bool = True,
    webhook_secret: str | None = "test-secret",
) -> MagicMock:
    integration = MagicMock()
    integration.webhooks_enabled = webhooks_enabled
    integration.webhook_secret = webhook_secret
    return integration


class TestGitHubWebhook:
    """Tests for POST /api/v1/projects/webhooks/github/{project_id}."""

    WEBHOOK_URL = f"{BASE}/webhooks/github/{PROJECT_ID}"

    def _post_webhook(
        self,
        client: TestClient,
        payload: Any,
        event: str = "ping",
        secret: str = "test-secret",
    ) -> Any:
        body = json.dumps(payload).encode()
        sig = _sign(secret, body)
        return client.post(
            self.WEBHOOK_URL,
            content=body,
            headers={
                "x-hub-signature-256": sig,
                "x-github-event": event,
                "content-type": "application/json",
            },
        )

    def _setup_integration(self, svc: AsyncMock, integration: MagicMock | None = None) -> None:
        """Configure mock_svc.db.execute to return the given integration."""
        if integration is None:
            integration = _make_integration()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = integration
        svc.db.execute.return_value = mock_result

    # --- Error cases ---

    def test_no_integration_returns_404(self, svc_client: tuple[TestClient, AsyncMock]) -> None:
        client, svc = svc_client
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        svc.db.execute.return_value = mock_result
        resp = self._post_webhook(client, {})
        assert resp.status_code == 404

    def test_webhooks_disabled_returns_403(self, svc_client: tuple[TestClient, AsyncMock]) -> None:
        client, svc = svc_client
        self._setup_integration(svc, _make_integration(webhooks_enabled=False))
        resp = self._post_webhook(client, {})
        assert resp.status_code == 403
        assert "not enabled" in resp.json()["detail"]

    def test_no_webhook_secret_returns_500(self, svc_client: tuple[TestClient, AsyncMock]) -> None:
        client, svc = svc_client
        self._setup_integration(svc, _make_integration(webhook_secret=None))
        resp = self._post_webhook(client, {})
        assert resp.status_code == 500
        assert "not configured" in resp.json()["detail"]

    def test_invalid_signature_returns_403(self, svc_client: tuple[TestClient, AsyncMock]) -> None:
        client, svc = svc_client
        self._setup_integration(svc)
        body = json.dumps({}).encode()
        resp = client.post(
            self.WEBHOOK_URL,
            content=body,
            headers={
                "x-hub-signature-256": "sha256=invalid",
                "x-github-event": "ping",
                "content-type": "application/json",
            },
        )
        assert resp.status_code == 403
        assert "Invalid webhook signature" in resp.json()["detail"]

    # --- Successful event handling ---

    def test_pull_request_event(self, svc_client: tuple[TestClient, AsyncMock]) -> None:
        client, svc = svc_client
        self._setup_integration(svc)
        payload = {
            "action": "opened",
            "pull_request": {"number": 1, "title": "Test"},
        }
        resp = self._post_webhook(client, payload, event="pull_request")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
        svc.handle_github_pr_webhook.assert_awaited_once_with(
            PROJECT_UUID,
            "opened",
            {"number": 1, "title": "Test"},
        )

    def test_pull_request_review_event(self, svc_client: tuple[TestClient, AsyncMock]) -> None:
        client, svc = svc_client
        self._setup_integration(svc)
        payload = {
            "action": "submitted",
            "review": {"id": 99, "state": "approved"},
            "pull_request": {"number": 1},
        }
        resp = self._post_webhook(client, payload, event="pull_request_review")
        assert resp.status_code == 200
        svc.handle_github_review_webhook.assert_awaited_once_with(
            PROJECT_UUID,
            "submitted",
            {"id": 99, "state": "approved"},
            {"number": 1},
        )

    def test_push_event_calls_handler(self, svc_client: tuple[TestClient, AsyncMock]) -> None:
        client, svc = svc_client
        # db.execute is called twice: once for integration, once for sync config.
        integration = _make_integration()
        result1 = MagicMock()
        result1.scalar_one_or_none.return_value = integration
        result2 = MagicMock()
        result2.scalar_one_or_none.return_value = None
        svc.db.execute.side_effect = [result1, result2]

        payload = {
            "ref": "refs/heads/main",
            "commits": [{"id": "abc", "added": [], "modified": ["ontology.ttl"]}],
        }
        resp = self._post_webhook(client, payload, event="push")
        assert resp.status_code == 200
        svc.handle_github_push_webhook.assert_awaited_once_with(
            PROJECT_UUID,
            "refs/heads/main",
            [{"id": "abc", "added": [], "modified": ["ontology.ttl"]}],
        )

    @patch("ontokit.api.routes.pull_requests.get_arq_pool", new_callable=AsyncMock)
    def test_push_event_triggers_sync_when_configured(
        self,
        mock_pool_fn: AsyncMock,
        svc_client: tuple[TestClient, AsyncMock],
    ) -> None:
        client, svc = svc_client
        integration = _make_integration()
        sync_config = MagicMock()
        sync_config.branch = "main"
        sync_config.file_path = "ontology.ttl"
        sync_config.status = "idle"

        result1 = MagicMock()
        result1.scalar_one_or_none.return_value = integration
        result2 = MagicMock()
        result2.scalar_one_or_none.return_value = sync_config
        svc.db.execute.side_effect = [result1, result2]

        mock_pool = AsyncMock()
        mock_pool_fn.return_value = mock_pool

        payload = {
            "ref": "refs/heads/main",
            "commits": [{"id": "abc", "added": [], "modified": ["ontology.ttl"]}],
        }
        resp = self._post_webhook(client, payload, event="push")
        assert resp.status_code == 200
        mock_pool.enqueue_job.assert_awaited_once_with("run_remote_check_task", PROJECT_ID)
        assert sync_config.status == "checking"

    @patch("ontokit.api.routes.pull_requests.get_arq_pool", new_callable=AsyncMock)
    def test_push_sync_no_pool_restores_status(
        self,
        mock_pool_fn: AsyncMock,
        svc_client: tuple[TestClient, AsyncMock],
    ) -> None:
        client, svc = svc_client
        integration = _make_integration()
        sync_config = MagicMock()
        sync_config.branch = "main"
        sync_config.file_path = "ontology.ttl"
        sync_config.status = "idle"

        result1 = MagicMock()
        result1.scalar_one_or_none.return_value = integration
        result2 = MagicMock()
        result2.scalar_one_or_none.return_value = sync_config
        svc.db.execute.side_effect = [result1, result2]

        mock_pool_fn.return_value = None

        payload = {
            "ref": "refs/heads/main",
            "commits": [{"id": "abc", "added": [], "modified": ["ontology.ttl"]}],
        }
        resp = self._post_webhook(client, payload, event="push")
        assert resp.status_code == 200
        assert sync_config.status == "idle"

    @patch("ontokit.api.routes.pull_requests.get_arq_pool", new_callable=AsyncMock)
    def test_push_sync_pool_error_restores_status(
        self,
        mock_pool_fn: AsyncMock,
        svc_client: tuple[TestClient, AsyncMock],
    ) -> None:
        client, svc = svc_client
        integration = _make_integration()
        sync_config = MagicMock()
        sync_config.branch = "main"
        sync_config.file_path = "ontology.ttl"
        sync_config.status = "idle"

        result1 = MagicMock()
        result1.scalar_one_or_none.return_value = integration
        result2 = MagicMock()
        result2.scalar_one_or_none.return_value = sync_config
        svc.db.execute.side_effect = [result1, result2]

        mock_pool = AsyncMock()
        mock_pool.enqueue_job.side_effect = RuntimeError("connection lost")
        mock_pool_fn.return_value = mock_pool

        payload = {
            "ref": "refs/heads/main",
            "commits": [{"id": "abc", "added": [], "modified": ["ontology.ttl"]}],
        }
        resp = self._post_webhook(client, payload, event="push")
        assert resp.status_code == 200
        assert sync_config.status == "idle"

    def test_push_event_non_branch_ref_skips_sync(
        self, svc_client: tuple[TestClient, AsyncMock]
    ) -> None:
        """Push events for tags (refs/tags/...) should skip sync config lookup."""
        client, svc = svc_client
        self._setup_integration(svc)
        payload = {
            "ref": "refs/tags/v1.0",
            "commits": [],
        }
        resp = self._post_webhook(client, payload, event="push")
        assert resp.status_code == 200
        svc.handle_github_push_webhook.assert_awaited_once()
        # db.execute called only once (for integration lookup)
        assert svc.db.execute.await_count == 1

    def test_push_event_file_not_touched_skips_sync(
        self, svc_client: tuple[TestClient, AsyncMock]
    ) -> None:
        """If the tracked file is not in the pushed commits, skip sync."""
        client, svc = svc_client
        integration = _make_integration()
        sync_config = MagicMock()
        sync_config.branch = "main"
        sync_config.file_path = "ontology.ttl"
        sync_config.status = "idle"

        result1 = MagicMock()
        result1.scalar_one_or_none.return_value = integration
        result2 = MagicMock()
        result2.scalar_one_or_none.return_value = sync_config
        svc.db.execute.side_effect = [result1, result2]

        payload = {
            "ref": "refs/heads/main",
            "commits": [{"id": "abc", "added": ["readme.md"], "modified": []}],
        }
        resp = self._post_webhook(client, payload, event="push")
        assert resp.status_code == 200
        assert sync_config.status == "idle"

    def test_unhandled_event_returns_ok(self, svc_client: tuple[TestClient, AsyncMock]) -> None:
        """Unknown event types should still return 200 ok."""
        client, svc = svc_client
        self._setup_integration(svc)
        resp = self._post_webhook(client, {"zen": "hi"}, event="ping")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
