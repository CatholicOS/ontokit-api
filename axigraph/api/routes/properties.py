"""OWL Property management endpoints."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from axigraph.schemas.owl_property import (
    OWLPropertyCreate,
    OWLPropertyListResponse,
    OWLPropertyResponse,
    OWLPropertyUpdate,
)
from axigraph.services.ontology import OntologyService

router = APIRouter()


def get_ontology_service() -> OntologyService:
    """Dependency to get ontology service."""
    return OntologyService()


@router.get("/ontologies/{ontology_id}/properties", response_model=OWLPropertyListResponse)
async def list_properties(
    ontology_id: UUID,
    service: Annotated[OntologyService, Depends(get_ontology_service)],
    property_type: Literal["object", "data", "annotation"] | None = None,
    include_imported: bool = False,
) -> OWLPropertyListResponse:
    """
    List properties in an ontology.

    Args:
        ontology_id: The ontology ID
        property_type: Filter by property type (object, data, annotation)
        include_imported: Include properties from imported ontologies
    """
    return await service.list_properties(
        ontology_id,
        property_type=property_type,
        include_imported=include_imported,
    )


@router.post(
    "/ontologies/{ontology_id}/properties",
    response_model=OWLPropertyResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_property(
    ontology_id: UUID,
    owl_property: OWLPropertyCreate,
    service: Annotated[OntologyService, Depends(get_ontology_service)],
) -> OWLPropertyResponse:
    """Create a new OWL property."""
    return await service.create_property(ontology_id, owl_property)


@router.get(
    "/ontologies/{ontology_id}/properties/{property_iri:path}",
    response_model=OWLPropertyResponse,
)
async def get_property(
    ontology_id: UUID,
    property_iri: str,
    service: Annotated[OntologyService, Depends(get_ontology_service)],
) -> OWLPropertyResponse:
    """Get a property by IRI."""
    result = await service.get_property(ontology_id, property_iri)
    if not result:
        raise HTTPException(status_code=404, detail="Property not found")
    return result


@router.put(
    "/ontologies/{ontology_id}/properties/{property_iri:path}",
    response_model=OWLPropertyResponse,
)
async def update_property(
    ontology_id: UUID,
    property_iri: str,
    owl_property: OWLPropertyUpdate,
    service: Annotated[OntologyService, Depends(get_ontology_service)],
) -> OWLPropertyResponse:
    """Update a property."""
    result = await service.update_property(ontology_id, property_iri, owl_property)
    if not result:
        raise HTTPException(status_code=404, detail="Property not found")
    return result


@router.delete(
    "/ontologies/{ontology_id}/properties/{property_iri:path}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_property(
    ontology_id: UUID,
    property_iri: str,
    service: Annotated[OntologyService, Depends(get_ontology_service)],
) -> None:
    """Delete a property."""
    deleted = await service.delete_property(ontology_id, property_iri)
    if not deleted:
        raise HTTPException(status_code=404, detail="Property not found")
