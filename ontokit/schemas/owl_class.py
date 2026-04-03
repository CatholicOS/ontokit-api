"""OWL Class schemas."""

from typing import Literal

from pydantic import BaseModel, Field, HttpUrl

from ontokit.schemas.ontology import LocalizedString


class OWLClassBase(BaseModel):
    """Base OWL class fields."""

    iri: HttpUrl = Field(..., description="The class IRI")
    labels: list[LocalizedString] = Field(default_factory=list)
    comments: list[LocalizedString] = Field(default_factory=list)
    deprecated: bool = False


class OWLClassCreate(OWLClassBase):
    """Schema for creating an OWL class."""

    parent_iris: list[HttpUrl] = Field(
        default_factory=lambda: [],
        description="Parent class IRIs (subClassOf)",
    )
    equivalent_iris: list[HttpUrl] = Field(
        default_factory=list,
        description="Equivalent class IRIs",
    )
    disjoint_iris: list[HttpUrl] = Field(
        default_factory=list,
        description="Disjoint class IRIs",
    )


class OWLClassUpdate(BaseModel):
    """Schema for updating an OWL class."""

    labels: list[LocalizedString] | None = None
    comments: list[LocalizedString] | None = None
    deprecated: bool | None = None
    parent_iris: list[HttpUrl] | None = None
    equivalent_iris: list[HttpUrl] | None = None
    disjoint_iris: list[HttpUrl] | None = None


class AnnotationProperty(BaseModel):
    """An annotation property with its values."""

    property_iri: str = Field(..., description="Full IRI of the annotation property")
    property_label: str = Field(..., description="Human-readable label (e.g., 'dc:creator')")
    values: list[LocalizedString] = Field(default_factory=list)


class OWLClassResponse(OWLClassBase):
    """Schema for OWL class responses."""

    parent_iris: list[str] = Field(default_factory=list)
    parent_labels: dict[str, str] = Field(
        default_factory=dict,
        description="Map of parent IRI to resolved label",
    )
    equivalent_iris: list[str] | None = Field(default=None)
    disjoint_iris: list[str] | None = Field(default=None)
    child_count: int = 0
    instance_count: int | None = None
    is_defined: bool = True  # vs just declared
    source_ontology: str | None = None  # If imported
    annotations: list[AnnotationProperty] = Field(
        default_factory=list,
        description="Additional annotation properties (DC, SKOS, etc.)",
    )

    class Config:
        from_attributes = True


class OWLClassListResponse(BaseModel):
    """List of OWL classes."""

    items: list[OWLClassResponse]
    total: int


class OWLClassTreeNode(BaseModel):
    """Simplified class node for tree view."""

    iri: str = Field(..., description="The class IRI")
    label: str = Field(..., description="Display label (from rdfs:label or local name)")
    child_count: int = Field(0, description="Number of direct subclasses")
    deprecated: bool = False

    class Config:
        from_attributes = True


class OWLClassTreeResponse(BaseModel):
    """Response for tree navigation endpoints."""

    nodes: list[OWLClassTreeNode]
    total_classes: int = Field(0, description="Total number of classes in the ontology")


class EntitySearchResult(BaseModel):
    """A single entity search result."""

    iri: str
    label: str
    entity_type: Literal["class", "property", "individual"]
    deprecated: bool = False


class EntitySearchResponse(BaseModel):
    """Response for entity search."""

    results: list[EntitySearchResult]
    total: int
