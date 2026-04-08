"""Tests for project and search routes."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Generator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from ontokit import __version__
from ontokit.core.database import get_db
from ontokit.main import app


async def _noop_verify_access(*_args: Any, **_kwargs: Any) -> None:  # noqa: ARG001
    """No-op replacement for verify_project_access in tests."""


@pytest.fixture
def mock_db_client() -> Generator[TestClient]:
    """Create a test client with the database dependency overridden.

    This avoids real database connections for routes that depend on ``get_db``.
    """
    mock_session = MagicMock()

    async def _override_get_db() -> AsyncGenerator[AsyncSession]:
        yield mock_session

    app.dependency_overrides[get_db] = _override_get_db
    client = TestClient(app, raise_server_exceptions=False)
    yield client
    app.dependency_overrides.clear()


class TestHealthAndRoot:
    """Tests for top-level endpoints (health, root)."""

    def test_health_check(self, client: TestClient) -> None:
        """GET /health returns 200 with healthy status."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}

    def test_root_returns_api_info(self, client: TestClient) -> None:
        """GET / returns expected API information structure."""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "OntoKit API"
        assert data["version"] == __version__
        assert data["docs"] == "/docs"
        assert data["openapi"] == "/openapi.json"


class TestProjectsRoute:
    """Tests for the /api/v1/projects endpoints."""

    def test_list_projects_anonymous_reachable(self, mock_db_client: TestClient) -> None:
        """GET /api/v1/projects without auth reaches the route (not 404/405).

        The endpoint uses OptionalUser so anonymous access is permitted.
        With a mocked DB session the service layer may raise an error, but
        the route itself must be routable.
        """
        response = mock_db_client.get("/api/v1/projects")
        # Route is registered (not 404 or 405)
        assert response.status_code != 404
        assert response.status_code != 405


class TestSearchRoute:
    """Tests for the /api/v1/search endpoints."""

    def test_search_endpoint_reachable(self, mock_db_client: TestClient) -> None:
        """GET /api/v1/search?q=test reaches the search route (not 404)."""
        response = mock_db_client.get("/api/v1/search", params={"q": "test"})
        # Route exists and is reachable
        assert response.status_code != 404
        assert response.status_code != 405

    def test_search_missing_query_param(self, client: TestClient) -> None:
        """GET /api/v1/search without q parameter returns 422 validation error."""
        response = client.get("/api/v1/search")
        assert response.status_code == 422

    @pytest.mark.parametrize(
        ("query", "expect_detail"),
        [
            ("INSERT DATA { <http://ex.org/s> <http://ex.org/p> <http://ex.org/o> }", True),
            ("DELETE WHERE { ?s ?p ?o }", False),
            ("DROP GRAPH <http://example.org/graph>", False),
            ("CLEAR ALL", False),
            ("CREATE GRAPH <http://example.org/new>", False),
        ],
        ids=["insert", "delete", "drop", "clear", "create"],
    )
    @patch("ontokit.api.routes.search.verify_project_access", _noop_verify_access)
    def test_sparql_blocks_mutation(
        self, mock_db_client: TestClient, query: str, expect_detail: bool
    ) -> None:
        """POST /api/v1/search/sparql with mutating queries returns 400."""
        response = mock_db_client.post(
            "/api/v1/search/sparql",
            json={
                "query": query,
                "ontology_id": "00000000-0000-0000-0000-000000000000",
            },
        )
        assert response.status_code == 400
        if expect_detail:
            assert "not allowed" in response.json()["detail"].lower()

    def test_sparql_empty_query_rejected(self, client: TestClient) -> None:
        """POST /api/v1/search/sparql with empty query returns 422."""
        response = client.post(
            "/api/v1/search/sparql",
            json={"query": "", "ontology_id": "00000000-0000-0000-0000-000000000000"},
        )
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert any(err["loc"] == ["body", "query"] for err in detail)
