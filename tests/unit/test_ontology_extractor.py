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

    @pytest.mark.parametrize(
        ("ext", "expected"),
        [
            (".ttl", "turtle"),
            (".owl", "xml"),
            (".owx", "xml"),
            (".jsonld", "json-ld"),
            (".csv", None),
        ],
    )
    def test_get_format_for_extension(self, ext: str, expected: str | None) -> None:
        assert OntologyMetadataExtractor.get_format_for_extension(ext) == expected

    @pytest.mark.parametrize(
        ("ext", "expected"),
        [(".ttl", True), (".csv", False)],
    )
    def test_is_supported_extension(self, ext: str, expected: bool) -> None:  # noqa: FBT001
        assert OntologyMetadataExtractor.is_supported_extension(ext) is expected

    @pytest.mark.parametrize(
        ("ext", "expected"),
        [
            (".ttl", "text/turtle"),
            (".owl", "application/rdf+xml"),
            (".xyz", "application/octet-stream"),
        ],
    )
    def test_get_content_type(self, ext: str, expected: str) -> None:
        assert OntologyMetadataExtractor.get_content_type(ext) == expected


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

    def test_already_normalized_turtle(self, extractor: OntologyMetadataExtractor) -> None:
        """Turtle that is already normalized returns (False, None)."""
        # First normalize, then check if normalized output needs normalization
        normalized, _ = extractor.normalize_to_turtle(TURTLE_WITH_DC, "onto.ttl")
        needs, report = extractor.check_normalization_needed(normalized, "onto.ttl")
        assert needs is False
        assert report is None


class TestNormalizeToTurtle:
    """Tests for normalize_to_turtle()."""

    def test_unsupported_format_raises(self, extractor: OntologyMetadataExtractor) -> None:
        """Raises UnsupportedFormatError for unsupported extensions."""
        with pytest.raises(UnsupportedFormatError, match="Unsupported file format"):
            extractor.normalize_to_turtle(b"data", "file.csv")

    def test_rdfxml_converts_to_turtle(self, extractor: OntologyMetadataExtractor) -> None:
        """RDF/XML is converted to Turtle with format conversion note."""
        normalized, report = extractor.normalize_to_turtle(RDFXML_CONTENT, "onto.owl")
        assert report.format_converted is True
        assert report.original_format == "RDF/XML"
        assert b"@prefix" in normalized


class TestExtractTitleFallback:
    """Tests for _extract_title global fallback (lines 376-382)."""

    def test_title_found_via_global_search(self, extractor: OntologyMetadataExtractor) -> None:
        """Falls back to global search when _find_ontology_iri returns None."""
        # Turtle where owl:Ontology has no rdf:about, so _find_ontology_iri returns None
        turtle_no_iri = b"""\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix dc: <http://purl.org/dc/elements/1.1/> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .

_:ont rdf:type owl:Ontology ;
    dc:title "Fallback Title" .
"""
        meta = extractor.extract_metadata(turtle_no_iri, "onto.ttl")
        assert meta.title == "Fallback Title"
        assert meta.ontology_iri is None


class TestExtractDescriptionFallback:
    """Tests for _extract_description global fallback (lines 408-413)."""

    def test_description_found_via_global_search(
        self, extractor: OntologyMetadataExtractor
    ) -> None:
        """Falls back to global search when _find_ontology_iri returns None."""
        turtle_no_iri = b"""\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix dc: <http://purl.org/dc/elements/1.1/> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .

_:ont rdf:type owl:Ontology ;
    dc:description "Fallback Description" .
"""
        meta = extractor.extract_metadata(turtle_no_iri, "onto.ttl")
        assert meta.description == "Fallback Description"
        assert meta.ontology_iri is None


class TestFactoryFunctions:
    """Tests for factory functions."""

    def test_get_ontology_extractor(self) -> None:
        """get_ontology_extractor returns an OntologyMetadataExtractor."""
        from ontokit.services.ontology_extractor import get_ontology_extractor

        result = get_ontology_extractor()
        assert isinstance(result, OntologyMetadataExtractor)

    def test_get_ontology_metadata_updater(self) -> None:
        """get_ontology_metadata_updater returns an OntologyMetadataUpdater."""
        from ontokit.services.ontology_extractor import (
            OntologyMetadataUpdater,
            get_ontology_metadata_updater,
        )

        result = get_ontology_metadata_updater()
        assert isinstance(result, OntologyMetadataUpdater)


