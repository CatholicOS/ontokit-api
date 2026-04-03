"""Tests for the three auth modes: required, optional, disabled."""

from unittest.mock import patch

import pytest
from fastapi import HTTPException

from ontokit.core.auth import (
    ANONYMOUS_USER,
    CurrentUser,
    get_current_user,
    get_current_user_optional,
    get_current_user_with_token,
)


# ---------------------------------------------------------------------------
# ANONYMOUS_USER constant
# ---------------------------------------------------------------------------


class TestAnonymousUser:
    """Tests for the ANONYMOUS_USER constant."""

    def test_anonymous_user_id(self) -> None:
        """ANONYMOUS_USER has id='anonymous'."""
        assert ANONYMOUS_USER.id == "anonymous"

    def test_anonymous_user_roles(self) -> None:
        """ANONYMOUS_USER has roles=['viewer']."""
        assert ANONYMOUS_USER.roles == ["viewer"]

    @patch("ontokit.core.auth.settings")
    def test_anonymous_user_is_not_superadmin(self, mock_settings) -> None:  # noqa: ANN001
        """ANONYMOUS_USER is never a superadmin."""
        mock_settings.superadmin_ids = set()
        assert ANONYMOUS_USER.is_superadmin is False

    def test_anonymous_user_is_current_user_instance(self) -> None:
        """ANONYMOUS_USER is an instance of CurrentUser."""
        assert isinstance(ANONYMOUS_USER, CurrentUser)


# ---------------------------------------------------------------------------
# AUTH_MODE=disabled
# ---------------------------------------------------------------------------


class TestAuthModeDisabled:
    """Tests for AUTH_MODE=disabled — all functions return ANONYMOUS_USER."""

    @pytest.mark.asyncio
    @patch("ontokit.core.auth.settings")
    async def test_disabled_get_current_user_returns_anonymous(self, mock_settings) -> None:  # noqa: ANN001
        """In disabled mode, get_current_user returns ANONYMOUS_USER (no credentials needed)."""
        mock_settings.auth_mode = "disabled"
        result = await get_current_user(credentials=None)
        assert result is ANONYMOUS_USER

    @pytest.mark.asyncio
    @patch("ontokit.core.auth.settings")
    async def test_disabled_get_current_user_optional_returns_anonymous(self, mock_settings) -> None:  # noqa: ANN001
        """In disabled mode, get_current_user_optional returns ANONYMOUS_USER (not None)."""
        mock_settings.auth_mode = "disabled"
        result = await get_current_user_optional(credentials=None)
        assert result is ANONYMOUS_USER

    @pytest.mark.asyncio
    @patch("ontokit.core.auth.settings")
    async def test_disabled_get_current_user_with_token_returns_anonymous(self, mock_settings) -> None:  # noqa: ANN001
        """In disabled mode, get_current_user_with_token returns (ANONYMOUS_USER, 'anonymous')."""
        mock_settings.auth_mode = "disabled"
        user, token = await get_current_user_with_token(credentials=None)
        assert user is ANONYMOUS_USER
        assert token == "anonymous"


# ---------------------------------------------------------------------------
# AUTH_MODE=required (default)
# ---------------------------------------------------------------------------


class TestAuthModeRequired:
    """Tests for AUTH_MODE=required — existing behavior, 401 without credentials."""

    @pytest.mark.asyncio
    @patch("ontokit.core.auth.settings")
    async def test_required_get_current_user_raises_401_without_credentials(self, mock_settings) -> None:  # noqa: ANN001
        """In required mode, get_current_user raises 401 when no credentials provided."""
        mock_settings.auth_mode = "required"
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(credentials=None)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    @patch("ontokit.core.auth.settings")
    async def test_required_get_current_user_optional_returns_none_without_credentials(self, mock_settings) -> None:  # noqa: ANN001
        """In required mode, get_current_user_optional returns None when no credentials provided."""
        mock_settings.auth_mode = "required"
        result = await get_current_user_optional(credentials=None)
        assert result is None


# ---------------------------------------------------------------------------
# AUTH_MODE=optional
# ---------------------------------------------------------------------------


class TestAuthModeOptional:
    """Tests for AUTH_MODE=optional — GET endpoints work anonymously, writes require auth."""

    @pytest.mark.asyncio
    @patch("ontokit.core.auth.settings")
    async def test_optional_get_current_user_raises_401_without_credentials(self, mock_settings) -> None:  # noqa: ANN001
        """In optional mode, get_current_user (RequiredUser) raises 401 without credentials (write protection)."""
        mock_settings.auth_mode = "optional"
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(credentials=None)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    @patch("ontokit.core.auth.settings")
    async def test_optional_get_current_user_optional_returns_none_without_credentials(self, mock_settings) -> None:  # noqa: ANN001
        """In optional mode, get_current_user_optional returns None without credentials (browse works)."""
        mock_settings.auth_mode = "optional"
        result = await get_current_user_optional(credentials=None)
        assert result is None
