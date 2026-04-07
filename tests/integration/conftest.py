"""Integration test fixtures with real database and Redis."""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_DATABASE_URL = os.environ.get("DATABASE_URL")
_REDIS_URL = os.environ.get("REDIS_URL")

needs_db = pytest.mark.skipif(not _DATABASE_URL, reason="DATABASE_URL not set")
needs_redis = pytest.mark.skipif(not _REDIS_URL, reason="REDIS_URL not set")


@pytest_asyncio.fixture
async def real_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Create a real async database session, rolling back after each test."""
    if not _DATABASE_URL:
        pytest.skip("DATABASE_URL not set")

    engine = create_async_engine(_DATABASE_URL, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        yield session
        await session.rollback()

    await engine.dispose()


@pytest_asyncio.fixture
async def real_redis() -> AsyncGenerator[object, None]:
    """Create a real Redis client."""
    if not _REDIS_URL:
        pytest.skip("REDIS_URL not set")

    import redis.asyncio as aioredis

    client = aioredis.from_url(_REDIS_URL)  # type: ignore[no-untyped-call]
    yield client
    await client.aclose()
