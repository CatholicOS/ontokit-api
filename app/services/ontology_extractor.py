"""Ontology metadata extraction and update service using RDFLib."""

from dataclasses import dataclass
from pathlib import Path

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.compare import to_canonical_graph
from rdflib.namespace import DC, DCTERMS, OWL, RDF, RDFS


@dataclass
class ExtractedMetadata:
    """Metadata extracted from an ontology file."""

    ontology_iri: str | None
    title: str | None
    description: str | None
    format_detected: str


@dataclass
class NormalizationReport:
    """Report of changes made during ontology normalization."""

    original_format: str
    original_filename: str
    original_size_bytes: int
    normalized_size_bytes: int
    triple_count: int
    prefixes_before: list[str]
    prefixes_after: list[str]
    prefixes_removed: list[str]
    prefixes_added: list[str]
    format_converted: bool
    notes: list[str]

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "original_format": self.original_format,
            "original_filename": self.original_filename,
            "original_size_bytes": self.original_size_bytes,
            "normalized_size_bytes": self.normalized_size_bytes,
            "triple_count": self.triple_count,
            "prefixes_before": self.prefixes_before,
            "prefixes_after": self.prefixes_after,
            "prefixes_removed": self.prefixes_removed,
            "prefixes_added": self.prefixes_added,
            "format_converted": self.format_converted,
            "notes": self.notes,
        }


WELL_KNOWN_PREFIXES: dict[str, str] = {
    "dc": "http://purl.org/dc/elements/1.1/",
    "dcterms": "http://purl.org/dc/terms/",
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "foaf": "http://xmlns.com/foaf/0.1/",
    "vann": "http://purl.org/vocab/vann/",
}


class OntologyParseError(Exception):
    """Exception raised when ontology parsing fails."""

    pass


class UnsupportedFormatError(Exception):
    """Exception raised when file format is not supported."""

    pass


