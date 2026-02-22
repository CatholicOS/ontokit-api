"""Tests for the ontology service label preference parsing and selection."""

import pytest
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS, SKOS

from ontokit.services.ontology import (
    DEFAULT_LABEL_PREFERENCES,
    LABEL_PROPERTY_MAP,
    LabelPreference,
    select_preferred_label,
)

EX = Namespace("http://example.org/")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def graph_with_labels() -> Graph:
    """Create an RDF graph with English and Italian labels on EX.Person."""
    g = Graph()
    g.add((EX.Person, RDF.type, OWL.Class))
    g.add((EX.Person, RDFS.label, Literal("Person", lang="en")))
    g.add((EX.Person, RDFS.label, Literal("Persona", lang="it")))
    return g


@pytest.fixture
def graph_with_skos_labels() -> Graph:
    """Create an RDF graph with SKOS preferred labels."""
    g = Graph()
    g.add((EX.Animal, RDF.type, OWL.Class))
    g.add((EX.Animal, SKOS.prefLabel, Literal("Animal", lang="en")))
    g.add((EX.Animal, SKOS.prefLabel, Literal("Tier", lang="de")))
    return g


@pytest.fixture
def graph_no_labels() -> Graph:
    """Create an RDF graph with a class but no labels."""
    g = Graph()
    g.add((EX.Thing, RDF.type, OWL.Class))
    return g


@pytest.fixture
def graph_untagged_label() -> Graph:
    """Create an RDF graph with a label that has no language tag."""
    g = Graph()
    g.add((EX.Widget, RDF.type, OWL.Class))
    g.add((EX.Widget, RDFS.label, Literal("Widget")))
    return g


# ---------------------------------------------------------------------------
# LabelPreference.parse tests
# ---------------------------------------------------------------------------


class TestLabelPreferenceParse:
    """Tests for LabelPreference.parse class method."""

    def test_label_preference_parse_with_lang(self) -> None:
        """'rdfs:label@en' parses to RDFS.label with language 'en'."""
        pref = LabelPreference.parse("rdfs:label@en")
        assert pref is not None
        assert pref.property_uri == RDFS.label
        assert pref.language == "en"

    def test_label_preference_parse_without_lang(self) -> None:
        """'rdfs:label' parses to RDFS.label with language None."""
        pref = LabelPreference.parse("rdfs:label")
        assert pref is not None
        assert pref.property_uri == RDFS.label
        assert pref.language is None

    def test_label_preference_parse_unknown(self) -> None:
        """'unknown:prop' returns None (unrecognized property)."""
        pref = LabelPreference.parse("unknown:prop")
        assert pref is None

    def test_label_preference_parse_skos_preflabel(self) -> None:
        """'skos:prefLabel@de' parses to SKOS.prefLabel with language 'de'."""
        pref = LabelPreference.parse("skos:prefLabel@de")
        assert pref is not None
        assert pref.property_uri == SKOS.prefLabel
        assert pref.language == "de"

    def test_label_preference_parse_skos_altlabel(self) -> None:
        """'skos:altLabel' parses to SKOS.altLabel with no language."""
        pref = LabelPreference.parse("skos:altLabel")
        assert pref is not None
        assert pref.property_uri == SKOS.altLabel
        assert pref.language is None

    def test_label_preference_parse_dcterms_title(self) -> None:
        """'dcterms:title@fr' parses correctly."""
        pref = LabelPreference.parse("dcterms:title@fr")
        assert pref is not None
        assert pref.property_uri == URIRef("http://purl.org/dc/terms/title")
        assert pref.language == "fr"

    def test_label_preference_parse_all_known_properties(self) -> None:
        """Every key in LABEL_PROPERTY_MAP parses successfully."""
        for prop_key, expected_uri in LABEL_PROPERTY_MAP.items():
            pref = LabelPreference.parse(prop_key)
            assert pref is not None, f"Failed to parse: {prop_key}"
            assert pref.property_uri == expected_uri
            assert pref.language is None

    def test_label_preference_parse_empty_string(self) -> None:
        """Empty string returns None (no matching property)."""
        pref = LabelPreference.parse("")
        assert pref is None


