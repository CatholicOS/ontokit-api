"""Tests for OntologyMetadataExtractor (ontokit/services/ontology_extractor.py)."""

from __future__ import annotations

import pytest

from ontokit.services.ontology_extractor import (
    OntologyMetadataExtractor,
    OntologyParseError,
    UnsupportedFormatError,
)

TURTLE_WITH_DC = b"""\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix dc: <http://purl.org/dc/elements/1.1/> .

<http://example.org/onto> rdf:type owl:Ontology ;
    dc:title "My Ontology" ;
    dc:description "A test ontology for unit tests." .
"""

TURTLE_WITH_RDFS = b"""\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

<http://example.org/onto2> rdf:type owl:Ontology ;
    rdfs:label "RDFS Label Title" ;
    rdfs:comment "Description via rdfs:comment" .
"""

RDFXML_CONTENT = b"""\
<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:owl="http://www.w3.org/2002/07/owl#"
         xmlns:dc="http://purl.org/dc/elements/1.1/">
  <owl:Ontology rdf:about="http://example.org/rdfxml-onto">
    <dc:title>RDF/XML Ontology</dc:title>
    <dc:description>An ontology in RDF/XML format.</dc:description>
  </owl:Ontology>
</rdf:RDF>
"""

TURTLE_NO_ONTOLOGY = b"""\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

<http://example.org/onto#Person> rdf:type owl:Class ;
    rdfs:label "Person" .
"""


@pytest.fixture
def extractor() -> OntologyMetadataExtractor:
    """Create an OntologyMetadataExtractor."""
    return OntologyMetadataExtractor()


class TestFormatDetection:
    """Tests for format detection helpers."""

    def test_turtle_extension(self) -> None:
        assert OntologyMetadataExtractor.get_format_for_extension(".ttl") == "turtle"

    def test_rdfxml_extension(self) -> None:
        assert OntologyMetadataExtractor.get_format_for_extension(".owl") == "xml"

    def test_jsonld_extension(self) -> None:
        assert OntologyMetadataExtractor.get_format_for_extension(".jsonld") == "json-ld"

    def test_unsupported_extension_returns_none(self) -> None:
        assert OntologyMetadataExtractor.get_format_for_extension(".csv") is None

    def test_is_supported_extension(self) -> None:
        assert OntologyMetadataExtractor.is_supported_extension(".ttl") is True
        assert OntologyMetadataExtractor.is_supported_extension(".csv") is False

    def test_get_content_type(self) -> None:
        assert OntologyMetadataExtractor.get_content_type(".ttl") == "text/turtle"
        assert OntologyMetadataExtractor.get_content_type(".owl") == "application/rdf+xml"
        assert OntologyMetadataExtractor.get_content_type(".xyz") == "application/octet-stream"


class TestExtractMetadataTurtle:
    """Tests for extract_metadata() with Turtle content."""

    def test_extracts_iri_title_description_from_dc(
        self, extractor: OntologyMetadataExtractor
    ) -> None:
        """Extracts ontology IRI, dc:title, and dc:description."""
        meta = extractor.extract_metadata(TURTLE_WITH_DC, "ontology.ttl")
        assert meta.ontology_iri == "http://example.org/onto"
        assert meta.title == "My Ontology"
        assert meta.description == "A test ontology for unit tests."
        assert meta.format_detected == "turtle"

    def test_extracts_rdfs_label_and_comment(self, extractor: OntologyMetadataExtractor) -> None:
        """Falls back to rdfs:label for title and rdfs:comment for description."""
        meta = extractor.extract_metadata(TURTLE_WITH_RDFS, "test.ttl")
        assert meta.title == "RDFS Label Title"
        assert meta.description == "Description via rdfs:comment"

    def test_no_ontology_declaration(self, extractor: OntologyMetadataExtractor) -> None:
        """Returns None IRI, title, description when no owl:Ontology is declared."""
        meta = extractor.extract_metadata(TURTLE_NO_ONTOLOGY, "classes.ttl")
        assert meta.ontology_iri is None
        assert meta.title is None
        assert meta.description is None


class TestExtractMetadataRDFXML:
    """Tests for extract_metadata() with RDF/XML content."""

    def test_extracts_from_rdfxml(self, extractor: OntologyMetadataExtractor) -> None:
        """Extracts metadata from RDF/XML format."""
        meta = extractor.extract_metadata(RDFXML_CONTENT, "ontology.owl")
        assert meta.ontology_iri == "http://example.org/rdfxml-onto"
        assert meta.title == "RDF/XML Ontology"
        assert meta.description == "An ontology in RDF/XML format."
        assert meta.format_detected == "xml"


class TestExtractMetadataErrors:
    """Tests for error handling in extract_metadata()."""

    def test_unsupported_format_raises(self, extractor: OntologyMetadataExtractor) -> None:
        """Raises UnsupportedFormatError for unsupported file extensions."""
        with pytest.raises(UnsupportedFormatError, match="Unsupported file format"):
            extractor.extract_metadata(b"data", "file.csv")

    def test_invalid_turtle_raises_parse_error(self, extractor: OntologyMetadataExtractor) -> None:
        """Raises OntologyParseError when content is not valid for the declared format."""
        with pytest.raises(OntologyParseError, match="Failed to parse"):
            extractor.extract_metadata(b"this is not valid turtle {{{", "broken.ttl")


class TestNormalizationCheck:
    """Tests for check_normalization_needed()."""

    def test_non_turtle_always_needs_normalization(
        self, extractor: OntologyMetadataExtractor
    ) -> None:
        """RDF/XML files always need normalization to Turtle."""
        needs, report = extractor.check_normalization_needed(RDFXML_CONTENT, "onto.owl")
        assert needs is True
        assert report is not None
        assert report.format_converted is True

    def test_unparseable_returns_false(self, extractor: OntologyMetadataExtractor) -> None:
        """Files that cannot be parsed return (False, None)."""
        needs, report = extractor.check_normalization_needed(b"not valid", "bad.ttl")
        assert needs is False
        assert report is None
