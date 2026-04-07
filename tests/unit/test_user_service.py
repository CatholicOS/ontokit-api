"""Tests for UserService (ontokit/services/user_service.py)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from ontokit.services.user_service import UserService, get_user_service

# Sample Zitadel API responses
ZITADEL_USER_RESPONSE = {
    "user": {
        "id": "user-001",
        "human": {
            "profile": {
                "displayName": "Jane Doe",
                "firstName": "Jane",
                "lastName": "Doe",
            },
            "email": {
                "email": "jane@example.com",
            },
        },
    },
}

ZITADEL_SEARCH_RESPONSE = {
    "details": {"totalResult": 2},
    "result": [
        {
            "userId": "user-001",
            "preferredLoginName": "janedoe",
            "human": {
                "profile": {
                    "displayName": "Jane Doe",
                    "givenName": "Jane",
                    "familyName": "Doe",
                },
                "email": {"email": "jane@example.com"},
            },
        },
        {
            "userId": "user-002",
            "userName": "johnsmith",
            "human": {
                "profile": {
                    "displayName": None,
                    "givenName": "John",
                    "familyName": "Smith",
                },
                "email": {"email": "john@example.com"},
            },
        },
    ],
}


@pytest.fixture(autouse=True)
def _mock_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set Zitadel settings for all tests."""
    monkeypatch.setattr(
        "ontokit.services.user_service.settings",
        type(
            "S",
            (),
            {
                "zitadel_service_token": "test-service-token",
                "zitadel_issuer": "https://auth.example.com",
                "zitadel_internal_url": "",
            },
        )(),
    )


@pytest.fixture
def user_service() -> UserService:
    """Create a fresh UserService instance (no cached data)."""
    return UserService()


def _mock_response(
    status_code: int = 200,
    json_data: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> MagicMock:
    """Create a mock httpx.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.headers = headers or {}
    return resp


class TestGetUserInfo:
    """Tests for get_user_info()."""

    @pytest.mark.asyncio
    async def test_successful_lookup(self, user_service: UserService) -> None:
        """Successful API call returns UserInfo dict."""
        mock_resp = _mock_response(200, ZITADEL_USER_RESPONSE)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await user_service.get_user_info("user-001")

        assert result is not None
        assert result["id"] == "user-001"
        assert result["name"] == "Jane Doe"
        assert result["email"] == "jane@example.com"

    @pytest.mark.asyncio
    async def test_caching(self, user_service: UserService) -> None:
        """Second call for same user_id returns cached result without HTTP request."""
        mock_resp = _mock_response(200, ZITADEL_USER_RESPONSE)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result1 = await user_service.get_user_info("user-001")
            result2 = await user_service.get_user_info("user-001")

        assert result1 == result2
        # Only one HTTP call should have been made
        assert mock_client.get.await_count == 1

    @pytest.mark.asyncio
    async def test_http_error_returns_none(self, user_service: UserService) -> None:
        """HTTP errors return None gracefully."""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("connection refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await user_service.get_user_info("user-001")

        assert result is None

    @pytest.mark.asyncio
    async def test_non_200_returns_none(self, user_service: UserService) -> None:
        """Non-200 status code returns None."""
        mock_resp = _mock_response(404)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await user_service.get_user_info("nonexistent-user")

        assert result is None

    @pytest.mark.asyncio
    async def test_no_service_token_returns_none(
        self, user_service: UserService, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Returns None when no service token is configured."""
        monkeypatch.setattr(
            "ontokit.services.user_service.settings",
            type(
                "S",
                (),
                {
                    "zitadel_service_token": "",
                    "zitadel_issuer": "https://auth.example.com",
                    "zitadel_internal_url": "",
                },
            )(),
        )
        result = await user_service.get_user_info("user-001")
        assert result is None

    @pytest.mark.asyncio
    async def test_display_name_fallback_to_first_last(self, user_service: UserService) -> None:
        """When displayName is empty, falls back to firstName + lastName."""
        response_data = {
            "user": {
                "id": "user-003",
                "human": {
                    "profile": {
                        "displayName": "",
                        "firstName": "Alice",
                        "lastName": "Wonder",
                    },
                    "email": {"email": "alice@example.com"},
                },
            },
        }
        mock_resp = _mock_response(200, response_data)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await user_service.get_user_info("user-003")

        assert result is not None
        assert result["name"] == "Alice Wonder"


class TestGetUsersInfo:
    """Tests for get_users_info()."""

    @pytest.mark.asyncio
    async def test_batch_fetch(self, user_service: UserService) -> None:
        """Fetches multiple users and returns a mapping."""
        mock_resp = _mock_response(200, ZITADEL_USER_RESPONSE)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await user_service.get_users_info(["user-001"])

        assert "user-001" in result
        assert result["user-001"]["name"] == "Jane Doe"

    @pytest.mark.asyncio
    async def test_batch_fetch_skips_failed(self, user_service: UserService) -> None:
        """Users that fail to fetch are excluded from the result."""
        mock_resp_ok = _mock_response(200, ZITADEL_USER_RESPONSE)
        mock_resp_fail = _mock_response(404)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[mock_resp_ok, mock_resp_fail])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await user_service.get_users_info(["user-001", "user-missing"])

        assert "user-001" in result
        assert "user-missing" not in result


