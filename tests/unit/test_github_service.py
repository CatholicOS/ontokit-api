"""Tests for GitHubService (ontokit/services/github_service.py)."""

from __future__ import annotations

import hashlib
import hmac
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from ontokit.services.github_service import GitHubService, get_github_service

# Sample GitHub API response data
GITHUB_USER_RESPONSE = {"login": "octocat", "id": 1}
GITHUB_USER_HEADERS = {"x-oauth-scopes": "repo, read:org"}

GITHUB_REPO_LIST = [
    {"id": 1, "full_name": "octocat/hello-world", "default_branch": "main"},
    {"id": 2, "full_name": "octocat/ontology-repo", "default_branch": "main"},
]

GITHUB_TREE_RESPONSE = {
    "sha": "abc123",
    "tree": [
        {"path": "README.md", "type": "blob", "size": 100},
        {"path": "ontology.ttl", "type": "blob", "size": 5000},
        {"path": "src/model.owl", "type": "blob", "size": 8000},
        {"path": "data/vocab.rdf", "type": "blob", "size": 3000},
        {"path": "lib/code.py", "type": "blob", "size": 200},
        {"path": "graphs/knowledge.jsonld", "type": "blob", "size": 1500},
        {"path": "docs/", "type": "tree"},
    ],
}


TOKEN = "ghp_test123"


@pytest.fixture
def github_service() -> GitHubService:
    """Create a fresh GitHubService instance."""
    return GitHubService()


