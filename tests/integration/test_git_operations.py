"""Integration tests for end-to-end git workflows using real pygit2 bare repos."""

from __future__ import annotations

from pathlib import Path

import pygit2
import pytest

from ontokit.git.bare_repository import BareOntologyRepository


class TestCreateRepoCommitAndRead:
    """Create a fresh repo, commit a file, and read it back."""

    def test_full_create_commit_read_cycle(self, tmp_path: Path) -> None:
        """Initialize a bare repo, write a file, and verify the content."""
        repo_path = tmp_path / "fresh.git"
        pygit2.init_repository(str(repo_path), bare=True)

        repo = BareOntologyRepository(repo_path)
        content = b"@prefix : <http://example.org/> .\n:Thing a owl:Class .\n"

        commit_info = repo.write_file(
            branch_name="main",
            filepath="ontology.ttl",
            content=content,
            message="Initial commit",
            author_name="Author",
            author_email="author@example.com",
        )

        assert commit_info.message == "Initial commit"
        assert len(commit_info.hash) == 40

        read_back = repo.read_file("main", "ontology.ttl")
        assert read_back == content

    def test_commit_info_fields(self, tmp_path: Path) -> None:
        """CommitInfo returned by write_file has all expected fields."""
        repo_path = tmp_path / "fields.git"
        pygit2.init_repository(str(repo_path), bare=True)
        repo = BareOntologyRepository(repo_path)

        info = repo.write_file(
            branch_name="main",
            filepath="data.ttl",
            content=b"data",
            message="Test fields",
            author_name="Jane Doe",
            author_email="jane@example.com",
        )

        assert info.author_name == "Jane Doe"
        assert info.author_email == "jane@example.com"
        assert info.short_hash == info.hash[:8]
        assert info.is_merge is False
        assert info.parent_hashes == []  # first commit has no parents


class TestBranchWorkflow:
    """Branch lifecycle: create, modify on branch, list."""

    def test_create_branch_modify_and_list(self, bare_git_repo: BareOntologyRepository) -> None:
        """Create a branch, commit on it, and verify both branches exist."""
        bare_git_repo.create_branch("feature-x", from_ref="main")

        bare_git_repo.write_file(
            branch_name="feature-x",
            filepath="feature.ttl",
            content=b"feature content",
            message="Feature work",
        )

        branches = {b.name for b in bare_git_repo.list_branches()}
        assert branches == {"main", "feature-x"}

        # Feature branch has the new file
        assert bare_git_repo.read_file("feature-x", "feature.ttl") == b"feature content"

        # Main branch does not
        with pytest.raises(KeyError):
            bare_git_repo.read_file("main", "feature.ttl")

    def test_branch_has_correct_ahead_behind(self, bare_git_repo: BareOntologyRepository) -> None:
        """A branch with extra commits reports commits_ahead > 0."""
        bare_git_repo.create_branch("ahead-branch", from_ref="main")
        bare_git_repo.write_file(
            branch_name="ahead-branch",
            filepath="extra.ttl",
            content=b"extra",
            message="Extra commit",
        )
        branches = {b.name: b for b in bare_git_repo.list_branches()}
        assert branches["ahead-branch"].commits_ahead == 1


class TestMergeWorkflow:
    """Full merge workflow: branch, commit, merge back to main."""

    def test_branch_commit_merge(self, bare_git_repo: BareOntologyRepository) -> None:
        """Branch off main, commit changes, merge back, verify content on main."""
        bare_git_repo.create_branch("merge-me", from_ref="main")

        # Commit on branch
        bare_git_repo.write_file(
            branch_name="merge-me",
            filepath="ontology.ttl",
            content=b"# merged version\n",
            message="Branch change",
        )

        # Merge back to main
        result = bare_git_repo.merge_branch(
            source="merge-me",
            target="main",
            message="Merge merge-me into main",
            author_name="Merger",
            author_email="merger@test.com",
        )

        assert result.success is True
        assert result.conflicts == []
        assert result.merge_commit_hash is not None

        # Main now has the branch's content
        content = bare_git_repo.read_file("main", "ontology.ttl")
        assert content == b"# merged version\n"

    def test_merge_nonexistent_source_raises(self, bare_git_repo: BareOntologyRepository) -> None:
        """Merging from a non-existent branch raises ValueError."""
        with pytest.raises(ValueError, match="Source branch not found"):
            bare_git_repo.merge_branch(source="ghost", target="main")

    def test_merge_nonexistent_target_raises(self, bare_git_repo: BareOntologyRepository) -> None:
        """Merging into a non-existent branch raises ValueError."""
        bare_git_repo.create_branch("exists", from_ref="main")
        with pytest.raises(ValueError, match="Target branch not found"):
            bare_git_repo.merge_branch(source="exists", target="ghost")


class TestHistoryChain:
    """Verify commit chain integrity."""

    def test_parent_hashes_form_chain(self, bare_git_repo: BareOntologyRepository) -> None:
        """Each commit's parent_hashes[0] points to the previous commit."""
        bare_git_repo.write_file(
            branch_name="main",
            filepath="ontology.ttl",
            content=b"v2",
            message="Second",
        )
        bare_git_repo.write_file(
            branch_name="main",
            filepath="ontology.ttl",
            content=b"v3",
            message="Third",
        )

        history = bare_git_repo.get_history(branch="main", all_branches=False)
        assert len(history) == 3

        # Each non-root commit's parent is the next entry in history
        assert history[0].parent_hashes[0] == history[1].hash
        assert history[1].parent_hashes[0] == history[2].hash
        # Root commit has no parents
        assert history[2].parent_hashes == []


class TestMultiFileRepo:
    """Verify handling of multiple files in a single repo."""

    def test_write_multiple_files_and_list(self, bare_git_repo: BareOntologyRepository) -> None:
        """Writing several files produces correct list_files output."""
        bare_git_repo.write_file(
            branch_name="main",
            filepath="second.ttl",
            content=b"second file",
            message="Add second file",
        )
        bare_git_repo.write_file(
            branch_name="main",
            filepath="subdir/third.ttl",
            content=b"third file",
            message="Add third file in subdir",
        )

        files = bare_git_repo.list_files("main")
        assert "ontology.ttl" in files
        assert "second.ttl" in files
        assert "subdir/third.ttl" in files

    def test_files_independent(self, bare_git_repo: BareOntologyRepository) -> None:
        """Updating one file does not alter another."""
        bare_git_repo.write_file(
            branch_name="main",
            filepath="other.ttl",
            content=b"other",
            message="Add other",
        )
        # Update ontology.ttl
        bare_git_repo.write_file(
            branch_name="main",
            filepath="ontology.ttl",
            content=b"changed",
            message="Update ontology",
        )
        # other.ttl is unaffected
        assert bare_git_repo.read_file("main", "other.ttl") == b"other"
        assert bare_git_repo.read_file("main", "ontology.ttl") == b"changed"
