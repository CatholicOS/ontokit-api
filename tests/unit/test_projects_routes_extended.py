"""Extended tests for project management routes (ontokit/api/routes/projects.py)."""

from __future__ import annotations

import uuid
from collections.abc import Generator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from ontokit.api.routes.projects import (
    get_git,
    get_indexed_ontology,
    get_ontology,
    get_service,
    get_storage,
)
from ontokit.core.auth import CurrentUser, get_current_user_with_token
from ontokit.main import app
from ontokit.schemas.project import MemberListResponse, MemberResponse, ProjectResponse
from ontokit.services.project_service import ProjectService

PROJECT_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_project_response(**overrides: Any) -> MagicMock:
    """Return a mock that quacks like a ProjectResponse."""
    resp = MagicMock()
    resp.id = overrides.get("id", PROJECT_ID)
    resp.name = overrides.get("name", "Test Project")
    resp.description = overrides.get("description", "A test project")
    resp.is_public = overrides.get("is_public", True)
    resp.owner_id = overrides.get("owner_id", "test-user-id")
    resp.created_at = overrides.get("created_at", datetime.now(UTC))
    resp.updated_at = overrides.get("updated_at", datetime.now(UTC))
    resp.member_count = overrides.get("member_count", 1)
    resp.source_file_path = overrides.get("source_file_path", "ontology.ttl")
    resp.user_role = overrides.get("user_role", "owner")
    resp.is_superadmin = overrides.get("is_superadmin", False)
    resp.git_ontology_path = overrides.get("git_ontology_path")
    resp.label_preferences = overrides.get("label_preferences")
    # Allow dict() / model_dump() for Pydantic compatibility
    resp.model_dump = lambda **_kw: {
        "id": str(resp.id),
        "name": resp.name,
        "description": resp.description,
        "is_public": resp.is_public,
        "owner_id": resp.owner_id,
        "created_at": resp.created_at.isoformat(),
        "updated_at": resp.updated_at.isoformat() if resp.updated_at else None,
        "member_count": resp.member_count,
    }
    return resp


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_project_service() -> Generator[AsyncMock, None, None]:
    """Provide an AsyncMock ProjectService and register it as a dependency override."""
    mock_svc = AsyncMock(spec=ProjectService)
    app.dependency_overrides[get_service] = lambda: mock_svc
    try:
        yield mock_svc
    finally:
        app.dependency_overrides.pop(get_service, None)


@pytest.fixture
def mock_git_service() -> Generator[MagicMock, None, None]:
    """Provide a MagicMock GitRepositoryService as a dependency override."""
    mock_git = MagicMock()
    app.dependency_overrides[get_git] = lambda: mock_git
    try:
        yield mock_git
    finally:
        app.dependency_overrides.pop(get_git, None)


@pytest.fixture
def mock_storage_service() -> Generator[MagicMock, None, None]:
    """Provide a MagicMock StorageService as a dependency override."""
    mock_stor = MagicMock()
    app.dependency_overrides[get_storage] = lambda: mock_stor
    try:
        yield mock_stor
    finally:
        app.dependency_overrides.pop(get_storage, None)


@pytest.fixture
def mock_ontology_service() -> Generator[MagicMock, None, None]:
    """Provide a MagicMock OntologyService as a dependency override."""
    mock_onto = MagicMock()
    app.dependency_overrides[get_ontology] = lambda: mock_onto
    try:
        yield mock_onto
    finally:
        app.dependency_overrides.pop(get_ontology, None)


@pytest.fixture
def mock_indexed_ontology_service() -> Generator[MagicMock, None, None]:
    """Provide a MagicMock IndexedOntologyService as a dependency override."""
    mock_idx = MagicMock()
    app.dependency_overrides[get_indexed_ontology] = lambda: mock_idx
    try:
        yield mock_idx
    finally:
        app.dependency_overrides.pop(get_indexed_ontology, None)


# ---------------------------------------------------------------------------
# POST /api/v1/projects — create project
# ---------------------------------------------------------------------------


