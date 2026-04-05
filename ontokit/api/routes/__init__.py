"""API v1 routes."""

from fastapi import APIRouter

from ontokit.api.routes import (
    analytics,
    auth,
    classes,
    embeddings,
    join_requests,
    lint,
    normalization,
    notifications,
    ontologies,
    projects,
    properties,
    pull_requests,
    quality,
    remote_sync,
    search,
    semantic_search,
    suggestions,
    user_settings,
)

router = APIRouter()

router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
router.include_router(projects.router, prefix="/projects", tags=["Projects"])
router.include_router(pull_requests.router, prefix="/projects", tags=["Pull Requests"])
router.include_router(join_requests.router, prefix="/projects", tags=["Join Requests"])
router.include_router(lint.router, prefix="/projects", tags=["Lint"])
router.include_router(normalization.router, prefix="/projects", tags=["Normalization"])
router.include_router(quality.router, prefix="/projects", tags=["Quality"])
router.include_router(analytics.router, prefix="/projects", tags=["Analytics"])
router.include_router(embeddings.router, prefix="/projects", tags=["Embeddings"])
router.include_router(semantic_search.router, prefix="/projects", tags=["Semantic Search"])
router.include_router(ontologies.router, prefix="/ontologies", tags=["Ontologies"])
router.include_router(classes.router, tags=["Classes"])
router.include_router(properties.router, tags=["Properties"])
router.include_router(suggestions.router, prefix="/projects", tags=["Suggestions"])
router.include_router(remote_sync.router, prefix="/projects", tags=["Remote Sync"])
router.include_router(notifications.router, prefix="/notifications", tags=["Notifications"])
router.include_router(search.router, prefix="/search", tags=["Search"])
router.include_router(user_settings.router, prefix="/users", tags=["User Settings"])
