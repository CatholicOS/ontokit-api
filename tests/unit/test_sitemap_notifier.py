"""Tests for sitemap notifier (ontokit/services/sitemap_notifier.py)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ontokit.services import sitemap_notifier

PROJECT_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")


class TestNotifySitemapAdd:
    """Tests for notify_sitemap_add()."""

    @pytest.mark.asyncio
    async def test_does_nothing_when_not_configured(self) -> None:
        """Returns early when frontend_url or revalidation_secret is empty."""
        with patch.object(sitemap_notifier, "_is_configured", return_value=False):
            # Should not raise or make any HTTP calls
            await sitemap_notifier.notify_sitemap_add(PROJECT_ID)

    @pytest.mark.asyncio
    async def test_posts_add_payload(self) -> None:
        """Posts the correct payload when configured."""
        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.object(sitemap_notifier, "_is_configured", return_value=True),
            patch.object(sitemap_notifier.settings, "frontend_url", "http://localhost:3000"),  # type: ignore[attr-defined]
            patch.object(sitemap_notifier.settings, "revalidation_secret", "test-secret"),  # type: ignore[attr-defined]
            patch("ontokit.services.sitemap_notifier.httpx.AsyncClient", return_value=mock_client),
        ):
            await sitemap_notifier.notify_sitemap_add(PROJECT_ID)
            mock_client.post.assert_awaited_once()
            call_kwargs = mock_client.post.call_args
            payload = (
                call_kwargs[1]["json"] if "json" in call_kwargs[1] else call_kwargs.kwargs["json"]
            )
            assert payload["action"] == "add"
            assert f"/projects/{PROJECT_ID}" in payload["url"]

    @pytest.mark.asyncio
    async def test_includes_lastmod_when_provided(self) -> None:
        """Includes lastmod in the payload when provided."""
        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        lastmod = datetime(2025, 6, 15, 12, 0, 0, tzinfo=UTC)

        with (
            patch.object(sitemap_notifier, "_is_configured", return_value=True),
            patch.object(sitemap_notifier.settings, "frontend_url", "http://localhost:3000"),  # type: ignore[attr-defined]
            patch.object(sitemap_notifier.settings, "revalidation_secret", "test-secret"),  # type: ignore[attr-defined]
            patch("ontokit.services.sitemap_notifier.httpx.AsyncClient", return_value=mock_client),
        ):
            await sitemap_notifier.notify_sitemap_add(PROJECT_ID, lastmod=lastmod)
            call_kwargs = mock_client.post.call_args
            payload = (
                call_kwargs[1]["json"] if "json" in call_kwargs[1] else call_kwargs.kwargs["json"]
            )
            assert "lastmod" in payload


class TestNotifySitemapRemove:
    """Tests for notify_sitemap_remove()."""

    @pytest.mark.asyncio
    async def test_does_nothing_when_not_configured(self) -> None:
        """Returns early when not configured."""
        with patch.object(sitemap_notifier, "_is_configured", return_value=False):
            await sitemap_notifier.notify_sitemap_remove(PROJECT_ID)

    @pytest.mark.asyncio
    async def test_posts_remove_payload(self) -> None:
        """Posts the correct remove payload when configured."""
        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.object(sitemap_notifier, "_is_configured", return_value=True),
            patch.object(sitemap_notifier.settings, "frontend_url", "http://localhost:3000"),  # type: ignore[attr-defined]
            patch.object(sitemap_notifier.settings, "revalidation_secret", "test-secret"),  # type: ignore[attr-defined]
            patch("ontokit.services.sitemap_notifier.httpx.AsyncClient", return_value=mock_client),
        ):
            await sitemap_notifier.notify_sitemap_remove(PROJECT_ID)
            mock_client.post.assert_awaited_once()
            call_kwargs = mock_client.post.call_args
            payload = (
                call_kwargs[1]["json"] if "json" in call_kwargs[1] else call_kwargs.kwargs["json"]
            )
            assert payload["action"] == "remove"
            assert f"/projects/{PROJECT_ID}" in payload["url"]