class TestCreateProject:
    def test_create_project_success(
        self,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,
    ) -> None:
        """Creating a project returns 201."""
        client, _db = authed_client
        mock_project_service.create = AsyncMock(
            return_value=ProjectResponse(
                id=PROJECT_ID,
                name="New Project",
                description="Desc",
                is_public=True,
                owner_id="test-user-id",
                owner=None,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                member_count=1,
                source_file_path=None,
                ontology_iri=None,
                user_role="owner",
                is_superadmin=False,
                git_ontology_path=None,
                label_preferences=None,
                normalization_report=None,
            )
        )

        response = client.post(
            "/api/v1/projects",
            json={"name": "New Project", "description": "Desc", "is_public": True},
        )
        assert response.status_code == 201

    def test_create_project_missing_name_returns_422(
        self,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,  # noqa: ARG002
    ) -> None:
        """Missing name in request body returns 422."""
        client, _db = authed_client
        response = client.post("/api/v1/projects", json={"description": "No name"})
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/projects/{id} — get project
# ---------------------------------------------------------------------------


class TestGetProject:
    def test_get_project_success(
        self,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,
    ) -> None:
        """Getting a project by ID returns 200."""
        client, _db = authed_client
        mock_project_service.get = AsyncMock(
            return_value=ProjectResponse(
                id=PROJECT_ID,
                name="My Project",
                description="Desc",
                is_public=True,
                owner_id="test-user-id",
                owner=None,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                member_count=1,
                source_file_path=None,
                ontology_iri=None,
                user_role="owner",
                is_superadmin=False,
                git_ontology_path=None,
                label_preferences=None,
                normalization_report=None,
            )
        )

        response = client.get(f"/api/v1/projects/{PROJECT_ID}")
        assert response.status_code == 200

    def test_get_project_not_found(
        self,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,
    ) -> None:
        """Getting a nonexistent project returns 404."""
        from fastapi import HTTPException

        client, _db = authed_client
        mock_project_service.get = AsyncMock(
            side_effect=HTTPException(status_code=404, detail="Not found")
        )

        response = client.get(f"/api/v1/projects/{PROJECT_ID}")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /api/v1/projects/{id} — update project
# ---------------------------------------------------------------------------


class TestUpdateProject:
    def test_update_project_success(
        self,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,
        mock_storage_service: MagicMock,  # noqa: ARG002
    ) -> None:
        """Updating a project returns 200."""
        client, _db = authed_client
        project_resp = ProjectResponse(
            id=PROJECT_ID,
            name="Updated",
            description="New desc",
            is_public=True,
            owner_id="test-user-id",
            owner=None,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            member_count=1,
            source_file_path=None,
            ontology_iri=None,
            user_role="owner",
            is_superadmin=False,
            git_ontology_path=None,
            label_preferences=None,
            normalization_report=None,
        )
        mock_project_service.get = AsyncMock(return_value=project_resp)
        mock_project_service.update = AsyncMock(return_value=project_resp)

        response = client.patch(
            f"/api/v1/projects/{PROJECT_ID}",
            json={"name": "Updated"},
        )
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# DELETE /api/v1/projects/{id} — delete project
# ---------------------------------------------------------------------------


class TestDeleteProject:
    def test_delete_project_success(
        self,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,
    ) -> None:
        """Deleting a project returns 204."""
        client, _db = authed_client
        mock_project_service.get = AsyncMock(
            return_value=MagicMock(is_public=True, id=PROJECT_ID, updated_at=datetime.now(UTC))
        )
        mock_project_service.delete = AsyncMock(return_value=None)

        response = client.delete(f"/api/v1/projects/{PROJECT_ID}")
        assert response.status_code == 204

    def test_delete_project_not_found(
        self,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,
    ) -> None:
        """Deleting a nonexistent project returns 404."""
        from fastapi import HTTPException

        client, _db = authed_client
        mock_project_service.get = AsyncMock(
            side_effect=HTTPException(status_code=404, detail="Not found")
        )

        response = client.delete(f"/api/v1/projects/{PROJECT_ID}")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/v1/projects/{id}/branches — list branches
# ---------------------------------------------------------------------------


class TestListBranches:
    def test_list_branches_no_repo(
        self,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,
        mock_git_service: MagicMock,
    ) -> None:
        """When no repository exists, returns empty branch list."""
        client, _db = authed_client
        mock_project_service.get = AsyncMock(
            return_value=MagicMock(
                user_role="owner",
                is_superadmin=False,
            )
        )
        mock_project_service.get_branch_preference = AsyncMock(return_value=None)

        mock_git_service.repository_exists.return_value = False

        response = client.get(f"/api/v1/projects/{PROJECT_ID}/branches")
        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        assert data["current_branch"] == "main"


