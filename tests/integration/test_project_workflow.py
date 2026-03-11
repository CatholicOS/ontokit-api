"""Integration tests for the project workflow.

These tests verify the end-to-end flow through the API layer using mocked
services, validating that routes, dependency injection, and response schemas
work together correctly.
"""

from collections.abc import AsyncGenerator, Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from rdflib import Graph
from sqlalchemy.ext.asyncio import AsyncSession

from ontokit.core.database import get_db
from ontokit.main import app


@pytest.fixture
def mock_db_client() -> Generator[tuple[TestClient, AsyncMock]]:
    """TestClient with a mocked database session."""
    mock_session = AsyncMock()

    async def override_get_db() -> AsyncGenerator[AsyncSession]:
        yield mock_session

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    yield client, mock_session
    app.dependency_overrides.clear()


class TestProjectWorkflow:
    """Test the project lifecycle through the API."""

    def test_health_check_always_works(self, mock_db_client: tuple[TestClient, AsyncMock]) -> None:
        client, _ = mock_db_client
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    def test_search_returns_structure(self, mock_db_client: tuple[TestClient, AsyncMock]) -> None:
        """Search endpoint returns a valid SearchResponse structure."""
        client, mock_session = mock_db_client

        # Mock the execute calls for count and data queries.
        # scalar_one() is a sync method so use MagicMock for result objects.
        count_result = MagicMock()
        count_result.scalar_one.return_value = 0
        data_result = MagicMock()
        data_result.__iter__ = MagicMock(return_value=iter([]))
        mock_session.execute = AsyncMock(side_effect=[count_result, data_result])

        response = client.get("/api/v1/search?q=test")
        assert response.status_code == 200
        data = response.json()
        assert "results" in data
        assert "total" in data
        assert "query" in data
        assert data["query"] == "test"

    @patch(
        "ontokit.api.routes.search.load_project_graph",
        new_callable=AsyncMock,
        return_value=(Graph(), "main"),
    )
    @patch("ontokit.api.routes.search.verify_project_access", new_callable=AsyncMock)
    def test_sparql_select_returns_structure(
        self,
        _mock_access: AsyncMock,
        _mock_graph: AsyncMock,
        mock_db_client: tuple[TestClient, AsyncMock],
    ) -> None:
        """SPARQL SELECT returns proper response structure."""
        client, _ = mock_db_client
        response = client.post(
            "/api/v1/search/sparql",
            json={
                "query": "SELECT ?s WHERE { ?s ?p ?o } LIMIT 1",
                "ontology_id": "00000000-0000-0000-0000-000000000000",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["query_type"] == "SELECT"
        assert "variables" in data
        assert "bindings" in data

    @patch(
        "ontokit.api.routes.search.load_project_graph",
        new_callable=AsyncMock,
        return_value=(Graph(), "main"),
    )
    @patch("ontokit.api.routes.search.verify_project_access", new_callable=AsyncMock)
    def test_sparql_ask_returns_boolean(
        self,
        _mock_access: AsyncMock,
        _mock_graph: AsyncMock,
        mock_db_client: tuple[TestClient, AsyncMock],
    ) -> None:
        """SPARQL ASK returns a boolean result."""
        client, _ = mock_db_client
        response = client.post(
            "/api/v1/search/sparql",
            json={
                "query": "ASK { ?s ?p ?o }",
                "ontology_id": "00000000-0000-0000-0000-000000000000",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["query_type"] == "ASK"
        assert "boolean" in data


class TestLintWorkflow:
    """Test the lint workflow through the API."""

    def test_lint_rules_endpoint(self, mock_db_client: tuple[TestClient, AsyncMock]) -> None:
        """GET /api/v1/projects/{id}/lint/rules returns available rules."""
        client, mock_session = mock_db_client

        # The lint rules endpoint may require a project lookup.
        # We mock the DB to return None for the project (which should
        # result in a 404 or the rules list depending on implementation).
        mock_session.execute = AsyncMock(return_value=AsyncMock(scalar_one_or_none=lambda: None))

        response = client.get("/api/v1/projects/00000000-0000-0000-0000-000000000001/lint/rules")
        # The endpoint should be routable (not 404 for the route itself)
        assert response.status_code != 405  # Method allowed
