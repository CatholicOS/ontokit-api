"""OWL Class management endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from axigraph.schemas.owl_class import (
    OWLClassCreate,
    OWLClassListResponse,
    OWLClassResponse,
    OWLClassUpdate,
)
from axigraph.services.ontology import OntologyService

router = APIRouter()


def get_ontology_service() -> OntologyService:
    """Dependency to get ontology service."""
    return OntologyService()


@router.get("/ontologies/{ontology_id}/classes", response_model=OWLClassListResponse)
async def list_classes(
    ontology_id: UUID,
    service: Annotated[OntologyService, Depends(get_ontology_service)],
    parent_iri: str | None = None,
    include_imported: bool = False,
) -> OWLClassListResponse:
    """
    List classes in an ontology.

    Args:
        ontology_id: The ontology ID
        parent_iri: Filter to only direct subclasses of this class
        include_imported: Include classes from imported ontologies
    """
    return await service.list_classes(
        ontology_id,
        parent_iri=parent_iri,
        include_imported=include_imported,
    )


@router.post(
    "/ontologies/{ontology_id}/classes",
    response_model=OWLClassResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_class(
    ontology_id: UUID,
    owl_class: OWLClassCreate,
    service: Annotated[OntologyService, Depends(get_ontology_service)],
) -> OWLClassResponse:
    """Create a new OWL class."""
    return await service.create_class(ontology_id, owl_class)


@router.get("/ontologies/{ontology_id}/classes/{class_iri:path}", response_model=OWLClassResponse)
async def get_class(
    ontology_id: UUID,
    class_iri: str,
    service: Annotated[OntologyService, Depends(get_ontology_service)],
) -> OWLClassResponse:
    """Get a class by IRI."""
    result = await service.get_class(ontology_id, class_iri)
    if not result:
        raise HTTPException(status_code=404, detail="Class not found")
    return result


@router.put("/ontologies/{ontology_id}/classes/{class_iri:path}", response_model=OWLClassResponse)
async def update_class(
    ontology_id: UUID,
    class_iri: str,
    owl_class: OWLClassUpdate,
    service: Annotated[OntologyService, Depends(get_ontology_service)],
) -> OWLClassResponse:
    """Update a class."""
    result = await service.update_class(ontology_id, class_iri, owl_class)
    if not result:
        raise HTTPException(status_code=404, detail="Class not found")
    return result


@router.delete(
    "/ontologies/{ontology_id}/classes/{class_iri:path}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_class(
    ontology_id: UUID,
    class_iri: str,
    service: Annotated[OntologyService, Depends(get_ontology_service)],
) -> None:
    """Delete a class."""
    deleted = await service.delete_class(ontology_id, class_iri)
    if not deleted:
        raise HTTPException(status_code=404, detail="Class not found")


@router.get("/ontologies/{ontology_id}/classes/{class_iri:path}/hierarchy")
async def get_class_hierarchy(
    ontology_id: UUID,
    class_iri: str,
    service: Annotated[OntologyService, Depends(get_ontology_service)],
    direction: str = "both",
    depth: int = 3,
) -> dict:
    """
    Get the class hierarchy around a specific class.

    Args:
        direction: 'ancestors', 'descendants', or 'both'
        depth: Maximum depth to traverse
    """
    return await service.get_class_hierarchy(
        ontology_id,
        class_iri,
        direction=direction,
        depth=depth,
    )
