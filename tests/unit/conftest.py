"""Unit test fixtures."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from ontokit.core.auth import CurrentUser, get_current_user, get_current_user_optional
from ontokit.core.database import get_db
from ontokit.main import app


@pytest.fixture
def authed_client() -> Generator[tuple[TestClient, AsyncMock], None, None]:
    """TestClient with mocked DB and authenticated user.

    Returns (client, mock_session) so tests can configure DB responses.
    """
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()
    mock_session.close = AsyncMock()
    mock_session.execute = AsyncMock()
    mock_session.refresh = AsyncMock()
    mock_session.add = lambda _x: None  # sync method
    mock_session.delete = AsyncMock()

    user = CurrentUser(
        id="test-user-id",
        email="test@example.com",
        name="Test User",
        username="testuser",
        roles=["owner"],
    )

    async def _override_get_db() -> Any:
        yield mock_session

    async def _override_get_current_user() -> CurrentUser:
        return user

    async def _override_get_current_user_optional() -> CurrentUser | None:
        return user

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_get_current_user
    app.dependency_overrides[get_current_user_optional] = _override_get_current_user_optional

    client = TestClient(app, raise_server_exceptions=False)
    yield client, mock_session

    app.dependency_overrides.clear()
