"""Tests for sitemap notifier (ontokit/services/sitemap_notifier.py)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ontokit.services import sitemap_notifier

PROJECT_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")


@pytest.fixture
def mock_http_client() -> AsyncMock:
    """Build and return a fully-configured AsyncMock HTTP client."""
    mock_response = MagicMock()
    mock_response.status_code = 200

    client = AsyncMock()
    client.post = AsyncMock(return_value=mock_response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


def _extract_payload(mock_client: AsyncMock) -> dict[str, str]:
    """Extract the JSON payload from the mocked post call."""
    return mock_client.post.call_args.kwargs["json"]  # type: ignore[no-any-return]


class TestNotifySitemapAdd:
    """Tests for notify_sitemap_add()."""

    @pytest.mark.asyncio
    async def test_does_nothing_when_not_configured(self) -> None:
        """Returns early when frontend_url or revalidation_secret is empty."""
        with (
            patch.object(sitemap_notifier, "_is_configured", return_value=False),
            patch("ontokit.services.sitemap_notifier.httpx.AsyncClient") as mock_cls,
        ):
            await sitemap_notifier.notify_sitemap_add(PROJECT_ID)
            mock_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_posts_add_payload(self, mock_http_client: AsyncMock) -> None:
        """Posts the correct payload when configured."""
        with (
            patch.object(sitemap_notifier, "_is_configured", return_value=True),
            patch.object(sitemap_notifier.settings, "frontend_url", "http://localhost:3000"),  # type: ignore[attr-defined]
            patch.object(sitemap_notifier.settings, "revalidation_secret", "test-secret"),  # type: ignore[attr-defined]
            patch(
                "ontokit.services.sitemap_notifier.httpx.AsyncClient",
                return_value=mock_http_client,
            ),
        ):
            await sitemap_notifier.notify_sitemap_add(PROJECT_ID)
            mock_http_client.post.assert_awaited_once()
            payload = _extract_payload(mock_http_client)
            assert payload["action"] == "add"
            assert f"/projects/{PROJECT_ID}" in payload["url"]

    @pytest.mark.asyncio
    async def test_includes_lastmod_when_provided(self, mock_http_client: AsyncMock) -> None:
        """Includes lastmod in the payload when provided."""
        lastmod = datetime(2025, 6, 15, 12, 0, 0, tzinfo=UTC)

        with (
            patch.object(sitemap_notifier, "_is_configured", return_value=True),
            patch.object(sitemap_notifier.settings, "frontend_url", "http://localhost:3000"),  # type: ignore[attr-defined]
            patch.object(sitemap_notifier.settings, "revalidation_secret", "test-secret"),  # type: ignore[attr-defined]
            patch(
                "ontokit.services.sitemap_notifier.httpx.AsyncClient",
                return_value=mock_http_client,
            ),
        ):
            await sitemap_notifier.notify_sitemap_add(PROJECT_ID, lastmod=lastmod)
            payload = _extract_payload(mock_http_client)
            assert payload["lastmod"] == lastmod.isoformat()


class TestNotifySitemapRemove:
    """Tests for notify_sitemap_remove()."""

    @pytest.mark.asyncio
    async def test_does_nothing_when_not_configured(self) -> None:
        """Returns early when not configured."""
        with (
            patch.object(sitemap_notifier, "_is_configured", return_value=False),
            patch("ontokit.services.sitemap_notifier.httpx.AsyncClient") as mock_cls,
        ):
            await sitemap_notifier.notify_sitemap_remove(PROJECT_ID)
            mock_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_posts_remove_payload(self, mock_http_client: AsyncMock) -> None:
        """Posts the correct remove payload when configured."""
        with (
            patch.object(sitemap_notifier, "_is_configured", return_value=True),
            patch.object(sitemap_notifier.settings, "frontend_url", "http://localhost:3000"),  # type: ignore[attr-defined]
            patch.object(sitemap_notifier.settings, "revalidation_secret", "test-secret"),  # type: ignore[attr-defined]
            patch(
                "ontokit.services.sitemap_notifier.httpx.AsyncClient",
                return_value=mock_http_client,
            ),
        ):
            await sitemap_notifier.notify_sitemap_remove(PROJECT_ID)
            mock_http_client.post.assert_awaited_once()
            payload = _extract_payload(mock_http_client)
            assert payload["action"] == "remove"
            assert f"/projects/{PROJECT_ID}" in payload["url"]