class TestSearchUsers:
    """Tests for search_users()."""

    @pytest.mark.asyncio
    async def test_search_with_results(self, user_service: UserService) -> None:
        """Search returns matching users and total count."""
        mock_resp = _mock_response(200, ZITADEL_SEARCH_RESPONSE)

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            results, total = await user_service.search_users("jane")

        assert total == 2
        assert len(results) == 2
        assert results[0]["id"] == "user-001"
        assert results[0]["username"] == "janedoe"
        assert results[0]["display_name"] == "Jane Doe"

    @pytest.mark.asyncio
    async def test_search_populates_cache(self, user_service: UserService) -> None:
        """Search results are opportunistically cached."""
        mock_resp = _mock_response(200, ZITADEL_SEARCH_RESPONSE)

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            await user_service.search_users("jane")

        # user-001 and user-002 should now be cached
        assert "user-001" in user_service._cache
        assert "user-002" in user_service._cache

    @pytest.mark.asyncio
    async def test_search_no_token_returns_empty(
        self, user_service: UserService, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Returns empty results when no service token is configured."""
        monkeypatch.setattr(
            "ontokit.services.user_service.settings",
            type(
                "S",
                (),
                {
                    "zitadel_service_token": "",
                    "zitadel_issuer": "https://auth.example.com",
                    "zitadel_internal_url": "",
                },
            )(),
        )
        results, total = await user_service.search_users("anything")
        assert results == []
        assert total == 0

    @pytest.mark.asyncio
    async def test_search_display_name_fallback(self, user_service: UserService) -> None:
        """User without displayName falls back to givenName + familyName."""
        mock_resp = _mock_response(200, ZITADEL_SEARCH_RESPONSE)

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            results, _ = await user_service.search_users("john")

        # Second user has displayName=None, should fall back
        user_002 = next(r for r in results if r["id"] == "user-002")
        assert user_002["display_name"] == "John Smith"


class TestGetServiceToken:
    """Tests for _get_service_token()."""

    def test_returns_token_from_settings(self, user_service: UserService) -> None:
        """Returns the configured service token."""
        token = user_service._get_service_token()
        assert token == "test-service-token"

    def test_returns_none_when_empty(
        self, user_service: UserService, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Returns None when token is empty string."""
        monkeypatch.setattr(
            "ontokit.services.user_service.settings",
            type(
                "S",
                (),
                {
                    "zitadel_service_token": "",
                    "zitadel_issuer": "https://auth.example.com",
                    "zitadel_internal_url": "",
                },
            )(),
        )
        assert user_service._get_service_token() is None


class TestClearCache:
    """Tests for clear_cache()."""

    def test_clears_all_entries(self, user_service: UserService) -> None:
        """clear_cache empties the internal cache."""
        user_service._cache["user-001"] = {
            "id": "user-001",
            "name": "Cached User",
            "email": "cached@example.com",
        }
        assert len(user_service._cache) == 1
        user_service.clear_cache()
        assert len(user_service._cache) == 0


class TestGetUserServiceSingleton:
    """Tests for get_user_service() factory."""

    def test_returns_user_service_instance(self) -> None:
        """get_user_service returns a UserService singleton."""
        # Reset singleton for clean test
        import ontokit.services.user_service as mod

        mod._user_service = None
        svc = get_user_service()
        assert isinstance(svc, UserService)

    def test_returns_same_instance(self) -> None:
        """Repeated calls return the same singleton."""
        import ontokit.services.user_service as mod

        mod._user_service = None
        svc1 = get_user_service()
        svc2 = get_user_service()
        assert svc1 is svc2
