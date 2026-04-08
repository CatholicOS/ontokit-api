"""Tests for BareGitRepositoryService wrapper (ontokit/git/bare_repository.py)."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from ontokit.git.bare_repository import BareGitRepositoryService, BareOntologyRepository


@pytest.fixture
def service(tmp_path: Path) -> BareGitRepositoryService:
    """Create a BareGitRepositoryService with a temp base path."""
    return BareGitRepositoryService(base_path=str(tmp_path))


@pytest.fixture
def project_id() -> uuid.UUID:
    return uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")


@pytest.fixture
def initialized_service(
    service: BareGitRepositoryService,
    project_id: uuid.UUID,
) -> BareGitRepositoryService:
    """Return a service with an initialized repo containing one commit."""
    service.initialize_repository(
        project_id=project_id,
        ontology_content=b"@prefix : <http://example.org/> .\n:A a :B .\n",
        filename="ontology.ttl",
        author_name="Test User",
        author_email="test@example.com",
        project_name="Test Ontology",
    )
    return service


# ---------------------------------------------------------------------------
# initialize_repository
# ---------------------------------------------------------------------------


class TestInitializeRepository:
    def test_initialize_creates_bare_repo(
        self,
        service: BareGitRepositoryService,
        project_id: uuid.UUID,
    ) -> None:
        """initialize_repository creates a bare repo and returns a CommitInfo."""
        commit_info = service.initialize_repository(
            project_id=project_id,
            ontology_content=b"content",
            filename="ontology.ttl",
            author_name="Alice",
            author_email="alice@example.com",
            project_name="My Ontology",
        )
        assert commit_info.message == "Initial import of My Ontology"
        assert commit_info.author_name == "Alice"
        assert len(commit_info.hash) == 40

    def test_initialize_default_project_name(
        self,
        service: BareGitRepositoryService,
        project_id: uuid.UUID,
    ) -> None:
        """initialize_repository uses 'ontology' when no project_name given."""
        commit_info = service.initialize_repository(
            project_id=project_id,
            ontology_content=b"data",
            filename="ontology.ttl",
        )
        assert "ontology" in commit_info.message


# ---------------------------------------------------------------------------
# get_repository
# ---------------------------------------------------------------------------


class TestGetRepository:
    def test_get_repository_returns_bare_repo(
        self,
        initialized_service: BareGitRepositoryService,
        project_id: uuid.UUID,
    ) -> None:
        """get_repository returns a BareOntologyRepository instance."""
        repo = initialized_service.get_repository(project_id)
        assert isinstance(repo, BareOntologyRepository)


# ---------------------------------------------------------------------------
# repository_exists
# ---------------------------------------------------------------------------


class TestRepositoryExists:
    def test_exists_true_after_init(
        self,
        initialized_service: BareGitRepositoryService,
        project_id: uuid.UUID,
    ) -> None:
        """repository_exists returns True after initialization."""
        assert initialized_service.repository_exists(project_id) is True

    def test_exists_false_before_init(
        self,
        service: BareGitRepositoryService,
        project_id: uuid.UUID,
    ) -> None:
        """repository_exists returns False before initialization."""
        assert service.repository_exists(project_id) is False


# ---------------------------------------------------------------------------
# delete_repository
# ---------------------------------------------------------------------------


class TestDeleteRepository:
    def test_delete_repository_removes_directory(
        self,
        initialized_service: BareGitRepositoryService,
        project_id: uuid.UUID,
    ) -> None:
        """delete_repository removes the repo directory."""
        assert initialized_service.repository_exists(project_id) is True
        initialized_service.delete_repository(project_id)
        assert initialized_service.repository_exists(project_id) is False

    def test_delete_nonexistent_repo_is_noop(
        self,
        service: BareGitRepositoryService,
        project_id: uuid.UUID,
    ) -> None:
        """Deleting a nonexistent repo does not raise."""
        service.delete_repository(project_id)  # should not raise


# ---------------------------------------------------------------------------
# commit_changes
# ---------------------------------------------------------------------------


class TestCommitChanges:
    def test_commit_changes_to_default_branch(
        self,
        initialized_service: BareGitRepositoryService,
        project_id: uuid.UUID,
    ) -> None:
        """commit_changes writes to the default branch when no branch specified."""
        commit = initialized_service.commit_changes(
            project_id=project_id,
            ontology_content=b"updated content",
            filename="ontology.ttl",
            message="Update ontology",
            author_name="Bob",
            author_email="bob@example.com",
        )
        assert commit.message == "Update ontology"

        # Verify content was updated
        content = initialized_service.get_file_at_version(project_id, "ontology.ttl", "main")
        assert content == "updated content"

    def test_commit_changes_to_specific_branch(
        self,
        initialized_service: BareGitRepositoryService,
        project_id: uuid.UUID,
    ) -> None:
        """commit_changes writes to a specific branch."""
        initialized_service.create_branch(project_id, "feature", "main")
        commit = initialized_service.commit_changes(
            project_id=project_id,
            ontology_content=b"feature content",
            filename="ontology.ttl",
            message="Feature work",
            branch_name="feature",
        )
        assert commit.message == "Feature work"

        content = initialized_service.get_file_at_version(project_id, "ontology.ttl", "feature")
        assert content == "feature content"


# ---------------------------------------------------------------------------
# get_file
# ---------------------------------------------------------------------------


class TestGetFile:
    def test_get_file_at_version(
        self,
        initialized_service: BareGitRepositoryService,
        project_id: uuid.UUID,
    ) -> None:
        """get_file_at_version returns file content as string."""
        content = initialized_service.get_file_at_version(project_id, "ontology.ttl", "main")
        assert "@prefix" in content

    def test_get_file_from_branch(
        self,
        initialized_service: BareGitRepositoryService,
        project_id: uuid.UUID,
    ) -> None:
        """get_file_from_branch returns file content as bytes."""
        content = initialized_service.get_file_from_branch(project_id, "main", "ontology.ttl")
        assert isinstance(content, bytes)
        assert b"@prefix" in content


# ---------------------------------------------------------------------------
# get_history
# ---------------------------------------------------------------------------


class TestGetHistory:
    def test_get_history_returns_commits(
        self,
        initialized_service: BareGitRepositoryService,
        project_id: uuid.UUID,
    ) -> None:
        """get_history returns at least the initial commit."""
        history = initialized_service.get_history(project_id, limit=10)
        assert len(history) >= 1
        assert "Initial import" in history[0].message

    def test_get_history_newest_first(
        self,
        initialized_service: BareGitRepositoryService,
        project_id: uuid.UUID,
    ) -> None:
        """get_history returns commits ordered newest-first."""
        # Create additional commits so we have multiple entries
        initialized_service.commit_changes(
            project_id=project_id,
            ontology_content=b"@prefix : <http://example.org/> .\n:A a :B ; :p 1 .\n",
            filename="ontology.ttl",
            message="Second commit",
            author_name="Test User",
            author_email="test@example.com",
        )
        initialized_service.commit_changes(
            project_id=project_id,
            ontology_content=b"@prefix : <http://example.org/> .\n:A a :B ; :p 2 .\n",
            filename="ontology.ttl",
            message="Third commit",
            author_name="Test User",
            author_email="test@example.com",
        )

        history = initialized_service.get_history(project_id, limit=10)
        assert len(history) >= 3
        # Newest commit first
        assert "Third commit" in history[0].message
        assert "Second commit" in history[1].message
        assert "Initial import" in history[2].message
        # Timestamps are newest-first
        assert history[0].timestamp >= history[1].timestamp
        assert history[1].timestamp >= history[2].timestamp


# ---------------------------------------------------------------------------
# list_branches
# ---------------------------------------------------------------------------


class TestListBranches:
    def test_list_branches_includes_main(
        self,
        initialized_service: BareGitRepositoryService,
        project_id: uuid.UUID,
    ) -> None:
        """list_branches includes main after initialization."""
        branches = initialized_service.list_branches(project_id)
        names = [b.name for b in branches]
        assert "main" in names


# ---------------------------------------------------------------------------
# create_branch
# ---------------------------------------------------------------------------


class TestCreateBranch:
    def test_create_branch_from_main(
        self,
        initialized_service: BareGitRepositoryService,
        project_id: uuid.UUID,
    ) -> None:
        """create_branch creates a new branch from main."""
        info = initialized_service.create_branch(project_id, "dev", "main")
        assert info.name == "dev"
        assert info.commit_hash is not None

        branches = initialized_service.list_branches(project_id)
        names = [b.name for b in branches]
        assert "dev" in names


# ---------------------------------------------------------------------------
# delete_branch
# ---------------------------------------------------------------------------


class TestDeleteBranch:
    def test_delete_branch_success(
        self,
        initialized_service: BareGitRepositoryService,
        project_id: uuid.UUID,
    ) -> None:
        """delete_branch removes a branch."""
        initialized_service.create_branch(project_id, "to-delete", "main")
        result = initialized_service.delete_branch(project_id, "to-delete")
        assert result is True

        branches = initialized_service.list_branches(project_id)
        names = [b.name for b in branches]
        assert "to-delete" not in names

    def test_delete_default_branch_raises(
        self,
        initialized_service: BareGitRepositoryService,
        project_id: uuid.UUID,
    ) -> None:
        """Deleting the default branch raises ValueError."""
        with pytest.raises(ValueError, match="Cannot delete"):
            initialized_service.delete_branch(project_id, "main")


# ---------------------------------------------------------------------------
# get_default_branch / get_current_branch
# ---------------------------------------------------------------------------


class TestDefaultAndCurrentBranch:
    def test_get_default_branch(
        self,
        initialized_service: BareGitRepositoryService,
        project_id: uuid.UUID,
    ) -> None:
        """get_default_branch returns 'main'."""
        assert initialized_service.get_default_branch(project_id) == "main"

    def test_get_current_branch(
        self,
        initialized_service: BareGitRepositoryService,
        project_id: uuid.UUID,
    ) -> None:
        """get_current_branch returns a branch name."""
        current = initialized_service.get_current_branch(project_id)
        assert current == "main"


# ---------------------------------------------------------------------------
# diff_versions
# ---------------------------------------------------------------------------


class TestDiffVersions:
    def test_diff_between_two_commits(
        self,
        initialized_service: BareGitRepositoryService,
        project_id: uuid.UUID,
    ) -> None:
        """diff_versions returns changes between two commits."""
        history_before = initialized_service.get_history(project_id)
        first_hash = history_before[0].hash

        initialized_service.commit_changes(
            project_id=project_id,
            ontology_content=b"changed content",
            filename="ontology.ttl",
            message="Change",
        )

        history_after = initialized_service.get_history(project_id)
        second_hash = history_after[0].hash

        diff = initialized_service.diff_versions(project_id, first_hash, second_hash)
        assert diff.files_changed >= 1
        assert diff.from_version == first_hash
        assert diff.to_version == second_hash
