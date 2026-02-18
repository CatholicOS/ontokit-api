"""Pytest configuration and fixtures."""

import pytest
from fastapi.testclient import TestClient

from axigraph.main import app


@pytest.fixture
def client() -> TestClient:
    """Create a test client for the FastAPI application."""
    return TestClient(app)


@pytest.fixture
def sample_ontology_turtle() -> str:
    """Sample ontology in Turtle format."""
    return """
@prefix : <http://example.org/ontology#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

<http://example.org/ontology> rdf:type owl:Ontology ;
    rdfs:label "Example Ontology"@en .

:Person rdf:type owl:Class ;
    rdfs:label "Person"@en ;
    rdfs:comment "A human being"@en .

:Organization rdf:type owl:Class ;
    rdfs:label "Organization"@en .

:worksFor rdf:type owl:ObjectProperty ;
    rdfs:domain :Person ;
    rdfs:range :Organization ;
    rdfs:label "works for"@en .

:hasName rdf:type owl:DatatypeProperty ;
    rdfs:domain :Person ;
    rdfs:range xsd:string ;
    rdfs:label "has name"@en .
"""
