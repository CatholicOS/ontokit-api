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


# ---------------------------------------------------------------------------
# BareOntologyRepository: _resolve_ref edge cases
# ---------------------------------------------------------------------------


class TestResolveRef:
    def test_resolve_by_commit_hash(
        self,
        initialized_service: BareGitRepositoryService,
        project_id: uuid.UUID,
    ) -> None:
        """_resolve_ref can resolve a full commit hash."""
        repo = initialized_service.get_repository(project_id)
        history = repo.get_history()
        commit_hash = history[0].hash
        # Reading file by commit hash exercises _resolve_ref with a hash
        content = repo.read_file(commit_hash, "ontology.ttl")
        assert b"@prefix" in content

    def test_resolve_head(
        self,
        initialized_service: BareGitRepositoryService,
        project_id: uuid.UUID,
    ) -> None:
        """_resolve_ref resolves HEAD to the latest commit."""
        repo = initialized_service.get_repository(project_id)
        content = repo.read_file("HEAD", "ontology.ttl")
        assert b"@prefix" in content

    def test_resolve_unknown_ref_raises(
        self,
        initialized_service: BareGitRepositoryService,
        project_id: uuid.UUID,
    ) -> None:
        """_resolve_ref raises ValueError for unknown references."""
        repo = initialized_service.get_repository(project_id)
        with pytest.raises(ValueError, match="Cannot resolve reference"):
            repo._resolve_ref("nonexistent-ref-xyz")

    def test_resolve_partial_hash(
        self,
        initialized_service: BareGitRepositoryService,
        project_id: uuid.UUID,
    ) -> None:
        """_resolve_ref resolves partial commit hashes."""
        repo = initialized_service.get_repository(project_id)
        history = repo.get_history()
        full_hash = history[0].hash
        partial = full_hash[:8]
        commit = repo._resolve_ref(partial)
        assert str(commit.id) == full_hash


# ---------------------------------------------------------------------------
# BareOntologyRepository: merge_branch
# ---------------------------------------------------------------------------


class TestMergeBranch:
    def test_fast_forward_merge(
        self,
        initialized_service: BareGitRepositoryService,
        project_id: uuid.UUID,
    ) -> None:
        """merge_branch merges a branch with new commits into target."""
        initialized_service.create_branch(project_id, "feature", "main")
        initialized_service.commit_changes(
            project_id=project_id,
            ontology_content=b"@prefix : <http://example.org/> .\n:A a :B ; :p 1 .\n",
            filename="ontology.ttl",
            message="Feature commit",
            branch_name="feature",
        )
        repo = initialized_service.get_repository(project_id)
        result = repo.merge_branch("feature", "main")
        assert result.success is True
        assert result.merge_commit_hash is not None

    def test_merge_already_up_to_date(
        self,
        initialized_service: BareGitRepositoryService,
        project_id: uuid.UUID,
    ) -> None:
        """merge_branch returns 'Already up to date' when nothing to merge."""
        initialized_service.create_branch(project_id, "feature", "main")
        repo = initialized_service.get_repository(project_id)
        result = repo.merge_branch("feature", "main")
        assert result.success is True
        assert "Already up to date" in result.message

    def test_merge_source_not_found(
        self,
        initialized_service: BareGitRepositoryService,
        project_id: uuid.UUID,
    ) -> None:
        """merge_branch raises ValueError for missing source branch."""
        repo = initialized_service.get_repository(project_id)
        with pytest.raises(ValueError, match="Source branch not found"):
            repo.merge_branch("nonexistent", "main")

    def test_merge_target_not_found(
        self,
        initialized_service: BareGitRepositoryService,
        project_id: uuid.UUID,
    ) -> None:
        """merge_branch raises ValueError for missing target branch."""
        repo = initialized_service.get_repository(project_id)
        with pytest.raises(ValueError, match="Target branch not found"):
            repo.merge_branch("main", "nonexistent")

    def test_merge_with_custom_message(
        self,
        initialized_service: BareGitRepositoryService,
        project_id: uuid.UUID,
    ) -> None:
        """merge_branch uses a custom merge commit message."""
        initialized_service.create_branch(project_id, "feature2", "main")
        initialized_service.commit_changes(
            project_id=project_id,
            ontology_content=b"@prefix : <http://example.org/> .\n:X a :Y .\n",
            filename="ontology.ttl",
            message="Feature2 work",
            branch_name="feature2",
        )
        repo = initialized_service.get_repository(project_id)
        result = repo.merge_branch(
            "feature2",
            "main",
            message="Custom merge message",
            author_name="Merger",
            author_email="merger@test.com",
        )
        assert result.success is True
        # Verify the merge commit message
        history = repo.get_history(branch="main", all_branches=False)
        assert history[0].message.strip() == "Custom merge message"
        assert history[0].is_merge is True