# ---------------------------------------------------------------------------
# POST /api/v1/projects/{id}/branches — create branch
# ---------------------------------------------------------------------------


class TestCreateBranch:
    def test_create_branch_no_repo_returns_404(
        self,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,
        mock_git_service: MagicMock,
    ) -> None:
        """Creating a branch when no repo exists returns 404."""
        client, _db = authed_client
        mock_project_service.get = AsyncMock(
            return_value=MagicMock(user_role="owner", is_superadmin=False)
        )

        mock_git_service.repository_exists.return_value = False

        response = client.post(
            f"/api/v1/projects/{PROJECT_ID}/branches",
            json={"name": "feature-x"},
        )
        assert response.status_code == 404

    def test_create_branch_viewer_forbidden(
        self,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,
        mock_git_service: MagicMock,  # noqa: ARG002
    ) -> None:
        """A viewer cannot create branches."""
        client, _db = authed_client
        mock_project_service.get = AsyncMock(
            return_value=MagicMock(user_role="viewer", is_superadmin=False)
        )

        response = client.post(
            f"/api/v1/projects/{PROJECT_ID}/branches",
            json={"name": "feature-x"},
        )
        assert response.status_code == 403


# ---------------------------------------------------------------------------
# GET /api/v1/projects/{id}/revisions — get revision history
# ---------------------------------------------------------------------------


class TestGetRevisionHistory:
    def test_revisions_no_repo_returns_empty(
        self,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,
        mock_git_service: MagicMock,
    ) -> None:
        """When no repository exists, returns empty revision history."""
        client, _db = authed_client
        mock_project_service.get = AsyncMock(return_value=MagicMock())

        mock_git_service.repository_exists.return_value = False

        response = client.get(f"/api/v1/projects/{PROJECT_ID}/revisions")
        assert response.status_code == 200
        data = response.json()
        assert data["commits"] == []
        assert data["total"] == 0

    def test_revisions_with_commits(
        self,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,
        mock_git_service: MagicMock,
    ) -> None:
        """Revision history returns commits when they exist."""
        client, _db = authed_client
        mock_project_service.get = AsyncMock(return_value=MagicMock())

        mock_commit = MagicMock()
        mock_commit.hash = "abc123"
        mock_commit.short_hash = "abc123"
        mock_commit.message = "Initial commit"
        mock_commit.author_name = "Test"
        mock_commit.author_email = "test@example.com"
        mock_commit.timestamp = "2025-01-01T00:00:00+00:00"
        mock_commit.is_merge = False
        mock_commit.merged_branch = None
        mock_commit.parent_hashes = []

        mock_git_service.repository_exists.return_value = True
        mock_git_service.get_history.return_value = [mock_commit]
        mock_git_service.list_branches.return_value = []

        response = client.get(f"/api/v1/projects/{PROJECT_ID}/revisions")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["commits"][0]["hash"] == "abc123"


# ---------------------------------------------------------------------------
# GET /api/v1/projects/{id}/ontology/search — search entities
# ---------------------------------------------------------------------------


class TestSearchEntities:
    def test_search_requires_query_param(
        self,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,  # noqa: ARG002
        mock_ontology_service: MagicMock,  # noqa: ARG002
        mock_git_service: MagicMock,  # noqa: ARG002
        mock_indexed_ontology_service: MagicMock,  # noqa: ARG002
    ) -> None:
        """Search without 'q' parameter returns 422."""
        client, _db = authed_client
        response = client.get(f"/api/v1/projects/{PROJECT_ID}/ontology/search")
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/projects/{id}/members — list members
# ---------------------------------------------------------------------------


