"""Tests for auth core functions: validate_token, get_jwks, get_current_user, etc."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from ontokit.core.auth import (
    CurrentUser,
    TokenPayload,
    clear_jwks_cache,
    get_current_user,
    get_current_user_optional,
    get_current_user_with_token,
    get_jwks,
    validate_token,
)

# ---------------------------------------------------------------------------
# Constants / helpers
# ---------------------------------------------------------------------------

FAKE_JWKS = {
    "keys": [
        {
            "kid": "test-key-id",
            "kty": "RSA",
            "n": "fake-n-value",
            "e": "AQAB",
            "alg": "RS256",
            "use": "sig",
        }
    ]
}

FAKE_OIDC_CONFIG = {
    "jwks_uri": "https://issuer.example.com/oauth/v2/keys",
}

FAKE_TOKEN_PAYLOAD = {
    "sub": "user-123",
    "exp": 9999999999,
    "iat": 1000000000,
    "iss": "https://issuer.example.com",
    "aud": ["test-client-id"],
    "azp": "test-client-id",
    "email": "user@example.com",
    "name": "Test User",
    "preferred_username": "testuser",
}


def _make_credentials(token: str = "fake-jwt-token") -> MagicMock:
    """Create a mock HTTPAuthorizationCredentials."""
    creds = MagicMock()
    creds.credentials = token
    return creds


# ---------------------------------------------------------------------------
# get_jwks
# ---------------------------------------------------------------------------


class TestGetJWKS:
    """Tests for the JWKS fetching and caching logic."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self) -> None:
        """Clear the JWKS cache before each test."""
        clear_jwks_cache()

    @pytest.mark.asyncio
    @patch("ontokit.core.auth.settings")
    @patch("ontokit.core.auth.httpx.AsyncClient")
    async def test_get_jwks_fetches_from_oidc_config(
        self, mock_client_cls: MagicMock, mock_settings: MagicMock
    ) -> None:
        """get_jwks fetches OIDC config then JWKS URI."""
        mock_settings.zitadel_internal_url = None
        mock_settings.zitadel_issuer = "https://issuer.example.com"
        mock_settings.zitadel_jwks_base_url = "https://issuer.example.com"

        oidc_response = MagicMock()
        oidc_response.json.return_value = FAKE_OIDC_CONFIG
        oidc_response.raise_for_status = MagicMock()

        jwks_response = MagicMock()
        jwks_response.json.return_value = FAKE_JWKS
        jwks_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[oidc_response, jwks_response])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await get_jwks()
        assert result == FAKE_JWKS
        assert mock_client.get.call_count == 2

    @pytest.mark.asyncio
    @patch("ontokit.core.auth.settings")
    @patch("ontokit.core.auth.httpx.AsyncClient")
    async def test_get_jwks_uses_cache_on_second_call(
        self, mock_client_cls: MagicMock, mock_settings: MagicMock
    ) -> None:
        """Second call within TTL uses cached value without network request."""
        mock_settings.zitadel_internal_url = None
        mock_settings.zitadel_issuer = "https://issuer.example.com"
        mock_settings.zitadel_jwks_base_url = "https://issuer.example.com"

        oidc_response = MagicMock()
        oidc_response.json.return_value = FAKE_OIDC_CONFIG
        oidc_response.raise_for_status = MagicMock()

        jwks_response = MagicMock()
        jwks_response.json.return_value = FAKE_JWKS
        jwks_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[oidc_response, jwks_response])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result1 = await get_jwks()
        result2 = await get_jwks()
        assert result1 == result2
        # Only 2 network calls total (OIDC + JWKS from first invocation)
        assert mock_client.get.call_count == 2

    @pytest.mark.asyncio
    @patch("ontokit.core.auth.settings")
    @patch("ontokit.core.auth.httpx.AsyncClient")
    async def test_get_jwks_force_refresh_bypasses_cache(
        self, mock_client_cls: MagicMock, mock_settings: MagicMock
    ) -> None:
        """force_refresh=True causes a fresh fetch even when cache is valid."""
        mock_settings.zitadel_internal_url = None
        mock_settings.zitadel_issuer = "https://issuer.example.com"
        mock_settings.zitadel_jwks_base_url = "https://issuer.example.com"

        oidc_response = MagicMock()
        oidc_response.json.return_value = FAKE_OIDC_CONFIG
        oidc_response.raise_for_status = MagicMock()

        jwks_response = MagicMock()
        jwks_response.json.return_value = FAKE_JWKS
        jwks_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            side_effect=[
                oidc_response,
                jwks_response,
                oidc_response,
                jwks_response,
            ]
        )
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        await get_jwks()
        await get_jwks(force_refresh=True)
        # 4 calls: 2 for initial fetch + 2 for force refresh
        assert mock_client.get.call_count == 4

    @pytest.mark.asyncio
    @patch("ontokit.core.auth.settings")
    @patch("ontokit.core.auth.httpx.AsyncClient")
    async def test_get_jwks_http_error_raises_503(
        self, mock_client_cls: MagicMock, mock_settings: MagicMock
    ) -> None:
        """HTTP errors when fetching JWKS raise 503."""
        import httpx

        mock_settings.zitadel_internal_url = None
        mock_settings.zitadel_issuer = "https://issuer.example.com"
        mock_settings.zitadel_jwks_base_url = "https://issuer.example.com"

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.HTTPError("connection failed"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        with pytest.raises(HTTPException) as exc_info:
            await get_jwks()
        assert exc_info.value.status_code == 503


# ---------------------------------------------------------------------------
# validate_token
# ---------------------------------------------------------------------------


class TestValidateToken:
    """Tests for JWT token validation."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self) -> None:
        clear_jwks_cache()

    @pytest.mark.asyncio
    @patch("ontokit.core.auth.settings")
    @patch("ontokit.core.auth.get_jwks")
    @patch("ontokit.core.auth.jwt")
    async def test_validate_token_success(
        self, mock_jwt: MagicMock, mock_get_jwks: AsyncMock, mock_settings: MagicMock
    ) -> None:
        """A valid token returns a TokenPayload."""
        mock_settings.zitadel_issuer = "https://issuer.example.com"
        mock_settings.zitadel_client_id = "test-client-id"

        mock_get_jwks.return_value = FAKE_JWKS
        mock_jwt.get_unverified_header.return_value = {"kid": "test-key-id", "alg": "RS256"}
        mock_jwt.decode.return_value = FAKE_TOKEN_PAYLOAD

        result = await validate_token("fake-jwt")
        assert isinstance(result, TokenPayload)
        assert result.sub == "user-123"
        assert result.email == "user@example.com"

    @pytest.mark.asyncio
    @patch("ontokit.core.auth.settings")
    @patch("ontokit.core.auth.get_jwks")
    @patch("ontokit.core.auth.jwt")
    async def test_validate_token_key_not_found_refreshes_jwks(
        self, mock_jwt: MagicMock, mock_get_jwks: AsyncMock, mock_settings: MagicMock
    ) -> None:
        """When the kid is not in initial JWKS, a force refresh is attempted."""
        mock_settings.zitadel_issuer = "https://issuer.example.com"
        mock_settings.zitadel_client_id = "test-client-id"

        # First call returns empty keys, second call (force refresh) returns the key
        mock_get_jwks.side_effect = [
            {"keys": []},
            FAKE_JWKS,
        ]
        mock_jwt.get_unverified_header.return_value = {"kid": "test-key-id", "alg": "RS256"}
        mock_jwt.decode.return_value = FAKE_TOKEN_PAYLOAD

        result = await validate_token("fake-jwt")
        assert result.sub == "user-123"
        assert mock_get_jwks.call_count == 2

    @pytest.mark.asyncio
    @patch("ontokit.core.auth.settings")
    @patch("ontokit.core.auth.get_jwks")
    @patch("ontokit.core.auth.jwt")
    async def test_validate_token_key_not_found_after_refresh_raises(
        self, mock_jwt: MagicMock, mock_get_jwks: AsyncMock, mock_settings: MagicMock
    ) -> None:
        """If the kid is still missing after JWKS refresh, raises 401."""
        mock_settings.zitadel_issuer = "https://issuer.example.com"
        mock_settings.zitadel_client_id = "test-client-id"

        mock_get_jwks.return_value = {"keys": []}
        mock_jwt.get_unverified_header.return_value = {"kid": "unknown-kid", "alg": "RS256"}

        with pytest.raises(HTTPException) as exc_info:
            await validate_token("fake-jwt")
        assert exc_info.value.status_code == 401
        assert "Unable to find appropriate key" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    @patch("ontokit.core.auth.settings")
    @patch("ontokit.core.auth.get_jwks")
    @patch("ontokit.core.auth.jwt")
    async def test_validate_token_jwt_error_raises_401(
        self, mock_jwt: MagicMock, mock_get_jwks: AsyncMock, mock_settings: MagicMock
    ) -> None:
        """JWTError during decode raises 401."""
        from jose import JWTError

        mock_settings.zitadel_issuer = "https://issuer.example.com"
        mock_settings.zitadel_client_id = "test-client-id"

        mock_get_jwks.return_value = FAKE_JWKS
        mock_jwt.get_unverified_header.return_value = {"kid": "test-key-id", "alg": "RS256"}
        mock_jwt.decode.side_effect = JWTError("invalid token")

        with pytest.raises(HTTPException) as exc_info:
            await validate_token("bad-jwt")
        assert exc_info.value.status_code == 401
        assert "Token validation failed" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    @patch("ontokit.core.auth.settings")
    @patch("ontokit.core.auth.get_jwks")
    @patch("ontokit.core.auth.jwt")
    async def test_validate_token_invalid_audience_raises(
        self, mock_jwt: MagicMock, mock_get_jwks: AsyncMock, mock_settings: MagicMock
    ) -> None:
        """Token with wrong audience and azp raises 401."""
        mock_settings.zitadel_issuer = "https://issuer.example.com"
        mock_settings.zitadel_client_id = "my-client-id"

        mock_get_jwks.return_value = FAKE_JWKS
        mock_jwt.get_unverified_header.return_value = {"kid": "test-key-id", "alg": "RS256"}
        mock_jwt.decode.return_value = {
            **FAKE_TOKEN_PAYLOAD,
            "aud": ["other-client"],
            "azp": "other-client",
        }

        with pytest.raises(HTTPException) as exc_info:
            await validate_token("fake-jwt")
        assert exc_info.value.status_code == 401
        assert "Invalid audience" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    @patch("ontokit.core.auth.settings")
    @patch("ontokit.core.auth.get_jwks")
    @patch("ontokit.core.auth.jwt")
    async def test_validate_token_string_audience(
        self, mock_jwt: MagicMock, mock_get_jwks: AsyncMock, mock_settings: MagicMock
    ) -> None:
        """Token with string audience (not list) is accepted when it matches."""
        mock_settings.zitadel_issuer = "https://issuer.example.com"
        mock_settings.zitadel_client_id = "test-client-id"

        mock_get_jwks.return_value = FAKE_JWKS
        mock_jwt.get_unverified_header.return_value = {"kid": "test-key-id", "alg": "RS256"}
        mock_jwt.decode.return_value = {
            **FAKE_TOKEN_PAYLOAD,
            "aud": "test-client-id",
        }

        result = await validate_token("fake-jwt")
        assert result.sub == "user-123"

    @pytest.mark.asyncio
    @patch("ontokit.core.auth.settings")
    @patch("ontokit.core.auth.get_jwks")
    @patch("ontokit.core.auth.jwt")
    async def test_validate_token_azp_fallback(
        self, mock_jwt: MagicMock, mock_get_jwks: AsyncMock, mock_settings: MagicMock
    ) -> None:
        """When aud doesn't match, azp matching the client_id is accepted."""
        mock_settings.zitadel_issuer = "https://issuer.example.com"
        mock_settings.zitadel_client_id = "test-client-id"

        mock_get_jwks.return_value = FAKE_JWKS
        mock_jwt.get_unverified_header.return_value = {"kid": "test-key-id", "alg": "RS256"}
        mock_jwt.decode.return_value = {
            **FAKE_TOKEN_PAYLOAD,
            "aud": ["other-client"],
            "azp": "test-client-id",
        }

        result = await validate_token("fake-jwt")
        assert result.sub == "user-123"

    @pytest.mark.asyncio
    @patch("ontokit.core.auth.settings")
    @patch("ontokit.core.auth.get_jwks")
    @patch("ontokit.core.auth.jwt")
    async def test_validate_token_extracts_roles(
        self, mock_jwt: MagicMock, mock_get_jwks: AsyncMock, mock_settings: MagicMock
    ) -> None:
        """Roles are extracted from the Zitadel roles claim in the token."""
        mock_settings.zitadel_issuer = "https://issuer.example.com"
        mock_settings.zitadel_client_id = "test-client-id"

        mock_get_jwks.return_value = FAKE_JWKS
        mock_jwt.get_unverified_header.return_value = {"kid": "test-key-id", "alg": "RS256"}
        mock_jwt.decode.return_value = {
            **FAKE_TOKEN_PAYLOAD,
            "urn:zitadel:iam:org:project:roles": {
                "admin": {"org_123": "My Org"},
            },
        }

        result = await validate_token("fake-jwt")
        assert "admin" in result.roles


# ---------------------------------------------------------------------------
# get_current_user
# ---------------------------------------------------------------------------


class TestGetCurrentUser:
    """Tests for the get_current_user dependency."""

    @pytest.mark.asyncio
    async def test_no_credentials_raises_401(self) -> None:
        """No credentials raises 401."""
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(None)
        assert exc_info.value.status_code == 401
        assert "Not authenticated" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    @patch("ontokit.core.auth.fetch_userinfo", new_callable=AsyncMock)
    @patch("ontokit.core.auth.validate_token", new_callable=AsyncMock)
    async def test_valid_credentials_returns_user(
        self, mock_validate: AsyncMock, mock_fetch_userinfo: AsyncMock
    ) -> None:
        """Valid credentials return a CurrentUser with token info."""
        mock_validate.return_value = TokenPayload(
            sub="user-123",
            exp=9999999999,
            iat=1000000000,
            iss="https://issuer.example.com",
            email="user@example.com",
            name="Test User",
            preferred_username="testuser",
            roles=["editor"],
        )
        mock_fetch_userinfo.return_value = None

        creds = _make_credentials("valid-token")
        result = await get_current_user(creds)

        assert isinstance(result, CurrentUser)
        assert result.id == "user-123"
        assert result.email == "user@example.com"
        assert result.name == "Test User"

    @pytest.mark.asyncio
    @patch("ontokit.core.auth.fetch_userinfo", new_callable=AsyncMock)
    @patch("ontokit.core.auth.validate_token", new_callable=AsyncMock)
    async def test_get_current_user_enriches_from_userinfo(
        self, mock_validate: AsyncMock, mock_fetch_userinfo: AsyncMock
    ) -> None:
        """When token lacks name/email, userinfo endpoint provides them."""
        mock_validate.return_value = TokenPayload(
            sub="user-123",
            exp=9999999999,
            iat=1000000000,
            iss="https://issuer.example.com",
            # name, email, preferred_username all None
        )
        mock_fetch_userinfo.return_value = {
            "name": "From Userinfo",
            "email": "userinfo@example.com",
            "preferred_username": "userinfouser",
        }

        creds = _make_credentials("valid-token")
        result = await get_current_user(creds)

        assert result.name == "From Userinfo"
        assert result.email == "userinfo@example.com"
        assert result.username == "userinfouser"


# ---------------------------------------------------------------------------
# get_current_user_optional
# ---------------------------------------------------------------------------


class TestGetCurrentUserOptional:
    """Tests for the get_current_user_optional dependency."""

    @pytest.mark.asyncio
    async def test_no_credentials_returns_none(self) -> None:
        """When no credentials are provided, None is returned."""
        result = await get_current_user_optional(None)
        assert result is None

    @pytest.mark.asyncio
    @patch("ontokit.core.auth.fetch_userinfo", new_callable=AsyncMock)
    @patch("ontokit.core.auth.validate_token", new_callable=AsyncMock)
    async def test_valid_credentials_returns_user(
        self, mock_validate: AsyncMock, mock_fetch_userinfo: AsyncMock
    ) -> None:
        """Valid credentials return the user."""
        mock_validate.return_value = TokenPayload(
            sub="user-456",
            exp=9999999999,
            iat=1000000000,
            iss="https://issuer.example.com",
            name="Optional User",
            email="optional@example.com",
            preferred_username="optuser",
            roles=["viewer"],
        )
        mock_fetch_userinfo.return_value = None

        creds = _make_credentials("valid-token")
        result = await get_current_user_optional(creds)

        assert result is not None
        assert result.id == "user-456"

    @pytest.mark.asyncio
    @patch("ontokit.core.auth.validate_token", new_callable=AsyncMock)
    async def test_invalid_token_returns_none(self, mock_validate: AsyncMock) -> None:
        """An invalid token returns None instead of raising."""
        mock_validate.side_effect = HTTPException(status_code=401, detail="bad token")

        creds = _make_credentials("bad-token")
        result = await get_current_user_optional(creds)
        assert result is None


# ---------------------------------------------------------------------------
# get_current_user_with_token
# ---------------------------------------------------------------------------


class TestGetCurrentUserWithToken:
    """Tests for the get_current_user_with_token dependency."""

    @pytest.mark.asyncio
    async def test_no_credentials_raises_401(self) -> None:
        """No credentials raises 401."""
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user_with_token(None)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    @patch("ontokit.core.auth.fetch_userinfo", new_callable=AsyncMock)
    @patch("ontokit.core.auth.validate_token", new_callable=AsyncMock)
    async def test_returns_user_and_token_tuple(
        self, mock_validate: AsyncMock, mock_fetch_userinfo: AsyncMock
    ) -> None:
        """Returns a tuple of (CurrentUser, access_token)."""
        mock_validate.return_value = TokenPayload(
            sub="user-789",
            exp=9999999999,
            iat=1000000000,
            iss="https://issuer.example.com",
            name="Token User",
            email="token@example.com",
            preferred_username="tokenuser",
            roles=["admin"],
        )
        mock_fetch_userinfo.return_value = None

        creds = _make_credentials("my-access-token")
        user, token = await get_current_user_with_token(creds)

        assert isinstance(user, CurrentUser)
        assert user.id == "user-789"
        assert token == "my-access-token"