# ---------------------------------------------------------------------------
# BareOntologyRepository: list_files
# ---------------------------------------------------------------------------


class TestListFiles:
    def test_list_files_returns_ontology(
        self,
        initialized_service: BareGitRepositoryService,
        project_id: uuid.UUID,
    ) -> None:
        """list_files includes the ontology file."""
        repo = initialized_service.get_repository(project_id)
        files = repo.list_files("main")
        assert "ontology.ttl" in files

    def test_list_files_empty_repo(
        self,
        service: BareGitRepositoryService,
    ) -> None:
        """list_files returns empty list for uninitialized repo."""
        pid = uuid.UUID("11111111-2222-3333-4444-555555555555")
        repo = service.get_repository(pid)
        files = repo.list_files()
        assert files == []


# ---------------------------------------------------------------------------
# BareOntologyRepository: get_current_branch / get_default_branch
# ---------------------------------------------------------------------------


class TestBranchDetection:
    def test_get_current_branch_returns_main(
        self,
        initialized_service: BareGitRepositoryService,
        project_id: uuid.UUID,
    ) -> None:
        """get_current_branch returns 'main' for a fresh repo."""
        repo = initialized_service.get_repository(project_id)
        assert repo.get_current_branch() == "main"

    def test_get_default_branch_returns_main(
        self,
        initialized_service: BareGitRepositoryService,
        project_id: uuid.UUID,
    ) -> None:
        """get_default_branch returns 'main'."""
        repo = initialized_service.get_repository(project_id)
        assert repo.get_default_branch() == "main"


# ---------------------------------------------------------------------------
# BareOntologyRepository: get_branch_commit_hash
# ---------------------------------------------------------------------------


class TestGetBranchCommitHash:
    def test_get_branch_commit_hash(
        self,
        initialized_service: BareGitRepositoryService,
        project_id: uuid.UUID,
    ) -> None:
        """get_branch_commit_hash returns a 40-char hash."""
        repo = initialized_service.get_repository(project_id)
        commit_hash = repo.get_branch_commit_hash("main")
        assert len(commit_hash) == 40

    def test_get_branch_commit_hash_matches_history(
        self,
        initialized_service: BareGitRepositoryService,
        project_id: uuid.UUID,
    ) -> None:
        """get_branch_commit_hash matches the latest commit in history."""
        repo = initialized_service.get_repository(project_id)
        commit_hash = repo.get_branch_commit_hash("main")
        history = repo.get_history(branch="main", all_branches=False)
        assert history[0].hash == commit_hash


# ---------------------------------------------------------------------------
# BareOntologyRepository: get_history (all_branches=False)
# ---------------------------------------------------------------------------