class TestListMembers:
    def test_list_members_returns_200(
        self,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,
    ) -> None:
        """GET /api/v1/projects/{id}/members returns 200 with member list."""
        client, _db = authed_client

        user = CurrentUser(
            id="test-user-id",
            email="test@example.com",
            name="Test User",
            username="testuser",
            roles=["owner"],
        )

        async def _override_with_token() -> tuple[CurrentUser, str]:
            return user, "test-token"

        app.dependency_overrides[get_current_user_with_token] = _override_with_token
        try:
            member = MemberResponse(
                id=uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"),
                project_id=PROJECT_ID,
                user_id="test-user-id",
                role="owner",
                user=None,
                created_at=datetime.now(UTC),
            )
            mock_project_service.list_members = AsyncMock(
                return_value=MemberListResponse(items=[member], total=1)
            )

            response = client.get(f"/api/v1/projects/{PROJECT_ID}/members")
            assert response.status_code == 200
            data = response.json()
            assert data["total"] == 1
            assert len(data["items"]) == 1
        finally:
            app.dependency_overrides.pop(get_current_user_with_token, None)


# ---------------------------------------------------------------------------
# PUT /api/v1/projects/{id}/source — save source content
# ---------------------------------------------------------------------------


class TestSaveSourceContent:
    def test_save_source_viewer_forbidden(
        self,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,
        mock_storage_service: MagicMock,  # noqa: ARG002
        mock_ontology_service: MagicMock,  # noqa: ARG002
        mock_git_service: MagicMock,  # noqa: ARG002
    ) -> None:
        """A viewer cannot save source content."""
        client, _db = authed_client
        mock_project_service.get = AsyncMock(
            return_value=MagicMock(
                user_role="viewer",
                is_superadmin=False,
                source_file_path="ontology.ttl",
            )
        )

        response = client.put(
            f"/api/v1/projects/{PROJECT_ID}/source",
            json={"content": "@prefix : <http://ex.org/> .", "commit_message": "Update"},
        )
        assert response.status_code == 403

    def test_save_source_no_file_path_returns_400(
        self,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,
        mock_storage_service: MagicMock,  # noqa: ARG002
        mock_ontology_service: MagicMock,  # noqa: ARG002
        mock_git_service: MagicMock,  # noqa: ARG002
    ) -> None:
        """Saving source when project has no source_file_path returns 400."""
        client, _db = authed_client
        mock_project_service.get = AsyncMock(
            return_value=MagicMock(
                user_role="owner",
                is_superadmin=False,
                source_file_path=None,
            )
        )

        response = client.put(
            f"/api/v1/projects/{PROJECT_ID}/source",
            json={"content": "@prefix : <http://ex.org/> .", "commit_message": "Update"},
        )
        assert response.status_code == 400

    def test_save_source_invalid_turtle_returns_422(
        self,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,
        mock_storage_service: MagicMock,  # noqa: ARG002
        mock_ontology_service: MagicMock,  # noqa: ARG002
        mock_git_service: MagicMock,  # noqa: ARG002
    ) -> None:
        """Submitting invalid Turtle returns 422."""
        client, _db = authed_client
        mock_project_service.get = AsyncMock(
            return_value=MagicMock(
                user_role="owner",
                is_superadmin=False,
                source_file_path="ontology.ttl",
            )
        )

        response = client.put(
            f"/api/v1/projects/{PROJECT_ID}/source",
            json={"content": "THIS IS NOT VALID TURTLE {{{{", "commit_message": "Bad"},
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/projects/{id}/revisions/diff — revision diff
# ---------------------------------------------------------------------------


class TestRevisionDiff:
    def test_diff_no_repo_returns_404(
        self,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,
        mock_git_service: MagicMock,
    ) -> None:
        """Diff when no repository exists returns 404."""
        client, _db = authed_client
        mock_project_service.get = AsyncMock(return_value=MagicMock())

        mock_git_service.repository_exists.return_value = False

        response = client.get(
            f"/api/v1/projects/{PROJECT_ID}/revisions/diff",
            params={"from_version": "abc123"},
        )
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/v1/projects/{id}/revisions/file — file at revision
# ---------------------------------------------------------------------------


class TestGetFileAtRevision:
    def test_file_at_revision_no_repo_returns_404(
        self,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,
        mock_git_service: MagicMock,
    ) -> None:
        """File at revision when no repository exists returns 404."""
        client, _db = authed_client
        mock_project_service.get = AsyncMock(return_value=MagicMock(git_ontology_path=None))

        mock_git_service.repository_exists.return_value = False

        response = client.get(
            f"/api/v1/projects/{PROJECT_ID}/revisions/file",
            params={"version": "main"},
        )
        assert response.status_code == 404
