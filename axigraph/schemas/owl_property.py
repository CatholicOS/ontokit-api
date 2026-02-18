"""OWL Property schemas."""

from typing import Literal

from pydantic import BaseModel, Field, HttpUrl

from axigraph.schemas.ontology import LocalizedString

PropertyType = Literal["object", "data", "annotation"]


class OWLPropertyBase(BaseModel):
    """Base OWL property fields."""

    iri: HttpUrl = Field(..., description="The property IRI")
    property_type: PropertyType
    labels: list[LocalizedString] = Field(default_factory=list)
    comments: list[LocalizedString] = Field(default_factory=list)
    deprecated: bool = False


class OWLPropertyCreate(OWLPropertyBase):
    """Schema for creating an OWL property."""

    domain_iris: list[HttpUrl] = Field(default_factory=list)
    range_iris: list[HttpUrl] = Field(default_factory=list)
    parent_iris: list[HttpUrl] = Field(default_factory=list)

    # Object property characteristics
    is_functional: bool = False
    is_inverse_functional: bool = False
    is_transitive: bool = False
    is_symmetric: bool = False
    is_asymmetric: bool = False
    is_reflexive: bool = False
    is_irreflexive: bool = False

    # Inverse property
    inverse_of: HttpUrl | None = None


class OWLPropertyUpdate(BaseModel):
    """Schema for updating an OWL property."""

    labels: list[LocalizedString] | None = None
    comments: list[LocalizedString] | None = None
    deprecated: bool | None = None
    domain_iris: list[HttpUrl] | None = None
    range_iris: list[HttpUrl] | None = None
    parent_iris: list[HttpUrl] | None = None

    is_functional: bool | None = None
    is_inverse_functional: bool | None = None
    is_transitive: bool | None = None
    is_symmetric: bool | None = None
    is_asymmetric: bool | None = None
    is_reflexive: bool | None = None
    is_irreflexive: bool | None = None
    inverse_of: HttpUrl | None = None


class OWLPropertyResponse(OWLPropertyBase):
    """Schema for OWL property responses."""

    domain_iris: list[str] = Field(default_factory=list)
    range_iris: list[str] = Field(default_factory=list)
    parent_iris: list[str] = Field(default_factory=list)

    is_functional: bool = False
    is_inverse_functional: bool = False
    is_transitive: bool = False
    is_symmetric: bool = False
    is_asymmetric: bool = False
    is_reflexive: bool = False
    is_irreflexive: bool = False

    inverse_of: str | None = None
    usage_count: int = 0
    source_ontology: str | None = None

    class Config:
        from_attributes = True


class OWLPropertyListResponse(BaseModel):
    """List of OWL properties."""

    items: list[OWLPropertyResponse]
    total: int
