"""Tests for BareOntologyRepository git operations."""

from __future__ import annotations

from pathlib import Path

import pytest

from ontokit.git.bare_repository import BareOntologyRepository


class TestWriteAndReadFile:
    """Tests for write_file() and read_file() round-trip."""

    def test_write_then_read_returns_same_content(
        self, bare_git_repo: BareOntologyRepository
    ) -> None:
        """write_file followed by read_file returns identical bytes."""
        content = b"@prefix : <http://example.org/> .\n:A a :B .\n"
        bare_git_repo.write_file(
            branch_name="main",
            filepath="new_file.ttl",
            content=content,
            message="Add new file",
            author_name="Tester",
            author_email="tester@test.com",
        )
        result = bare_git_repo.read_file("main", "new_file.ttl")
        assert result == content

    def test_overwrite_existing_file(self, bare_git_repo: BareOntologyRepository) -> None:
        """Overwriting an existing file updates its content."""
        new_content = b"# updated content\n"
        bare_git_repo.write_file(
            branch_name="main",
            filepath="ontology.ttl",
            content=new_content,
            message="Update ontology",
        )
        result = bare_git_repo.read_file("main", "ontology.ttl")
        assert result == new_content

    def test_read_initial_commit_file(
        self, bare_git_repo: BareOntologyRepository, sample_ontology_turtle: str
    ) -> None:
        """The fixture's initial commit file is readable."""
        result = bare_git_repo.read_file("main", "ontology.ttl")
        assert result == sample_ontology_turtle.encode()


class TestHistory:
    """Tests for commit history tracking."""

    def test_write_creates_history_entry(self, bare_git_repo: BareOntologyRepository) -> None:
        """A write_file call appears in get_history."""
        history = bare_git_repo.get_history(branch="main", all_branches=False)
        assert len(history) >= 1
        assert history[0].message == "Initial commit"

    def test_multiple_commits_create_ordered_history(
        self, bare_git_repo: BareOntologyRepository
    ) -> None:
        """Multiple commits appear in reverse-chronological order."""
        bare_git_repo.write_file(
            branch_name="main",
            filepath="ontology.ttl",
            content=b"v2",
            message="Second commit",
        )
        bare_git_repo.write_file(
            branch_name="main",
            filepath="ontology.ttl",
            content=b"v3",
            message="Third commit",
        )
        history = bare_git_repo.get_history(branch="main", all_branches=False)
        assert len(history) == 3
        assert history[0].message == "Third commit"
        assert history[1].message == "Second commit"
        assert history[2].message == "Initial commit"

    def test_commit_info_has_author(self, bare_git_repo: BareOntologyRepository) -> None:
        """CommitInfo records the author name and email."""
        history = bare_git_repo.get_history(branch="main", all_branches=False)
        assert history[0].author_name == "Test User"
        assert history[0].author_email == "test@example.com"


class TestBranches:
    """Tests for branch operations."""

    def test_create_branch_from_main(self, bare_git_repo: BareOntologyRepository) -> None:
        """create_branch creates a new branch pointing at the same commit."""
        main_hash = bare_git_repo.get_branch_commit_hash("main")
        info = bare_git_repo.create_branch("feature-1", from_ref="main")
        assert info.name == "feature-1"
        assert info.commit_hash == main_hash

    def test_list_branches_includes_new_branch(self, bare_git_repo: BareOntologyRepository) -> None:
        """list_branches returns all branches including newly created ones."""
        bare_git_repo.create_branch("dev", from_ref="main")
        names = {b.name for b in bare_git_repo.list_branches()}
        assert "main" in names
        assert "dev" in names

    def test_delete_branch(self, bare_git_repo: BareOntologyRepository) -> None:
        """delete_branch removes a merged branch."""
        bare_git_repo.create_branch("to-delete", from_ref="main")
        assert bare_git_repo.delete_branch("to-delete") is True
        names = {b.name for b in bare_git_repo.list_branches()}
        assert "to-delete" not in names

    def test_delete_default_branch_raises(self, bare_git_repo: BareOntologyRepository) -> None:
        """Deleting the default branch raises ValueError."""
        with pytest.raises(ValueError, match="Cannot delete the default branch"):
            bare_git_repo.delete_branch("main")

    def test_delete_nonexistent_branch_raises(self, bare_git_repo: BareOntologyRepository) -> None:
        """Deleting a branch that does not exist raises ValueError."""
        with pytest.raises(ValueError, match="Branch not found"):
            bare_git_repo.delete_branch("no-such-branch")

    def test_delete_unmerged_branch_without_force_raises(
        self, bare_git_repo: BareOntologyRepository
    ) -> None:
        """Deleting an unmerged branch without force raises ValueError."""
        bare_git_repo.create_branch("unmerged", from_ref="main")
        bare_git_repo.write_file(
            branch_name="unmerged",
            filepath="extra.ttl",
            content=b"data",
            message="Unmerged work",
        )
        with pytest.raises(ValueError, match="unmerged commits"):
            bare_git_repo.delete_branch("unmerged")

    def test_delete_unmerged_branch_with_force(self, bare_git_repo: BareOntologyRepository) -> None:
        """Force-deleting an unmerged branch succeeds."""
        bare_git_repo.create_branch("unmerged", from_ref="main")
        bare_git_repo.write_file(
            branch_name="unmerged",
            filepath="extra.ttl",
            content=b"data",
            message="Unmerged work",
        )
        assert bare_git_repo.delete_branch("unmerged", force=True) is True

    def test_get_branch_commit_hash(self, bare_git_repo: BareOntologyRepository) -> None:
        """get_branch_commit_hash returns a valid hex string."""
        commit_hash = bare_git_repo.get_branch_commit_hash("main")
        assert len(commit_hash) == 40
        int(commit_hash, 16)  # valid hex


