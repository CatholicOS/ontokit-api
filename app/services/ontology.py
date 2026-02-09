"""Ontology service for managing OWL ontologies."""

from dataclasses import dataclass
from typing import Any, Literal as TypingLiteral
from uuid import UUID

from rdflib import Graph, Literal as RDFLiteral, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS, SKOS

from app.schemas.ontology import (
    OntologyCreate,
    OntologyResponse,
    OntologyListResponse,
    OntologyUpdate,
)
from app.schemas.owl_class import (
    AnnotationProperty,
    OWLClassCreate,
    OWLClassResponse,
    OWLClassUpdate,
    OWLClassListResponse,
    OWLClassTreeNode,
)
from app.schemas.owl_property import (
    OWLPropertyCreate,
    OWLPropertyResponse,
    OWLPropertyUpdate,
    OWLPropertyListResponse,
)
from app.services.storage import StorageService, StorageError


# Map file extensions to RDF formats
FORMAT_MAP = {
    ".owl": "xml",
    ".rdf": "xml",
    ".xml": "xml",
    ".ttl": "turtle",
    ".n3": "n3",
    ".nt": "nt",
    ".jsonld": "json-ld",
    ".json": "json-ld",
}

# Map prefix names to RDF properties
LABEL_PROPERTY_MAP = {
    "rdfs:label": RDFS.label,
    "skos:prefLabel": SKOS.prefLabel,
    "skos:altLabel": SKOS.altLabel,
    "dcterms:title": URIRef("http://purl.org/dc/terms/title"),
    "dc:title": URIRef("http://purl.org/dc/elements/1.1/title"),
}

# Default label preferences if none specified
DEFAULT_LABEL_PREFERENCES = ["rdfs:label@en", "rdfs:label", "skos:prefLabel@en", "skos:prefLabel"]

# Common annotation properties to extract for class details
# (excludes rdfs:label and rdfs:comment which are handled separately)
ANNOTATION_PROPERTIES = {
    # Dublin Core Elements
    "dc:creator": URIRef("http://purl.org/dc/elements/1.1/creator"),
    "dc:contributor": URIRef("http://purl.org/dc/elements/1.1/contributor"),
    "dc:date": URIRef("http://purl.org/dc/elements/1.1/date"),
    "dc:source": URIRef("http://purl.org/dc/elements/1.1/source"),
    "dc:rights": URIRef("http://purl.org/dc/elements/1.1/rights"),
    "dc:subject": URIRef("http://purl.org/dc/elements/1.1/subject"),
    "dc:title": URIRef("http://purl.org/dc/elements/1.1/title"),
    "dc:description": URIRef("http://purl.org/dc/elements/1.1/description"),
    # Dublin Core Terms
    "dcterms:creator": URIRef("http://purl.org/dc/terms/creator"),
    "dcterms:created": URIRef("http://purl.org/dc/terms/created"),
    "dcterms:modified": URIRef("http://purl.org/dc/terms/modified"),
    "dcterms:title": URIRef("http://purl.org/dc/terms/title"),
    "dcterms:description": URIRef("http://purl.org/dc/terms/description"),
    # SKOS
    "skos:prefLabel": SKOS.prefLabel,
    "skos:altLabel": SKOS.altLabel,
    "skos:definition": SKOS.definition,
    "skos:notation": SKOS.notation,
    "skos:example": SKOS.example,
    "skos:note": SKOS.note,
    "skos:scopeNote": SKOS.scopeNote,
    "skos:historyNote": SKOS.historyNote,
    "skos:editorialNote": SKOS.editorialNote,
    "skos:changeNote": SKOS.changeNote,
    # Other common RDFS/OWL
    "rdfs:seeAlso": RDFS.seeAlso,
    "rdfs:isDefinedBy": RDFS.isDefinedBy,
}


@dataclass
class LabelPreference:
    """Parsed label preference."""
    property_uri: URIRef
    language: str | None  # None means any language or no language tag

    @classmethod
    def parse(cls, pref_string: str) -> "LabelPreference | None":
        """
        Parse a preference string like 'rdfs:label@en' or 'skos:prefLabel'.

        Returns None if the property is not recognized.
        """
        if "@" in pref_string:
            prop_part, lang = pref_string.rsplit("@", 1)
        else:
            prop_part = pref_string
            lang = None

        prop_uri = LABEL_PROPERTY_MAP.get(prop_part)
        if prop_uri is None:
            return None

        return cls(property_uri=prop_uri, language=lang)