# ---------------------------------------------------------------------------
# select_preferred_label tests
# ---------------------------------------------------------------------------


class TestSelectPreferredLabel:
    """Tests for the select_preferred_label function."""

    def test_select_preferred_label_english(self, graph_with_labels: Graph) -> None:
        """Selects English label when preferences request 'rdfs:label@en'."""
        result = select_preferred_label(
            graph_with_labels, EX.Person, preferences=["rdfs:label@en"]
        )
        assert result == "Person"

    def test_select_preferred_label_italian(self, graph_with_labels: Graph) -> None:
        """Selects Italian label when preferences request 'rdfs:label@it'."""
        result = select_preferred_label(
            graph_with_labels, EX.Person, preferences=["rdfs:label@it"]
        )
        assert result == "Persona"

    def test_select_preferred_label_fallback(self, graph_with_labels: Graph) -> None:
        """Falls back to rdfs:label when preferred language is not available."""
        result = select_preferred_label(
            graph_with_labels, EX.Person, preferences=["rdfs:label@de"]
        )
        # No German label, but fallback logic returns any rdfs:label
        assert result in ("Person", "Persona")

    def test_select_preferred_label_no_labels(self, graph_no_labels: Graph) -> None:
        """Returns None when the subject has no labels at all."""
        result = select_preferred_label(graph_no_labels, EX.Thing)
        assert result is None

    def test_select_preferred_label_default_preferences(
        self, graph_with_labels: Graph
    ) -> None:
        """Using default preferences (None) selects English rdfs:label first."""
        result = select_preferred_label(graph_with_labels, EX.Person, preferences=None)
        assert result == "Person"

    def test_select_preferred_label_skos(self, graph_with_skos_labels: Graph) -> None:
        """Selects SKOS prefLabel when preferences request it."""
        result = select_preferred_label(
            graph_with_skos_labels, EX.Animal, preferences=["skos:prefLabel@en"]
        )
        assert result == "Animal"

    def test_select_preferred_label_skos_german(
        self, graph_with_skos_labels: Graph
    ) -> None:
        """Selects German SKOS prefLabel when preferences request 'skos:prefLabel@de'."""
        result = select_preferred_label(
            graph_with_skos_labels, EX.Animal, preferences=["skos:prefLabel@de"]
        )
        assert result == "Tier"

    def test_select_preferred_label_any_language(
        self, graph_with_labels: Graph
    ) -> None:
        """Preference without language tag matches any available label."""
        result = select_preferred_label(
            graph_with_labels, EX.Person, preferences=["rdfs:label"]
        )
        # Should return one of the available labels (either language)
        assert result in ("Person", "Persona")

    def test_select_preferred_label_untagged_literal(
        self, graph_untagged_label: Graph
    ) -> None:
        """Label without a language tag is matched by a no-lang preference."""
        result = select_preferred_label(
            graph_untagged_label, EX.Widget, preferences=["rdfs:label"]
        )
        assert result == "Widget"

    def test_select_preferred_label_nonexistent_subject(
        self, graph_with_labels: Graph
    ) -> None:
        """Returns None for a subject that does not exist in the graph."""
        result = select_preferred_label(graph_with_labels, EX.NonExistent)
        assert result is None

    def test_select_preferred_label_priority_order(self) -> None:
        """Earlier preferences take priority over later ones."""
        g = Graph()
        g.add((EX.Concept, RDF.type, OWL.Class))
        g.add((EX.Concept, RDFS.label, Literal("English Label", lang="en")))
        g.add((EX.Concept, SKOS.prefLabel, Literal("SKOS English", lang="en")))

        # rdfs:label@en first -> should return "English Label"
        result = select_preferred_label(
            g, EX.Concept, preferences=["rdfs:label@en", "skos:prefLabel@en"]
        )
        assert result == "English Label"

        # skos:prefLabel@en first -> should return "SKOS English"
        result = select_preferred_label(
            g, EX.Concept, preferences=["skos:prefLabel@en", "rdfs:label@en"]
        )
        assert result == "SKOS English"
