"""OntoKit API - Main FastAPI Application."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy import text

from ontokit import __version__
from ontokit.api.routes import router as api_router
from ontokit.core.config import settings
from ontokit.core.database import engine
from ontokit.core.exceptions import ConflictError, ForbiddenError, NotFoundError, ValidationError
from ontokit.core.middleware import (
    AccessLogMiddleware,
    RequestIDMiddleware,
    SecurityHeadersMiddleware,
)
from ontokit.services.storage import StorageService

logger = logging.getLogger(__name__)

# Module-level reference so other modules can access the pool if needed
redis_pool: aioredis.Redis | None = None

# Rate limiter
limiter = Limiter(key_func=get_remote_address, default_limits=["100/minute"])


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler for startup/shutdown events."""
    global redis_pool  # noqa: PLW0603

    logger.info("Starting OntoKit API v%s (env=%s)", __version__, settings.app_env)

    # --- Database -----------------------------------------------------------
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("Database connection verified")
    except Exception:
        logger.exception("Failed to connect to the database")
        raise

    # --- Redis --------------------------------------------------------------
    try:
        redis_pool = aioredis.from_url(
            str(settings.redis_url),
            decode_responses=True,
        )
        await redis_pool.ping()
        logger.info("Redis connection verified")
    except Exception:
        logger.exception("Failed to connect to Redis — continuing startup")
        redis_pool = None

    # --- MinIO / Object Storage ---------------------------------------------
    try:
        storage = StorageService()
        await storage.ensure_bucket_exists()
        logger.info("MinIO bucket '%s' is ready", settings.minio_bucket)
    except Exception:
        logger.exception("Failed to initialise MinIO storage — continuing startup")

    logger.info("Startup complete")

    yield

    # --- Shutdown -----------------------------------------------------------
    logger.info("Shutting down OntoKit API")

    # Close Redis
    if redis_pool is not None:
        try:
            await redis_pool.aclose()
            logger.info("Redis connection closed")
        except Exception:
            logger.exception("Error closing Redis connection")

    # Dispose of the async SQLAlchemy engine (closes the connection pool)
    try:
        await engine.dispose()
        logger.info("Database engine disposed")
    except Exception:
        logger.exception("Error disposing database engine")

    logger.info("Shutdown complete")


app = FastAPI(
    title="OntoKit API",
    description="Collaborative OWL Ontology Curation Platform",
    version=__version__,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# Attach rate limiter to app state for slowapi
app.state.limiter = limiter

# --- Middleware (applied in reverse order — last added runs first) ----------

# CORS (outermost — must run before anything else touches the response)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Security headers
app.add_middleware(SecurityHeadersMiddleware, is_production=settings.is_production)

# Access logging (after request ID so the ID is available)
app.add_middleware(AccessLogMiddleware)

# Request ID (innermost — first to run)
app.add_middleware(RequestIDMiddleware)


# --- Exception handlers ----------------------------------------------------


def _error_response(
    status_code: int, code: str, message: str, detail: object = None
) -> JSONResponse:
    body: dict = {"error": {"code": code, "message": message}}
    if detail is not None:
        body["error"]["detail"] = detail
    return JSONResponse(status_code=status_code, content=body)


@app.exception_handler(NotFoundError)
async def not_found_handler(_request: Request, exc: NotFoundError) -> JSONResponse:
    return _error_response(404, "not_found", exc.message, exc.detail)


@app.exception_handler(ValidationError)
async def validation_error_handler(_request: Request, exc: ValidationError) -> JSONResponse:
    return _error_response(422, "validation_error", exc.message, exc.detail)


@app.exception_handler(ConflictError)
async def conflict_handler(_request: Request, exc: ConflictError) -> JSONResponse:
    return _error_response(409, "conflict", exc.message, exc.detail)


@app.exception_handler(ForbiddenError)
async def forbidden_handler(_request: Request, exc: ForbiddenError) -> JSONResponse:
    return _error_response(403, "forbidden", exc.message, exc.detail)


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(_request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return _error_response(429, "rate_limit_exceeded", str(exc.detail))


# --- Routers ---------------------------------------------------------------

app.include_router(api_router, prefix="/api/v1")


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy"}


@app.get("/")
async def root() -> dict[str, str]:
    """Root endpoint with API information."""
    return {
        "name": "OntoKit API",
        "version": __version__,
        "docs": "/docs",
        "openapi": "/openapi.json",
    }
