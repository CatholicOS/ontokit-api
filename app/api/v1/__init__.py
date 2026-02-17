"""API v1 routes."""

from fastapi import APIRouter

from app.api.v1 import (
    auth,
    classes,
    lint,
    normalization,
    ontologies,
    projects,
    properties,
    pull_requests,
    search,
    user_settings,
)

router = APIRouter()

router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
router.include_router(projects.router, prefix="/projects", tags=["Projects"])
router.include_router(pull_requests.router, prefix="/projects", tags=["Pull Requests"])
router.include_router(lint.router, prefix="/projects", tags=["Lint"])
router.include_router(normalization.router, prefix="/projects", tags=["Normalization"])
router.include_router(ontologies.router, prefix="/ontologies", tags=["Ontologies"])
router.include_router(classes.router, tags=["Classes"])
router.include_router(properties.router, tags=["Properties"])
router.include_router(search.router, prefix="/search", tags=["Search"])
router.include_router(user_settings.router, prefix="/users", tags=["User Settings"])