class TestGetHistoryBranchSpecific:
    def test_get_history_single_branch(
        self,
        initialized_service: BareGitRepositoryService,
        project_id: uuid.UUID,
    ) -> None:
        """get_history with all_branches=False returns only branch commits."""
        initialized_service.create_branch(project_id, "other", "main")
        initialized_service.commit_changes(
            project_id=project_id,
            ontology_content=b"other content",
            filename="ontology.ttl",
            message="Other branch commit",
            branch_name="other",
        )
        repo = initialized_service.get_repository(project_id)
        main_history = repo.get_history(branch="main", all_branches=False)
        # Main should only have initial commit
        assert len(main_history) == 1
        assert "Initial import" in main_history[0].message

    def test_get_history_default_branch_no_branch_arg(
        self,
        initialized_service: BareGitRepositoryService,
        project_id: uuid.UUID,
    ) -> None:
        """get_history with all_branches=False and no branch uses HEAD."""
        repo = initialized_service.get_repository(project_id)
        history = repo.get_history(all_branches=False)
        assert len(history) >= 1


# ---------------------------------------------------------------------------
# BareOntologyRepository: list_branches with ahead/behind
# ---------------------------------------------------------------------------


class TestListBranchesAheadBehind:
    def test_list_branches_shows_ahead_behind(
        self,
        initialized_service: BareGitRepositoryService,
        project_id: uuid.UUID,
    ) -> None:
        """list_branches calculates commits_ahead for non-default branches."""
        initialized_service.create_branch(project_id, "dev", "main")
        initialized_service.commit_changes(
            project_id=project_id,
            ontology_content=b"dev content",
            filename="ontology.ttl",
            message="Dev commit",
            branch_name="dev",
        )
        repo = initialized_service.get_repository(project_id)
        branches = repo.list_branches()
        dev_branch = next(b for b in branches if b.name == "dev")
        assert dev_branch.commits_ahead == 1
        assert dev_branch.commits_behind == 0

    def test_list_branches_default_is_flagged(
        self,
        initialized_service: BareGitRepositoryService,
        project_id: uuid.UUID,
    ) -> None:
        """list_branches marks the default branch with is_default=True."""
        repo = initialized_service.get_repository(project_id)
        branches = repo.list_branches()
        main_branch = next(b for b in branches if b.name == "main")
        assert main_branch.is_default is True
        assert main_branch.commits_ahead == 0
        assert main_branch.commits_behind == 0


# ---------------------------------------------------------------------------
# BareOntologyRepository: delete_branch edge cases
# ---------------------------------------------------------------------------


class TestDeleteBranchEdgeCases:
    def test_delete_nonexistent_branch_raises(
        self,
        initialized_service: BareGitRepositoryService,
        project_id: uuid.UUID,
    ) -> None:
        """delete_branch raises ValueError for a branch that does not exist."""
        repo = initialized_service.get_repository(project_id)
        with pytest.raises(ValueError, match="Branch not found"):
            repo.delete_branch("nonexistent")

    def test_delete_unmerged_branch_raises(
        self,
        initialized_service: BareGitRepositoryService,
        project_id: uuid.UUID,
    ) -> None:
        """delete_branch raises when branch has unmerged commits."""
        initialized_service.create_branch(project_id, "unmerged", "main")
        initialized_service.commit_changes(
            project_id=project_id,
            ontology_content=b"unmerged content",
            filename="ontology.ttl",
            message="Unmerged work",
            branch_name="unmerged",
        )
        repo = initialized_service.get_repository(project_id)
        with pytest.raises(ValueError, match="unmerged commits"):
            repo.delete_branch("unmerged")

    def test_force_delete_unmerged_branch(
        self,
        initialized_service: BareGitRepositoryService,
        project_id: uuid.UUID,
    ) -> None:
        """delete_branch with force=True deletes unmerged branch."""
        initialized_service.create_branch(project_id, "unmerged2", "main")
        initialized_service.commit_changes(
            project_id=project_id,
            ontology_content=b"unmerged2 content",
            filename="ontology.ttl",
            message="Unmerged2 work",
            branch_name="unmerged2",
        )
        repo = initialized_service.get_repository(project_id)
        result = repo.delete_branch("unmerged2", force=True)
        assert result is True
        branches = repo.list_branches()
        names = [b.name for b in branches]
        assert "unmerged2" not in names


