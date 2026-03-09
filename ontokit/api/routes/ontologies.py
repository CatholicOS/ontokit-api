"""Ontology management endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, UploadFile, status
from fastapi.responses import Response

from ontokit.schemas.ontology import (
    OntologyCreate,
    OntologyListResponse,
    OntologyResponse,
    OntologyUpdate,
)
from ontokit.services.ontology import OntologyService

router = APIRouter()

# Content type to RDFLib format mapping
FORMAT_MAP = {
    "text/turtle": "turtle",
    "application/rdf+xml": "xml",
    "application/ld+json": "json-ld",
    "application/n-triples": "nt",
    "application/n-quads": "nquads",
    "application/owl+xml": "pretty-xml",
}


def get_ontology_service() -> OntologyService:
    """Dependency to get ontology service."""
    return OntologyService()


@router.post("", response_model=OntologyResponse, status_code=status.HTTP_201_CREATED)
async def create_ontology(
    ontology: OntologyCreate,
    service: Annotated[OntologyService, Depends(get_ontology_service)],
) -> OntologyResponse:
    """Create a new ontology."""
    return await service.create(ontology)


@router.get("", response_model=OntologyListResponse)
async def list_ontologies(
    service: Annotated[OntologyService, Depends(get_ontology_service)],
    skip: int = 0,
    limit: int = 20,
) -> OntologyListResponse:
    """List all ontologies the user has access to."""
    return await service.list_all(skip=skip, limit=limit)


@router.get("/{ontology_id}")
async def get_ontology(
    ontology_id: UUID,
    service: Annotated[OntologyService, Depends(get_ontology_service)],
    accept: Annotated[str, Header()] = "text/turtle",
) -> Response:
    """
    Get an ontology by ID.

    Supports content negotiation via Accept header:
    - text/turtle (default)
    - application/rdf+xml
    - application/ld+json
    - application/n-triples
    - application/owl+xml
    """
    ontology = await service.get(ontology_id)
    if not ontology:
        raise HTTPException(status_code=404, detail="Ontology not found")

    # Determine output format from Accept header
    format_key = accept.split(",")[0].strip()
    rdf_format = FORMAT_MAP.get(format_key, "turtle")
    media_type = format_key if format_key in FORMAT_MAP else "text/turtle"

    content = await service.serialize(ontology_id, format=rdf_format)
    return Response(content=content, media_type=media_type)


@router.put("/{ontology_id}", response_model=OntologyResponse)
async def update_ontology(
    ontology_id: UUID,
    ontology: OntologyUpdate,
    service: Annotated[OntologyService, Depends(get_ontology_service)],
) -> OntologyResponse:
    """Update ontology metadata."""
    result = await service.update(ontology_id, ontology)
    if not result:
        raise HTTPException(status_code=404, detail="Ontology not found")
    return result


@router.delete("/{ontology_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_ontology(
    ontology_id: UUID,
    service: Annotated[OntologyService, Depends(get_ontology_service)],
) -> None:
    """Delete an ontology."""
    deleted = await service.delete(ontology_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Ontology not found")


@router.post("/{ontology_id}/import", response_model=OntologyResponse)
async def import_ontology(
    ontology_id: UUID,
    file: UploadFile,
    service: Annotated[OntologyService, Depends(get_ontology_service)],
) -> OntologyResponse:
    """Import an ontology from a file."""
    content = await file.read()
    return await service.import_from_file(ontology_id, content, file.filename or "ontology.owl")


@router.get("/{ontology_id}/export")
async def export_ontology(
    ontology_id: UUID,
    service: Annotated[OntologyService, Depends(get_ontology_service)],
    format: str = "turtle",
) -> Response:
    """Export an ontology to a specific format."""
    if format not in ["turtle", "xml", "json-ld", "nt", "nquads", "pretty-xml"]:
        raise HTTPException(status_code=400, detail=f"Unsupported format: {format}")

    content = await service.serialize(ontology_id, format=format)

    # Determine content type from format
    content_type_map = {v: k for k, v in FORMAT_MAP.items()}
    content_type = content_type_map.get(format, "text/turtle")

    return Response(content=content, media_type=content_type)


@router.get("/{ontology_id}/history")
async def get_ontology_history(
    ontology_id: UUID,
    service: Annotated[OntologyService, Depends(get_ontology_service)],
    limit: int = 50,
) -> list[dict[str, object]]:
    """Get version history for an ontology."""
    return await service.get_history(ontology_id, limit=limit)


@router.get("/{ontology_id}/diff")
async def diff_ontology_versions(
    ontology_id: UUID,
    service: Annotated[OntologyService, Depends(get_ontology_service)],
    from_version: str,
    to_version: str = "HEAD",
) -> dict[str, object]:
    """Compare two versions of an ontology."""
    return await service.diff(ontology_id, from_version, to_version)
