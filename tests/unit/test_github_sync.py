"""Tests for github_sync module (ontokit/services/github_sync.py)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ontokit.services.github_sync import _try_merge, sync_github_project

PROJECT_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
PAT = "ghp_testtoken123"
BRANCH = "main"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_integration(
    *,
    default_branch: str = BRANCH,
    sync_status: str = "idle",
) -> MagicMock:
    integration = MagicMock()
    integration.project_id = PROJECT_ID
    integration.default_branch = default_branch
    integration.sync_status = sync_status
    integration.sync_error = None
    integration.last_sync_at = None
    return integration


def _make_git_service(
    *,
    repo_exists: bool = True,
) -> MagicMock:
    git_service = MagicMock()
    git_service.repository_exists.return_value = repo_exists
    return git_service


def _make_mock_repo(
    *,
    fetch_ok: bool = True,
    push_ok: bool = True,
) -> MagicMock:
    repo = MagicMock()
    repo.fetch.return_value = fetch_ok
    repo.push.return_value = push_ok
    return repo


def _make_pygit2_repo(
    *,
    local_oid: object | None = "local_oid_123",
    remote_oid: object | None = "remote_oid_456",
    ahead: int = 0,
    behind: int = 0,
    local_missing: bool = False,
    remote_missing: bool = False,
) -> MagicMock:
    pygit2_repo = MagicMock()

    refs = MagicMock()
    if local_missing:
        refs.__getitem__ = MagicMock(side_effect=KeyError("refs/heads/main"))
    elif remote_missing:
        local_ref = MagicMock()
        local_ref.target = local_oid

        def _getitem(key: str) -> MagicMock:
            if key == f"refs/heads/{BRANCH}":
                return local_ref
            raise KeyError(key)

        refs.__getitem__ = MagicMock(side_effect=_getitem)
    else:
        local_ref = MagicMock()
        local_ref.target = local_oid
        remote_ref = MagicMock()
        remote_ref.target = remote_oid

        def _getitem_both(key: str) -> MagicMock:
            if key == f"refs/heads/{BRANCH}":
                return local_ref
            if key == f"refs/remotes/origin/{BRANCH}":
                return remote_ref
            raise KeyError(key)

        refs.__getitem__ = MagicMock(side_effect=_getitem_both)

    pygit2_repo.references = refs
    pygit2_repo.ahead_behind.return_value = (ahead, behind)
    return pygit2_repo


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSyncGitHubProject:
    @pytest.mark.asyncio
    async def test_no_repo_returns_error(self) -> None:
        """Returns error when local repository does not exist."""
        integration = _make_integration()
        git_service = _make_git_service(repo_exists=False)
        mock_db = AsyncMock()

        result = await sync_github_project(integration, PAT, git_service, mock_db)
        assert result["status"] == "error"
        assert result["reason"] == "no_repo"
        assert integration.sync_status == "error"

    @pytest.mark.asyncio
    async def test_fetch_failed_returns_error(self) -> None:
        """Returns error when fetch from remote fails."""
        integration = _make_integration()
        git_service = _make_git_service()
        mock_repo = _make_mock_repo(fetch_ok=False)
        git_service.get_repository.return_value = mock_repo
        mock_db = AsyncMock()

        result = await sync_github_project(integration, PAT, git_service, mock_db)
        assert result["status"] == "error"
        assert result["reason"] == "fetch_failed"

    @pytest.mark.asyncio
    async def test_no_local_branch_returns_idle(self) -> None:
        """Returns idle when local branch doesn't exist."""
        integration = _make_integration()
        git_service = _make_git_service()
        mock_repo = _make_mock_repo()
        pygit2_repo = _make_pygit2_repo(local_missing=True)
        mock_repo.repo = pygit2_repo
        git_service.get_repository.return_value = mock_repo
        mock_db = AsyncMock()

        result = await sync_github_project(integration, PAT, git_service, mock_db)
        assert result["status"] == "idle"
        assert result["reason"] == "no_local_branch"

    @pytest.mark.asyncio
    async def test_up_to_date_returns_idle(self) -> None:
        """Returns idle when local and remote are already in sync."""
        same_oid = MagicMock()
        integration = _make_integration()
        git_service = _make_git_service()
        mock_repo = _make_mock_repo()
        pygit2_repo = _make_pygit2_repo(local_oid=same_oid, remote_oid=same_oid)
        mock_repo.repo = pygit2_repo
        git_service.get_repository.return_value = mock_repo
        mock_db = AsyncMock()

        result = await sync_github_project(integration, PAT, git_service, mock_db)
        assert result["status"] == "idle"
        assert result["reason"] == "up_to_date"

    @pytest.mark.asyncio
    async def test_remote_ahead_fast_forwards(self) -> None:
        """Fast-forwards local branch when remote is ahead."""
        local_oid = MagicMock()
        remote_oid = MagicMock()
        integration = _make_integration()
        git_service = _make_git_service()
        mock_repo = _make_mock_repo()
        pygit2_repo = _make_pygit2_repo(
            local_oid=local_oid, remote_oid=remote_oid, ahead=0, behind=3
        )
        mock_repo.repo = pygit2_repo
        git_service.get_repository.return_value = mock_repo
        mock_db = AsyncMock()

        result = await sync_github_project(integration, PAT, git_service, mock_db)
        assert result["status"] == "pulled"
        assert result["behind"] == 3

    @pytest.mark.asyncio
    async def test_local_ahead_pushes(self) -> None:
        """Pushes to remote when local is ahead."""
        local_oid = MagicMock()
        remote_oid = MagicMock()
        integration = _make_integration()
        git_service = _make_git_service()
        mock_repo = _make_mock_repo(push_ok=True)
        pygit2_repo = _make_pygit2_repo(
            local_oid=local_oid, remote_oid=remote_oid, ahead=2, behind=0
        )
        mock_repo.repo = pygit2_repo
        git_service.get_repository.return_value = mock_repo
        mock_db = AsyncMock()

        result = await sync_github_project(integration, PAT, git_service, mock_db)
        assert result["status"] == "pushed"
        assert result["ahead"] == 2

    @pytest.mark.asyncio
    async def test_local_ahead_push_fails(self) -> None:
        """Returns error when push fails."""
        local_oid = MagicMock()
        remote_oid = MagicMock()
        integration = _make_integration()
        git_service = _make_git_service()
        mock_repo = _make_mock_repo(push_ok=False)
        pygit2_repo = _make_pygit2_repo(
            local_oid=local_oid, remote_oid=remote_oid, ahead=2, behind=0
        )
        mock_repo.repo = pygit2_repo
        git_service.get_repository.return_value = mock_repo
        mock_db = AsyncMock()

        result = await sync_github_project(integration, PAT, git_service, mock_db)
        assert result["status"] == "error"
        assert result["reason"] == "push_failed"

    @pytest.mark.asyncio
    async def test_remote_no_branch_pushes(self) -> None:
        """Pushes when remote branch doesn't exist yet."""
        integration = _make_integration()
        git_service = _make_git_service()
        mock_repo = _make_mock_repo(push_ok=True)
        pygit2_repo = _make_pygit2_repo(remote_missing=True)
        mock_repo.repo = pygit2_repo
        git_service.get_repository.return_value = mock_repo
        mock_db = AsyncMock()

        result = await sync_github_project(integration, PAT, git_service, mock_db)
        assert result["status"] == "pushed"
        assert result["reason"] == "new_remote_branch"

    @pytest.mark.asyncio
    async def test_remote_no_branch_push_fails(self) -> None:
        """Returns error when remote branch doesn't exist and push fails."""
        integration = _make_integration()
        git_service = _make_git_service()
        mock_repo = _make_mock_repo(push_ok=False)
        pygit2_repo = _make_pygit2_repo(remote_missing=True)
        mock_repo.repo = pygit2_repo
        git_service.get_repository.return_value = mock_repo
        mock_db = AsyncMock()

        result = await sync_github_project(integration, PAT, git_service, mock_db)
        assert result["status"] == "error"
        assert result["reason"] == "push_failed"
        assert integration.sync_status == "error"

    @pytest.mark.asyncio
    async def test_diverged_merge_conflict(self) -> None:
        """Returns conflict status when branches have diverged and merge conflicts."""
        local_oid = MagicMock()
        remote_oid = MagicMock()
        integration = _make_integration()
        git_service = _make_git_service()
        mock_repo = _make_mock_repo()
        pygit2_repo = _make_pygit2_repo(
            local_oid=local_oid, remote_oid=remote_oid, ahead=2, behind=3
        )
        mock_repo.repo = pygit2_repo
        git_service.get_repository.return_value = mock_repo
        mock_db = AsyncMock()

        with patch(
            "ontokit.services.github_sync._try_merge",
            return_value={"conflict": True, "error": "Conflicting files: onto.ttl"},
        ):
            result = await sync_github_project(integration, PAT, git_service, mock_db)

        assert result["status"] == "conflict"
        assert result["ahead"] == 2
        assert result["behind"] == 3
        assert integration.sync_status == "conflict"

    @pytest.mark.asyncio
    async def test_diverged_merge_success_push_ok(self) -> None:
        """Merges and pushes when branches diverged and merge succeeds."""
        local_oid = MagicMock()
        remote_oid = MagicMock()
        integration = _make_integration()
        git_service = _make_git_service()
        mock_repo = _make_mock_repo(push_ok=True)
        pygit2_repo = _make_pygit2_repo(
            local_oid=local_oid, remote_oid=remote_oid, ahead=1, behind=2
        )
        mock_repo.repo = pygit2_repo
        git_service.get_repository.return_value = mock_repo
        mock_db = AsyncMock()

        with patch(
            "ontokit.services.github_sync._try_merge",
            return_value={"conflict": False},
        ):
            result = await sync_github_project(integration, PAT, git_service, mock_db)

        assert result["status"] == "merged_and_pushed"
        assert result["ahead"] == 1
        assert result["behind"] == 2
        assert integration.sync_status == "idle"

    @pytest.mark.asyncio
    async def test_diverged_merge_success_push_fails(self) -> None:
        """Returns error when merge succeeds but push fails."""
        local_oid = MagicMock()
        remote_oid = MagicMock()
        integration = _make_integration()
        git_service = _make_git_service()
        mock_repo = _make_mock_repo(push_ok=False)
        pygit2_repo = _make_pygit2_repo(
            local_oid=local_oid, remote_oid=remote_oid, ahead=1, behind=2
        )
        mock_repo.repo = pygit2_repo
        git_service.get_repository.return_value = mock_repo
        mock_db = AsyncMock()

        with patch(
            "ontokit.services.github_sync._try_merge",
            return_value={"conflict": False},
        ):
            result = await sync_github_project(integration, PAT, git_service, mock_db)

        assert result["status"] == "error"
        assert result["reason"] == "post_merge_push_failed"
        assert integration.sync_status == "error"
        assert integration.sync_error == "Merge succeeded but push failed"

    @pytest.mark.asyncio
    async def test_exception_during_sync(self) -> None:
        """Returns error when an unexpected exception occurs during sync."""
        integration = _make_integration()
        git_service = _make_git_service()
        git_service.get_repository.side_effect = RuntimeError("unexpected failure")
        mock_db = AsyncMock()

        result = await sync_github_project(integration, PAT, git_service, mock_db)
        assert result["status"] == "error"
        assert "unexpected failure" in str(result["reason"])
        assert integration.sync_status == "error"
        assert "unexpected failure" in str(integration.sync_error)

    @pytest.mark.asyncio
    async def test_default_branch_none_uses_main(self) -> None:
        """Falls back to 'main' when default_branch is None."""
        integration = _make_integration(default_branch=None)  # type: ignore[arg-type]
        git_service = _make_git_service(repo_exists=False)
        mock_db = AsyncMock()

        result = await sync_github_project(integration, PAT, git_service, mock_db)
        # Just verify we get through without error about branch
        assert result["status"] == "error"
        assert result["reason"] == "no_repo"


