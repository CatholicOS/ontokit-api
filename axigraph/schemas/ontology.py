"""Ontology schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl


class LocalizedString(BaseModel):
    """A string with language tag."""

    value: str
    lang: str = "en"


class OntologyBase(BaseModel):
    """Base ontology fields."""

    iri: HttpUrl = Field(..., description="The ontology IRI")
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    version_iri: HttpUrl | None = None
    labels: list[LocalizedString] = Field(default_factory=list)


class OntologyCreate(OntologyBase):
    """Schema for creating an ontology."""

    prefix: str = Field(..., min_length=1, max_length=20, pattern=r"^[a-zA-Z][a-zA-Z0-9_]*$")


class OntologyUpdate(BaseModel):
    """Schema for updating ontology metadata."""

    title: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    version_iri: HttpUrl | None = None
    labels: list[LocalizedString] | None = None


class OntologyResponse(OntologyBase):
    """Schema for ontology responses."""

    id: UUID
    prefix: str
    created_at: datetime
    updated_at: datetime
    created_by: str | None = None
    class_count: int = 0
    property_count: int = 0
    individual_count: int = 0

    class Config:
        from_attributes = True


class OntologyListResponse(BaseModel):
    """Paginated list of ontologies."""

    items: list[OntologyResponse]
    total: int
    skip: int
    limit: int
