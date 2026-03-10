"""Search endpoints for ontology content."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from rdflib.plugins.sparql.parser import parseQuery, parseUpdate
from sqlalchemy.ext.asyncio import AsyncSession

from ontokit.api.dependencies import load_project_graph, verify_project_access
from ontokit.core.auth import OptionalUser
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
    db: Annotated[AsyncSession, Depends(get_db)],
    user: OptionalUser,
    branch: str | None = Query(default=None, description="Branch name"),
) -> SPARQLResponse:
    """
    Execute a SPARQL query against a project's ontology graph.

    Supports SELECT, ASK, and CONSTRUCT queries.
    UPDATE queries are not allowed.
    Requires `ontology_id` in the request body to identify the project.
    """
    project_id = UUID(query.ontology_id)

    # Verify access (public projects allow unauthenticated queries)
    await verify_project_access(project_id, db, user)

    # Parse the query to determine its type and block updates
    query_text = query.query.strip()
    try:
        parseQuery(query_text)
    except Exception as query_err:
        # parseQuery only handles SELECT/ASK/CONSTRUCT/DESCRIBE.
        # Check if it's a valid SPARQL Update (INSERT/DELETE/LOAD/CLEAR/DROP/CREATE).
        try:
            parseUpdate(query_text)
        except Exception:
            raise HTTPException(
                status_code=400,
                detail="Invalid SPARQL query: could not parse as query or update.",
            ) from query_err
        raise HTTPException(
            status_code=400,
            detail="UPDATE queries are not allowed. Use the REST API for modifications.",
        ) from None

    # Load the project's ontology graph
    graph, _ = await load_project_graph(project_id, branch, db)

    try:
        return await service.execute_sparql(query, graph=graph)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
