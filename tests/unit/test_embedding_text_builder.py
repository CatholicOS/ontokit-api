"""Tests for embedding_text_builder (ontokit/services/embedding_text_builder.py)."""

from __future__ import annotations

from rdflib import Graph, Namespace
from rdflib import Literal as RDFLiteral
from rdflib.namespace import OWL, RDF, RDFS, SKOS

from ontokit.services.embedding_text_builder import _local_name, build_embedding_text

EX = Namespace("http://example.org/ontology#")


# ---------------------------------------------------------------------------
# _local_name
# ---------------------------------------------------------------------------


class TestLocalName:
    def test_hash_separator(self) -> None:
        """Extracts name after '#'."""
        assert _local_name("http://example.org/ontology#Person") == "Person"

    def test_slash_separator(self) -> None:
        """Extracts name after last '/'."""
        assert _local_name("http://example.org/ontology/Person") == "Person"


# ---------------------------------------------------------------------------
# build_embedding_text
# ---------------------------------------------------------------------------


class TestBuildEmbeddingText:
    def test_class_with_label_and_comment(self) -> None:
        """Builds text with label and comment for a class."""
        g = Graph()
        g.add((EX.Person, RDF.type, OWL.Class))
        g.add((EX.Person, RDFS.label, RDFLiteral("Person", lang="en")))
        g.add((EX.Person, RDFS.comment, RDFLiteral("A human being", lang="en")))

        result = build_embedding_text(g, EX.Person, "class")
        assert result.startswith("class: Person")
        assert "A human being" in result

    def test_class_with_parents(self) -> None:
        """Includes parent labels in the text."""
        g = Graph()
        g.add((EX.Student, RDF.type, OWL.Class))
        g.add((EX.Student, RDFS.label, RDFLiteral("Student")))
        g.add((EX.Student, RDFS.subClassOf, EX.Person))
        g.add((EX.Person, RDFS.label, RDFLiteral("Person")))

        result = build_embedding_text(g, EX.Student, "class")
        assert "Parents: Person" in result

    def test_class_with_alt_labels(self) -> None:
        """Includes alternative labels in the text."""
        g = Graph()
        g.add((EX.Person, RDF.type, OWL.Class))
        g.add((EX.Person, RDFS.label, RDFLiteral("Person")))
        g.add((EX.Person, SKOS.altLabel, RDFLiteral("Human")))

        result = build_embedding_text(g, EX.Person, "class")
        assert "Also known as: Human" in result

    def test_entity_with_no_label_uses_local_name(self) -> None:
        """Falls back to local name when no rdfs:label exists."""
        g = Graph()
        g.add((EX.UnlabeledThing, RDF.type, OWL.Class))

        result = build_embedding_text(g, EX.UnlabeledThing, "class")
        assert "class: UnlabeledThing" in result

    def test_property_uses_subpropertyof(self) -> None:
        """Uses rdfs:subPropertyOf for property parent lookup."""
        g = Graph()
        g.add((EX.worksAt, RDF.type, OWL.ObjectProperty))
        g.add((EX.worksAt, RDFS.label, RDFLiteral("works at")))
        g.add((EX.worksAt, RDFS.subPropertyOf, EX.relatedTo))
        g.add((EX.relatedTo, RDFS.label, RDFLiteral("related to")))

        result = build_embedding_text(g, EX.worksAt, "property")
        assert "Parents: related to" in result

    def test_skos_definition_used_when_no_comment(self) -> None:
        """Falls back to skos:definition when no rdfs:comment exists."""
        g = Graph()
        g.add((EX.Concept, RDF.type, OWL.Class))
        g.add((EX.Concept, RDFS.label, RDFLiteral("Concept")))
        g.add((EX.Concept, SKOS.definition, RDFLiteral("A general idea")))

        result = build_embedding_text(g, EX.Concept, "class")
        assert "A general idea" in result
