"""Pytest configuration and fixtures."""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pygit2
import pytest
from fastapi.testclient import TestClient
from rdflib import Graph

from ontokit.core.auth import CurrentUser
from ontokit.git.bare_repository import BareOntologyRepository
from ontokit.main import app
from ontokit.services.github_service import GitHubService
from ontokit.services.storage import StorageService
from ontokit.services.user_service import UserService


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
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

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
def sample_project_data() -> dict[str, object]:
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


@pytest.fixture
def mock_arq_pool() -> AsyncMock:
    """Create an async mock of the ARQ Redis pool."""
    pool = AsyncMock()
    pool.enqueue_job = AsyncMock(return_value=Mock(job_id="test-job-id"))
    return pool


@pytest.fixture
def bare_git_repo(tmp_path: Path, sample_ontology_turtle: str) -> BareOntologyRepository:
    """Create a real pygit2 bare repo with an initial Turtle commit."""
    repo_path = tmp_path / "test-project.git"
    raw_repo = pygit2.init_repository(str(repo_path), bare=True)
    # Ensure HEAD points to refs/heads/main regardless of system git config
    raw_repo.set_head("refs/heads/main")

    repo = BareOntologyRepository(repo_path)
    repo.write_file(
        branch_name="main",
        filepath="ontology.ttl",
        content=sample_ontology_turtle.encode(),
        message="Initial commit",
        author_name="Test User",
        author_email="test@example.com",
    )
    return repo


@pytest.fixture
def mock_github_service() -> Mock:
    """Create a mock of the GitHubService with canned responses."""
    service = Mock(spec=GitHubService)
    service.get_authenticated_user = AsyncMock(return_value=("testuser", "repo,read:org"))
    service.list_user_repos = AsyncMock(return_value=[])
    service.scan_ontology_files = AsyncMock(return_value=[])
    service.get_file_content = AsyncMock(return_value=b"# empty")
    service.verify_webhook_signature = Mock(return_value=True)
    return service


@pytest.fixture
def mock_user_service() -> Mock:
    """Create a mock of the UserService with canned responses."""
    service = Mock(spec=UserService)
    service.get_user_info = AsyncMock(
        return_value={"id": "test-user-id", "name": "Test User", "email": "test@example.com"}
    )
    service.get_users_info = AsyncMock(
        return_value={
            "test-user-id": {
                "id": "test-user-id",
                "name": "Test User",
                "email": "test@example.com",
            }
        }
    )
    service.search_users = AsyncMock(return_value=([], 0))
    return service
