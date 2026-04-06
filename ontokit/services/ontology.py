"""Ontology service for managing OWL ontologies."""

from dataclasses import dataclass
from typing import Any, cast
from typing import Literal as TypingLiteral
from uuid import UUID

from rdflib import Graph, URIRef
from rdflib import Literal as RDFLiteral
from rdflib.namespace import OWL, RDF, RDFS, SKOS

from ontokit.schemas.ontology import (
    OntologyCreate,
    OntologyListResponse,
    OntologyResponse,
    OntologyUpdate,
)
from ontokit.schemas.owl_class import (
    AnnotationProperty,
    EntitySearchResponse,
    EntitySearchResult,
    OWLClassCreate,
    OWLClassListResponse,
    OWLClassResponse,
    OWLClassTreeNode,
    OWLClassUpdate,
)
from ontokit.schemas.owl_property import (
    OWLPropertyCreate,
    OWLPropertyListResponse,
    OWLPropertyResponse,
    OWLPropertyUpdate,
)
from ontokit.services.storage import StorageService

# Map file extensions to RDF formats
FORMAT_MAP = {
    ".owl": "xml",
    ".owx": "xml",
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
    # Dublin Core Elements 1.1 (all 15 properties)
    "dc:contributor": URIRef("http://purl.org/dc/elements/1.1/contributor"),
    "dc:coverage": URIRef("http://purl.org/dc/elements/1.1/coverage"),
    "dc:creator": URIRef("http://purl.org/dc/elements/1.1/creator"),
    "dc:date": URIRef("http://purl.org/dc/elements/1.1/date"),
    "dc:description": URIRef("http://purl.org/dc/elements/1.1/description"),
    "dc:format": URIRef("http://purl.org/dc/elements/1.1/format"),
    "dc:identifier": URIRef("http://purl.org/dc/elements/1.1/identifier"),
    "dc:language": URIRef("http://purl.org/dc/elements/1.1/language"),
    "dc:publisher": URIRef("http://purl.org/dc/elements/1.1/publisher"),
    "dc:relation": URIRef("http://purl.org/dc/elements/1.1/relation"),
    "dc:rights": URIRef("http://purl.org/dc/elements/1.1/rights"),
    "dc:source": URIRef("http://purl.org/dc/elements/1.1/source"),
    "dc:subject": URIRef("http://purl.org/dc/elements/1.1/subject"),
    "dc:title": URIRef("http://purl.org/dc/elements/1.1/title"),
    "dc:type": URIRef("http://purl.org/dc/elements/1.1/type"),
    # Dublin Core Terms (commonly used)
    "dcterms:contributor": URIRef("http://purl.org/dc/terms/contributor"),
    "dcterms:coverage": URIRef("http://purl.org/dc/terms/coverage"),
    "dcterms:created": URIRef("http://purl.org/dc/terms/created"),
    "dcterms:creator": URIRef("http://purl.org/dc/terms/creator"),
    "dcterms:date": URIRef("http://purl.org/dc/terms/date"),
    "dcterms:description": URIRef("http://purl.org/dc/terms/description"),
    "dcterms:format": URIRef("http://purl.org/dc/terms/format"),
    "dcterms:identifier": URIRef("http://purl.org/dc/terms/identifier"),
    "dcterms:language": URIRef("http://purl.org/dc/terms/language"),
    "dcterms:modified": URIRef("http://purl.org/dc/terms/modified"),
    "dcterms:publisher": URIRef("http://purl.org/dc/terms/publisher"),
    "dcterms:relation": URIRef("http://purl.org/dc/terms/relation"),
    "dcterms:rights": URIRef("http://purl.org/dc/terms/rights"),
    "dcterms:source": URIRef("http://purl.org/dc/terms/source"),
    "dcterms:subject": URIRef("http://purl.org/dc/terms/subject"),
    "dcterms:title": URIRef("http://purl.org/dc/terms/title"),
    "dcterms:type": URIRef("http://purl.org/dc/terms/type"),
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
        self._graphs: dict[tuple[UUID, str], Graph] = {}

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

    async def serialize(
        self, ontology_id: UUID, format: str = "turtle", branch: str = "main"
    ) -> str:
        """Serialize ontology to string in specified format."""
        graph = await self._get_graph(ontology_id, branch)
        base = self._find_ontology_iri(graph)
        return graph.serialize(format=format, base=base)

    @staticmethod
    def _find_ontology_iri(graph: Graph) -> str | None:
        """Find the ontology IRI (subject of rdf:type owl:Ontology) for @base."""
        for subject in graph.subjects(RDF.type, OWL.Ontology):
            if isinstance(subject, URIRef):
                return str(subject)
        return None

    async def import_from_file(
        self,
        ontology_id: UUID,  # noqa: ARG002
        content: bytes,
        filename: str,
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
        include_imported: bool = False,  # noqa: ARG002
        branch: str = "main",
    ) -> OWLClassListResponse:
        """List classes in an ontology."""
        graph = await self._get_graph(ontology_id, branch)
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
        branch: str = "main",
    ) -> OWLClassResponse | None:
        """Get a class by IRI."""
        graph = await self._get_graph(ontology_id, branch)
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

    async def build_entity_graph(
        self,
        ontology_id: UUID,
        class_iri: str,
        branch: str = "main",
        ancestors_depth: int = 5,
        descendants_depth: int = 2,
        max_nodes: int = 200,
        include_see_also: bool = True,
        max_see_also_per_node: int = 5,
    ) -> "EntityGraphResponse | None":
        """Build a multi-hop graph around a class via BFS.

        Traverses ancestors (subClassOf upward), descendants (subClassOf downward),
        and optional seeAlso cross-links. Returns nodes with lineage-based types
        for ontology-agnostic coloring.
        """
        from ontokit.schemas.graph import EntityGraphResponse, GraphEdge, GraphNode

        graph = await self._get_graph(ontology_id, branch)
        class_uri = URIRef(class_iri)

        if (class_uri, RDF.type, OWL.Class) not in graph:
            return None

        owl_thing = OWL.Thing
        EXTERNAL_NAMESPACES = (
            "http://www.w3.org/2000/01/rdf-schema#",
            "http://www.w3.org/2002/07/owl#",
            "http://xmlns.com/foaf/0.1/",
            "http://purl.org/dc/elements/1.1/",
            "http://purl.org/dc/terms/",
            "http://www.w3.org/2004/02/skos/core#",
        )

        visited: dict[str, GraphNode] = {}
        edges: list[GraphEdge] = []
        edge_ids: set[str] = set()
        total_discovered = [0]

        def _get_local_name(iri: str) -> str:
            if "#" in iri:
                return iri.split("#")[-1]
            return iri.rsplit("/", 1)[-1]

        def _get_label(uri: URIRef) -> str:
            label = select_preferred_label(graph, uri)
            return label if label else _get_local_name(str(uri))

        def _is_external(iri: str) -> bool:
            return any(iri.startswith(ns) for ns in EXTERNAL_NAMESPACES)

        def _is_root_class(uri: URIRef) -> bool:
            parents = [
                p for p in graph.objects(uri, RDFS.subClassOf)
                if isinstance(p, URIRef) and p != owl_thing
            ]
            return len(parents) == 0

        def _classify_node(uri: URIRef, is_focus: bool, depth: int) -> str:
            iri = str(uri)
            if is_focus:
                return "focus"
            if _is_external(iri):
                return "external"
            # Check if individual (instance, not a class)
            if (uri, RDF.type, OWL.Class) not in graph:
                for rdf_type in graph.objects(uri, RDF.type):
                    if rdf_type in (OWL.ObjectProperty, OWL.DatatypeProperty, OWL.AnnotationProperty):
                        return "property"
                return "individual"
            if _is_root_class(uri):
                return "root"
            return "class"

        def _get_definition(uri: URIRef) -> str | None:
            # Try SKOS definition first, then rdfs:comment
            for obj in graph.objects(uri, SKOS.definition):
                if isinstance(obj, RDFLiteral):
                    return str(obj)
            for obj in graph.objects(uri, RDFS.comment):
                if isinstance(obj, RDFLiteral):
                    return str(obj)
            return None

        def _child_count(uri: URIRef) -> int:
            return sum(
                1 for s in graph.subjects(RDFS.subClassOf, uri)
                if isinstance(s, URIRef) and (s, RDF.type, OWL.Class) in graph
            )

        def _make_node(uri: URIRef, depth: int) -> GraphNode | None:
            iri = str(uri)
            if iri in visited:
                return visited[iri]
            total_discovered[0] += 1
            if len(visited) >= max_nodes:
                return None
            is_focus = (uri == class_uri)
            node = GraphNode(
                id=iri,
                label=_get_label(uri),
                iri=iri,
                definition=_get_definition(uri),
                is_focus=is_focus,
                is_root=_is_root_class(uri),
                depth=depth,
                node_type=_classify_node(uri, is_focus, depth),
                child_count=_child_count(uri),
            )
            visited[iri] = node
            return node

        def _add_edge(source: str, target: str, edge_type: str, label: str | None = None) -> None:
            eid = f"{source}->{target}:{edge_type}"
            if eid in edge_ids:
                return
            edge_ids.add(eid)
            edges.append(GraphEdge(id=eid, source=source, target=target, edge_type=edge_type, label=label))

        # Create focus node
        focus_node = _make_node(class_uri, 0)
        if not focus_node:
            return None

        # BFS upward (ancestors)
        ancestor_queue: list[tuple[URIRef, int]] = [(class_uri, 0)]
        ancestor_visited: set[str] = {class_iri}
        while ancestor_queue:
            current_uri, current_depth = ancestor_queue.pop(0)
            if current_depth >= ancestors_depth:
                continue
            for parent in graph.objects(current_uri, RDFS.subClassOf):
                if not isinstance(parent, URIRef) or parent == owl_thing:
                    continue
                parent_iri = str(parent)
                parent_node = _make_node(parent, -(current_depth + 1))
                if parent_node is None:
                    continue
                _add_edge(parent_iri, str(current_uri), "subClassOf")
                if parent_iri not in ancestor_visited:
                    ancestor_visited.add(parent_iri)
                    ancestor_queue.append((parent, current_depth + 1))

        # BFS downward (descendants)
        descendant_queue: list[tuple[URIRef, int]] = [(class_uri, 0)]
        descendant_visited: set[str] = {class_iri}
        while descendant_queue:
            current_uri, current_depth = descendant_queue.pop(0)
            if current_depth >= descendants_depth:
                continue
            for child in graph.subjects(RDFS.subClassOf, current_uri):
                if not isinstance(child, URIRef):
                    continue
                child_iri = str(child)
                child_node = _make_node(child, current_depth + 1)
                if child_node is None:
                    continue
                _add_edge(str(current_uri), child_iri, "subClassOf")
                if child_iri not in descendant_visited:
                    descendant_visited.add(child_iri)
                    descendant_queue.append((child, current_depth + 1))

        # Collect equivalentClass and disjointWith for visited nodes
        for node_iri in list(visited.keys()):
            node_uri = URIRef(node_iri)
            for equiv in graph.objects(node_uri, OWL.equivalentClass):
                if isinstance(equiv, URIRef) and str(equiv) in visited:
                    if node_iri < str(equiv):
                        _add_edge(node_iri, str(equiv), "equivalentClass", "equivalentTo")
                    else:
                        _add_edge(str(equiv), node_iri, "equivalentClass", "equivalentTo")
            for disj in graph.objects(node_uri, OWL.disjointWith):
                if isinstance(disj, URIRef) and str(disj) in visited:
                    if node_iri < str(disj):
                        _add_edge(node_iri, str(disj), "disjointWith", "disjointWith")
                    else:
                        _add_edge(str(disj), node_iri, "disjointWith", "disjointWith")

        # Collect seeAlso cross-links
        see_also_nodes: list[URIRef] = []
        if include_see_also:
            for node_iri in list(visited.keys()):
                node_uri = URIRef(node_iri)
                sa_count = 0
                for related in graph.objects(node_uri, RDFS.seeAlso):
                    if not isinstance(related, URIRef) or sa_count >= max_see_also_per_node:
                        break
                    related_iri = str(related)
                    was_new = related_iri not in visited
                    if was_new:
                        related_node = _make_node(related, 0)
                        if related_node is None:
                            continue
                        see_also_nodes.append(related)
                    if node_iri < related_iri:
                        _add_edge(node_iri, related_iri, "seeAlso", "rdfs:seeAlso")
                    else:
                        _add_edge(related_iri, node_iri, "seeAlso", "rdfs:seeAlso")
                    sa_count += 1

        # BFS upward from seeAlso nodes to their roots
        if see_also_nodes:
            sa_queue: list[tuple[URIRef, int]] = [(u, 0) for u in see_also_nodes]
            sa_visited: set[str] = {str(u) for u in see_also_nodes} | ancestor_visited
            while sa_queue:
                current_uri, current_depth = sa_queue.pop(0)
                if current_depth >= ancestors_depth:
                    continue
                for parent in graph.objects(current_uri, RDFS.subClassOf):
                    if not isinstance(parent, URIRef) or parent == owl_thing:
                        continue
                    parent_iri = str(parent)
                    parent_node = _make_node(parent, -(current_depth + 1))
                    if parent_node is None:
                        continue
                    _add_edge(parent_iri, str(current_uri), "subClassOf")
                    if parent_iri not in sa_visited:
                        sa_visited.add(parent_iri)
                        sa_queue.append((parent, current_depth + 1))

        truncated = total_discovered[0] > len(visited)

        return EntityGraphResponse(
            focus_iri=class_iri,
            focus_label=_get_label(class_uri),
            nodes=list(visited.values()),
            edges=edges,
            truncated=truncated,
            total_concept_count=total_discovered[0],
        )

    async def get_root_classes(
        self,
        project_id: UUID,
        label_preferences: list[str] | None = None,
        branch: str = "main",
    ) -> list[OWLClassResponse]:
        """
        Get all root classes (classes with no parent or only owl:Thing as parent).

        These are the top-level classes in the ontology hierarchy.
        """
        graph = await self._get_graph(project_id, branch)
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
                p for p in graph.objects(class_uri, RDFS.subClassOf) if isinstance(p, URIRef)
            ]

            # Check if this is a root class:
            # - No parents, or
            # - Only parent is owl:Thing
            is_root = len(parents) == 0 or (len(parents) == 1 and parents[0] == owl_thing)

            if is_root:
                root_classes.append(
                    await self._class_to_response(graph, class_uri, label_preferences)
                )

        # Sort by label (or IRI if no label)
        def sort_key(cls: OWLClassResponse) -> str:
            if cls.labels:
                return cls.labels[0].value.lower()
            return str(cls.iri).lower()

        root_classes.sort(key=sort_key)
        return root_classes

    async def get_class_children(
        self,
        project_id: UUID,
        class_iri: str,
        label_preferences: list[str] | None = None,
        branch: str = "main",
    ) -> list[OWLClassResponse]:
        """
        Get direct children of a class (classes that have this class as a direct parent).
        """
        graph = await self._get_graph(project_id, branch)
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
            return str(cls.iri).lower()

        children.sort(key=sort_key)
        return children

    async def get_class_count(self, project_id: UUID, branch: str = "main") -> int:
        """Get total number of classes in the ontology."""
        graph = await self._get_graph(project_id, branch)
        return sum(
            1
            for s in graph.subjects(RDF.type, OWL.Class)
            if isinstance(s, URIRef) and s != OWL.Thing
        )

    async def search_entities(
        self,
        project_id: UUID,
        query: str,
        entity_types: list[str] | None = None,
        label_preferences: list[str] | None = None,
        limit: int = 50,
        branch: str = "main",
    ) -> EntitySearchResponse:
        """
        Search for entities (classes, properties, individuals) by name.

        Matches against labels, local names, and full IRIs (case-insensitive substring).
        """
        graph = await self._get_graph(project_id, branch)
        query_lower = query.lower()

        # Map entity type names to (RDF type, result entity_type)
        type_mapping: dict[str, list[tuple[URIRef, str]]] = {
            "class": [(OWL.Class, "class")],
            "property": [
                (OWL.ObjectProperty, "property"),
                (OWL.DatatypeProperty, "property"),
                (OWL.AnnotationProperty, "property"),
            ],
            "individual": [(OWL.NamedIndividual, "individual")],
        }

        allowed_types = entity_types or ["class", "property", "individual"]
        rdf_types: list[tuple[URIRef, str]] = []
        for t in allowed_types:
            if t in type_mapping:
                rdf_types.extend(type_mapping[t])

        owl_thing = OWL.Thing
        results: list[EntitySearchResult] = []

        for rdf_type, entity_type in rdf_types:
            for subject in graph.subjects(RDF.type, rdf_type):
                if not isinstance(subject, URIRef):
                    continue
                if subject == owl_thing:
                    continue

                iri_str = str(subject)

                # Extract local name
                if "#" in iri_str:
                    local_name = iri_str.split("#")[-1]
                else:
                    local_name = iri_str.rsplit("/", 1)[-1]

                # Collect all label values for matching
                all_labels: list[str] = []
                for label_prop in LABEL_PROPERTY_MAP.values():
                    for obj in graph.objects(subject, label_prop):
                        if isinstance(obj, RDFLiteral):
                            all_labels.append(str(obj))

                # Check for match ("*" matches everything)
                if query_lower != "*":
                    matched = (
                        query_lower in local_name.lower()
                        or query_lower in iri_str.lower()
                        or any(query_lower in lbl.lower() for lbl in all_labels)
                    )

                    if not matched:
                        continue

                # Resolve display label
                display_label = select_preferred_label(graph, subject, label_preferences)
                if not display_label:
                    display_label = local_name

                # Check deprecated status
                deprecated = False
                for obj in graph.objects(subject, OWL.deprecated):
                    if str(obj).lower() in ("true", "1"):
                        deprecated = True
                        break

                results.append(
                    EntitySearchResult(
                        iri=iri_str,
                        label=display_label,
                        entity_type=cast(
                            TypingLiteral["class", "property", "individual"], entity_type
                        ),
                        deprecated=deprecated,
                    )
                )

        # Sort: exact prefix matches on label first, then alphabetical
        def sort_key(r: EntitySearchResult) -> tuple[int, str]:
            label_lower = r.label.lower()
            if label_lower.startswith(query_lower):
                return (0, label_lower)
            return (1, label_lower)

        results.sort(key=sort_key)
        total = len(results)
        results = results[:limit]

        return EntitySearchResponse(results=results, total=total)

    async def get_ancestor_path(
        self,
        project_id: UUID,
        class_iri: str,
        label_preferences: list[str] | None = None,
        branch: str = "main",
    ) -> list[OWLClassTreeNode]:
        """
        Get the path from root to a specific class.

        Returns a list of tree nodes starting from the root class down to
        (but not including) the target class. This is useful for expanding
        the tree to reveal a specific class.

        Returns an empty list if the class is a root class or not found.
        """
        graph = await self._get_graph(project_id, branch)
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
                p
                for p in graph.objects(current, RDFS.subClassOf)
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
        branch: str = "main",
    ) -> list[OWLClassTreeNode]:
        """Get root classes as tree nodes (optimized for tree view)."""
        root_classes = await self.get_root_classes(project_id, label_preferences, branch)
        return [self._class_to_tree_node(cls, label_preferences) for cls in root_classes]

    async def get_children_tree_nodes(
        self,
        project_id: UUID,
        class_iri: str,
        label_preferences: list[str] | None = None,
        branch: str = "main",
    ) -> list[OWLClassTreeNode]:
        """Get children of a class as tree nodes (optimized for tree view)."""
        children = await self.get_class_children(project_id, class_iri, label_preferences, branch)
        return [self._class_to_tree_node(cls, label_preferences) for cls in children]

    def _class_to_tree_node(
        self,
        cls: OWLClassResponse,
        label_preferences: list[str] | None = None,  # noqa: ARG002
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
            label = iri.split("#")[-1] if "#" in iri else iri.rsplit("/", 1)[-1]

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

    async def get_property(
        self, ontology_id: UUID, property_iri: str
    ) -> OWLPropertyResponse | None:
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

    async def load_from_storage(
        self, project_id: UUID, source_file_path: str, branch: str = "main"
    ) -> Graph:
        """
        Load an ontology from MinIO storage.

        Args:
            project_id: The project UUID (used for caching)
            source_file_path: The full path in MinIO (e.g., "ontokit/projects/{id}/ontology.owl")
            branch: The branch name (used for cache key)

        Returns:
            The parsed RDF graph

        Raises:
            StorageError: If the file cannot be loaded
            ValueError: If the file format is not supported
        """
        if self._storage is None:
            raise ValueError("Storage service not configured")

        # Extract the object name (remove bucket prefix if present)
        # source_file_path format: "ontokit/projects/{id}/ontology.owl" or "projects/{id}/ontology.owl"
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

        # Cache the graph with branch key
        self._graphs[(project_id, branch)] = graph
        return graph

    async def load_from_git(
        self,
        project_id: UUID,
        branch: str,
        filename: str,
        git_service: Any,
    ) -> Graph:
        """
        Load an ontology from a git branch.

        Args:
            project_id: The project UUID
            branch: The branch name to read from
            filename: The ontology filename (e.g., "ontology.ttl")
            git_service: GitRepositoryService instance

        Returns:
            The parsed RDF graph
        """
        # Determine format from file extension
        ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        rdf_format = FORMAT_MAP.get(ext)
        if not rdf_format:
            raise ValueError(f"Unsupported file format: {ext}")

        # Read file content from git branch
        content = git_service.get_file_from_branch(project_id, branch, filename)

        graph = Graph()
        graph.parse(data=content.decode("utf-8"), format=rdf_format)

        # Cache with branch key
        self._graphs[(project_id, branch)] = graph
        return graph

    async def _get_graph(self, ontology_id: UUID, branch: str = "main") -> Graph:
        """Get the cached RDF graph for a project and branch."""
        key = (ontology_id, branch)
        if key not in self._graphs:
            raise ValueError(
                f"Graph for project {ontology_id} branch {branch} not loaded. "
                "Call load_from_storage or load_from_git first."
            )
        return self._graphs[key]

    def set_graph(self, project_id: UUID, branch: str, graph: Graph) -> None:
        """Inject a pre-parsed graph into the cache (for testing/benchmarks)."""
        self._graphs[(project_id, branch)] = graph

    async def get_graph(self, ontology_id: UUID, branch: str = "main") -> Graph:
        """Get the cached RDF graph for a project and branch.

        Raises ``ValueError`` if the graph has not been loaded yet.
        """
        return await self._get_graph(ontology_id, branch)

    def is_loaded(self, project_id: UUID, branch: str = "main") -> bool:
        """Check if a project's ontology graph is loaded in memory for a given branch."""
        return (project_id, branch) in self._graphs

    def unload(self, project_id: UUID, branch: str | None = None) -> None:
        """Remove a project's ontology graph from memory.

        If branch is None, remove all cached graphs for the project.
        Otherwise, remove only the specified branch's graph.
        """
        if branch is None:
            keys_to_remove = [k for k in self._graphs if k[0] == project_id]
            for k in keys_to_remove:
                del self._graphs[k]
        else:
            self._graphs.pop((project_id, branch), None)

    async def _class_to_response(
        self,
        graph: Graph,
        class_uri: URIRef,
        label_preferences: list[str] | None = None,
    ) -> OWLClassResponse:
        """Convert a class URI to response schema."""
        from ontokit.schemas.ontology import LocalizedString

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

        parent_iris = [
            str(p) for p in graph.objects(class_uri, RDFS.subClassOf) if isinstance(p, URIRef)
        ]

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
            1
            for _ in graph.subjects(RDFS.subClassOf, class_uri)
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
            1 for _ in graph.subjects(RDF.type, class_uri) if isinstance(_, URIRef)
        )

        # Extract additional annotation properties (DC, SKOS, etc.)
        annotations = []
        for prop_label, prop_uri in ANNOTATION_PROPERTIES.items():
            values = []
            for obj in graph.objects(class_uri, prop_uri):
                if isinstance(obj, RDFLiteral):
                    values.append(LocalizedString(value=str(obj), lang=obj.language or ""))
                elif isinstance(obj, URIRef):
                    # For URI values, store as string with empty lang
                    values.append(LocalizedString(value=str(obj), lang=""))
            if values:
                annotations.append(
                    AnnotationProperty(
                        property_iri=str(prop_uri), property_label=prop_label, values=values
                    )
                )

        return OWLClassResponse(
            iri=str(class_uri),  # type: ignore[arg-type]  # Pydantic coerces str to HttpUrl
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