def select_preferred_label(
    graph: Graph,
    subject: URIRef,
    preferences: list[str] | None = None,
) -> str | None:
    """
    Select the best label for a subject based on preferences.

    Args:
        graph: The RDF graph
        subject: The subject to get a label for
        preferences: List of preference strings like ['rdfs:label@en', 'rdfs:label']

    Returns:
        The best matching label value, or None if no label found
    """
    prefs = preferences or DEFAULT_LABEL_PREFERENCES

    for pref_string in prefs:
        pref = LabelPreference.parse(pref_string)
        if pref is None:
            continue

        for obj in graph.objects(subject, pref.property_uri):
            if isinstance(obj, RDFLiteral):
                obj_lang = obj.language
                if pref.language is None:
                    # No language specified in preference - match any
                    return str(obj)
                elif pref.language == "" and obj_lang is None:
                    # Empty string means prefer no language tag
                    return str(obj)
                elif obj_lang == pref.language:
                    # Exact language match
                    return str(obj)

    # Fallback: return any label from rdfs:label
    for obj in graph.objects(subject, RDFS.label):
        if isinstance(obj, RDFLiteral):
            return str(obj)

    return None


class OntologyService:
    """Service for ontology CRUD operations."""

    def __init__(self, storage: StorageService | None = None) -> None:
        self._storage = storage
        self._graphs: dict[UUID, Graph] = {}

    async def create(self, ontology: OntologyCreate) -> OntologyResponse:
        """Create a new ontology."""
        # TODO: Implement with database storage
        raise NotImplementedError("Database integration pending")

    async def list_all(self, skip: int = 0, limit: int = 20) -> OntologyListResponse:
        """List all ontologies."""
        # TODO: Implement with database query
        raise NotImplementedError("Database integration pending")

    async def get(self, ontology_id: UUID) -> OntologyResponse | None:
        """Get an ontology by ID."""
        # TODO: Implement with database query
        raise NotImplementedError("Database integration pending")

    async def update(self, ontology_id: UUID, ontology: OntologyUpdate) -> OntologyResponse | None:
        """Update ontology metadata."""
        # TODO: Implement with database update
        raise NotImplementedError("Database integration pending")

    async def delete(self, ontology_id: UUID) -> bool:
        """Delete an ontology."""
        # TODO: Implement with database delete
        raise NotImplementedError("Database integration pending")

    async def serialize(self, ontology_id: UUID, format: str = "turtle") -> str:
        """Serialize ontology to string in specified format."""
        graph = await self._get_graph(ontology_id)
        return graph.serialize(format=format)

    async def import_from_file(
        self, ontology_id: UUID, content: bytes, filename: str
    ) -> OntologyResponse:
        """Import ontology content from file."""
        # Detect format from filename
        format_map = {
            ".ttl": "turtle",
            ".rdf": "xml",
            ".owl": "xml",
            ".xml": "xml",
            ".nt": "nt",
            ".n3": "n3",
            ".jsonld": "json-ld",
            ".json": "json-ld",
        }
        ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        rdf_format = format_map.get(ext, "turtle")

        graph = Graph()
        graph.parse(data=content.decode("utf-8"), format=rdf_format)

        # TODO: Store graph and update database
        raise NotImplementedError("Storage integration pending")

    async def get_history(self, ontology_id: UUID, limit: int = 50) -> list[dict[str, Any]]:
        """Get version history for an ontology."""
        # TODO: Implement with Git integration
        raise NotImplementedError("Git integration pending")

    async def diff(self, ontology_id: UUID, from_version: str, to_version: str) -> dict[str, Any]:
        """Compare two versions of an ontology."""
        # TODO: Implement semantic diff
        raise NotImplementedError("Diff implementation pending")

    # Class operations

    async def list_classes(
        self,
        ontology_id: UUID,
        parent_iri: str | None = None,
        include_imported: bool = False,
    ) -> OWLClassListResponse:
        """List classes in an ontology."""
        graph = await self._get_graph(ontology_id)
        classes = []

        for s in graph.subjects(RDF.type, OWL.Class):
            if isinstance(s, URIRef):
                # Filter by parent if specified
                if parent_iri:
                    parents = list(graph.objects(s, RDFS.subClassOf))
                    if URIRef(parent_iri) not in parents:
                        continue

                classes.append(await self._class_to_response(graph, s))

        return OWLClassListResponse(items=classes, total=len(classes))

    async def create_class(self, ontology_id: UUID, owl_class: OWLClassCreate) -> OWLClassResponse:
        """Create a new OWL class."""
        graph = await self._get_graph(ontology_id)
        class_uri = URIRef(str(owl_class.iri))

        # Add class declaration
        graph.add((class_uri, RDF.type, OWL.Class))

        # Add parent classes
        for parent_iri in owl_class.parent_iris:
            graph.add((class_uri, RDFS.subClassOf, URIRef(str(parent_iri))))

        # Add labels
        for label in owl_class.labels:
            graph.add((class_uri, RDFS.label, RDFLiteral(label.value, lang=label.lang)))

        # TODO: Persist changes
        return await self._class_to_response(graph, class_uri)

    async def get_class(
        self,
        ontology_id: UUID,
        class_iri: str,
        label_preferences: list[str] | None = None,
    ) -> OWLClassResponse | None:
        """Get a class by IRI."""
        graph = await self._get_graph(ontology_id)
        class_uri = URIRef(class_iri)

        if (class_uri, RDF.type, OWL.Class) not in graph:
            return None

        return await self._class_to_response(graph, class_uri, label_preferences)

    async def update_class(
        self, ontology_id: UUID, class_iri: str, owl_class: OWLClassUpdate
    ) -> OWLClassResponse | None:
        """Update a class."""
        # TODO: Implement class update
        raise NotImplementedError("Class update pending")

    async def delete_class(self, ontology_id: UUID, class_iri: str) -> bool:
        """Delete a class."""
        # TODO: Implement class deletion
        raise NotImplementedError("Class deletion pending")

    async def get_class_hierarchy(
        self,
        ontology_id: UUID,
        class_iri: str,
        direction: str = "both",
        depth: int = 3,
    ) -> dict[str, Any]:
        """Get class hierarchy around a specific class."""
        # TODO: Implement hierarchy traversal
        raise NotImplementedError("Hierarchy implementation pending")

    async def get_root_classes(
        self,
        project_id: UUID,
        label_preferences: list[str] | None = None,
    ) -> list[OWLClassResponse]:
        """
        Get all root classes (classes with no parent or only owl:Thing as parent).

        These are the top-level classes in the ontology hierarchy.
        """
        graph = await self._get_graph(project_id)
        root_classes = []

        owl_thing = OWL.Thing

        for class_uri in graph.subjects(RDF.type, OWL.Class):
            if not isinstance(class_uri, URIRef):
                continue

            # Skip owl:Thing itself
            if class_uri == owl_thing:
                continue

            # Get all parents
            parents = [
                p for p in graph.objects(class_uri, RDFS.subClassOf)
                if isinstance(p, URIRef)
            ]

            # Check if this is a root class:
            # - No parents, or
            # - Only parent is owl:Thing
            is_root = (
                len(parents) == 0 or
                (len(parents) == 1 and parents[0] == owl_thing)
            )

            if is_root:
                root_classes.append(await self._class_to_response(graph, class_uri, label_preferences))

        # Sort by label (or IRI if no label)
        def sort_key(cls: OWLClassResponse) -> str:
            if cls.labels:
                return cls.labels[0].value.lower()
            return cls.iri.lower()

        root_classes.sort(key=sort_key)
        return root_classes

    async def get_class_children(
        self,
        project_id: UUID,
        class_iri: str,
        label_preferences: list[str] | None = None,
    ) -> list[OWLClassResponse]:
        """
        Get direct children of a class (classes that have this class as a direct parent).
        """
        graph = await self._get_graph(project_id)
        parent_uri = URIRef(class_iri)
        children = []

        for class_uri in graph.subjects(RDFS.subClassOf, parent_uri):
            if not isinstance(class_uri, URIRef):
                continue
            if (class_uri, RDF.type, OWL.Class) not in graph:
                continue
            children.append(await self._class_to_response(graph, class_uri, label_preferences))

        # Sort by label (or IRI if no label)
        def sort_key(cls: OWLClassResponse) -> str:
            if cls.labels:
                return cls.labels[0].value.lower()
            return cls.iri.lower()

        children.sort(key=sort_key)
        return children

    async def get_class_count(self, project_id: UUID) -> int:
        """Get total number of classes in the ontology."""
        graph = await self._get_graph(project_id)
        return sum(
            1 for s in graph.subjects(RDF.type, OWL.Class)
            if isinstance(s, URIRef) and s != OWL.Thing
        )

    async def get_ancestor_path(
        self,
        project_id: UUID,
        class_iri: str,
        label_preferences: list[str] | None = None,
    ) -> list[OWLClassTreeNode]:
        """
        Get the path from root to a specific class.

        Returns a list of tree nodes starting from the root class down to
        (but not including) the target class. This is useful for expanding
        the tree to reveal a specific class.

        Returns an empty list if the class is a root class or not found.
        """
        graph = await self._get_graph(project_id)
        target_uri = URIRef(class_iri)
        owl_thing = OWL.Thing

        # Check if target class exists
        if (target_uri, RDF.type, OWL.Class) not in graph:
            return []

        # Build ancestor path by traversing upward
        path: list[URIRef] = []
        visited: set[str] = set()
        current = target_uri

        while True:
            if str(current) in visited:
                # Circular hierarchy - break
                break
            visited.add(str(current))

            # Get parents
            parents = [
                p for p in graph.objects(current, RDFS.subClassOf)
                if isinstance(p, URIRef) and p != owl_thing
            ]

            if not parents:
                # Reached a root class
                break

            # Use first parent for the path (in complex hierarchies,
            # a class might have multiple parents - we pick one path)
            parent = parents[0]
            path.append(parent)
            current = parent

        # Reverse to get root-to-target order
        path.reverse()

        # Convert to tree nodes
        result = []
        for uri in path:
            response = await self._class_to_response(graph, uri, label_preferences)
            result.append(self._class_to_tree_node(response, label_preferences))

        return result

    async def get_root_tree_nodes(
        self,
        project_id: UUID,
        label_preferences: list[str] | None = None,
    ) -> list[OWLClassTreeNode]:
        """Get root classes as tree nodes (optimized for tree view)."""
        root_classes = await self.get_root_classes(project_id, label_preferences)
        return [self._class_to_tree_node(cls, label_preferences) for cls in root_classes]

    async def get_children_tree_nodes(
        self,
        project_id: UUID,
        class_iri: str,
        label_preferences: list[str] | None = None,
    ) -> list[OWLClassTreeNode]:
        """Get children of a class as tree nodes (optimized for tree view)."""
        children = await self.get_class_children(project_id, class_iri, label_preferences)
        return [self._class_to_tree_node(cls, label_preferences) for cls in children]

    def _class_to_tree_node(
        self,
        cls: OWLClassResponse,
        label_preferences: list[str] | None = None,
    ) -> OWLClassTreeNode:
        """Convert an OWLClassResponse to a tree node."""
        # The preferred label should already be computed during _class_to_response
        # For tree nodes, we want a single label - use first from labels list
        # which should be ordered by preference
        if cls.labels:
            label = cls.labels[0].value
        else:
            # Extract local name from IRI (after # or last /)
            iri = str(cls.iri)
            if "#" in iri:
                label = iri.split("#")[-1]
            else:
                label = iri.rsplit("/", 1)[-1]

        return OWLClassTreeNode(
            iri=str(cls.iri),
            label=label,
            child_count=cls.child_count,
            deprecated=cls.deprecated,
        )

    # Property operations

    async def list_properties(
        self,
        ontology_id: UUID,
        property_type: TypingLiteral["object", "data", "annotation"] | None = None,
        include_imported: bool = False,
    ) -> OWLPropertyListResponse:
        """List properties in an ontology."""
        # TODO: Implement property listing
        raise NotImplementedError("Property listing pending")

    async def create_property(
        self, ontology_id: UUID, owl_property: OWLPropertyCreate
    ) -> OWLPropertyResponse:
        """Create a new OWL property."""
        # TODO: Implement property creation
        raise NotImplementedError("Property creation pending")

    async def get_property(self, ontology_id: UUID, property_iri: str) -> OWLPropertyResponse | None:
        """Get a property by IRI."""
        # TODO: Implement property retrieval
        raise NotImplementedError("Property retrieval pending")

    async def update_property(
        self, ontology_id: UUID, property_iri: str, owl_property: OWLPropertyUpdate
    ) -> OWLPropertyResponse | None:
        """Update a property."""
        # TODO: Implement property update
        raise NotImplementedError("Property update pending")

    async def delete_property(self, ontology_id: UUID, property_iri: str) -> bool:
        """Delete a property."""
        # TODO: Implement property deletion
        raise NotImplementedError("Property deletion pending")

    # Helper methods

    async def load_from_storage(self, project_id: UUID, source_file_path: str) -> Graph:
        """
        Load an ontology from MinIO storage.

        Args:
            project_id: The project UUID (used for caching)
            source_file_path: The full path in MinIO (e.g., "axigraph/projects/{id}/ontology.owl")

        Returns:
            The parsed RDF graph

        Raises:
            StorageError: If the file cannot be loaded
            ValueError: If the file format is not supported
        """
        if self._storage is None:
            raise ValueError("Storage service not configured")

        # Extract the object name (remove bucket prefix if present)
        # source_file_path format: "axigraph/projects/{id}/ontology.owl" or "projects/{id}/ontology.owl"
        parts = source_file_path.split("/", 1)
        if len(parts) == 2 and parts[0] == self._storage.bucket:
            object_name = parts[1]
        else:
            object_name = source_file_path

        # Determine format from file extension
        ext = "." + object_name.rsplit(".", 1)[-1].lower() if "." in object_name else ""
        rdf_format = FORMAT_MAP.get(ext)
        if not rdf_format:
            raise ValueError(f"Unsupported file format: {ext}")

        # Download and parse
        content = await self._storage.download_file(object_name)
        graph = Graph()
        graph.parse(data=content.decode("utf-8"), format=rdf_format)

        # Cache the graph
        self._graphs[project_id] = graph
        return graph

    async def _get_graph(self, ontology_id: UUID) -> Graph:
        """Get the cached RDF graph for a project."""
        if ontology_id not in self._graphs:
            raise ValueError(
                f"Graph for project {ontology_id} not loaded. "
                "Call load_from_storage first."
            )
        return self._graphs[ontology_id]

    def is_loaded(self, project_id: UUID) -> bool:
        """Check if a project's ontology graph is loaded in memory."""
        return project_id in self._graphs

    def unload(self, project_id: UUID) -> None:
        """Remove a project's ontology graph from memory."""
        self._graphs.pop(project_id, None)

    async def _class_to_response(
        self,
        graph: Graph,
        class_uri: URIRef,
        label_preferences: list[str] | None = None,
    ) -> OWLClassResponse:
        """Convert a class URI to response schema."""
        from app.schemas.ontology import LocalizedString

        labels = [
            LocalizedString(value=str(label), lang=label.language or "en")
            for label in graph.objects(class_uri, RDFS.label)
            if isinstance(label, RDFLiteral)
        ]

        comments = [
            LocalizedString(value=str(comment), lang=comment.language or "en")
            for comment in graph.objects(class_uri, RDFS.comment)
            if isinstance(comment, RDFLiteral)
        ]

        parent_iris = [str(p) for p in graph.objects(class_uri, RDFS.subClassOf) if isinstance(p, URIRef)]

        # Resolve labels for parent classes
        parent_labels: dict[str, str] = {}
        for parent_iri in parent_iris:
            parent_uri = URIRef(parent_iri)
            label = select_preferred_label(graph, parent_uri, label_preferences)
            if label:
                parent_labels[parent_iri] = label
            else:
                # Fall back to local name
                if "#" in parent_iri:
                    parent_labels[parent_iri] = parent_iri.split("#")[-1]
                else:
                    parent_labels[parent_iri] = parent_iri.rsplit("/", 1)[-1]

        # Count direct children (classes that have this class as a parent)
        child_count = sum(
            1 for _ in graph.subjects(RDFS.subClassOf, class_uri)
            if isinstance(_, URIRef) and (_, RDF.type, OWL.Class) in graph
        )

        # Check for deprecated annotation (owl:deprecated = true)
        deprecated = False
        for obj in graph.objects(class_uri, OWL.deprecated):
            if str(obj).lower() in ("true", "1"):
                deprecated = True
                break

        # Count instances (individuals of this class)
        instance_count = sum(
            1 for _ in graph.subjects(RDF.type, class_uri)
            if isinstance(_, URIRef)
        )

        # Extract additional annotation properties (DC, SKOS, etc.)
        annotations = []
        for prop_label, prop_uri in ANNOTATION_PROPERTIES.items():
            values = []
            for obj in graph.objects(class_uri, prop_uri):
                if isinstance(obj, RDFLiteral):
                    values.append(LocalizedString(
                        value=str(obj),
                        lang=obj.language or ""
                    ))
                elif isinstance(obj, URIRef):
                    # For URI values, store as string with empty lang
                    values.append(LocalizedString(value=str(obj), lang=""))
            if values:
                annotations.append(AnnotationProperty(
                    property_iri=str(prop_uri),
                    property_label=prop_label,
                    values=values
                ))

        return OWLClassResponse(
            iri=str(class_uri),
            labels=labels,
            comments=comments,
            deprecated=deprecated,
            parent_iris=parent_iris,
            parent_labels=parent_labels,
            equivalent_iris=[],
            disjoint_iris=[],
            child_count=child_count,
            instance_count=instance_count,
            annotations=annotations,
        )


# Singleton instance for caching (shares graph cache across requests)
_ontology_service: OntologyService | None = None


def get_ontology_service(storage: StorageService | None = None) -> OntologyService:
    """
    Get the ontology service singleton.

    The singleton pattern is used to share the graph cache across requests.
    """
    global _ontology_service
    if _ontology_service is None:
        _ontology_service = OntologyService(storage=storage)
    elif storage is not None and _ontology_service._storage is None:
        _ontology_service._storage = storage
    return _ontology_service