class OntologyMetadataExtractor:
    """Service for extracting metadata from ontology files."""

    # Map file extensions to RDFLib format strings
    FORMAT_MAP: dict[str, str] = {
        ".owl": "xml",
        ".owx": "xml",
        ".rdf": "xml",
        ".ttl": "turtle",
        ".n3": "n3",
        ".jsonld": "json-ld",
    }

    # Content type mapping for storage
    CONTENT_TYPE_MAP: dict[str, str] = {
        ".owl": "application/rdf+xml",
        ".owx": "application/rdf+xml",
        ".rdf": "application/rdf+xml",
        ".ttl": "text/turtle",
        ".n3": "text/n3",
        ".jsonld": "application/ld+json",
    }

    # Supported extensions for validation
    SUPPORTED_EXTENSIONS = frozenset(FORMAT_MAP.keys())

    @classmethod
    def get_format_for_extension(cls, extension: str) -> str | None:
        """Get the RDFLib format string for a file extension."""
        return cls.FORMAT_MAP.get(extension.lower())

    @classmethod
    def get_content_type(cls, extension: str) -> str:
        """Get the content type for a file extension."""
        return cls.CONTENT_TYPE_MAP.get(extension.lower(), "application/octet-stream")

    @classmethod
    def is_supported_extension(cls, extension: str) -> bool:
        """Check if the file extension is supported."""
        return extension.lower() in cls.SUPPORTED_EXTENSIONS

    def extract_metadata(self, content: bytes, filename: str) -> ExtractedMetadata:
        """
        Extract metadata from an ontology file.

        Args:
            content: The file content as bytes
            filename: The original filename (used to determine format)

        Returns:
            ExtractedMetadata with ontology IRI, title, description, and format

        Raises:
            UnsupportedFormatError: If the file format is not supported
            OntologyParseError: If the file cannot be parsed
        """
        extension = Path(filename).suffix.lower()

        if not self.is_supported_extension(extension):
            supported = ", ".join(sorted(self.SUPPORTED_EXTENSIONS))
            raise UnsupportedFormatError(
                f"Unsupported file format: {extension}. Supported formats: {supported}"
            )

        rdf_format = self.get_format_for_extension(extension)
        if rdf_format is None:
            raise UnsupportedFormatError(f"Could not determine format for: {extension}")

        try:
            graph = Graph()
            graph.parse(data=content, format=rdf_format)
        except Exception as e:
            raise OntologyParseError(f"Failed to parse ontology: {e}") from e

        # Find the ontology IRI
        ontology_iri = self._find_ontology_iri(graph)

        # Extract title and description
        title = self._extract_title(graph, ontology_iri)
        description = self._extract_description(graph, ontology_iri)

        return ExtractedMetadata(
            ontology_iri=ontology_iri,
            title=title,
            description=description,
            format_detected=rdf_format,
        )

    def normalize_to_turtle(
        self, content: bytes, filename: str, use_canonical: bool = True
    ) -> tuple[bytes, NormalizationReport]:
        """
        Normalize an ontology file to canonical Turtle format.

        This parses the content in its original format and re-serializes
        to Turtle, ensuring a consistent canonical representation. This
        should be called on initial import so that subsequent edits
        produce minimal diffs.

        Args:
            content: The file content as bytes
            filename: The original filename (used to determine input format)

        Returns:
            Tuple of (normalized_content, normalization_report)

        Raises:
            UnsupportedFormatError: If the file format is not supported
            OntologyParseError: If the file cannot be parsed
        """
        extension = Path(filename).suffix.lower()

        if not self.is_supported_extension(extension):
            supported = ", ".join(sorted(self.SUPPORTED_EXTENSIONS))
            raise UnsupportedFormatError(
                f"Unsupported file format: {extension}. Supported formats: {supported}"
            )

        rdf_format = self.get_format_for_extension(extension)
        if rdf_format is None:
            raise UnsupportedFormatError(f"Could not determine format for: {extension}")

        # Human-readable format names
        format_names = {
            "xml": "RDF/XML",
            "turtle": "Turtle",
            "n3": "Notation3",
            "json-ld": "JSON-LD",
        }
        original_format_name = format_names.get(rdf_format, rdf_format)

        try:
            graph = Graph()
            graph.parse(data=content, format=rdf_format)
        except Exception as e:
            raise OntologyParseError(f"Failed to parse ontology: {e}") from e

        # Capture prefixes before serialization
        prefixes_before = sorted([prefix for prefix, _ in graph.namespaces() if prefix])

        # Count triples
        triple_count = len(graph)

        # Optionally convert to canonical graph with deterministic bnode identifiers
        # This is expensive for large graphs, so it can be disabled for imports
        if use_canonical:
            # to_canonical_graph() creates SHA-256 based bnode IDs for determinism
            # This ensures consistent serialization regardless of parse order
            # Note: to_canonical_graph() returns a ReadOnlyGraphAggregate in newer RDFLib,
            # so we need to copy triples to a new writable Graph
            canonical = to_canonical_graph(graph)
            output_graph = Graph()
            # Copy namespace bindings first
            for prefix, namespace in graph.namespaces():
                output_graph.bind(prefix, namespace)
            # Copy all triples from the canonical graph
            for triple in canonical:
                output_graph.add(triple)
        else:
            # Use the original graph (faster but non-deterministic bnode ordering)
            output_graph = graph

        # Ensure well-known namespaces get standard prefix names
        for prefix, ns in WELL_KNOWN_PREFIXES.items():
            output_graph.bind(prefix, Namespace(ns), override=True)

        # Detect ontology IRI to preserve as @base directive
        base_iri = self._find_ontology_iri(output_graph)

        # Serialize to Turtle (canonical format)
        normalized = output_graph.serialize(format="turtle", base=base_iri)
        if isinstance(normalized, str):
            normalized = normalized.encode("utf-8")

        # Parse the normalized output to get actual prefixes used
        normalized_graph = Graph()
        normalized_graph.parse(data=normalized, format="turtle")
        prefixes_after = sorted([prefix for prefix, _ in normalized_graph.namespaces() if prefix])

        # Calculate prefix changes
        prefixes_before_set = set(prefixes_before)
        prefixes_after_set = set(prefixes_after)
        prefixes_removed = sorted(prefixes_before_set - prefixes_after_set)
        prefixes_added = sorted(prefixes_after_set - prefixes_before_set)

        # Build notes about what changed
        notes: list[str] = []

        if rdf_format != "turtle":
            notes.append(f"Converted from {original_format_name} to Turtle format")

        if prefixes_removed:
            notes.append(
                f"Removed {len(prefixes_removed)} unused prefix(es): {', '.join(prefixes_removed)}"
            )

        if prefixes_added:
            notes.append(f"Added {len(prefixes_added)} prefix(es): {', '.join(prefixes_added)}")

        size_diff = len(normalized) - len(content)
        if size_diff < 0:
            notes.append(f"File size reduced by {abs(size_diff):,} bytes")
        elif size_diff > 0:
            notes.append(f"File size increased by {size_diff:,} bytes")

        notes.append("Triples reordered into canonical sequence")
        notes.append("Whitespace and formatting standardized")

        report = NormalizationReport(
            original_format=original_format_name,
            original_filename=filename,
            original_size_bytes=len(content),
            normalized_size_bytes=len(normalized),
            triple_count=triple_count,
            prefixes_before=prefixes_before,
            prefixes_after=prefixes_after,
            prefixes_removed=prefixes_removed,
            prefixes_added=prefixes_added,
            format_converted=(rdf_format != "turtle"),
            notes=notes,
        )

        return normalized, report

    def check_normalization_needed(
        self, content: bytes, filename: str = "ontology.ttl"
    ) -> tuple[bool, NormalizationReport | None]:
        """
        Check if normalization would change the content.

        This is a lightweight check that only examines:
        1. File format (non-Turtle always needs normalization)
        2. Byte comparison (if bytes match, no normalization needed)

        Note: This may report "needs normalization" for files that only differ
        in blank node ordering due to RDFLib's non-deterministic serialization.
        This is acceptable as the check runs in a background job, not on page load.

        Args:
            content: The current ontology file content as bytes
            filename: The filename (used to determine format, defaults to .ttl)

        Returns:
            Tuple of (needs_normalization, report_if_needed)
            - needs_normalization: True if content would change
            - report_if_needed: The normalization report if changes would occur
        """
        try:
            extension = Path(filename).suffix.lower()
            rdf_format = self.get_format_for_extension(extension)

            # Always needs normalization if not already Turtle
            if rdf_format != "turtle":
                # Skip canonical for status check (faster), just report format conversion needed
                normalized, report = self.normalize_to_turtle(
                    content, filename, use_canonical=False
                )
                return True, report

            # For Turtle files, just do a byte comparison
            # Skip canonical for status check to avoid expensive computation
            normalized, report = self.normalize_to_turtle(content, filename, use_canonical=False)

            if normalized == content:
                return False, None

            return True, report

        except (UnsupportedFormatError, OntologyParseError):
            # If we can't parse it, we can't normalize it
            return False, None

    def _find_ontology_iri(self, graph: Graph) -> str | None:
        """Find the ontology IRI (subject of rdf:type owl:Ontology)."""
        for subject in graph.subjects(RDF.type, OWL.Ontology):
            if isinstance(subject, URIRef):
                return str(subject)
        return None

    def _extract_title(self, graph: Graph, ontology_iri: str | None) -> str | None:
        """
        Extract the title from the ontology.

        Priority: dc:title > dcterms:title > rdfs:label
        """
        # Define subjects to check (ontology IRI first, then any subject)
        subjects_to_check: list[URIRef | None] = []
        if ontology_iri:
            subjects_to_check.append(URIRef(ontology_iri))

        # Priority order for title properties
        title_properties = [DC.title, DCTERMS.title, RDFS.label]

        for subject in subjects_to_check:
            for prop in title_properties:
                for obj in graph.objects(subject, prop):
                    value = str(obj)
                    if value:
                        return value

        # If no ontology IRI, search globally for any title on owl:Ontology subjects
        for subject in graph.subjects(RDF.type, OWL.Ontology):
            for prop in title_properties:
                for obj in graph.objects(subject, prop):
                    value = str(obj)
                    if value:
                        return value

        return None

    def _extract_description(self, graph: Graph, ontology_iri: str | None) -> str | None:
        """
        Extract the description from the ontology.

        Priority: dc:description > dcterms:description > rdfs:comment
        """
        # Define subjects to check (ontology IRI first)
        subjects_to_check: list[URIRef | None] = []
        if ontology_iri:
            subjects_to_check.append(URIRef(ontology_iri))

        # Priority order for description properties
        desc_properties = [DC.description, DCTERMS.description, RDFS.comment]

        for subject in subjects_to_check:
            for prop in desc_properties:
                for obj in graph.objects(subject, prop):
                    value = str(obj)
                    if value:
                        return value

        # If no ontology IRI, search globally for any description on owl:Ontology subjects
        for subject in graph.subjects(RDF.type, OWL.Ontology):
            for prop in desc_properties:
                for obj in graph.objects(subject, prop):
                    value = str(obj)
                    if value:
                        return value

        return None