class TestDiff:
    """Tests for diff operations."""

    def test_diff_between_commits(self, bare_git_repo: BareOntologyRepository) -> None:
        """diff_versions returns changes between two commits."""
        history_before = bare_git_repo.get_history(branch="main", all_branches=False)
        first_hash = history_before[0].hash

        bare_git_repo.write_file(
            branch_name="main",
            filepath="ontology.ttl",
            content=b"# changed\n",
            message="Change content",
        )
        history_after = bare_git_repo.get_history(branch="main", all_branches=False)
        second_hash = history_after[0].hash

        diff = bare_git_repo.diff_versions(first_hash, second_hash)
        assert diff.files_changed >= 1
        assert diff.from_version == first_hash
        assert diff.to_version == second_hash


class TestInitialization:
    """Tests for repository initialization."""

    def test_is_initialized_true(self, bare_git_repo: BareOntologyRepository) -> None:
        """is_initialized is True for an existing repo."""
        assert bare_git_repo.is_initialized is True

    def test_is_initialized_false_for_missing_path(self, tmp_path: Path) -> None:
        """is_initialized is False when the path does not exist."""
        repo = BareOntologyRepository(tmp_path / "nonexistent.git")
        assert repo.is_initialized is False

    def test_repo_property_auto_initializes(self, tmp_path: Path) -> None:
        """Accessing .repo on a new path auto-creates a bare repository."""
        repo_path = tmp_path / "auto-init.git"
        repo = BareOntologyRepository(repo_path)
        _ = repo.repo  # triggers auto-init
        assert repo_path.exists()
        assert (repo_path / "HEAD").exists()


class TestWriteToBranch:
    """Tests for writing to non-main branches."""

    def test_write_to_feature_branch(self, bare_git_repo: BareOntologyRepository) -> None:
        """Writing to a feature branch does not affect main."""
        bare_git_repo.create_branch("feature", from_ref="main")
        bare_git_repo.write_file(
            branch_name="feature",
            filepath="feature_file.ttl",
            content=b"feature data",
            message="Feature commit",
        )
        # Feature branch has the file
        result = bare_git_repo.read_file("feature", "feature_file.ttl")
        assert result == b"feature data"

        # Main branch does not have the file
        with pytest.raises(KeyError):
            bare_git_repo.read_file("main", "feature_file.ttl")


class TestReadNonexistent:
    """Tests for reading files that do not exist."""

    def test_read_missing_file_raises(self, bare_git_repo: BareOntologyRepository) -> None:
        """read_file raises KeyError for a file not in the tree."""
        with pytest.raises(KeyError):
            bare_git_repo.read_file("main", "does_not_exist.ttl")


class TestMerge:
    """Tests for merge operations."""

    def test_fast_forward_merge(self, bare_git_repo: BareOntologyRepository) -> None:
        """Merging a branch with new commits into main succeeds."""
        bare_git_repo.create_branch("ff-branch", from_ref="main")
        bare_git_repo.write_file(
            branch_name="ff-branch",
            filepath="ontology.ttl",
            content=b"merged content",
            message="Branch commit",
        )
        result = bare_git_repo.merge_branch(
            source="ff-branch",
            target="main",
            author_name="Merger",
            author_email="merger@test.com",
        )
        assert result.success is True
        assert result.merge_commit_hash is not None

        # Main now has the merged content
        content = bare_git_repo.read_file("main", "ontology.ttl")
        assert content == b"merged content"

    def test_merge_already_up_to_date(self, bare_git_repo: BareOntologyRepository) -> None:
        """Merging a branch that is behind target returns already up to date."""
        bare_git_repo.create_branch("old-branch", from_ref="main")
        # main advances
        bare_git_repo.write_file(
            branch_name="main",
            filepath="ontology.ttl",
            content=b"advanced main",
            message="Advance main",
        )
        result = bare_git_repo.merge_branch(source="old-branch", target="main")
        assert result.success is True
        assert "Already up to date" in result.message


class TestNestedFiles:
    """Tests for nested file paths."""

    def test_write_and_read_nested_file(self, bare_git_repo: BareOntologyRepository) -> None:
        """Files at nested paths (subdir/file.ttl) round-trip correctly."""
        content = b"nested content"
        bare_git_repo.write_file(
            branch_name="main",
            filepath="subdir/nested.ttl",
            content=content,
            message="Add nested file",
        )
        result = bare_git_repo.read_file("main", "subdir/nested.ttl")
        assert result == content

    def test_deeply_nested_file(self, bare_git_repo: BareOntologyRepository) -> None:
        """Files at deeply nested paths round-trip correctly."""
        content = b"deep content"
        bare_git_repo.write_file(
            branch_name="main",
            filepath="a/b/c/deep.ttl",
            content=content,
            message="Add deeply nested file",
        )
        result = bare_git_repo.read_file("main", "a/b/c/deep.ttl")
        assert result == content

    def test_list_files_includes_nested(self, bare_git_repo: BareOntologyRepository) -> None:
        """list_files returns nested files with full paths."""
        bare_git_repo.write_file(
            branch_name="main",
            filepath="dir/file.ttl",
            content=b"data",
            message="Add dir/file",
        )
        files = bare_git_repo.list_files("main")
        assert "ontology.ttl" in files
        assert "dir/file.ttl" in files