# ---------------------------------------------------------------------------
# BareOntologyRepository: get_commits_between
# ---------------------------------------------------------------------------


class TestGetCommitsBetween:
    def test_get_commits_between_two_refs(
        self,
        initialized_service: BareGitRepositoryService,
        project_id: uuid.UUID,
    ) -> None:
        """get_commits_between returns commits in the range."""
        history_before = initialized_service.get_history(project_id)
        first_hash = history_before[0].hash

        initialized_service.commit_changes(
            project_id=project_id,
            ontology_content=b"second content",
            filename="ontology.ttl",
            message="Second commit",
        )
        initialized_service.commit_changes(
            project_id=project_id,
            ontology_content=b"third content",
            filename="ontology.ttl",
            message="Third commit",
        )

        repo = initialized_service.get_repository(project_id)
        commits = repo.get_commits_between(first_hash, "main")
        assert len(commits) == 2
        messages = [c.message.strip() for c in commits]
        assert "Third commit" in messages
        assert "Second commit" in messages

    def test_get_commits_between_same_ref(
        self,
        initialized_service: BareGitRepositoryService,
        project_id: uuid.UUID,
    ) -> None:
        """get_commits_between returns empty list when refs are the same."""
        repo = initialized_service.get_repository(project_id)
        commits = repo.get_commits_between("main", "main")
        assert commits == []


# ---------------------------------------------------------------------------
# BareOntologyRepository: remote operations
# ---------------------------------------------------------------------------


class TestRemoteOperations:
    def test_add_remote(
        self,
        initialized_service: BareGitRepositoryService,
        project_id: uuid.UUID,
    ) -> None:
        """add_remote adds a remote and list_remotes shows it."""
        repo = initialized_service.get_repository(project_id)
        result = repo.add_remote("origin", "https://example.com/repo.git")
        assert result is True
        remotes = repo.list_remotes()
        assert len(remotes) == 1
        assert remotes[0]["name"] == "origin"
        assert remotes[0]["url"] == "https://example.com/repo.git"

    def test_add_remote_overwrites_existing(
        self,
        initialized_service: BareGitRepositoryService,
        project_id: uuid.UUID,
    ) -> None:
        """add_remote updates the URL if remote already exists."""
        repo = initialized_service.get_repository(project_id)
        repo.add_remote("origin", "https://old.com/repo.git")
        repo.add_remote("origin", "https://new.com/repo.git")
        remotes = repo.list_remotes()
        origin = next(r for r in remotes if r["name"] == "origin")
        assert origin["url"] == "https://new.com/repo.git"

    def test_remove_remote(
        self,
        initialized_service: BareGitRepositoryService,
        project_id: uuid.UUID,
    ) -> None:
        """remove_remote removes a remote."""
        repo = initialized_service.get_repository(project_id)
        repo.add_remote("origin", "https://example.com/repo.git")
        result = repo.remove_remote("origin")
        assert result is True
        remotes = repo.list_remotes()
        assert len(remotes) == 0

    def test_remove_nonexistent_remote(
        self,
        initialized_service: BareGitRepositoryService,
        project_id: uuid.UUID,
    ) -> None:
        """remove_remote returns False for nonexistent remote."""
        repo = initialized_service.get_repository(project_id)
        result = repo.remove_remote("nonexistent")
        assert result is False

    def test_list_remotes_empty(
        self,
        initialized_service: BareGitRepositoryService,
        project_id: uuid.UUID,
    ) -> None:
        """list_remotes returns empty list when no remotes configured."""
        repo = initialized_service.get_repository(project_id)
        remotes = repo.list_remotes()
        assert remotes == []

    def test_push_no_remote_returns_false(
        self,
        initialized_service: BareGitRepositoryService,
        project_id: uuid.UUID,
    ) -> None:
        """push returns False when no remote is configured."""
        repo = initialized_service.get_repository(project_id)
        result = repo.push("origin", "main")
        assert result is False

    def test_fetch_no_remote_returns_false(
        self,
        initialized_service: BareGitRepositoryService,
        project_id: uuid.UUID,
    ) -> None:
        """fetch returns False when no remote is configured."""
        repo = initialized_service.get_repository(project_id)
        result = repo.fetch("origin")
        assert result is False


