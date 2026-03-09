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
        pool = aioredis.from_url(  # type: ignore[no-untyped-call]
            str(settings.redis_url),
            decode_responses=True,
        )
        await pool.ping()
        redis_pool = pool
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
            await redis_pool.close()
            logger.info("Redis connection closed")
        except Exception:
            logger.exception("Error closing Redis connection")

    # Close ARQ Redis pool
    try:
        from ontokit.api.utils.redis import close_arq_pool

        await close_arq_pool()
    except Exception:
        logger.exception("Error closing ARQ Redis pool")

    # Dispose of the async SQLAlchemy engine (closes the connection pool)
    try:
        await engine.dispose()
        logger.info("Database engine disposed")
    except Exception:
        logger.exception("Error disposing database engine")

    logger.info("Shutdown complete")


openapi_tags: list[dict[str, str]] = [
    {
        "name": "Authentication",
        "description": (
            "OAuth2 Device Authorization Grant for desktop/CLI clients and token refresh. "
            "Web clients authenticate via Zitadel OIDC directly."
        ),
    },
    {
        "name": "Projects",
        "description": (
            "Create, manage, and configure ontology projects. Each project wraps a bare Git "
            "repository with team membership, branch management, and role-based access control. "
            "Supports importing from file upload or GitHub."
        ),
    },
    {
        "name": "Ontologies",
        "description": (
            "CRUD operations on standalone ontology resources. Create, read, update, delete "
            "ontologies, and manage their classes, properties, import/export, diff, and history."
        ),
    },
    {
        "name": "Classes",
        "description": (
            "OWL class operations within an ontology: list, create, read, update, delete, "
            "and query the class hierarchy."
        ),
    },
    {
        "name": "Properties",
        "description": (
            "OWL property operations within an ontology: list, create, read, update, and "
            "delete object, datatype, and annotation properties."
        ),
    },
    {
        "name": "Pull Requests",
        "description": (
            "Git-based pull request workflow for collaborative ontology editing. Create "
            "branches, propose changes via PRs with semantic diffs, review with comments, "
            "and merge. Includes GitHub integration for two-way sync."
        ),
    },
    {
        "name": "Suggestions",
        "description": (
            "Suggestion sessions allow non-editor contributors (suggesters) to propose "
            "ontology changes without direct write access. Each session creates a dedicated "
            "branch, auto-saves edits, and can be submitted for editor review. Includes a "
            "sendBeacon endpoint for saving on tab close."
        ),
    },
    {
        "name": "Join Requests",
        "description": (
            "Request and manage project membership. Users can request to join a project; "
            "project admins/owners can approve or decline. Includes pending summary for "
            "notification badges."
        ),
    },
    {
        "name": "Lint",
        "description": (
            "Ontology health checking with 20+ semantic validation rules. Trigger lint runs, "
            "view issues, dismiss false positives, and query available rule definitions."
        ),
    },
    {
        "name": "Normalization",
        "description": (
            "Convert ontology files to canonical Turtle format for consistent formatting and "
            "meaningful diffs. Supports queuing background normalization jobs with status "
            "tracking and run history."
        ),
    },
    {
        "name": "Quality",
        "description": (
            "Ontology quality analysis: consistency checking (cycle detection, hierarchy "
            "validation, deprecated entity tracking), duplicate detection using label "
            "similarity with union-find clustering, and cross-reference validation."
        ),
    },
    {
        "name": "Analytics",
        "description": (
            "Project and entity-level analytics: activity timelines, contributor statistics, "
            "hot entities (most frequently edited), and per-entity change history."
        ),
    },
    {
        "name": "Embeddings",
        "description": (
            "Vector embedding management for semantic intelligence features. Configure "
            "embedding providers (local sentence-transformers, OpenAI, or Voyage), trigger "
            "background generation jobs, monitor status, and clear embeddings."
        ),
    },
    {
        "name": "Semantic Search",
        "description": (
            "Search and discover ontology entities using vector similarity. Find entities "
            "by natural language query, discover similar entities to a given IRI, and rank "
            "candidate entities by contextual relevance. Requires generated embeddings."
        ),
    },
    {
        "name": "Search",
        "description": (
            "Full-text search across ontologies using PostgreSQL tsvector/tsquery with "
            "ranking. Also provides a read-only SPARQL endpoint supporting SELECT, ASK, "
            "and CONSTRUCT queries."
        ),
    },
    {
        "name": "User Settings",
        "description": (
            "User profile and integration settings. Manage GitHub personal access tokens "
            "for repository access, list connected GitHub repos, and search users."
        ),
    },
]

app = FastAPI(
    title="OntoKit API",
    description=(
        "**OntoKit** is a collaborative OWL ontology curation platform with Git-based "
        "version control, real-time collaboration, and semantic intelligence.\n\n"
        "## Key capabilities\n\n"
        "- **Ontology editing** — Create and manage OWL 2 ontologies with classes, "
        "properties, and individuals\n"
        "- **Git version control** — Branch-based workflow with pull requests and "
        "semantic diffs\n"
        "- **Suggestions** — Non-editors can propose changes via suggestion sessions "
        "with editor review\n"
        "- **Quality analysis** — Linting (20+ rules), consistency checking, and "
        "duplicate detection\n"
        "- **Semantic search** — Vector similarity search with pluggable embedding "
        "providers\n"
        "- **Analytics** — Activity timelines, contributor stats, and entity change "
        "history\n"
        "- **SPARQL** — Read-only SPARQL endpoint for SELECT, ASK, and CONSTRUCT queries\n"
        "- **GitHub integration** — Two-way sync with GitHub repositories\n\n"
        "## Authentication\n\n"
        "Most endpoints require a Bearer token obtained via Zitadel OIDC. "
        "Desktop/CLI clients can use the Device Authorization Grant flow. "
        "Public project data is accessible without authentication.\n\n"
        "## Rate limiting\n\n"
        "Default rate limit is **100 requests per minute** per IP address. "
        "Rate-limited responses include `Retry-After` and `X-RateLimit-Limit` headers."
    ),
    version=__version__,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    openapi_tags=openapi_tags,
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
    error: dict[str, object] = {"code": code, "message": message}
    if detail is not None:
        error["detail"] = detail
    body: dict[str, object] = {"error": error}
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
    response = _error_response(429, "rate_limit_exceeded", str(exc.detail))
    if exc.limit and hasattr(exc.limit, "limit"):
        retry_after = exc.limit.limit.get_expiry()
        response.headers["Retry-After"] = str(retry_after)
        response.headers["X-RateLimit-Limit"] = str(exc.limit.limit.amount)
    return response


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