class TestTryMerge:
    """Tests for the _try_merge helper function."""

    def test_merge_with_conflicts(self) -> None:
        """Returns conflict=True with conflicting file paths."""
        repo = MagicMock()
        merge_index = MagicMock()

        # Simulate conflict entries: each is (ancestor, ours, theirs)
        entry_ours = MagicMock()
        entry_ours.path = "ontology.ttl"
        entry_theirs = MagicMock()
        entry_theirs.path = "ontology.ttl"
        merge_index.conflicts = [(None, entry_ours, entry_theirs)]

        repo.merge_commits.return_value = merge_index

        local_oid = MagicMock()
        remote_oid = MagicMock()
        result = _try_merge(repo, local_oid, remote_oid, "main")

        assert result["conflict"] is True
        assert "ontology.ttl" in str(result["error"])

    def test_merge_with_conflict_ancestor_entry(self) -> None:
        """Handles conflict where ancestor entry is the first non-None."""
        repo = MagicMock()
        merge_index = MagicMock()

        entry_ancestor = MagicMock()
        entry_ancestor.path = "data.owl"
        merge_index.conflicts = [(entry_ancestor, None, None)]

        repo.merge_commits.return_value = merge_index

        result = _try_merge(repo, MagicMock(), MagicMock(), "main")
        assert result["conflict"] is True
        assert "data.owl" in str(result["error"])

    def test_merge_success(self) -> None:
        """Returns conflict=False on successful merge and creates commit."""
        repo = MagicMock()
        merge_index = MagicMock()
        merge_index.conflicts = None
        merged_tree_oid = MagicMock()
        merge_index.write_tree.return_value = merged_tree_oid

        repo.merge_commits.return_value = merge_index

        local_commit = MagicMock()
        local_commit.id = MagicMock()
        remote_commit = MagicMock()
        remote_commit.id = MagicMock()
        repo.get.side_effect = [local_commit, remote_commit]

        result = _try_merge(repo, MagicMock(), MagicMock(), "main")
        assert result["conflict"] is False
        repo.create_commit.assert_called_once()

    def test_merge_exception(self) -> None:
        """Returns conflict=True when merge_commits raises an exception."""
        repo = MagicMock()
        repo.merge_commits.side_effect = RuntimeError("git error")

        result = _try_merge(repo, MagicMock(), MagicMock(), "main")
        assert result["conflict"] is True
        assert "Merge failed" in str(result["error"])

    def test_merge_conflict_all_none_entries(self) -> None:
        """Handles conflict where all entries in a conflict tuple are None."""
        repo = MagicMock()
        merge_index = MagicMock()
        # Edge case: all entries None (shouldn't normally happen but be defensive)
        merge_index.conflicts = [(None, None, None)]

        repo.merge_commits.return_value = merge_index

        result = _try_merge(repo, MagicMock(), MagicMock(), "main")
        assert result["conflict"] is True