def get_ontology_extractor() -> OntologyMetadataExtractor:
    """Factory function for dependency injection."""
    return OntologyMetadataExtractor()


@dataclass
class DetectedMetadataProperty:
    """Information about a detected metadata property in an ontology."""

    property_uri: URIRef
    property_curie: str  # e.g., "dc:title"
    current_value: str | None
    language: str | None = None


class OntologyMetadataUpdater:
    """Service for updating metadata properties in ontology files."""

    # Priority order for title properties (first found wins)
    TITLE_PROPERTIES: list[tuple[URIRef, str]] = [
        (DC.title, "dc:title"),
        (DCTERMS.title, "dcterms:title"),
        (RDFS.label, "rdfs:label"),
    ]

    # Priority order for description properties (first found wins)
    DESCRIPTION_PROPERTIES: list[tuple[URIRef, str]] = [
        (DC.description, "dc:description"),
        (DCTERMS.description, "dcterms:description"),
        (RDFS.comment, "rdfs:comment"),
    ]

    # Map file extensions to RDFLib format strings (same as extractor)
    FORMAT_MAP: dict[str, str] = {
        ".owl": "xml",
        ".rdf": "xml",
        ".ttl": "turtle",
        ".n3": "n3",
        ".jsonld": "json-ld",
    }

    def detect_title_property(
        self, graph: Graph, ontology_iri: URIRef | None
    ) -> DetectedMetadataProperty | None:
        """
        Detect which property is used for the ontology title.

        Checks in priority order: dc:title, dcterms:title, rdfs:label

        Args:
            graph: The RDF graph to search
            ontology_iri: The ontology IRI (subject to check)

        Returns:
            DetectedMetadataProperty if found, None otherwise
        """
        if ontology_iri is None:
            return None

        for prop_uri, prop_curie in self.TITLE_PROPERTIES:
            for obj in graph.objects(ontology_iri, prop_uri):
                value = str(obj)
                language = None
                if isinstance(obj, Literal) and obj.language:
                    language = obj.language
                return DetectedMetadataProperty(
                    property_uri=prop_uri,
                    property_curie=prop_curie,
                    current_value=value,
                    language=language,
                )

        return None

    def detect_description_property(
        self, graph: Graph, ontology_iri: URIRef | None
    ) -> DetectedMetadataProperty | None:
        """
        Detect which property is used for the ontology description.

        Checks in priority order: dc:description, dcterms:description, rdfs:comment

        Args:
            graph: The RDF graph to search
            ontology_iri: The ontology IRI (subject to check)

        Returns:
            DetectedMetadataProperty if found, None otherwise
        """
        if ontology_iri is None:
            return None

        for prop_uri, prop_curie in self.DESCRIPTION_PROPERTIES:
            for obj in graph.objects(ontology_iri, prop_uri):
                value = str(obj)
                language = None
                if isinstance(obj, Literal) and obj.language:
                    language = obj.language
                return DetectedMetadataProperty(
                    property_uri=prop_uri,
                    property_curie=prop_curie,
                    current_value=value,
                    language=language,
                )

        return None

    def _find_ontology_iri(self, graph: Graph) -> URIRef | None:
        """Find the ontology IRI (subject of rdf:type owl:Ontology)."""
        for subject in graph.subjects(RDF.type, OWL.Ontology):
            if isinstance(subject, URIRef):
                return subject
        return None

    def _ensure_dc_prefix(self, graph: Graph) -> None:
        """Ensure the dc: prefix is bound in the graph."""
        dc_namespace = Namespace("http://purl.org/dc/elements/1.1/")
        # Check if dc is already bound
        existing_namespaces = dict(graph.namespaces())
        if "dc" not in existing_namespaces:
            graph.bind("dc", dc_namespace)

    def update_metadata(
        self,
        content: bytes,
        filename: str,
        new_title: str | None = None,
        new_description: str | None = None,
    ) -> tuple[bytes, list[str]]:
        """
        Update metadata properties in an ontology file.

        This method:
        1. Parses the content into an RDF graph
        2. Detects existing title/description properties
        3. Updates or adds the properties as needed
        4. Serializes back to Turtle format

        Args:
            content: The ontology file content as bytes
            filename: The original filename (used to determine input format)
            new_title: New title value (None to skip updating)
            new_description: New description value (None to skip updating)

        Returns:
            Tuple of (updated_content_bytes, list_of_changes_made)

        Raises:
            OntologyParseError: If the content cannot be parsed
        """
        extension = Path(filename).suffix.lower()
        rdf_format = self.FORMAT_MAP.get(extension)

        if rdf_format is None:
            raise UnsupportedFormatError(f"Unsupported format: {extension}")

        # Parse the graph
        try:
            graph = Graph()
            graph.parse(data=content, format=rdf_format)
        except Exception as e:
            raise OntologyParseError(f"Failed to parse ontology: {e}") from e

        # Find ontology IRI
        ontology_iri = self._find_ontology_iri(graph)
        if ontology_iri is None:
            raise OntologyParseError("Cannot update metadata: no owl:Ontology declaration found")

        changes: list[str] = []

        # Update title if provided
        if new_title is not None:
            title_prop = self.detect_title_property(graph, ontology_iri)
            if title_prop:
                # Remove old triple(s)
                graph.remove((ontology_iri, title_prop.property_uri, None))
                # Add new triple with same language tag if it had one
                if title_prop.language:
                    graph.add(
                        (
                            ontology_iri,
                            title_prop.property_uri,
                            Literal(new_title, lang=title_prop.language),
                        )
                    )
                else:
                    graph.add((ontology_iri, title_prop.property_uri, Literal(new_title)))
                old_val = title_prop.current_value or "(empty)"
                changes.append(f'Title ({title_prop.property_curie}): "{old_val}" → "{new_title}"')
            else:
                # No existing title property - add dc:title
                self._ensure_dc_prefix(graph)
                graph.add((ontology_iri, DC.title, Literal(new_title)))
                changes.append(f'Title (dc:title): added "{new_title}"')

        # Update description if provided
        if new_description is not None:
            desc_prop = self.detect_description_property(graph, ontology_iri)
            if desc_prop:
                # Remove old triple(s)
                graph.remove((ontology_iri, desc_prop.property_uri, None))
                # Add new triple with same language tag if it had one
                if desc_prop.language:
                    graph.add(
                        (
                            ontology_iri,
                            desc_prop.property_uri,
                            Literal(new_description, lang=desc_prop.language),
                        )
                    )
                else:
                    graph.add((ontology_iri, desc_prop.property_uri, Literal(new_description)))
                old_val = desc_prop.current_value
                if old_val and len(old_val) > 50:
                    old_val = old_val[:50] + "..."
                changes.append(f"Description ({desc_prop.property_curie}): updated")
            else:
                # No existing description property - add dc:description
                self._ensure_dc_prefix(graph)
                graph.add((ontology_iri, DC.description, Literal(new_description)))
                changes.append("Description (dc:description): added")

        # Serialize to Turtle (canonical format), preserving @base directive
        updated_content = graph.serialize(format="turtle", base=str(ontology_iri))
        if isinstance(updated_content, str):
            updated_content = updated_content.encode("utf-8")

        return updated_content, changes


def get_ontology_metadata_updater() -> OntologyMetadataUpdater:
    """Factory function for dependency injection."""
    return OntologyMetadataUpdater()
