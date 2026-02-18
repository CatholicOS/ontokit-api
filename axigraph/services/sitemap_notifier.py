"""Sitemap revalidation notifier.

Sends fire-and-forget HTTP requests to the frontend to update sitemap.xml
when public projects are created, updated, or deleted.
"""

import logging
from datetime import datetime
from uuid import UUID

import httpx

from axigraph.core.config import settings

logger = logging.getLogger(__name__)


def _is_configured() -> bool:
    return bool(settings.frontend_url and settings.revalidation_secret)


async def notify_sitemap_add(project_id: UUID, lastmod: datetime | None = None) -> None:
    """Notify the frontend to add a project URL to the sitemap."""
    if not _is_configured():
        return

    payload: dict = {
        "secret": settings.revalidation_secret,
        "action": "add",
        "url": f"/projects/{project_id}",
    }
    if lastmod is not None:
        payload["lastmod"] = lastmod.isoformat()

    await _post(payload)


async def notify_sitemap_remove(project_id: UUID) -> None:
    """Notify the frontend to remove a project URL from the sitemap."""
    if not _is_configured():
        return

    payload = {
        "secret": settings.revalidation_secret,
        "action": "remove",
        "url": f"/projects/{project_id}",
    }
    await _post(payload)


async def _post(payload: dict) -> None:
    """POST to the frontend sitemap revalidation endpoint. Logs warnings on failure."""
    url = f"{settings.frontend_url}/api/sitemap"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code >= 400:
                logger.warning("Sitemap revalidation failed: %s %s", resp.status_code, resp.text)
    except Exception:
        logger.warning("Sitemap revalidation request to %s failed", url, exc_info=True)
