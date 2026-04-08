"""Tests targeting UNCOVERED paths in ontokit/api/routes/projects.py."""

from __future__ import annotations

import uuid
from collections.abc import Generator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from fastapi.testclient import TestClient

from ontokit.api.routes.projects import (
    get_git,
    get_ontology,
    get_service,
    get_storage,
)
from ontokit.main import app
from ontokit.schemas.project import ProjectResponse
from ontokit.services.project_service import ProjectService

PROJECT_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")

VALID_TURTLE = """\
@prefix : <http://example.org/ontology#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

<http://example.org/ontology> rdf:type owl:Ontology .
:Person rdf:type owl:Class .
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _project_response(**overrides: Any) -> ProjectResponse:
    defaults: dict[str, Any] = {
        "id": PROJECT_ID,
        "name": "Test Project",
        "description": "desc",
        "is_public": True,
        "owner_id": "test-user-id",
        "owner": None,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
        "member_count": 1,
        "source_file_path": "ontology.ttl",
        "ontology_iri": None,
        "user_role": "owner",
        "is_superadmin": False,
        "git_ontology_path": None,
        "label_preferences": None,
        "normalization_report": None,
    }
    defaults.update(overrides)
    return ProjectResponse(**defaults)


def _make_branch(
    name: str = "feature-x",
    *,
    is_current: bool = False,
    is_default: bool = False,
) -> MagicMock:
    b = MagicMock()
    b.name = name
    b.is_current = is_current
    b.is_default = is_default
    b.commit_hash = "abc123"
    b.commit_message = "some commit"
    b.commit_date = datetime.now(UTC)
    b.commits_ahead = 0
    b.commits_behind = 0
    b.remote_commits_ahead = 0
    b.remote_commits_behind = 0
    return b


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_project_service() -> Generator[AsyncMock, None, None]:
    mock_svc = AsyncMock(spec=ProjectService)
    app.dependency_overrides[get_service] = lambda: mock_svc
    try:
        yield mock_svc
    finally:
        app.dependency_overrides.pop(get_service, None)


@pytest.fixture
def mock_git_service() -> Generator[MagicMock, None, None]:
    mock_git = MagicMock()
    app.dependency_overrides[get_git] = lambda: mock_git
    try:
        yield mock_git
    finally:
        app.dependency_overrides.pop(get_git, None)


@pytest.fixture
def mock_storage_service() -> Generator[MagicMock, None, None]:
    mock_stor = MagicMock()
    mock_stor.upload_file = AsyncMock(return_value="ontokit/test-object")
    app.dependency_overrides[get_storage] = lambda: mock_stor
    try:
        yield mock_stor
    finally:
        app.dependency_overrides.pop(get_storage, None)


@pytest.fixture
def mock_ontology_service() -> Generator[MagicMock, None, None]:
    mock_onto = MagicMock()
    mock_onto.is_loaded = MagicMock(return_value=False)
    mock_onto.load_from_git = AsyncMock()
    mock_onto._get_graph = AsyncMock(return_value=None)
    mock_onto.unload = MagicMock()
    app.dependency_overrides[get_ontology] = lambda: mock_onto
    try:
        yield mock_onto
    finally:
        app.dependency_overrides.pop(get_ontology, None)


# ---------------------------------------------------------------------------
# list_branches — full data path (lines 927-1001)
# ---------------------------------------------------------------------------


class TestListBranchesFullPath:
    """Cover the path where branches exist with GitHub integration and metadata."""

    def test_list_branches_with_branches_and_metadata(
        self,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,
        mock_git_service: MagicMock,
    ) -> None:
        """When branches exist, returns branch info with permissions."""
        client, mock_db = authed_client

        mock_project_service.get = AsyncMock(
            return_value=_project_response(user_role="admin", is_superadmin=False)
        )
        mock_project_service.get_branch_preference = AsyncMock(return_value="feature-x")

        mock_git_service.repository_exists.return_value = True
        mock_git_service.list_branches.return_value = [
            _make_branch("main", is_default=True, is_current=True),
            _make_branch("feature-x"),
        ]
        mock_git_service.get_default_branch.return_value = "main"

        # DB execute calls: GitHubIntegration, BranchMetadata, PullRequest
        gh_result = MagicMock()
        gh_result.scalar_one_or_none.return_value = None  # no GitHub integration

        meta_scalars = MagicMock()
        meta_scalars.all.return_value = []  # no metadata rows
        meta_result = MagicMock()
        meta_result.scalars.return_value = meta_scalars

        pr_result = MagicMock()
        pr_result.all.return_value = []  # no open PRs

        mock_db.execute = AsyncMock(side_effect=[gh_result, meta_result, pr_result])

        response = client.get(f"/api/v1/projects/{PROJECT_ID}/branches")
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 2
        assert data["current_branch"] == "main"
        assert data["default_branch"] == "main"
        assert data["preferred_branch"] == "feature-x"

    def test_list_branches_with_github_integration(
        self,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,
        mock_git_service: MagicMock,
    ) -> None:
        """When GitHub integration exists, response includes remote metadata."""
        client, mock_db = authed_client

        mock_project_service.get = AsyncMock(return_value=_project_response(user_role="owner"))
        mock_project_service.get_branch_preference = AsyncMock(return_value=None)

        mock_git_service.repository_exists.return_value = True
        mock_git_service.list_branches.return_value = [
            _make_branch("main", is_default=True, is_current=True),
        ]
        mock_git_service.get_default_branch.return_value = "main"

        # GitHub integration present
        gh_integration = MagicMock()
        gh_integration.last_sync_at = datetime(2025, 1, 1, tzinfo=UTC)
        gh_integration.sync_status = "synced"
        gh_result = MagicMock()
        gh_result.scalar_one_or_none.return_value = gh_integration

        meta_scalars = MagicMock()
        meta_scalars.all.return_value = []
        meta_result = MagicMock()
        meta_result.scalars.return_value = meta_scalars

        pr_result = MagicMock()
        pr_result.all.return_value = []

        mock_db.execute = AsyncMock(side_effect=[gh_result, meta_result, pr_result])

        response = client.get(f"/api/v1/projects/{PROJECT_ID}/branches")
        assert response.status_code == 200
        data = response.json()
        assert data["has_github_remote"] is True
        assert data["sync_status"] == "synced"

    def test_list_branches_editor_own_branch_can_delete(
        self,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,
        mock_git_service: MagicMock,
    ) -> None:
        """Editor can delete their own branch (not default, no open PR)."""
        client, mock_db = authed_client

        mock_project_service.get = AsyncMock(
            return_value=_project_response(user_role="editor", is_superadmin=False)
        )
        mock_project_service.get_branch_preference = AsyncMock(return_value=None)

        mock_git_service.repository_exists.return_value = True
        mock_git_service.list_branches.return_value = [
            _make_branch("main", is_default=True, is_current=True),
            _make_branch("my-branch"),
        ]
        mock_git_service.get_default_branch.return_value = "main"

        gh_result = MagicMock()
        gh_result.scalar_one_or_none.return_value = None

        # BranchMetadata for "my-branch" created by test-user-id
        meta_obj = MagicMock()
        meta_obj.branch_name = "my-branch"
        meta_obj.created_by_id = "test-user-id"
        meta_obj.created_by_name = "Test User"
        meta_scalars = MagicMock()
        meta_scalars.all.return_value = [meta_obj]
        meta_result = MagicMock()
        meta_result.scalars.return_value = meta_scalars

        pr_result = MagicMock()
        pr_result.all.return_value = []

        mock_db.execute = AsyncMock(side_effect=[gh_result, meta_result, pr_result])

        response = client.get(f"/api/v1/projects/{PROJECT_ID}/branches")
        assert response.status_code == 200
        items = response.json()["items"]
        my_branch = next(b for b in items if b["name"] == "my-branch")
        assert my_branch["has_delete_permission"] is True
        assert my_branch["can_delete"] is True

    def test_list_branches_open_pr_blocks_delete(
        self,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,
        mock_git_service: MagicMock,
    ) -> None:
        """Branch with open PR shows can_delete=False even for admin."""
        client, mock_db = authed_client

        mock_project_service.get = AsyncMock(return_value=_project_response(user_role="admin"))
        mock_project_service.get_branch_preference = AsyncMock(return_value=None)

        mock_git_service.repository_exists.return_value = True
        mock_git_service.list_branches.return_value = [
            _make_branch("main", is_default=True),
            _make_branch("pr-branch"),
        ]
        mock_git_service.get_default_branch.return_value = "main"

        gh_result = MagicMock()
        gh_result.scalar_one_or_none.return_value = None

        meta_scalars = MagicMock()
        meta_scalars.all.return_value = []
        meta_result = MagicMock()
        meta_result.scalars.return_value = meta_scalars

        # "pr-branch" has an open PR
        pr_result = MagicMock()
        pr_result.all.return_value = [("pr-branch",)]

        mock_db.execute = AsyncMock(side_effect=[gh_result, meta_result, pr_result])

        response = client.get(f"/api/v1/projects/{PROJECT_ID}/branches")
        assert response.status_code == 200
        items = response.json()["items"]
        pr_branch = next(b for b in items if b["name"] == "pr-branch")
        assert pr_branch["has_open_pr"] is True
        assert pr_branch["can_delete"] is False


# ---------------------------------------------------------------------------
# create_branch — success path (lines 1051-1079)
# ---------------------------------------------------------------------------


class TestCreateBranchSuccess:
    def test_create_branch_success(
        self,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,
        mock_git_service: MagicMock,
    ) -> None:
        """Successfully creating a branch returns 201."""
        client, mock_db = authed_client

        mock_project_service.get = AsyncMock(return_value=_project_response(user_role="editor"))

        mock_git_service.repository_exists.return_value = True

        result_branch = _make_branch("feature-new")
        mock_git_service.create_branch.return_value = result_branch

        # db.add is sync lambda by default; replace with Mock to allow commit
        mock_db.add = Mock()
        mock_db.commit = AsyncMock()

        response = client.post(
            f"/api/v1/projects/{PROJECT_ID}/branches",
            json={"name": "feature-new"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "feature-new"
        assert data["can_delete"] is True
        assert data["has_open_pr"] is False
        mock_db.add.assert_called_once()

    def test_create_branch_git_error_returns_400(
        self,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,
        mock_git_service: MagicMock,
    ) -> None:
        """Git error during branch creation returns 400."""
        client, _db = authed_client

        mock_project_service.get = AsyncMock(return_value=_project_response(user_role="owner"))
        mock_git_service.repository_exists.return_value = True
        mock_git_service.create_branch.side_effect = RuntimeError("ref already exists")

        response = client.post(
            f"/api/v1/projects/{PROJECT_ID}/branches",
            json={"name": "duplicate"},
        )
        assert response.status_code == 400
        assert "Could not create branch" in response.json()["detail"]


# ---------------------------------------------------------------------------
# delete_branch (lines 1162-1235)
# ---------------------------------------------------------------------------


class TestDeleteBranch:
    def test_delete_branch_success_admin(
        self,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,
        mock_git_service: MagicMock,
    ) -> None:
        """Admin can delete any branch; metadata is cleaned up."""
        client, mock_db = authed_client

        mock_project_service.get = AsyncMock(return_value=_project_response(user_role="admin"))
        mock_git_service.repository_exists.return_value = True
        mock_git_service.delete_branch.return_value = None

        # No open PRs
        mock_db.scalar = AsyncMock(return_value=0)
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()

        response = client.delete(f"/api/v1/projects/{PROJECT_ID}/branches/feature-x")
        assert response.status_code == 204

    def test_delete_branch_open_pr_returns_409(
        self,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,
        mock_git_service: MagicMock,
    ) -> None:
        """Cannot delete a branch with an open pull request."""
        client, mock_db = authed_client

        mock_project_service.get = AsyncMock(return_value=_project_response(user_role="admin"))
        mock_git_service.repository_exists.return_value = True

        # open_pr_count = 1
        mock_db.scalar = AsyncMock(return_value=1)

        response = client.delete(f"/api/v1/projects/{PROJECT_ID}/branches/feature-x")
        assert response.status_code == 409
        assert "open pull request" in response.json()["detail"]

    def test_delete_branch_editor_not_author_returns_403(
        self,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,
        mock_git_service: MagicMock,
    ) -> None:
        """Editor cannot delete a branch created by someone else."""
        client, mock_db = authed_client

        mock_project_service.get = AsyncMock(
            return_value=_project_response(user_role="editor", is_superadmin=False)
        )
        mock_git_service.repository_exists.return_value = True

        # No open PRs
        meta = MagicMock()
        meta.created_by_id = "another-user-id"
        mock_db.scalar = AsyncMock(side_effect=[0, meta])

        response = client.delete(f"/api/v1/projects/{PROJECT_ID}/branches/feature-x")
        assert response.status_code == 403
        assert "only delete branches you created" in response.json()["detail"]

    def test_delete_branch_editor_no_metadata_returns_403(
        self,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,
        mock_git_service: MagicMock,
    ) -> None:
        """Editor cannot delete a branch with no metadata (unknown creator)."""
        client, mock_db = authed_client

        mock_project_service.get = AsyncMock(
            return_value=_project_response(user_role="editor", is_superadmin=False)
        )
        mock_git_service.repository_exists.return_value = True

        # No open PRs, no metadata
        mock_db.scalar = AsyncMock(side_effect=[0, None])

        response = client.delete(f"/api/v1/projects/{PROJECT_ID}/branches/feature-x")
        assert response.status_code == 403

    def test_delete_branch_git_not_found_returns_404(
        self,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,
        mock_git_service: MagicMock,
    ) -> None:
        """Branch not found in git returns 404."""
        client, mock_db = authed_client

        mock_project_service.get = AsyncMock(return_value=_project_response(user_role="admin"))
        mock_git_service.repository_exists.return_value = True
        mock_git_service.delete_branch.side_effect = KeyError("feature-x")

        mock_db.scalar = AsyncMock(return_value=0)

        response = client.delete(f"/api/v1/projects/{PROJECT_ID}/branches/feature-x")
        assert response.status_code == 404
        assert "Branch not found" in response.json()["detail"]

    def test_delete_branch_viewer_returns_403(
        self,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,
        mock_git_service: MagicMock,  # noqa: ARG002
    ) -> None:
        """Viewer cannot delete branches."""
        client, _db = authed_client

        mock_project_service.get = AsyncMock(return_value=_project_response(user_role="viewer"))

        response = client.delete(f"/api/v1/projects/{PROJECT_ID}/branches/feature-x")
        assert response.status_code == 403

    def test_delete_branch_no_repo_returns_404(
        self,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,
        mock_git_service: MagicMock,
    ) -> None:
        """No repository returns 404."""
        client, _db = authed_client

        mock_project_service.get = AsyncMock(return_value=_project_response(user_role="admin"))
        mock_git_service.repository_exists.return_value = False

        response = client.delete(f"/api/v1/projects/{PROJECT_ID}/branches/feature-x")
        assert response.status_code == 404

    def test_delete_branch_value_error_returns_400(
        self,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,
        mock_git_service: MagicMock,
    ) -> None:
        """ValueError from git (e.g. deleting default branch) returns 400."""
        client, mock_db = authed_client

        mock_project_service.get = AsyncMock(return_value=_project_response(user_role="owner"))
        mock_git_service.repository_exists.return_value = True
        mock_git_service.delete_branch.side_effect = ValueError("Cannot delete default branch")

        mock_db.scalar = AsyncMock(return_value=0)

        response = client.delete(f"/api/v1/projects/{PROJECT_ID}/branches/main")
        assert response.status_code == 400


# ---------------------------------------------------------------------------
# save_source_content — success path (lines 1287-1415)
# ---------------------------------------------------------------------------


class TestSaveSourceContentSuccess:
    @patch("ontokit.api.routes.projects.get_arq_pool", new_callable=AsyncMock)
    def test_save_source_success(
        self,
        mock_get_arq_pool: AsyncMock,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,
        mock_storage_service: MagicMock,  # noqa: ARG002
        mock_ontology_service: MagicMock,  # noqa: ARG002
        mock_git_service: MagicMock,
    ) -> None:
        """Happy path: valid turtle is committed and response returned."""
        client, mock_db = authed_client

        mock_project_service.get = AsyncMock(
            return_value=_project_response(
                user_role="editor",
                source_file_path="ontology.ttl",
                git_ontology_path=None,
            )
        )

        mock_git_service.repository_exists.return_value = True
        mock_git_service.get_default_branch.return_value = "main"

        commit_info = MagicMock()
        commit_info.hash = "deadbeef"
        commit_info.message = "Update ontology"
        mock_git_service.commit_changes.return_value = commit_info

        # ARQ pool mock
        mock_pool = AsyncMock()
        mock_pool.enqueue_job = AsyncMock()
        mock_get_arq_pool.return_value = mock_pool

        response = client.put(
            f"/api/v1/projects/{PROJECT_ID}/source",
            json={"content": VALID_TURTLE, "commit_message": "Update ontology"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["commit_hash"] == "deadbeef"
        assert data["branch"] == "main"

    @patch("ontokit.api.routes.projects.get_arq_pool", new_callable=AsyncMock)
    def test_save_source_with_branch_param(
        self,
        mock_get_arq_pool: AsyncMock,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,
        mock_storage_service: MagicMock,  # noqa: ARG002
        mock_ontology_service: MagicMock,  # noqa: ARG002
        mock_git_service: MagicMock,
    ) -> None:
        """Save to a specific branch via query param."""
        client, _db = authed_client

        mock_project_service.get = AsyncMock(
            return_value=_project_response(
                user_role="owner",
                source_file_path="ontology.ttl",
            )
        )

        mock_git_service.repository_exists.return_value = True

        commit_info = MagicMock()
        commit_info.hash = "cafebabe"
        commit_info.message = "Branch save"
        mock_git_service.commit_changes.return_value = commit_info

        mock_get_arq_pool.return_value = None  # no ARQ pool

        response = client.put(
            f"/api/v1/projects/{PROJECT_ID}/source?branch=feature-x",
            json={"content": VALID_TURTLE, "commit_message": "Branch save"},
        )
        assert response.status_code == 200
        assert response.json()["branch"] == "feature-x"

    @patch("ontokit.api.routes.projects.get_arq_pool", new_callable=AsyncMock)
    def test_save_source_no_repo_returns_404(
        self,
        mock_get_arq_pool: AsyncMock,  # noqa: ARG002
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,
        mock_storage_service: MagicMock,  # noqa: ARG002
        mock_ontology_service: MagicMock,  # noqa: ARG002
        mock_git_service: MagicMock,
    ) -> None:
        """Valid turtle but no git repo returns 404."""
        client, _db = authed_client

        mock_project_service.get = AsyncMock(
            return_value=_project_response(
                user_role="editor",
                source_file_path="ontology.ttl",
            )
        )
        mock_git_service.repository_exists.return_value = False

        response = client.put(
            f"/api/v1/projects/{PROJECT_ID}/source",
            json={"content": VALID_TURTLE, "commit_message": "Save"},
        )
        assert response.status_code == 404

    @patch("ontokit.api.routes.projects.get_arq_pool", new_callable=AsyncMock)
    def test_save_source_commit_failure_returns_500(
        self,
        mock_get_arq_pool: AsyncMock,  # noqa: ARG002
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,
        mock_storage_service: MagicMock,  # noqa: ARG002
        mock_ontology_service: MagicMock,  # noqa: ARG002
        mock_git_service: MagicMock,
    ) -> None:
        """Git commit failure returns 500."""
        client, _db = authed_client

        mock_project_service.get = AsyncMock(
            return_value=_project_response(
                user_role="editor",
                source_file_path="ontology.ttl",
            )
        )
        mock_git_service.repository_exists.return_value = True
        mock_git_service.get_default_branch.return_value = "main"
        mock_git_service.commit_changes.side_effect = RuntimeError("disk full")

        response = client.put(
            f"/api/v1/projects/{PROJECT_ID}/source",
            json={"content": VALID_TURTLE, "commit_message": "Save"},
        )
        assert response.status_code == 500
        assert "Failed to commit" in response.json()["detail"]

    @patch("ontokit.api.routes.projects.get_arq_pool", new_callable=AsyncMock)
    def test_save_source_storage_error_returns_503(
        self,
        mock_get_arq_pool: AsyncMock,  # noqa: ARG002
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,
        mock_storage_service: MagicMock,
        mock_ontology_service: MagicMock,  # noqa: ARG002
        mock_git_service: MagicMock,
    ) -> None:
        """Storage upload failure returns 503."""
        from ontokit.services.storage import StorageError

        client, _db = authed_client

        mock_project_service.get = AsyncMock(
            return_value=_project_response(
                user_role="editor",
                source_file_path="ontology.ttl",
            )
        )
        mock_git_service.repository_exists.return_value = True
        mock_git_service.get_default_branch.return_value = "main"
        mock_storage_service.upload_file = AsyncMock(side_effect=StorageError("bucket gone"))

        response = client.put(
            f"/api/v1/projects/{PROJECT_ID}/source",
            json={"content": VALID_TURTLE, "commit_message": "Save"},
        )
        assert response.status_code == 503


# ---------------------------------------------------------------------------
# trigger_ontology_reindex (lines 1418+)
# ---------------------------------------------------------------------------


class TestTriggerOntologyReindex:
    @patch("ontokit.api.routes.projects.get_arq_pool", new_callable=AsyncMock)
    def test_reindex_success(
        self,
        mock_get_arq_pool: AsyncMock,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,
        mock_git_service: MagicMock,
    ) -> None:
        """Admin triggers reindex, gets 202."""
        client, _db = authed_client

        mock_project_service.get = AsyncMock(return_value=_project_response(user_role="admin"))
        mock_git_service.get_default_branch.return_value = "main"

        mock_pool = AsyncMock()
        mock_pool.enqueue_job = AsyncMock()
        mock_get_arq_pool.return_value = mock_pool

        response = client.post(f"/api/v1/projects/{PROJECT_ID}/ontology/reindex")
        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "accepted"
        assert data["branch"] == "main"

    @patch("ontokit.api.routes.projects.get_arq_pool", new_callable=AsyncMock)
    def test_reindex_editor_forbidden(
        self,
        mock_get_arq_pool: AsyncMock,  # noqa: ARG002
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,
        mock_git_service: MagicMock,  # noqa: ARG002
    ) -> None:
        """Editor cannot trigger reindex."""
        client, _db = authed_client

        mock_project_service.get = AsyncMock(return_value=_project_response(user_role="editor"))

        response = client.post(f"/api/v1/projects/{PROJECT_ID}/ontology/reindex")
        assert response.status_code == 403

    @patch("ontokit.api.routes.projects.get_arq_pool", new_callable=AsyncMock)
    def test_reindex_no_pool_returns_503(
        self,
        mock_get_arq_pool: AsyncMock,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,
        mock_git_service: MagicMock,
    ) -> None:
        """No ARQ pool returns 503."""
        client, _db = authed_client

        mock_project_service.get = AsyncMock(return_value=_project_response(user_role="owner"))
        mock_git_service.get_default_branch.return_value = "main"
        mock_get_arq_pool.return_value = None

        response = client.post(f"/api/v1/projects/{PROJECT_ID}/ontology/reindex")
        assert response.status_code == 503

    @patch("ontokit.api.routes.projects.get_arq_pool", new_callable=AsyncMock)
    def test_reindex_with_branch_param(
        self,
        mock_get_arq_pool: AsyncMock,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,
        mock_git_service: MagicMock,  # noqa: ARG002
    ) -> None:
        """Reindex with explicit branch param."""
        client, _db = authed_client

        mock_project_service.get = AsyncMock(return_value=_project_response(user_role="owner"))

        mock_pool = AsyncMock()
        mock_pool.enqueue_job = AsyncMock()
        mock_get_arq_pool.return_value = mock_pool

        response = client.post(f"/api/v1/projects/{PROJECT_ID}/ontology/reindex?branch=dev")
        assert response.status_code == 202
        assert response.json()["branch"] == "dev"


# ---------------------------------------------------------------------------
# update_project — sitemap visibility change paths (lines 373-378)
# ---------------------------------------------------------------------------


class TestUpdateProjectSitemap:
    def test_update_project_became_public(
        self,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,
        mock_storage_service: MagicMock,  # noqa: ARG002
    ) -> None:
        """Project becoming public triggers sitemap add."""
        client, _db = authed_client

        # Old state: private
        mock_project_service.get = AsyncMock(return_value=_project_response(is_public=False))
        # New state: public
        mock_project_service.update = AsyncMock(return_value=_project_response(is_public=True))

        response = client.patch(
            f"/api/v1/projects/{PROJECT_ID}",
            json={"is_public": True},
        )
        assert response.status_code == 200

    def test_update_project_became_private(
        self,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,
        mock_storage_service: MagicMock,  # noqa: ARG002
    ) -> None:
        """Project becoming private triggers sitemap remove."""
        client, _db = authed_client

        # Old state: public
        mock_project_service.get = AsyncMock(return_value=_project_response(is_public=True))
        # New state: private
        mock_project_service.update = AsyncMock(return_value=_project_response(is_public=False))

        response = client.patch(
            f"/api/v1/projects/{PROJECT_ID}",
            json={"is_public": False},
        )
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# create_project_from_github (lines 262-332)
# ---------------------------------------------------------------------------


class TestCreateProjectFromGitHub:
    @patch("ontokit.api.routes.projects.get_arq_pool", new_callable=AsyncMock)
    @patch("ontokit.api.routes.projects.get_github_service")
    @patch("ontokit.api.routes.projects._resolve_github_pat", new_callable=AsyncMock)
    def test_create_from_github_ttl_file(
        self,
        mock_resolve_pat: AsyncMock,
        mock_get_github: MagicMock,
        mock_get_arq_pool: AsyncMock,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,
        mock_storage_service: MagicMock,  # noqa: ARG002
    ) -> None:
        """Import a .ttl file from GitHub succeeds."""
        client, _db = authed_client

        mock_resolve_pat.return_value = "ghp_fake_token"

        mock_github = AsyncMock()
        mock_github.get_repo_info = AsyncMock(return_value={"default_branch": "main"})
        mock_github.get_file_content = AsyncMock(return_value=VALID_TURTLE.encode())
        mock_get_github.return_value = mock_github

        from ontokit.schemas.project import ProjectImportResponse

        mock_project_service.create_from_github = AsyncMock(
            return_value=ProjectImportResponse(
                id=PROJECT_ID,
                name="GitHub Project",
                description="From GitHub",
                is_public=True,
                owner_id="test-user-id",
                owner=None,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                member_count=1,
                source_file_path="ontology.ttl",
                file_path="ontology.ttl",
                ontology_iri=None,
                user_role="owner",
                is_superadmin=False,
                git_ontology_path="ontology.ttl",
                label_preferences=None,
                normalization_report=None,
            )
        )

        mock_get_arq_pool.return_value = None  # no pool

        response = client.post(
            "/api/v1/projects/from-github",
            json={
                "repo_owner": "test-org",
                "repo_name": "test-repo",
                "ontology_file_path": "ontology.ttl",
                "is_public": True,
            },
        )
        assert response.status_code == 201

    @patch("ontokit.api.routes.projects.get_github_service")
    @patch("ontokit.api.routes.projects._resolve_github_pat", new_callable=AsyncMock)
    def test_create_from_github_non_ttl_missing_turtle_path(
        self,
        mock_resolve_pat: AsyncMock,
        mock_get_github: MagicMock,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,  # noqa: ARG002
        mock_storage_service: MagicMock,  # noqa: ARG002
    ) -> None:
        """Non-.ttl source without turtle_file_path returns 400."""
        client, _db = authed_client

        mock_resolve_pat.return_value = "ghp_fake_token"

        mock_github = AsyncMock()
        mock_github.get_repo_info = AsyncMock(return_value={"default_branch": "main"})
        mock_github.get_file_content = AsyncMock(return_value=b"<rdf>...</rdf>")
        mock_get_github.return_value = mock_github

        response = client.post(
            "/api/v1/projects/from-github",
            json={
                "repo_owner": "test-org",
                "repo_name": "test-repo",
                "ontology_file_path": "ontology.owl",
                "is_public": True,
            },
        )
        assert response.status_code == 400
        assert "turtle_file_path is required" in response.json()["detail"]

    @patch("ontokit.api.routes.projects.get_github_service")
    @patch("ontokit.api.routes.projects._resolve_github_pat", new_callable=AsyncMock)
    def test_create_from_github_invalid_turtle_file_path(
        self,
        mock_resolve_pat: AsyncMock,
        mock_get_github: MagicMock,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,  # noqa: ARG002
        mock_storage_service: MagicMock,  # noqa: ARG002
    ) -> None:
        """turtle_file_path not ending in .ttl returns 400."""
        client, _db = authed_client

        mock_resolve_pat.return_value = "ghp_fake_token"

        mock_github = AsyncMock()
        mock_github.get_repo_info = AsyncMock(return_value={"default_branch": "main"})
        mock_github.get_file_content = AsyncMock(return_value=b"<rdf>...</rdf>")
        mock_get_github.return_value = mock_github

        response = client.post(
            "/api/v1/projects/from-github",
            json={
                "repo_owner": "test-org",
                "repo_name": "test-repo",
                "ontology_file_path": "ontology.owl",
                "turtle_file_path": "output.owl",
                "is_public": True,
            },
        )
        assert response.status_code == 400
        assert "must end with .ttl" in response.json()["detail"]

    @patch("ontokit.api.routes.projects.get_github_service")
    @patch("ontokit.api.routes.projects._resolve_github_pat", new_callable=AsyncMock)
    def test_create_from_github_download_failure(
        self,
        mock_resolve_pat: AsyncMock,
        mock_get_github: MagicMock,
        authed_client: tuple[TestClient, AsyncMock],
        mock_project_service: AsyncMock,  # noqa: ARG002
        mock_storage_service: MagicMock,  # noqa: ARG002
    ) -> None:
        """Failed file download from GitHub returns 400."""
        client, _db = authed_client

        mock_resolve_pat.return_value = "ghp_fake_token"

        mock_github = AsyncMock()
        mock_github.get_repo_info = AsyncMock(return_value={"default_branch": "main"})
        mock_github.get_file_content = AsyncMock(side_effect=RuntimeError("404 Not Found"))
        mock_get_github.return_value = mock_github

        response = client.post(
            "/api/v1/projects/from-github",
            json={
                "repo_owner": "test-org",
                "repo_name": "test-repo",
                "ontology_file_path": "ontology.ttl",
                "is_public": True,
            },
        )
        assert response.status_code == 400
        assert "Failed to download" in response.json()["detail"]


# ---------------------------------------------------------------------------
# scan_github_repo_files / _resolve_github_pat — no token path (lines 208-220)
# ---------------------------------------------------------------------------


class TestScanGitHubRepoFiles:
    def test_scan_no_github_token_returns_400(
        self,
        authed_client: tuple[TestClient, AsyncMock],
    ) -> None:
        """No stored GitHub token returns 400."""
        client, mock_db = authed_client

        # db.execute returns a result whose scalar_one_or_none is None
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=result_mock)

        response = client.get(
            "/api/v1/projects/github/scan-files",
            params={"owner": "test-org", "repo": "test-repo"},
        )
        assert response.status_code == 400
        assert "No GitHub token found" in response.json()["detail"]
