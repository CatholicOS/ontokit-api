"""API v1 routes."""

from fastapi import APIRouter

from app.api.v1 import auth, classes, ontologies, projects, properties, search

router = APIRouter()

router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
router.include_router(projects.router, prefix="/projects", tags=["Projects"])
router.include_router(ontologies.router, prefix="/ontologies", tags=["Ontologies"])
router.include_router(classes.router, tags=["Classes"])
router.include_router(properties.router, tags=["Properties"])
router.include_router(search.router, prefix="/search", tags=["Search"])
