# ruff: noqa: ARG001, ARG002
"""Tests for user settings routes (GitHub token, repos, user search)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from fastapi.testclient import TestClient

from ontokit.main import app
from ontokit.services.github_service import GitHubService, get_github_service
from ontokit.services.user_service import UserService, get_user_service


class TestGetGitHubTokenStatus:
    """Tests for GET /api/v1/users/me/github-token."""

    def test_no_token_stored(self, authed_client: tuple[TestClient, AsyncMock]) -> None:
        """Returns has_token=false when user has no stored token."""
        client, mock_session = authed_client

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        response = client.get("/api/v1/users/me/github-token")
        assert response.status_code == 200
        data = response.json()
        assert data["has_token"] is False
        assert data["github_username"] is None

    def test_token_exists(self, authed_client: tuple[TestClient, AsyncMock]) -> None:
        """Returns has_token=true with github_username when token exists."""
        client, mock_session = authed_client

        mock_row = Mock()
        mock_row.github_username = "octocat"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_row
        mock_session.execute.return_value = mock_result

        response = client.get("/api/v1/users/me/github-token")
        assert response.status_code == 200
        data = response.json()
        assert data["has_token"] is True
        assert data["github_username"] == "octocat"


class TestSaveGitHubToken:
    """Tests for POST /api/v1/users/me/github-token."""

    @patch("ontokit.api.routes.user_settings.encrypt_token", return_value="encrypted-tok")
    @patch("ontokit.api.routes.user_settings._token_preview", return_value="ghp_...wxyz")
    def test_save_token_success(
        self,
        mock_preview: MagicMock,
        mock_encrypt: MagicMock,
        authed_client: tuple[TestClient, AsyncMock],
    ) -> None:
        """Saves token and returns 201 with metadata."""
        client, mock_session = authed_client

        mock_github = AsyncMock(spec=GitHubService)
        mock_github.get_authenticated_user.return_value = ("octocat", "repo,read:org")
        app.dependency_overrides[get_github_service] = lambda: mock_github

        try:
            # No existing token
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = None
            mock_session.execute.return_value = mock_result

            now = datetime.now(UTC)

            def _fake_refresh(obj: Any) -> None:
                obj.created_at = now
                obj.updated_at = now

            mock_session.refresh.side_effect = _fake_refresh

            response = client.post(
                "/api/v1/users/me/github-token",
                json={"token": "ghp_testtoken1234567890"},
            )
            assert response.status_code == 201
            data = response.json()
            assert data["github_username"] == "octocat"
            assert data["token_scopes"] == "repo,read:org"
        finally:
            app.dependency_overrides.pop(get_github_service, None)

    def test_save_token_invalid(self, authed_client: tuple[TestClient, AsyncMock]) -> None:
        """Returns 400 when GitHub rejects the token."""
        client, _ = authed_client

        mock_github = AsyncMock(spec=GitHubService)
        mock_github.get_authenticated_user.side_effect = Exception("Bad credentials")
        app.dependency_overrides[get_github_service] = lambda: mock_github

        try:
            response = client.post(
                "/api/v1/users/me/github-token",
                json={"token": "ghp_badtoken"},
            )
            assert response.status_code == 400
            assert "Invalid GitHub token" in response.json()["detail"]
        finally:
            app.dependency_overrides.pop(get_github_service, None)

    def test_save_token_missing_repo_scope(
        self, authed_client: tuple[TestClient, AsyncMock]
    ) -> None:
        """Returns 400 when token lacks repo scope."""
        client, _ = authed_client

        mock_github = AsyncMock(spec=GitHubService)
        mock_github.get_authenticated_user.return_value = ("octocat", "read:org")
        app.dependency_overrides[get_github_service] = lambda: mock_github

        try:
            response = client.post(
                "/api/v1/users/me/github-token",
                json={"token": "ghp_norepo"},
            )
            assert response.status_code == 400
            assert "repo" in response.json()["detail"].lower()
        finally:
            app.dependency_overrides.pop(get_github_service, None)


class TestDeleteGitHubToken:
    """Tests for DELETE /api/v1/users/me/github-token."""

    def test_delete_token_success(self, authed_client: tuple[TestClient, AsyncMock]) -> None:
        """Returns 204 when token is deleted."""
        client, mock_session = authed_client

        mock_row = Mock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_row
        mock_session.execute.return_value = mock_result

        response = client.delete("/api/v1/users/me/github-token")
        assert response.status_code == 204
        mock_session.delete.assert_called_once_with(mock_row)

    def test_delete_token_not_found(self, authed_client: tuple[TestClient, AsyncMock]) -> None:
        """Returns 404 when no token exists."""
        client, mock_session = authed_client

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        response = client.delete("/api/v1/users/me/github-token")
        assert response.status_code == 404
        assert "No GitHub token found" in response.json()["detail"]


class TestListGitHubRepos:
    """Tests for GET /api/v1/users/me/github-repos."""

    @patch("ontokit.api.routes.user_settings.decrypt_token", return_value="ghp_plaintoken")
    def test_list_repos_success(
        self,
        mock_decrypt: MagicMock,
        authed_client: tuple[TestClient, AsyncMock],
    ) -> None:
        """Returns repo list when token exists."""
        client, mock_session = authed_client

        mock_row = Mock()
        mock_row.encrypted_token = "encrypted-val"
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_row
        mock_session.execute.return_value = mock_result

        mock_github = AsyncMock(spec=GitHubService)
        mock_github.list_user_repos.return_value = [
            {
                "full_name": "octocat/hello-world",
                "owner": {"login": "octocat"},
                "name": "hello-world",
                "description": "A test repo",
                "private": False,
                "default_branch": "main",
                "html_url": "https://github.com/octocat/hello-world",
            }
        ]
        app.dependency_overrides[get_github_service] = lambda: mock_github

        try:
            response = client.get("/api/v1/users/me/github-repos")
            assert response.status_code == 200
            data = response.json()
            assert data["total"] == 1
            assert data["items"][0]["full_name"] == "octocat/hello-world"
        finally:
            app.dependency_overrides.pop(get_github_service, None)

    def test_list_repos_no_token(self, authed_client: tuple[TestClient, AsyncMock]) -> None:
        """Returns 400 when user has no stored token."""
        client, mock_session = authed_client

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        response = client.get("/api/v1/users/me/github-repos")
        assert response.status_code == 400
        assert "No GitHub token found" in response.json()["detail"]


class TestSearchUsers:
    """Tests for GET /api/v1/users/search."""

    def test_search_users_success(self, authed_client: tuple[TestClient, AsyncMock]) -> None:
        """Returns matching users."""
        client, _ = authed_client

        mock_user_svc = AsyncMock(spec=UserService)
        mock_user_svc.search_users.return_value = (
            [{"id": "u1", "username": "alice", "display_name": "Alice", "email": "a@b.com"}],
            1,
        )
        app.dependency_overrides[get_user_service] = lambda: mock_user_svc

        try:
            response = client.get("/api/v1/users/search", params={"q": "alice"})
            assert response.status_code == 200
            data = response.json()
            assert data["total"] == 1
            assert data["items"][0]["username"] == "alice"
        finally:
            app.dependency_overrides.pop(get_user_service, None)

    def test_search_users_query_too_short(
        self, authed_client: tuple[TestClient, AsyncMock]
    ) -> None:
        """Returns 422 when query is less than 2 characters."""
        client, _ = authed_client

        response = client.get("/api/v1/users/search", params={"q": "a"})
        assert response.status_code == 422

    def test_search_users_missing_query(self, authed_client: tuple[TestClient, AsyncMock]) -> None:
        """Returns 422 when query param is missing."""
        client, _ = authed_client

        response = client.get("/api/v1/users/search")
        assert response.status_code == 422
