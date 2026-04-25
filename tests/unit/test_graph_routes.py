"""Tests for entity graph route handlers."""

from __future__ import annotations

import uuid
from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from ontokit.api.routes.projects import get_git, get_ontology, get_service
from ontokit.main import app
from ontokit.schemas.graph import EntityGraphResponse, GraphNode

PROJECT_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
FOCUS_IRI = "http://example.org/ontology#Person"


def _sample_graph_response() -> EntityGraphResponse:
    return EntityGraphResponse(
        focus_iri=FOCUS_IRI,
        focus_label="Person",
        nodes=[
            GraphNode(id=FOCUS_IRI, label="Person", iri=FOCUS_IRI, is_focus=True, node_type="focus")
        ],
        edges=[],
        truncated=False,
        total_concept_count=1,
    )


# ---------------------------------------------------------------------------
# projects.py — GET /api/v1/projects/{id}/ontology/classes/graph
# ---------------------------------------------------------------------------


class TestProjectsGraphRoute:
    @pytest.fixture
    def mock_services(
        self,
        authed_client: tuple[TestClient, AsyncMock],
    ) -> Generator[tuple[TestClient, AsyncMock, MagicMock, AsyncMock], None, None]:
        client, _db = authed_client

        mock_project_svc = AsyncMock()
        mock_project_svc.get = AsyncMock(
            return_value=MagicMock(source_file_path="ontology.ttl", label_preferences=None)
        )

        mock_onto = AsyncMock()
        mock_git = MagicMock()
        mock_git.get_default_branch = MagicMock(return_value="main")

        app.dependency_overrides[get_service] = lambda: mock_project_svc
        app.dependency_overrides[get_ontology] = lambda: mock_onto
        app.dependency_overrides[get_git] = lambda: mock_git
        try:
            yield client, mock_onto, mock_git, mock_project_svc
        finally:
            app.dependency_overrides.pop(get_service, None)
            app.dependency_overrides.pop(get_ontology, None)
            app.dependency_overrides.pop(get_git, None)

    def test_graph_success(
        self,
        mock_services: tuple[TestClient, AsyncMock, MagicMock, AsyncMock],
    ) -> None:
        client, mock_onto, _git, _proj = mock_services
        mock_onto.build_entity_graph = AsyncMock(return_value=_sample_graph_response())
        resp = client.get(
            f"/api/v1/projects/{PROJECT_ID}/ontology/classes/graph",
            params={"class_iri": FOCUS_IRI},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["focus_iri"] == FOCUS_IRI

    def test_graph_not_found(
        self,
        mock_services: tuple[TestClient, AsyncMock, MagicMock, AsyncMock],
    ) -> None:
        client, mock_onto, _git, _proj = mock_services
        mock_onto.build_entity_graph = AsyncMock(return_value=None)
        resp = client.get(
            f"/api/v1/projects/{PROJECT_ID}/ontology/classes/graph",
            params={"class_iri": "http://example.org/Missing"},
        )
        assert resp.status_code == 404

    def test_graph_uses_default_branch(
        self,
        mock_services: tuple[TestClient, AsyncMock, MagicMock, AsyncMock],
    ) -> None:
        client, mock_onto, mock_git, _proj = mock_services
        mock_onto.build_entity_graph = AsyncMock(return_value=_sample_graph_response())
        mock_git.get_default_branch = MagicMock(return_value="develop")
        resp = client.get(
            f"/api/v1/projects/{PROJECT_ID}/ontology/classes/graph",
            params={"class_iri": FOCUS_IRI},
        )
        assert resp.status_code == 200
        mock_onto.build_entity_graph.assert_called_once()
        call_kwargs = mock_onto.build_entity_graph.call_args[1]
        assert call_kwargs["branch"] == "develop"
