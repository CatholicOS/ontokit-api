"""Search endpoints for ontology content."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ontokit.core.database import get_db
from ontokit.schemas.search import SearchQuery, SearchResponse, SPARQLQuery, SPARQLResponse
from ontokit.services.search import SearchService

router = APIRouter()


def get_search_service(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SearchService:
    """Dependency to get search service with database session."""
    return SearchService(db=db)


@router.get("", response_model=SearchResponse)
async def search(
    service: Annotated[SearchService, Depends(get_search_service)],
    q: str,
    ontology_id: str | None = None,
    entity_types: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> SearchResponse:
    """
    Search across ontologies.

    Args:
        q: Search query string
        ontology_id: Limit search to specific ontology (comma-separated for multiple)
        entity_types: Filter by entity type (class, property, individual)
        limit: Maximum results to return
        offset: Offset for pagination
    """
    query = SearchQuery(
        query=q,
        ontology_ids=ontology_id.split(",") if ontology_id else None,
        entity_types=entity_types.split(",") if entity_types else None,
        limit=limit,
        offset=offset,
    )
    return await service.search(query)


@router.post("/sparql", response_model=SPARQLResponse)
async def execute_sparql(
    query: SPARQLQuery,
    service: Annotated[SearchService, Depends(get_search_service)],
) -> SPARQLResponse:
    """
    Execute a SPARQL query.

    Supports SELECT, ASK, and CONSTRUCT queries.
    UPDATE queries are not allowed.
    """
    # Block UPDATE queries for safety
    query_upper = query.query.upper().strip()
    if any(keyword in query_upper for keyword in ["INSERT", "DELETE", "CLEAR", "DROP", "CREATE"]):
        raise HTTPException(
            status_code=400,
            detail="UPDATE queries are not allowed. Use the REST API for modifications.",
        )

    return await service.execute_sparql(query)