class TestOntologyMetadataUpdater:
    """Tests for OntologyMetadataUpdater (lines 459-646)."""

    def test_detect_title_property_dc(self) -> None:
        """detect_title_property finds dc:title."""
        from ontokit.services.ontology_extractor import OntologyMetadataUpdater

        updater = OntologyMetadataUpdater()
        from rdflib import Graph, URIRef

        g = Graph()
        g.parse(data=TURTLE_WITH_DC, format="turtle")
        ontology_iri = URIRef("http://example.org/onto")

        result = updater.detect_title_property(g, ontology_iri)
        assert result is not None
        assert result.property_curie == "dc:title"
        assert result.current_value == "My Ontology"

    def test_detect_title_property_none_iri(self) -> None:
        """detect_title_property returns None when ontology_iri is None."""
        from ontokit.services.ontology_extractor import OntologyMetadataUpdater

        updater = OntologyMetadataUpdater()
        from rdflib import Graph

        g = Graph()
        result = updater.detect_title_property(g, None)
        assert result is None

    def test_detect_description_property_dc(self) -> None:
        """detect_description_property finds dc:description."""
        from ontokit.services.ontology_extractor import OntologyMetadataUpdater

        updater = OntologyMetadataUpdater()
        from rdflib import Graph, URIRef

        g = Graph()
        g.parse(data=TURTLE_WITH_DC, format="turtle")
        ontology_iri = URIRef("http://example.org/onto")

        result = updater.detect_description_property(g, ontology_iri)
        assert result is not None
        assert result.property_curie == "dc:description"

    def test_detect_description_property_none_iri(self) -> None:
        """detect_description_property returns None when ontology_iri is None."""
        from ontokit.services.ontology_extractor import OntologyMetadataUpdater

        updater = OntologyMetadataUpdater()
        from rdflib import Graph

        g = Graph()
        result = updater.detect_description_property(g, None)
        assert result is None

    def test_update_metadata_title(self) -> None:
        """update_metadata changes the title."""
        from ontokit.services.ontology_extractor import OntologyMetadataUpdater

        updater = OntologyMetadataUpdater()
        content, changes = updater.update_metadata(
            TURTLE_WITH_DC, "onto.ttl", new_title="Updated Title"
        )
        assert any("Title" in c for c in changes)
        assert b"Updated Title" in content

    def test_update_metadata_description(self) -> None:
        """update_metadata changes the description."""
        from ontokit.services.ontology_extractor import OntologyMetadataUpdater

        updater = OntologyMetadataUpdater()
        content, changes = updater.update_metadata(
            TURTLE_WITH_DC, "onto.ttl", new_description="New description"
        )
        assert any("Description" in c for c in changes)
        assert b"New description" in content

    def test_update_metadata_no_existing_title(self) -> None:
        """update_metadata adds dc:title when no title property exists."""
        from ontokit.services.ontology_extractor import OntologyMetadataUpdater

        updater = OntologyMetadataUpdater()
        # Use ontology without title
        turtle_no_title = b"""\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .

<http://example.org/onto> rdf:type owl:Ontology .
"""
        content, changes = updater.update_metadata(
            turtle_no_title, "onto.ttl", new_title="Brand New Title"
        )
        assert any("dc:title" in c and "added" in c for c in changes)
        assert b"Brand New Title" in content

    def test_update_metadata_no_existing_description(self) -> None:
        """update_metadata adds dc:description when no description property exists."""
        from ontokit.services.ontology_extractor import OntologyMetadataUpdater

        updater = OntologyMetadataUpdater()
        turtle_no_desc = b"""\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .

<http://example.org/onto> rdf:type owl:Ontology .
"""
        content, changes = updater.update_metadata(
            turtle_no_desc, "onto.ttl", new_description="Brand New Description"
        )
        assert any("dc:description" in c and "added" in c for c in changes)
        assert b"Brand New Description" in content

    def test_update_metadata_unsupported_format(self) -> None:
        """update_metadata raises UnsupportedFormatError for unknown extensions."""
        from ontokit.services.ontology_extractor import OntologyMetadataUpdater

        updater = OntologyMetadataUpdater()
        with pytest.raises(UnsupportedFormatError, match="Unsupported format"):
            updater.update_metadata(b"data", "file.csv", new_title="X")

    def test_update_metadata_invalid_content(self) -> None:
        """update_metadata raises OntologyParseError for invalid content."""
        from ontokit.services.ontology_extractor import OntologyMetadataUpdater

        updater = OntologyMetadataUpdater()
        with pytest.raises(OntologyParseError, match="Failed to parse"):
            updater.update_metadata(b"not valid turtle {{{", "bad.ttl", new_title="X")

    def test_update_metadata_no_ontology_declaration(self) -> None:
        """update_metadata raises OntologyParseError when no owl:Ontology found."""
        from ontokit.services.ontology_extractor import OntologyMetadataUpdater

        updater = OntologyMetadataUpdater()
        with pytest.raises(OntologyParseError, match="no owl:Ontology"):
            updater.update_metadata(TURTLE_NO_ONTOLOGY, "classes.ttl", new_title="X")
