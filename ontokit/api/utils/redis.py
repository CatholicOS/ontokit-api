"""Shared ARQ Redis pool for background job enqueueing."""

from arq import ArqRedis, create_pool
from arq.connections import RedisSettings

from ontokit.core.config import settings

_arq_pool: ArqRedis | None = None


async def get_arq_pool() -> ArqRedis:
    """Get or create the ARQ Redis connection pool."""
    global _arq_pool
    if _arq_pool is None:
        redis_settings = RedisSettings.from_dsn(str(settings.redis_url))
        _arq_pool = await create_pool(redis_settings)
    return _arq_pool


async def close_arq_pool() -> None:
    """Close the cached ARQ Redis pool."""
    global _arq_pool
    if _arq_pool is not None:
        await _arq_pool.close()
        _arq_pool = None