# ---------------------------------------------------------------------------
# BareOntologyRepository: nested file paths
# ---------------------------------------------------------------------------


class TestNestedFilePaths:
    def test_write_and_read_nested_file(
        self,
        initialized_service: BareGitRepositoryService,
        project_id: uuid.UUID,
    ) -> None:
        """write_file handles nested paths like 'dir/file.ttl'."""
        repo = initialized_service.get_repository(project_id)
        repo.write_file(
            branch_name="main",
            filepath="subdir/nested.ttl",
            content=b"nested content",
            message="Add nested file",
        )
        content = repo.read_file("main", "subdir/nested.ttl")
        assert content == b"nested content"

    def test_list_files_includes_nested(
        self,
        initialized_service: BareGitRepositoryService,
        project_id: uuid.UUID,
    ) -> None:
        """list_files includes files in subdirectories."""
        repo = initialized_service.get_repository(project_id)
        repo.write_file(
            branch_name="main",
            filepath="a/b/deep.ttl",
            content=b"deep content",
            message="Add deep file",
        )
        files = repo.list_files("main")
        assert "a/b/deep.ttl" in files


# ---------------------------------------------------------------------------
# BareOntologyRepository: read_file error case
# ---------------------------------------------------------------------------


class TestReadFileErrors:
    def test_read_nonexistent_file_raises(
        self,
        initialized_service: BareGitRepositoryService,
        project_id: uuid.UUID,
    ) -> None:
        """read_file raises KeyError for files that don't exist."""
        repo = initialized_service.get_repository(project_id)
        with pytest.raises(KeyError):
            repo.read_file("main", "nonexistent.ttl")


# ---------------------------------------------------------------------------
# BareGitRepositoryService: switch_branch
# ---------------------------------------------------------------------------


class TestSwitchBranch:
    def test_switch_branch_returns_info(
        self,
        initialized_service: BareGitRepositoryService,
        project_id: uuid.UUID,
    ) -> None:
        """switch_branch returns BranchInfo for an existing branch."""
        from ontokit.git.bare_repository import BranchInfo

        info = initialized_service.switch_branch(project_id, "main")
        assert isinstance(info, BranchInfo)
        assert info.name == "main"

    def test_switch_branch_nonexistent_raises(
        self,
        initialized_service: BareGitRepositoryService,
        project_id: uuid.UUID,
    ) -> None:
        """switch_branch raises KeyError for a missing branch."""
        with pytest.raises(KeyError, match="Branch not found"):
            initialized_service.switch_branch(project_id, "no-such-branch")


# ---------------------------------------------------------------------------
# BareGitRepositoryService: service-layer delegations
# ---------------------------------------------------------------------------


