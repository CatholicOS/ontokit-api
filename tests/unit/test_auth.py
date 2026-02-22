"""Tests for the authentication and authorization module."""

from unittest.mock import patch

import pytest
from fastapi import HTTPException

from ontokit.core.auth import (
    ZITADEL_ROLES_CLAIM,
    CurrentUser,
    PermissionChecker,
    TokenPayload,
    _JWKS_CACHE_TTL,
    _extract_roles,
    clear_jwks_cache,
)


# ---------------------------------------------------------------------------
# _extract_roles
# ---------------------------------------------------------------------------


class TestExtractRoles:
    """Tests for the _extract_roles helper function."""

    def test_extract_roles_with_roles(self) -> None:
        """Payload with the Zitadel roles claim returns role names."""
        payload = {
            ZITADEL_ROLES_CLAIM: {
                "admin": {"org_123": "My Org"},
                "editor": {"org_123": "My Org"},
            },
        }
        roles = _extract_roles(payload)
        assert sorted(roles) == ["admin", "editor"]

    def test_extract_roles_empty(self) -> None:
        """Payload without a roles claim returns an empty list."""
        payload = {"sub": "user-1", "exp": 0}
        roles = _extract_roles(payload)
        assert roles == []

    def test_extract_roles_not_dict(self) -> None:
        """Non-dict roles claim value returns an empty list."""
        payload_str = {ZITADEL_ROLES_CLAIM: "not-a-dict"}
        assert _extract_roles(payload_str) == []

        payload_list = {ZITADEL_ROLES_CLAIM: ["admin", "editor"]}
        assert _extract_roles(payload_list) == []

        payload_none = {ZITADEL_ROLES_CLAIM: None}
        assert _extract_roles(payload_none) == []


# ---------------------------------------------------------------------------
# TokenPayload model
# ---------------------------------------------------------------------------


class TestTokenPayload:
    """Tests for the TokenPayload Pydantic model."""

    def test_token_payload_defaults(self) -> None:
        """TokenPayload has correct default values for optional fields."""
        payload = TokenPayload(
            sub="user-1",
            exp=9999999999,
            iat=1000000000,
            iss="https://issuer.example.com",
        )
        assert payload.sub == "user-1"
        assert payload.aud is None
        assert payload.azp is None
        assert payload.scope is None
        assert payload.email is None
        assert payload.name is None
        assert payload.preferred_username is None
        assert payload.roles == []


# ---------------------------------------------------------------------------
# CurrentUser model
# ---------------------------------------------------------------------------


class TestCurrentUser:
    """Tests for the CurrentUser Pydantic model."""

    @patch("ontokit.core.auth.settings")
    def test_current_user_is_superadmin(self, mock_settings) -> None:  # noqa: ANN001
        """User whose id is in superadmin_ids is detected as superadmin."""
        mock_settings.superadmin_ids = {"super-user-id", "other-admin"}
        user = CurrentUser(
            id="super-user-id",
            email="admin@example.com",
            name="Super Admin",
            roles=["admin"],
        )
        assert user.is_superadmin is True

    @patch("ontokit.core.auth.settings")
    def test_current_user_not_superadmin(self, mock_settings) -> None:  # noqa: ANN001
        """User whose id is NOT in superadmin_ids is not superadmin."""
        mock_settings.superadmin_ids = {"super-user-id"}
        user = CurrentUser(
            id="regular-user-id",
            email="user@example.com",
            name="Regular User",
            roles=["editor"],
        )
        assert user.is_superadmin is False


# ---------------------------------------------------------------------------
# PermissionChecker
# ---------------------------------------------------------------------------


class TestPermissionChecker:
    """Tests for the PermissionChecker dependency."""

    @pytest.mark.asyncio
    async def test_permission_checker_allows(self) -> None:
        """PermissionChecker allows a user who has at least one matching role."""
        checker = PermissionChecker(required_roles=["editor", "admin"])
        user = CurrentUser(
            id="user-1",
            email="user@example.com",
            name="Test User",
            roles=["editor"],
        )
        result = await checker(user)
        assert result is user

    @pytest.mark.asyncio
    async def test_permission_checker_denies(self) -> None:
        """PermissionChecker raises 403 when user lacks required roles."""
        checker = PermissionChecker(required_roles=["admin"])
        user = CurrentUser(
            id="user-1",
            email="user@example.com",
            name="Test User",
            roles=["viewer"],
        )
        with pytest.raises(HTTPException) as exc_info:
            await checker(user)
        assert exc_info.value.status_code == 403
        assert "Insufficient permissions" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_permission_checker_no_requirements(self) -> None:
        """PermissionChecker with no required_roles allows any authenticated user."""
        checker = PermissionChecker(required_roles=[])
        user = CurrentUser(
            id="user-1",
            email="user@example.com",
            name="Test User",
            roles=[],
        )
        result = await checker(user)
        assert result is user


# ---------------------------------------------------------------------------
# JWKS cache
# ---------------------------------------------------------------------------


class TestJWKSCache:
    """Tests for the JWKS cache behaviour."""

    def test_jwks_cache_ttl(self) -> None:
        """JWKS cache TTL is set to one hour (3600 seconds)."""
        assert _JWKS_CACHE_TTL == 3600

    @pytest.mark.asyncio
    async def test_jwks_cache_cleared(self) -> None:
        """clear_jwks_cache resets the cache so the next call refetches."""
        clear_jwks_cache()
        import ontokit.core.auth as auth_mod

        assert auth_mod._jwks_cache is None
        assert auth_mod._jwks_cache_time == 0.0