def _mock_response(
    status_code: int = 200,
    json_data: dict[str, Any] | list[dict[str, Any]] | None = None,
    headers: dict[str, str] | None = None,
    content: bytes = b"",
) -> MagicMock:
    """Create a mock httpx.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data if json_data is not None else {}
    resp.headers = headers or {}
    resp.content = content
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp
        )
    return resp


def _make_async_client(
    get_response: MagicMock | None = None,
    post_response: MagicMock | None = None,
    request_response: MagicMock | None = None,
) -> AsyncMock:
    """Create a mock httpx.AsyncClient as async context manager."""
    client = AsyncMock()
    if get_response is not None:
        client.get = AsyncMock(return_value=get_response)
    if post_response is not None:
        client.post = AsyncMock(return_value=post_response)
    if request_response is not None:
        client.request = AsyncMock(return_value=request_response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


class TestGetAuthenticatedUser:
    """Tests for get_authenticated_user()."""

    @pytest.mark.asyncio
    async def test_returns_username_and_scopes(self, github_service: GitHubService) -> None:
        """Returns (username, scopes) tuple from /user endpoint."""
        mock_resp = _mock_response(200, GITHUB_USER_RESPONSE, GITHUB_USER_HEADERS)
        mock_client = _make_async_client(get_response=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            username, scopes = await github_service.get_authenticated_user(TOKEN)

        assert username == "octocat"
        assert scopes == "repo, read:org"

    @pytest.mark.asyncio
    async def test_api_error_raises(self, github_service: GitHubService) -> None:
        """HTTP errors from /user are propagated."""
        mock_resp = _mock_response(401)
        mock_client = _make_async_client(get_response=mock_resp)

        with (
            patch("httpx.AsyncClient", return_value=mock_client),
            pytest.raises(httpx.HTTPStatusError),
        ):
            await github_service.get_authenticated_user(TOKEN)


class TestListUserRepos:
    """Tests for list_user_repos()."""

    @pytest.mark.asyncio
    async def test_returns_repo_list(self, github_service: GitHubService) -> None:
        """Returns list of repos without query."""
        mock_resp = _mock_response(200, GITHUB_REPO_LIST)
        mock_client = _make_async_client(request_response=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            repos = await github_service.list_user_repos(TOKEN)

        assert len(repos) == 2
        assert repos[0]["full_name"] == "octocat/hello-world"

    @pytest.mark.asyncio
    async def test_search_with_query(self, github_service: GitHubService) -> None:
        """Uses search API when query is provided."""
        search_response = {"items": GITHUB_REPO_LIST}
        mock_resp = _mock_response(200, search_response)
        mock_client = _make_async_client(request_response=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            repos = await github_service.list_user_repos(TOKEN, query="ontology")

        assert len(repos) == 2
        # Verify search endpoint was called
        call_args = mock_client.request.call_args
        assert "search/repositories" in call_args.kwargs.get("url", call_args[1].get("url", ""))


class TestScanOntologyFiles:
    """Tests for scan_ontology_files()."""

    @pytest.mark.asyncio
    async def test_filters_by_extension(self, github_service: GitHubService) -> None:
        """Only files with ontology extensions are returned."""
        mock_resp = _mock_response(200, GITHUB_TREE_RESPONSE)
        mock_client = _make_async_client(request_response=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            files = await github_service.scan_ontology_files(TOKEN, "octocat", "repo", ref="main")

        paths = [f["path"] for f in files]
        assert "ontology.ttl" in paths
        assert "src/model.owl" in paths
        assert "data/vocab.rdf" in paths
        assert "graphs/knowledge.jsonld" in paths
        # Non-ontology files excluded
        assert "README.md" not in paths
        assert "lib/code.py" not in paths

    @pytest.mark.asyncio
    async def test_returns_name_and_size(self, github_service: GitHubService) -> None:
        """Each result includes path, name, and size."""
        mock_resp = _mock_response(200, GITHUB_TREE_RESPONSE)
        mock_client = _make_async_client(request_response=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            files = await github_service.scan_ontology_files(TOKEN, "octocat", "repo", ref="main")

        ttl_file = next(f for f in files if f["path"] == "ontology.ttl")
        assert ttl_file["name"] == "ontology.ttl"
        assert ttl_file["size"] == 5000

    @pytest.mark.asyncio
    async def test_default_ref_fetches_repo_info(self, github_service: GitHubService) -> None:
        """When ref is None, fetches repo info to determine default branch."""
        repo_resp = _mock_response(200, {"default_branch": "develop"})
        tree_resp = _mock_response(200, {"tree": []})

        mock_client = _make_async_client()
        mock_client.request = AsyncMock(side_effect=[repo_resp, tree_resp])

        with patch("httpx.AsyncClient", return_value=mock_client):
            files = await github_service.scan_ontology_files(TOKEN, "octocat", "repo")

        assert files == []
        # Two requests: repo info + tree
        assert mock_client.request.await_count == 2


class TestGetFileContent:
    """Tests for get_file_content()."""

    @pytest.mark.asyncio
    async def test_returns_bytes(self, github_service: GitHubService) -> None:
        """Returns raw file content as bytes."""
        file_bytes = b"@prefix owl: <http://www.w3.org/2002/07/owl#> ."
        mock_resp = _mock_response(200, content=file_bytes)
        mock_client = _make_async_client(get_response=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            content = await github_service.get_file_content(
                TOKEN, "octocat", "repo", "ontology.ttl", ref="main"
            )

        assert content == file_bytes

    @pytest.mark.asyncio
    async def test_api_error_raises(self, github_service: GitHubService) -> None:
        """HTTP errors are propagated."""
        mock_resp = _mock_response(404)
        mock_client = _make_async_client(get_response=mock_resp)

        with (
            patch("httpx.AsyncClient", return_value=mock_client),
            pytest.raises(httpx.HTTPStatusError),
        ):
            await github_service.get_file_content(TOKEN, "octocat", "repo", "nonexistent.ttl")


class TestVerifyWebhookSignature:
    """Tests for verify_webhook_signature()."""

    def test_valid_signature(self) -> None:
        """Returns True for a valid HMAC-SHA256 signature."""
        payload = b'{"action": "push"}'
        secret = "webhook-secret"
        computed = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        signature = f"sha256={computed}"

        assert GitHubService.verify_webhook_signature(payload, signature, secret) is True

    def test_invalid_signature(self) -> None:
        """Returns False for an invalid signature."""
        payload = b'{"action": "push"}'
        secret = "webhook-secret"
        signature = "sha256=0000000000000000000000000000000000000000000000000000000000000000"

        assert GitHubService.verify_webhook_signature(payload, signature, secret) is False

    def test_missing_sha256_prefix(self) -> None:
        """Returns False when signature lacks sha256= prefix."""
        payload = b'{"action": "push"}'
        secret = "webhook-secret"
        computed = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()

        assert GitHubService.verify_webhook_signature(payload, computed, secret) is False

    def test_wrong_secret(self) -> None:
        """Returns False when computed with wrong secret."""
        payload = b'{"action": "push"}'
        correct_secret = "correct-secret"
        wrong_secret = "wrong-secret"
        computed = hmac.new(wrong_secret.encode(), payload, hashlib.sha256).hexdigest()
        signature = f"sha256={computed}"

        assert GitHubService.verify_webhook_signature(payload, signature, correct_secret) is False


class TestErrorHandling:
    """Tests for API error handling."""

    @pytest.mark.asyncio
    async def test_request_propagates_http_error(self, github_service: GitHubService) -> None:
        """_request raises HTTPStatusError for non-success responses."""
        mock_resp = _mock_response(403)
        mock_client = _make_async_client(request_response=mock_resp)

        with (
            patch("httpx.AsyncClient", return_value=mock_client),
            pytest.raises(httpx.HTTPStatusError),
        ):
            await github_service._request("GET", "/repos/octocat/repo", TOKEN)

    @pytest.mark.asyncio
    async def test_request_handles_204_no_content(self, github_service: GitHubService) -> None:
        """_request returns empty dict for 204 No Content."""
        mock_resp = _mock_response(204)
        mock_client = _make_async_client(request_response=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await github_service._request("DELETE", "/some/endpoint", TOKEN)

        assert result == {}


class TestScopeHelpers:
    """Tests for scope checking static methods."""

    def test_has_hook_read_scope_with_admin(self) -> None:
        assert GitHubService.has_hook_read_scope("repo, admin:repo_hook") is True

    def test_has_hook_read_scope_with_read(self) -> None:
        assert GitHubService.has_hook_read_scope("repo, read:repo_hook") is True

    def test_has_hook_read_scope_without(self) -> None:
        assert GitHubService.has_hook_read_scope("repo, read:org") is False

    def test_has_hook_write_scope_with_admin(self) -> None:
        assert GitHubService.has_hook_write_scope("admin:repo_hook") is True

    def test_has_hook_write_scope_with_write(self) -> None:
        assert GitHubService.has_hook_write_scope("repo, write:repo_hook") is True

    def test_has_hook_write_scope_without(self) -> None:
        assert GitHubService.has_hook_write_scope("repo, read:repo_hook") is False


class TestCreatePullRequest:
    """Tests for create_pull_request()."""

    @pytest.mark.asyncio
    async def test_creates_pr(self, github_service: GitHubService) -> None:
        """Creates a PR and returns a GitHubPR dataclass."""
        pr_data = {
            "number": 42,
            "title": "Add Person class",
            "body": "Adds Person to the ontology",
            "state": "open",
            "html_url": "https://github.com/org/repo/pull/42",
            "head": {"ref": "feature/person"},
            "base": {"ref": "main"},
            "user": {"login": "octocat"},
            "created_at": "2024-01-15T10:00:00Z",
            "updated_at": "2024-01-15T10:00:00Z",
            "merged_at": None,
            "merged": False,
        }
        mock_resp = _mock_response(200, pr_data)
        mock_client = _make_async_client(request_response=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            pr = await github_service.create_pull_request(
                TOKEN, "org", "repo", "Add Person class", "feature/person", "main"
            )

        assert pr.number == 42
        assert pr.title == "Add Person class"
        assert pr.head_ref == "feature/person"
        assert pr.base_ref == "main"


class TestListPullRequests:
    """Tests for list_pull_requests()."""

    @pytest.mark.asyncio
    async def test_returns_pr_list(self, github_service: GitHubService) -> None:
        """Returns a list of GitHubPR objects."""
        pr_list = [
            {
                "number": 1,
                "title": "PR 1",
                "body": None,
                "state": "open",
                "html_url": "https://github.com/org/repo/pull/1",
                "head": {"ref": "branch-1"},
                "base": {"ref": "main"},
                "user": {"login": "octocat"},
                "created_at": "2024-01-10T10:00:00Z",
                "updated_at": "2024-01-10T12:00:00Z",
                "merged_at": None,
                "merged": False,
            },
        ]
        mock_resp = _mock_response(200, pr_list)
        mock_client = _make_async_client(request_response=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            prs = await github_service.list_pull_requests(TOKEN, "org", "repo")

        assert len(prs) == 1
        assert prs[0].number == 1

    @pytest.mark.asyncio
    async def test_returns_empty_for_non_list_response(self, github_service: GitHubService) -> None:
        """Returns empty list when response is not a list."""
        mock_resp = _mock_response(200, {})
        mock_client = _make_async_client(request_response=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            prs = await github_service.list_pull_requests(TOKEN, "org", "repo")

        assert prs == []


class TestGetPullRequest:
    """Tests for get_pull_request()."""

    @pytest.mark.asyncio
    async def test_returns_single_pr(self, github_service: GitHubService) -> None:
        """Returns a single GitHubPR by number."""
        pr_data = {
            "number": 5,
            "title": "Fix ontology",
            "body": "Fixed a class issue",
            "state": "closed",
            "html_url": "https://github.com/org/repo/pull/5",
            "head": {"ref": "fix/class"},
            "base": {"ref": "main"},
            "user": {"login": "dev"},
            "created_at": "2024-02-01T10:00:00Z",
            "updated_at": "2024-02-02T08:00:00Z",
            "merged_at": "2024-02-02T08:00:00Z",
            "merged": True,
        }
        mock_resp = _mock_response(200, pr_data)
        mock_client = _make_async_client(request_response=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            pr = await github_service.get_pull_request(TOKEN, "org", "repo", 5)

        assert pr.number == 5
        assert pr.merged is True
        assert pr.merged_at is not None


class TestCreateReview:
    """Tests for create_review()."""

    @pytest.mark.asyncio
    async def test_creates_review(self, github_service: GitHubService) -> None:
        """Creates a review and returns a GitHubReview."""
        review_data = {
            "id": 100,
            "user": {"login": "reviewer"},
            "state": "APPROVED",
            "body": "LGTM",
            "submitted_at": "2024-01-20T15:00:00Z",
        }
        mock_resp = _mock_response(200, review_data)
        mock_client = _make_async_client(request_response=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            review = await github_service.create_review(
                TOKEN, "org", "repo", 42, "APPROVE", body="LGTM"
            )

        assert review.id == 100
        assert review.state == "APPROVED"
        assert review.user_login == "reviewer"


class TestListReviews:
    """Tests for list_reviews()."""

    @pytest.mark.asyncio
    async def test_returns_reviews(self, github_service: GitHubService) -> None:
        """Returns a list of GitHubReview objects."""
        reviews = [
            {
                "id": 200,
                "user": {"login": "reviewer1"},
                "state": "COMMENTED",
                "body": "Needs work",
                "submitted_at": "2024-01-21T10:00:00Z",
            },
        ]
        mock_resp = _mock_response(200, reviews)
        mock_client = _make_async_client(request_response=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await github_service.list_reviews(TOKEN, "org", "repo", 42)

        assert len(result) == 1
        assert result[0].id == 200

    @pytest.mark.asyncio
    async def test_returns_empty_for_non_list(self, github_service: GitHubService) -> None:
        """Returns empty list when response is not a list."""
        mock_resp = _mock_response(200, {})
        mock_client = _make_async_client(request_response=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await github_service.list_reviews(TOKEN, "org", "repo", 42)

        assert result == []


class TestCreateComment:
    """Tests for create_comment()."""

    @pytest.mark.asyncio
    async def test_creates_comment(self, github_service: GitHubService) -> None:
        """Creates a comment and returns a GitHubComment."""
        comment_data = {
            "id": 300,
            "user": {"login": "commenter"},
            "body": "Great work!",
            "created_at": "2024-01-22T12:00:00Z",
            "updated_at": "2024-01-22T12:00:00Z",
        }
        mock_resp = _mock_response(200, comment_data)
        mock_client = _make_async_client(request_response=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            comment = await github_service.create_comment(TOKEN, "org", "repo", 42, "Great work!")

        assert comment.id == 300
        assert comment.body == "Great work!"
        assert comment.user_login == "commenter"


class TestListComments:
    """Tests for list_comments()."""

    @pytest.mark.asyncio
    async def test_returns_comments(self, github_service: GitHubService) -> None:
        """Returns a list of GitHubComment objects."""
        comments = [
            {
                "id": 400,
                "user": {"login": "user1"},
                "body": "Comment 1",
                "created_at": "2024-01-23T10:00:00Z",
                "updated_at": "2024-01-23T10:00:00Z",
            },
            {
                "id": 401,
                "user": {"login": "user2"},
                "body": "Comment 2",
                "created_at": "2024-01-23T11:00:00Z",
                "updated_at": "2024-01-23T11:00:00Z",
            },
        ]
        mock_resp = _mock_response(200, comments)
        mock_client = _make_async_client(request_response=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await github_service.list_comments(TOKEN, "org", "repo", 42)

        assert len(result) == 2
        assert result[0].body == "Comment 1"
        assert result[1].body == "Comment 2"

    @pytest.mark.asyncio
    async def test_returns_empty_for_non_list(self, github_service: GitHubService) -> None:
        """Returns empty list when response is not a list."""
        mock_resp = _mock_response(200, {})
        mock_client = _make_async_client(request_response=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await github_service.list_comments(TOKEN, "org", "repo", 42)

        assert result == []


class TestGetGitHubService:
    """Tests for the factory function."""

    def test_returns_github_service_instance(self) -> None:
        """get_github_service returns a GitHubService."""
        svc = get_github_service()
        assert isinstance(svc, GitHubService)