class TestServiceDelegations:
    def test_merge_branch_via_service(
        self,
        initialized_service: BareGitRepositoryService,
        project_id: uuid.UUID,
    ) -> None:
        """merge_branch service method delegates to repo."""
        initialized_service.create_branch(project_id, "feat", "main")
        initialized_service.commit_changes(
            project_id=project_id,
            ontology_content=b"feat content",
            filename="ontology.ttl",
            message="Feat commit",
            branch_name="feat",
        )
        result = initialized_service.merge_branch(project_id, "feat", "main")
        assert result.success is True

    def test_get_commits_between_via_service(
        self,
        initialized_service: BareGitRepositoryService,
        project_id: uuid.UUID,
    ) -> None:
        """get_commits_between service method delegates to repo."""
        history = initialized_service.get_history(project_id)
        first_hash = history[0].hash
        initialized_service.commit_changes(
            project_id=project_id,
            ontology_content=b"new content",
            filename="ontology.ttl",
            message="New commit",
        )
        commits = initialized_service.get_commits_between(project_id, first_hash, "main")
        assert len(commits) == 1

    def test_setup_remote_via_service(
        self,
        initialized_service: BareGitRepositoryService,
        project_id: uuid.UUID,
    ) -> None:
        """setup_remote service method delegates to repo.add_remote."""
        result = initialized_service.setup_remote(
            project_id, "https://example.com/repo.git", "origin"
        )
        assert result is True

    def test_push_branch_via_service(
        self,
        initialized_service: BareGitRepositoryService,
        project_id: uuid.UUID,
    ) -> None:
        """push_branch returns False when no remote configured."""
        result = initialized_service.push_branch(project_id, "main")
        assert result is False

    def test_fetch_remote_via_service(
        self,
        initialized_service: BareGitRepositoryService,
        project_id: uuid.UUID,
    ) -> None:
        """fetch_remote returns False when no remote configured."""
        result = initialized_service.fetch_remote(project_id)
        assert result is False

    def test_list_remotes_via_service(
        self,
        initialized_service: BareGitRepositoryService,
        project_id: uuid.UUID,
    ) -> None:
        """list_remotes service method delegates to repo."""
        remotes = initialized_service.list_remotes(project_id)
        assert remotes == []

    def test_clone_from_github_existing_raises(
        self,
        initialized_service: BareGitRepositoryService,
        project_id: uuid.UUID,
    ) -> None:
        """clone_from_github raises ValueError if repo already exists."""
        with pytest.raises(ValueError, match="Repository already exists"):
            initialized_service.clone_from_github(project_id, "https://github.com/test/repo.git")


# ---------------------------------------------------------------------------
# Module-level functions: _find_ontology_iri, serialize_deterministic, semantic_diff
# ---------------------------------------------------------------------------


class TestModuleFunctions:
    def test_find_ontology_iri(self) -> None:
        """_find_ontology_iri finds the ontology IRI in a graph."""
        from rdflib import OWL, RDF, Graph, URIRef

        from ontokit.git.bare_repository import _find_ontology_iri

        g = Graph()
        iri = URIRef("http://example.org/ontology")
        g.add((iri, RDF.type, OWL.Ontology))
        assert _find_ontology_iri(g) == "http://example.org/ontology"

    def test_find_ontology_iri_none(self) -> None:
        """_find_ontology_iri returns None when no ontology declared."""
        from rdflib import Graph

        from ontokit.git.bare_repository import _find_ontology_iri

        g = Graph()
        assert _find_ontology_iri(g) is None

    def test_serialize_deterministic(self) -> None:
        """serialize_deterministic produces consistent Turtle output."""
        from rdflib import OWL, RDF, Graph, URIRef

        from ontokit.git.bare_repository import serialize_deterministic

        g = Graph()
        iri = URIRef("http://example.org/ontology")
        g.add((iri, RDF.type, OWL.Ontology))
        result = serialize_deterministic(g)
        assert isinstance(result, str)
        assert "Ontology" in result

    def test_semantic_diff(self) -> None:
        """semantic_diff computes added and removed triples."""
        from rdflib import Graph, Literal, URIRef

        from ontokit.git.bare_repository import semantic_diff

        old_g = Graph()
        new_g = Graph()
        s = URIRef("http://example.org/A")
        p = URIRef("http://example.org/p")
        old_g.add((s, p, Literal("old")))
        new_g.add((s, p, Literal("new")))

        result = semantic_diff(old_g, new_g)
        assert result["added_count"] == 1
        assert result["removed_count"] == 1
        assert "added" in result
        assert "removed" in result


# ---------------------------------------------------------------------------
# get_bare_git_service factory
# ---------------------------------------------------------------------------


class TestGetBareGitService:
    def test_factory_returns_service(self) -> None:
        """get_bare_git_service returns a BareGitRepositoryService."""
        from ontokit.git.bare_repository import get_bare_git_service

        svc = get_bare_git_service()
        assert isinstance(svc, BareGitRepositoryService)
