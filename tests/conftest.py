"""Pytest configuration and fixtures."""

import uuid
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient
from rdflib import Graph

from ontokit.core.auth import CurrentUser
from ontokit.main import app
from ontokit.services.storage import StorageService


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


@pytest.fixture
def mock_db_session() -> AsyncMock:
    """Create an async mock of an SQLAlchemy AsyncSession."""
    session = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.close = AsyncMock()
    session.execute = AsyncMock()
    session.refresh = AsyncMock()
    session.add = Mock()
    session.delete = AsyncMock()
    return session


@pytest.fixture
def mock_redis() -> AsyncMock:
    """Create an async mock of a Redis client."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock(return_value=True)
    redis.delete = AsyncMock(return_value=1)
    redis.exists = AsyncMock(return_value=0)
    redis.expire = AsyncMock(return_value=True)
    redis.publish = AsyncMock(return_value=1)
    redis.close = AsyncMock()
    return redis


@pytest.fixture
def mock_storage() -> Mock:
    """Create a mock of the StorageService."""
    storage = Mock(spec=StorageService)
    storage.upload_file = AsyncMock(return_value="ontokit/test-object")
    storage.download_file = AsyncMock(return_value=b"file content")
    storage.delete_file = AsyncMock()
    storage.file_exists = AsyncMock(return_value=True)
    storage.ensure_bucket_exists = AsyncMock()
    return storage


@pytest.fixture
def authenticated_user() -> CurrentUser:
    """Create an authenticated test user."""
    return CurrentUser(
        id="test-user-id",
        email="test@example.com",
        name="Test User",
        username="testuser",
        roles=["editor"],
    )


@pytest.fixture
def auth_token() -> str:
    """Provide a fake JWT token for testing."""
    return "test-token-123"


@pytest.fixture
def sample_project_data() -> dict:
    """Provide sample project data as a dictionary."""
    return {
        "id": uuid.UUID("12345678-1234-5678-1234-567812345678"),
        "name": "Test Ontology Project",
        "description": "A sample project for testing purposes.",
        "is_public": True,
        "owner_id": "test-user-id",
    }


@pytest.fixture
def sample_graph(sample_ontology_turtle: str) -> Graph:
    """Parse the sample ontology Turtle string into an RDFLib Graph."""
    graph = Graph()
    graph.parse(data=sample_ontology_turtle, format="turtle")
    return graph
