"""Ontology schemas."""

import re
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

_IRI_PATTERN = re.compile(r"^(https?://|urn:)\S+$")


def _validate_iri(value: str) -> str:
    """Validate that a string is a well-formed IRI with a recognised scheme."""
    if not _IRI_PATTERN.match(value):
        raise ValueError(
            "Invalid IRI: must start with 'http://', 'https://', or 'urn:' "
            "and contain no whitespace"
        )
    return value


class LocalizedString(BaseModel):
    """A string with language tag."""

    value: str = Field(..., max_length=5000)
    lang: str = Field(default="en", max_length=10)


class OntologyBase(BaseModel):
    """Base ontology fields."""

    iri: str = Field(..., description="The ontology IRI", max_length=2048)
    title: str = Field(..., min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=5000)
    version_iri: str | None = Field(default=None, max_length=2048)
    labels: list[LocalizedString] = Field(default_factory=list)

    @field_validator("iri")
    @classmethod
    def iri_must_be_valid(cls, v: str) -> str:
        return _validate_iri(v)

    @field_validator("version_iri")
    @classmethod
    def version_iri_must_be_valid(cls, v: str | None) -> str | None:
        if v is not None:
            return _validate_iri(v)
        return v


class OntologyCreate(OntologyBase):
    """Schema for creating an ontology."""

    prefix: str = Field(..., min_length=1, max_length=20, pattern=r"^[a-zA-Z][a-zA-Z0-9_]*$")


class OntologyUpdate(BaseModel):
    """Schema for updating ontology metadata."""

    title: str | None = Field(None, min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=5000)
    version_iri: str | None = Field(default=None, max_length=2048)
    labels: list[LocalizedString] | None = None

    @field_validator("version_iri")
    @classmethod
    def version_iri_must_be_valid(cls, v: str | None) -> str | None:
        if v is not None:
            return _validate_iri(v)
        return v


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
