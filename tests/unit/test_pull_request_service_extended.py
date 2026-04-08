"""Extended tests for PullRequestService — covering previously uncovered paths."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from fastapi import HTTPException

from ontokit.core.auth import CurrentUser
from ontokit.git.bare_repository import BranchInfo as GitBranchInfo
from ontokit.models.pull_request import PRStatus
from ontokit.schemas.pull_request import BranchCreate, CommentUpdate, PRMergeRequest, ReviewCreate
from ontokit.services.pull_request_service import PullRequestService

PROJECT_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
PR_ID = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
COMMENT_ID = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
OWNER_ID = "owner-user-id"
EDITOR_ID = "editor-user-id"
VIEWER_ID = "viewer-user-id"
OTHER_ID = "other-user-id"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_member(user_id: str, role: str) -> MagicMock:
    m = MagicMock()
    m.user_id = user_id
    m.role = role
    m.project_id = PROJECT_ID
    m.preferred_branch = None
    m.created_at = datetime.now(UTC)
    return m


def _make_project(
    *,
    is_public: bool = True,
    owner_id: str = OWNER_ID,
    pr_approval_required: int = 0,
    members: list[MagicMock] | None = None,
) -> MagicMock:
    project = MagicMock()
    project.id = PROJECT_ID
    project.name = "Test Ontology"
    project.is_public = is_public
    project.owner_id = owner_id
    project.pr_approval_required = pr_approval_required
    if members is None:
        members = [
            _make_member(owner_id, "owner"),
            _make_member(EDITOR_ID, "editor"),
            _make_member(VIEWER_ID, "viewer"),
        ]
    project.members = members
    return project


def _make_pr(
    *,
    author_id: str = EDITOR_ID,
    status: str = PRStatus.OPEN.value,
    source_branch: str = "feature",
    target_branch: str = "main",
    github_pr_number: int | None = None,
) -> MagicMock:
    pr = MagicMock()
    pr.id = PR_ID
    pr.project_id = PROJECT_ID
    pr.pr_number = 1
    pr.title = "Test PR"
    pr.description = "PR description"
    pr.source_branch = source_branch
    pr.target_branch = target_branch
    pr.status = status
    pr.author_id = author_id
    pr.author_name = "Editor User"
    pr.author_email = "editor@example.com"
    pr.github_pr_number = github_pr_number
    pr.github_pr_url = None
    pr.reviews = []
    pr.comments = []
    pr.base_commit_hash = None
    pr.head_commit_hash = None
    pr.merge_commit_hash = None
    pr.merged_by = None
    pr.merged_at = None
    pr.created_at = datetime.now(UTC)
    pr.updated_at = None
    return pr


def _make_comment(author_id: str = EDITOR_ID) -> MagicMock:
    comment = MagicMock()
    comment.id = COMMENT_ID
    comment.pull_request_id = PR_ID
    comment.author_id = author_id
    comment.author_name = "Editor User"
    comment.author_email = "editor@example.com"
    comment.body = "Nice change"
    comment.parent_id = None
    comment.replies = []
    comment.github_comment_id = None
    comment.created_at = datetime.now(UTC)
    comment.updated_at = None
    return comment


def _make_merge_commit(
    *,
    merged_branch: str = "feature",
    commit_hash: str = "abc123",
    author_name: str = "Developer",
    author_email: str = "dev@example.com",
    parent_hashes: list[str] | None = None,
) -> MagicMock:
    commit = MagicMock()
    commit.hash = commit_hash
    commit.short_hash = commit_hash[:7]
    commit.message = f"Merge branch '{merged_branch}'"
    commit.is_merge = True
    commit.merged_branch = merged_branch
    commit.author_name = author_name
    commit.author_email = author_email
    commit.timestamp = "2025-01-01T00:00:00+00:00"
    commit.parent_hashes = parent_hashes or ["base111", "head222"]
    return commit


def _make_user(user_id: str = OWNER_ID, name: str = "Test User") -> CurrentUser:
    return CurrentUser(
        id=user_id, email=f"{user_id}@example.com", name=name, username=user_id, roles=[]
    )


def _make_git_branch_info(name: str) -> GitBranchInfo:
    return GitBranchInfo(
        name=name,
        is_current=(name == "main"),
        is_default=(name == "main"),
        commit_hash="abc123",
        commit_message="Some commit",
        commit_date=None,
        commits_ahead=0,
        commits_behind=0,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_db() -> AsyncMock:
    session = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.flush = AsyncMock()
    session.close = AsyncMock()
    session.execute = AsyncMock()
    session.refresh = AsyncMock()
    session.add = Mock()
    session.delete = AsyncMock()
    session.scalar = AsyncMock()
    return session


@pytest.fixture
def mock_git_service() -> MagicMock:
    git = MagicMock()
    git.list_branches = MagicMock(return_value=[])
    git.get_current_branch = MagicMock(return_value="main")
    git.get_default_branch = MagicMock(return_value="main")
    git.get_history = MagicMock(return_value=[])
    git.merge_branch = MagicMock()
    git.delete_branch = MagicMock()
    git.create_branch = MagicMock()
    git.switch_branch = MagicMock()
    git.diff_versions = MagicMock()
    return git


@pytest.fixture
def mock_github_service() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_user_service() -> MagicMock:
    svc = MagicMock()
    svc.get_user_info = AsyncMock(return_value=None)
    return svc


@pytest.fixture
def service(
    mock_db: AsyncMock,
    mock_git_service: MagicMock,
    mock_github_service: MagicMock,
    mock_user_service: MagicMock,
) -> PullRequestService:
    return PullRequestService(
        db=mock_db,
        git_service=mock_git_service,
        github_service=mock_github_service,
        user_service=mock_user_service,
    )


def _project_result(project: MagicMock) -> MagicMock:
    r = MagicMock()
    r.scalar_one_or_none.return_value = project
    return r


def _pr_result(pr: MagicMock | None) -> MagicMock:
    r = MagicMock()
    r.scalar_one_or_none.return_value = pr
    return r


def _scalars_result(items: list[MagicMock]) -> MagicMock:
    r = MagicMock()
    r.scalars.return_value.all.return_value = items
    return r


def _scalar_result(value: object) -> MagicMock:
    r = MagicMock()
    r.scalar.return_value = value
    r.scalar_one_or_none.return_value = value
    return r


# ---------------------------------------------------------------------------
# _sync_merge_commits_to_prs
# ---------------------------------------------------------------------------


class TestSyncMergeCommitsToPRs:
    @pytest.mark.asyncio
    async def test_git_history_exception_returns_early(
        self, service: PullRequestService, mock_git_service: MagicMock, mock_db: AsyncMock
    ) -> None:
        """If get_history raises, function logs and returns without DB calls."""
        mock_git_service.get_history.side_effect = RuntimeError("git error")

        await service._sync_merge_commits_to_prs(PROJECT_ID)

        mock_db.execute.assert_not_called()
        mock_db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_backfills_commit_hashes_for_existing_pr(
        self, service: PullRequestService, mock_git_service: MagicMock, mock_db: AsyncMock
    ) -> None:
        """Existing merged PR missing commit hashes gets backfilled from git history."""
        merge_commit = _make_merge_commit(
            merged_branch="feature",
            parent_hashes=["base111", "head222"],
        )
        mock_git_service.get_history.return_value = [merge_commit]

        # Existing merged PR with no commit hashes
        existing_pr = MagicMock()
        existing_pr.pr_number = 1
        existing_pr.source_branch = "feature"
        existing_pr.merge_commit_hash = None
        existing_pr.base_commit_hash = None
        existing_pr.head_commit_hash = None
        existing_pr.author_name = None
        existing_pr.author_email = None

        # DB calls: select merged PRs, select max PR number
        merged_prs_result = _scalars_result([existing_pr])
        max_number_result = _scalar_result(1)
        mock_db.execute.side_effect = [merged_prs_result, max_number_result]

        await service._sync_merge_commits_to_prs(PROJECT_ID)

        # Should have backfilled commit hashes
        assert existing_pr.merge_commit_hash == "abc123"
        assert existing_pr.base_commit_hash == "base111"
        assert existing_pr.head_commit_hash == "head222"
        mock_db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_creates_retroactive_pr_for_direct_merge(
        self, service: PullRequestService, mock_git_service: MagicMock, mock_db: AsyncMock
    ) -> None:
        """Creates a retroactive PR record for a merge commit with no existing PR."""
        merge_commit = _make_merge_commit(merged_branch="hotfix")
        mock_git_service.get_history.return_value = [merge_commit]

        # No existing merged PRs
        merged_prs_result = _scalars_result([])
        max_number_result = _scalar_result(5)
        mock_db.execute.side_effect = [merged_prs_result, max_number_result]

        await service._sync_merge_commits_to_prs(PROJECT_ID)

        # Should have called db.add to create a new PR record
        mock_db.add.assert_called_once()
        mock_db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_no_commit_when_nothing_changed(
        self, service: PullRequestService, mock_git_service: MagicMock, mock_db: AsyncMock
    ) -> None:
        """No DB commit when merge commits all have existing PRs with hashes."""
        merge_commit = _make_merge_commit(merged_branch="feature")
        mock_git_service.get_history.return_value = [merge_commit]

        # Existing PR already has all commit hashes
        existing_pr = MagicMock()
        existing_pr.source_branch = "feature"
        existing_pr.merge_commit_hash = "abc123"
        existing_pr.base_commit_hash = "base111"
        existing_pr.head_commit_hash = "head222"

        merged_prs_result = _scalars_result([existing_pr])
        max_number_result = _scalar_result(1)
        mock_db.execute.side_effect = [merged_prs_result, max_number_result]

        await service._sync_merge_commits_to_prs(PROJECT_ID)

        mock_db.commit.assert_not_awaited()


# ---------------------------------------------------------------------------
# list_pull_requests — filters
# ---------------------------------------------------------------------------


class TestListPullRequestsFilters:
    @pytest.mark.asyncio
    async def test_list_prs_with_status_filter(
        self, service: PullRequestService, mock_db: AsyncMock, mock_git_service: MagicMock
    ) -> None:
        """list_pull_requests passes status_filter to the query."""
        project = _make_project()
        pr = _make_pr()
        user = _make_user(EDITOR_ID)

        mock_git_service.get_history.return_value = []

        merged_prs_result = _scalars_result([])
        max_number_result = _scalar_result(0)
        list_result = _scalars_result([pr])
        project_result_2 = _project_result(project)

        mock_db.execute.side_effect = [
            _project_result(project),
            merged_prs_result,
            max_number_result,
            list_result,
            project_result_2,
        ]
        mock_db.scalar = AsyncMock(return_value=1)

        result = await service.list_pull_requests(PROJECT_ID, user, status_filter="open")
        assert len(result.items) == 1

    @pytest.mark.asyncio
    async def test_list_prs_with_author_filter(
        self, service: PullRequestService, mock_db: AsyncMock, mock_git_service: MagicMock
    ) -> None:
        """list_pull_requests passes author_id filter to the query."""
        project = _make_project()
        pr = _make_pr(author_id=EDITOR_ID)
        user = _make_user(OWNER_ID)

        mock_git_service.get_history.return_value = []

        merged_prs_result = _scalars_result([])
        max_number_result = _scalar_result(0)
        list_result = _scalars_result([pr])
        project_result_2 = _project_result(project)

        mock_db.execute.side_effect = [
            _project_result(project),
            merged_prs_result,
            max_number_result,
            list_result,
            project_result_2,
        ]
        mock_db.scalar = AsyncMock(return_value=1)

        result = await service.list_pull_requests(PROJECT_ID, user, author_id=EDITOR_ID)
        assert len(result.items) == 1


# ---------------------------------------------------------------------------
# close_pull_request — GitHub sync
# ---------------------------------------------------------------------------


class TestClosePullRequestGitHubSync:
    @pytest.mark.asyncio
    async def test_close_pr_with_github_pr_number_syncs(
        self,
        service: PullRequestService,
        mock_db: AsyncMock,
        mock_github_service: MagicMock,
    ) -> None:
        """close_pull_request syncs to GitHub when github_pr_number is set."""
        from unittest.mock import patch

        project = _make_project()
        pr = _make_pr(author_id=OWNER_ID, github_pr_number=42)
        user = _make_user(OWNER_ID)

        integration = MagicMock()
        integration.repo_owner = "org"
        integration.repo_name = "repo"
        integration.sync_enabled = True
        integration.connected_by_user_id = "user-123"

        token_row = MagicMock()
        token_row.encrypted_token = "encrypted-abc"

        mock_db.execute.side_effect = [
            _project_result(project),
            _pr_result(pr),
            _scalar_result(integration),  # _get_github_integration
            _scalar_result(token_row),  # UserGitHubToken lookup
            _project_result(project),  # _to_pr_response -> _get_project
        ]

        mock_github_service.close_pull_request = AsyncMock()

        with patch(
            "ontokit.services.pull_request_service.decrypt_token",
            return_value="decrypted-token",
        ):
            await service.close_pull_request(PROJECT_ID, 1, user)

        assert pr.status == PRStatus.CLOSED.value
        mock_github_service.close_pull_request.assert_awaited_once_with(
            token="decrypted-token",
            owner="org",
            repo="repo",
            pr_number=42,
        )


# ---------------------------------------------------------------------------
# reopen_pull_request — GitHub sync
# ---------------------------------------------------------------------------


class TestReopenPullRequestGitHubSync:
    @pytest.mark.asyncio
    async def test_reopen_pr_with_github_pr_number_syncs(
        self,
        service: PullRequestService,
        mock_db: AsyncMock,
        mock_github_service: MagicMock,
    ) -> None:
        """reopen_pull_request syncs to GitHub when github_pr_number is set."""
        from unittest.mock import patch

        project = _make_project()
        pr = _make_pr(
            author_id=OWNER_ID,
            status=PRStatus.CLOSED.value,
            github_pr_number=42,
        )
        user = _make_user(OWNER_ID)

        integration = MagicMock()
        integration.repo_owner = "org"
        integration.repo_name = "repo"
        integration.sync_enabled = True
        integration.connected_by_user_id = "user-123"

        token_row = MagicMock()
        token_row.encrypted_token = "encrypted-abc"

        mock_db.execute.side_effect = [
            _project_result(project),
            _pr_result(pr),
            _scalar_result(integration),  # _get_github_integration
            _scalar_result(token_row),  # UserGitHubToken
            _project_result(project),  # _to_pr_response
        ]

        mock_github_service.reopen_pull_request = AsyncMock()

        with patch(
            "ontokit.services.pull_request_service.decrypt_token",
            return_value="decrypted-token",
        ):
            await service.reopen_pull_request(PROJECT_ID, 1, user)

        assert pr.status == PRStatus.OPEN.value
        mock_github_service.reopen_pull_request.assert_awaited_once_with(
            token="decrypted-token",
            owner="org",
            repo="repo",
            pr_number=42,
        )


# ---------------------------------------------------------------------------
# merge_pull_request — delete_source_branch path + merge notification
# ---------------------------------------------------------------------------


class TestMergePullRequestExtended:
    @pytest.mark.asyncio
    async def test_merge_with_delete_source_branch(
        self,
        service: PullRequestService,
        mock_db: AsyncMock,
        mock_git_service: MagicMock,
    ) -> None:
        """merge_pull_request deletes source branch when delete_source_branch=True."""
        project = _make_project()
        pr = _make_pr(author_id=OWNER_ID)  # same user, no notification
        user = _make_user(OWNER_ID)

        main_branch = MagicMock()
        main_branch.name = "main"
        main_branch.commit_hash = "aaa"
        feature_branch = MagicMock()
        feature_branch.name = "feature"
        feature_branch.commit_hash = "bbb"
        mock_git_service.list_branches.return_value = [main_branch, feature_branch]

        merge_result = MagicMock()
        merge_result.success = True
        merge_result.merge_commit_hash = "ccc"
        mock_git_service.merge_branch.return_value = merge_result

        # DB calls: _get_project, _get_pr, sa_delete(BranchMetadata), _get_github_integration
        mock_db.execute.side_effect = [
            _project_result(project),
            _pr_result(pr),
            MagicMock(),  # sa_delete result (ignored)
            _scalar_result(None),  # _get_github_integration (no GitHub)
        ]

        merge_req = PRMergeRequest(delete_source_branch=True)
        result = await service.merge_pull_request(PROJECT_ID, 1, merge_req, user)

        assert result.success is True
        mock_git_service.delete_branch.assert_called_once_with(PROJECT_ID, "feature")

    @pytest.mark.asyncio
    @patch("ontokit.services.pull_request_service.NotificationService")
    async def test_merge_notifies_pr_author(
        self,
        mock_notif_cls: MagicMock,
        service: PullRequestService,
        mock_db: AsyncMock,
        mock_git_service: MagicMock,
    ) -> None:
        """merge_pull_request sends notification to PR author when merged by someone else."""
        project = _make_project()
        pr = _make_pr(author_id=EDITOR_ID)  # author is editor, merger is owner
        user = _make_user(OWNER_ID)

        main_branch = MagicMock()
        main_branch.name = "main"
        main_branch.commit_hash = "aaa"
        feature_branch = MagicMock()
        feature_branch.name = "feature"
        feature_branch.commit_hash = "bbb"
        mock_git_service.list_branches.return_value = [main_branch, feature_branch]

        merge_result = MagicMock()
        merge_result.success = True
        merge_result.merge_commit_hash = "ccc"
        mock_git_service.merge_branch.return_value = merge_result

        mock_notif = AsyncMock()
        mock_notif.create_notification = AsyncMock()
        mock_notif_cls.return_value = mock_notif

        mock_db.execute.side_effect = [
            _project_result(project),
            _pr_result(pr),
            _scalar_result(None),  # _get_github_integration
        ]

        merge_req = PRMergeRequest()
        result = await service.merge_pull_request(PROJECT_ID, 1, merge_req, user)

        assert result.success is True
        mock_notif.create_notification.assert_awaited_once()
        assert mock_notif.create_notification.await_args is not None
        call_kwargs = mock_notif.create_notification.await_args.kwargs
        assert call_kwargs["user_id"] == EDITOR_ID
        assert call_kwargs["notification_type"] == "pr_merged"
        assert call_kwargs["project_id"] == PROJECT_ID


# ---------------------------------------------------------------------------
# create_review — notification path
# ---------------------------------------------------------------------------


class TestCreateReviewNotification:
    @pytest.mark.asyncio
    @patch("ontokit.services.pull_request_service.NotificationService")
    async def test_create_review_notifies_author(
        self,
        mock_notif_cls: MagicMock,
        service: PullRequestService,
        mock_db: AsyncMock,
    ) -> None:
        """create_review sends notification to PR author when reviewer != author."""
        project = _make_project()
        pr = _make_pr(author_id=EDITOR_ID)
        user = _make_user(OWNER_ID)

        mock_notif = AsyncMock()
        mock_notif.create_notification = AsyncMock()
        mock_notif_cls.return_value = mock_notif

        # After refresh, populate id and created_at on the ORM object
        def _populate(obj: object) -> None:
            obj.id = uuid.uuid4()  # type: ignore[attr-defined]
            obj.created_at = datetime.now(UTC)  # type: ignore[attr-defined]

        mock_db.execute.side_effect = [
            _project_result(project),
            _pr_result(pr),
        ]
        mock_db.refresh.side_effect = _populate

        review_create = ReviewCreate(status="commented", body="Looks good")
        await service.create_review(PROJECT_ID, 1, review_create, user)

        mock_notif.create_notification.assert_awaited_once()
        assert mock_notif.create_notification.await_args is not None
        call_kwargs = mock_notif.create_notification.await_args.kwargs
        assert call_kwargs["user_id"] == EDITOR_ID
        assert call_kwargs["notification_type"] == "pr_review"
        assert call_kwargs["project_id"] == PROJECT_ID


# ---------------------------------------------------------------------------
# list_reviews — private project forbidden
# ---------------------------------------------------------------------------


class TestListReviews:
    @pytest.mark.asyncio
    async def test_list_reviews_private_forbidden(
        self, service: PullRequestService, mock_db: AsyncMock
    ) -> None:
        """Non-members cannot list reviews on a private project."""
        project = _make_project(is_public=False)
        user = _make_user(OTHER_ID)

        mock_db.execute.return_value = _project_result(project)

        with pytest.raises(HTTPException) as exc_info:
            await service.list_reviews(PROJECT_ID, 1, user)
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# update_comment
# ---------------------------------------------------------------------------


class TestUpdateComment:
    @pytest.mark.asyncio
    async def test_update_comment_success(
        self, service: PullRequestService, mock_db: AsyncMock
    ) -> None:
        """Comment author can update the comment body."""
        project = _make_project()
        pr = _make_pr()
        comment = _make_comment(author_id=EDITOR_ID)
        user = _make_user(EDITOR_ID)

        mock_db.execute.side_effect = [
            _project_result(project),
            _pr_result(pr),
            _pr_result(comment),  # comment lookup
        ]

        comment_update = CommentUpdate(body="Updated body")
        result = await service.update_comment(PROJECT_ID, 1, COMMENT_ID, comment_update, user)
        assert comment.body == "Updated body"
        assert result is not None

    @pytest.mark.asyncio
    async def test_update_comment_not_found(
        self, service: PullRequestService, mock_db: AsyncMock
    ) -> None:
        """Returns 404 when comment does not exist."""
        project = _make_project()
        pr = _make_pr()
        user = _make_user(EDITOR_ID)

        mock_db.execute.side_effect = [
            _project_result(project),
            _pr_result(pr),
            _pr_result(None),  # comment not found
        ]

        comment_update = CommentUpdate(body="Updated")
        with pytest.raises(HTTPException) as exc_info:
            await service.update_comment(PROJECT_ID, 1, COMMENT_ID, comment_update, user)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_update_comment_not_author_forbidden(
        self, service: PullRequestService, mock_db: AsyncMock
    ) -> None:
        """Non-author cannot update a comment."""
        project = _make_project()
        pr = _make_pr()
        comment = _make_comment(author_id=EDITOR_ID)
        user = _make_user(OWNER_ID)  # different user

        mock_db.execute.side_effect = [
            _project_result(project),
            _pr_result(pr),
            _pr_result(comment),
        ]

        comment_update = CommentUpdate(body="Sneaky edit")
        with pytest.raises(HTTPException) as exc_info:
            await service.update_comment(PROJECT_ID, 1, COMMENT_ID, comment_update, user)
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# delete_comment
# ---------------------------------------------------------------------------


class TestDeleteComment:
    @pytest.mark.asyncio
    async def test_delete_comment_by_author(
        self, service: PullRequestService, mock_db: AsyncMock
    ) -> None:
        """Comment author can delete their comment."""
        project = _make_project()
        pr = _make_pr()
        comment = _make_comment(author_id=EDITOR_ID)
        user = _make_user(EDITOR_ID)

        mock_db.execute.side_effect = [
            _project_result(project),
            _pr_result(pr),
            _pr_result(comment),
        ]

        await service.delete_comment(PROJECT_ID, 1, COMMENT_ID, user)
        mock_db.delete.assert_awaited_once_with(comment)

    @pytest.mark.asyncio
    async def test_delete_comment_by_owner(
        self, service: PullRequestService, mock_db: AsyncMock
    ) -> None:
        """Project owner can delete any comment."""
        project = _make_project()
        pr = _make_pr()
        comment = _make_comment(author_id=EDITOR_ID)
        user = _make_user(OWNER_ID)  # owner, not comment author

        mock_db.execute.side_effect = [
            _project_result(project),
            _pr_result(pr),
            _pr_result(comment),
        ]

        await service.delete_comment(PROJECT_ID, 1, COMMENT_ID, user)
        mock_db.delete.assert_awaited_once_with(comment)

    @pytest.mark.asyncio
    async def test_delete_comment_not_found(
        self, service: PullRequestService, mock_db: AsyncMock
    ) -> None:
        """Returns 404 when comment does not exist."""
        project = _make_project()
        pr = _make_pr()
        user = _make_user(EDITOR_ID)

        mock_db.execute.side_effect = [
            _project_result(project),
            _pr_result(pr),
            _pr_result(None),
        ]

        with pytest.raises(HTTPException) as exc_info:
            await service.delete_comment(PROJECT_ID, 1, COMMENT_ID, user)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_comment_viewer_forbidden(
        self, service: PullRequestService, mock_db: AsyncMock
    ) -> None:
        """Viewer cannot delete someone else's comment."""
        project = _make_project()
        pr = _make_pr()
        comment = _make_comment(author_id=EDITOR_ID)
        user = _make_user(VIEWER_ID)  # viewer, not comment author

        mock_db.execute.side_effect = [
            _project_result(project),
            _pr_result(pr),
            _pr_result(comment),
        ]

        with pytest.raises(HTTPException) as exc_info:
            await service.delete_comment(PROJECT_ID, 1, COMMENT_ID, user)
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# list_branches
# ---------------------------------------------------------------------------


class TestListBranches:
    @pytest.mark.asyncio
    async def test_list_branches_success(
        self, service: PullRequestService, mock_db: AsyncMock, mock_git_service: MagicMock
    ) -> None:
        """Returns branch list for an accessible project."""
        project = _make_project()
        user = _make_user(EDITOR_ID)

        mock_db.execute.return_value = _project_result(project)
        mock_git_service.list_branches.return_value = [
            _make_git_branch_info("main"),
            _make_git_branch_info("feature"),
        ]

        result = await service.list_branches(PROJECT_ID, user)
        assert len(result.items) == 2
        assert result.current_branch == "main"
        assert result.default_branch == "main"

    @pytest.mark.asyncio
    async def test_list_branches_private_project_forbidden(
        self, service: PullRequestService, mock_db: AsyncMock
    ) -> None:
        """Non-member cannot list branches of a private project."""
        project = _make_project(is_public=False)
        user = _make_user(OTHER_ID)

        mock_db.execute.return_value = _project_result(project)

        with pytest.raises(HTTPException) as exc_info:
            await service.list_branches(PROJECT_ID, user)
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# create_branch
# ---------------------------------------------------------------------------


class TestCreateBranch:
    @pytest.mark.asyncio
    async def test_create_branch_success(
        self, service: PullRequestService, mock_db: AsyncMock, mock_git_service: MagicMock
    ) -> None:
        """Editor can create a branch."""
        project = _make_project()
        user = _make_user(EDITOR_ID)

        mock_db.execute.return_value = _project_result(project)
        mock_git_service.create_branch.return_value = _make_git_branch_info("feature")

        branch_create = BranchCreate(name="feature", from_branch="main")
        result = await service.create_branch(PROJECT_ID, branch_create, user)
        assert result.name == "feature"

    @pytest.mark.asyncio
    async def test_create_branch_git_error_returns_400(
        self, service: PullRequestService, mock_db: AsyncMock, mock_git_service: MagicMock
    ) -> None:
        """Git errors creating a branch become 400."""
        project = _make_project()
        user = _make_user(EDITOR_ID)

        mock_db.execute.return_value = _project_result(project)
        mock_git_service.create_branch.side_effect = ValueError("branch already exists")

        branch_create = BranchCreate(name="existing", from_branch="main")
        with pytest.raises(HTTPException) as exc_info:
            await service.create_branch(PROJECT_ID, branch_create, user)
        assert exc_info.value.status_code == 400
        assert "branch already exists" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_create_branch_viewer_forbidden(
        self, service: PullRequestService, mock_db: AsyncMock
    ) -> None:
        """Viewers cannot create branches."""
        project = _make_project()
        user = _make_user(VIEWER_ID)

        mock_db.execute.return_value = _project_result(project)

        branch_create = BranchCreate(name="my-branch")
        with pytest.raises(HTTPException) as exc_info:
            await service.create_branch(PROJECT_ID, branch_create, user)
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# switch_branch
# ---------------------------------------------------------------------------


class TestSwitchBranch:
    @pytest.mark.asyncio
    async def test_switch_branch_success(
        self, service: PullRequestService, mock_db: AsyncMock, mock_git_service: MagicMock
    ) -> None:
        """Editor can switch to an existing branch."""
        project = _make_project()
        user = _make_user(EDITOR_ID)

        mock_db.execute.return_value = _project_result(project)
        mock_git_service.switch_branch.return_value = _make_git_branch_info("feature")

        result = await service.switch_branch(PROJECT_ID, "feature", user)
        assert result.name == "feature"

    @pytest.mark.asyncio
    async def test_switch_branch_not_found_raises_404(
        self, service: PullRequestService, mock_db: AsyncMock, mock_git_service: MagicMock
    ) -> None:
        """KeyError from git service becomes 404."""
        project = _make_project()
        user = _make_user(EDITOR_ID)

        mock_db.execute.return_value = _project_result(project)
        mock_git_service.switch_branch.side_effect = KeyError("no-such-branch")

        with pytest.raises(HTTPException) as exc_info:
            await service.switch_branch(PROJECT_ID, "no-such-branch", user)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_switch_branch_generic_error_returns_400(
        self, service: PullRequestService, mock_db: AsyncMock, mock_git_service: MagicMock
    ) -> None:
        """Generic git errors become 400."""
        project = _make_project()
        user = _make_user(EDITOR_ID)

        mock_db.execute.return_value = _project_result(project)
        mock_git_service.switch_branch.side_effect = RuntimeError("detached HEAD")

        with pytest.raises(HTTPException) as exc_info:
            await service.switch_branch(PROJECT_ID, "feature", user)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_switch_branch_viewer_forbidden(
        self, service: PullRequestService, mock_db: AsyncMock
    ) -> None:
        """Viewers cannot switch branches."""
        project = _make_project()
        user = _make_user(VIEWER_ID)

        mock_db.execute.return_value = _project_result(project)

        with pytest.raises(HTTPException) as exc_info:
            await service.switch_branch(PROJECT_ID, "main", user)
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# get_github_integration
# ---------------------------------------------------------------------------


class TestGetGitHubIntegration:
    @pytest.mark.asyncio
    async def test_get_github_integration_returns_response(
        self, service: PullRequestService, mock_db: AsyncMock
    ) -> None:
        """Owner can get GitHub integration details when one exists."""
        project = _make_project()
        user = _make_user(OWNER_ID)

        integration = MagicMock()
        integration.id = uuid.uuid4()
        integration.project_id = PROJECT_ID
        integration.repo_owner = "myorg"
        integration.repo_name = "myrepo"
        integration.default_branch = "main"
        integration.ontology_file_path = "ontology.ttl"
        integration.turtle_file_path = None
        integration.connected_by_user_id = None
        integration.webhooks_enabled = False
        integration.webhook_secret = None
        integration.github_hook_id = None
        integration.sync_enabled = True
        integration.last_sync_at = None
        integration.created_at = datetime.now(UTC)
        integration.updated_at = None

        mock_db.execute.side_effect = [
            _project_result(project),
            _scalar_result(integration),
        ]

        result = await service.get_github_integration(PROJECT_ID, user)
        assert result is not None
        assert result.repo_owner == "myorg"

    @pytest.mark.asyncio
    async def test_get_github_integration_no_integration(
        self, service: PullRequestService, mock_db: AsyncMock
    ) -> None:
        """Returns None when no GitHub integration exists."""
        project = _make_project()
        user = _make_user(OWNER_ID)

        mock_db.execute.side_effect = [
            _project_result(project),
            _scalar_result(None),
        ]

        result = await service.get_github_integration(PROJECT_ID, user)
        assert result is None


# ---------------------------------------------------------------------------
# delete_github_integration
# ---------------------------------------------------------------------------


class TestDeleteGitHubIntegration:
    @pytest.mark.asyncio
    async def test_delete_github_integration_success(
        self, service: PullRequestService, mock_db: AsyncMock
    ) -> None:
        """Owner can delete GitHub integration."""
        project = _make_project()
        user = _make_user(OWNER_ID)

        integration = MagicMock()

        mock_db.execute.side_effect = [
            _project_result(project),
            _scalar_result(integration),
        ]

        await service.delete_github_integration(PROJECT_ID, user)
        mock_db.delete.assert_awaited_once_with(integration)
        mock_db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_delete_github_integration_not_owner_forbidden(
        self, service: PullRequestService, mock_db: AsyncMock
    ) -> None:
        """Non-owner cannot delete GitHub integration."""
        project = _make_project()
        user = _make_user(EDITOR_ID)

        mock_db.execute.return_value = _project_result(project)

        with pytest.raises(HTTPException) as exc_info:
            await service.delete_github_integration(PROJECT_ID, user)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_delete_github_integration_not_found(
        self, service: PullRequestService, mock_db: AsyncMock
    ) -> None:
        """Returns 404 when integration does not exist."""
        project = _make_project()
        user = _make_user(OWNER_ID)

        mock_db.execute.side_effect = [
            _project_result(project),
            _scalar_result(None),
        ]

        with pytest.raises(HTTPException) as exc_info:
            await service.delete_github_integration(PROJECT_ID, user)
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# _sync_remote_config_for_webhooks
# ---------------------------------------------------------------------------


class TestSyncRemoteConfigForWebhooks:
    @pytest.mark.asyncio
    async def test_creates_sync_config_when_webhooks_enabled(
        self, service: PullRequestService, mock_db: AsyncMock
    ) -> None:
        """Creates RemoteSyncConfig when webhooks_enabled=True and none exists."""
        integration = MagicMock()
        integration.repo_owner = "org"
        integration.repo_name = "repo"
        integration.default_branch = "main"
        integration.ontology_file_path = "ontology.ttl"

        # No existing sync config
        mock_db.execute.return_value = _scalar_result(None)

        await service._sync_remote_config_for_webhooks(
            PROJECT_ID, integration, webhooks_enabled=True
        )

        mock_db.add.assert_called_once()
        added_config = mock_db.add.call_args[0][0]
        assert added_config.frequency == "webhook"
        assert added_config.enabled is True
        assert added_config.branch == "main"
        assert added_config.file_path == "ontology.ttl"

    @pytest.mark.asyncio
    async def test_updates_sync_config_when_webhooks_disabled(
        self, service: PullRequestService, mock_db: AsyncMock
    ) -> None:
        """Sets frequency to 'manual' when webhooks disabled and webhook config exists."""
        integration = MagicMock()

        sync_config = MagicMock()
        sync_config.frequency = "webhook"
        mock_db.execute.return_value = _scalar_result(sync_config)

        await service._sync_remote_config_for_webhooks(
            PROJECT_ID, integration, webhooks_enabled=False
        )

        assert sync_config.frequency == "manual"

    @pytest.mark.asyncio
    async def test_updates_existing_config_when_webhooks_enabled(
        self, service: PullRequestService, mock_db: AsyncMock
    ) -> None:
        """Updates existing sync config to 'webhook' when already present."""
        integration = MagicMock()
        integration.repo_owner = "org"
        integration.repo_name = "repo"
        integration.default_branch = "main"
        integration.ontology_file_path = "ontology.ttl"

        sync_config = MagicMock()
        sync_config.frequency = "manual"
        sync_config.enabled = False
        mock_db.execute.return_value = _scalar_result(sync_config)

        await service._sync_remote_config_for_webhooks(
            PROJECT_ID, integration, webhooks_enabled=True
        )

        assert sync_config.frequency == "webhook"
        assert sync_config.enabled is True


# ---------------------------------------------------------------------------
# handle_github_pr_webhook
# ---------------------------------------------------------------------------


class TestHandleGitHubPRWebhook:
    @pytest.mark.asyncio
    async def test_closed_merged_pr(self, service: PullRequestService, mock_db: AsyncMock) -> None:
        """Sets status to MERGED when action=closed and merged=True."""
        integration = MagicMock()
        integration.sync_enabled = True

        pr = MagicMock()
        pr.status = "open"

        mock_db.execute.side_effect = [
            _scalar_result(integration),
            _scalar_result(pr),
        ]

        await service.handle_github_pr_webhook(
            PROJECT_ID,
            action="closed",
            pr_data={"number": 42, "merged": True},
        )

        assert pr.status == "merged"
        mock_db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_closed_not_merged(self, service: PullRequestService, mock_db: AsyncMock) -> None:
        """Sets status to CLOSED when action=closed and merged=False."""
        integration = MagicMock()
        integration.sync_enabled = True

        pr = MagicMock()
        pr.status = "open"

        mock_db.execute.side_effect = [
            _scalar_result(integration),
            _scalar_result(pr),
        ]

        await service.handle_github_pr_webhook(
            PROJECT_ID,
            action="closed",
            pr_data={"number": 42, "merged": False},
        )

        assert pr.status == "closed"
        mock_db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_reopened_pr(self, service: PullRequestService, mock_db: AsyncMock) -> None:
        """Sets status to OPEN when action=reopened."""
        integration = MagicMock()
        integration.sync_enabled = True

        pr = MagicMock()
        pr.status = "closed"

        mock_db.execute.side_effect = [
            _scalar_result(integration),
            _scalar_result(pr),
        ]

        await service.handle_github_pr_webhook(
            PROJECT_ID,
            action="reopened",
            pr_data={"number": 42},
        )

        assert pr.status == "open"

    @pytest.mark.asyncio
    async def test_edited_pr(self, service: PullRequestService, mock_db: AsyncMock) -> None:
        """Updates title/description when action=edited."""
        integration = MagicMock()
        integration.sync_enabled = True

        pr = MagicMock()
        pr.title = "Old title"
        pr.description = "Old body"

        mock_db.execute.side_effect = [
            _scalar_result(integration),
            _scalar_result(pr),
        ]

        await service.handle_github_pr_webhook(
            PROJECT_ID,
            action="edited",
            pr_data={"number": 42, "title": "New title", "body": "New body"},
        )

        assert pr.title == "New title"
        assert pr.description == "New body"

    @pytest.mark.asyncio
    async def test_no_integration_returns_early(
        self, service: PullRequestService, mock_db: AsyncMock
    ) -> None:
        """Returns early when no integration or sync disabled."""
        mock_db.execute.return_value = _scalar_result(None)

        await service.handle_github_pr_webhook(
            PROJECT_ID,
            action="closed",
            pr_data={"number": 1},
        )

        mock_db.commit.assert_not_awaited()


# ---------------------------------------------------------------------------
# handle_github_review_webhook
# ---------------------------------------------------------------------------


class TestHandleGitHubReviewWebhook:
    @pytest.mark.asyncio
    async def test_submitted_review_creates_record(
        self, service: PullRequestService, mock_db: AsyncMock
    ) -> None:
        """Creates a review record for a submitted GitHub review."""
        integration = MagicMock()
        integration.sync_enabled = True

        pr = MagicMock()
        pr.id = PR_ID

        # DB: get integration, find PR, check existing review (none)
        mock_db.execute.side_effect = [
            _scalar_result(integration),
            _scalar_result(pr),
            _scalar_result(None),  # no existing review
        ]

        await service.handle_github_review_webhook(
            PROJECT_ID,
            action="submitted",
            review_data={
                "id": 999,
                "state": "APPROVED",
                "body": "LGTM",
                "user": {"login": "ghuser"},
            },
            pr_data={"number": 42},
        )

        mock_db.add.assert_called_once()
        mock_db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_non_submitted_action_returns_early(
        self, service: PullRequestService, mock_db: AsyncMock
    ) -> None:
        """Non-submitted actions are ignored."""
        await service.handle_github_review_webhook(
            PROJECT_ID,
            action="dismissed",
            review_data={"id": 1},
            pr_data={"number": 1},
        )

        mock_db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_existing_review_skipped(
        self, service: PullRequestService, mock_db: AsyncMock
    ) -> None:
        """Duplicate review IDs are skipped."""
        integration = MagicMock()
        integration.sync_enabled = True

        pr = MagicMock()
        pr.id = PR_ID

        existing_review = MagicMock()

        mock_db.execute.side_effect = [
            _scalar_result(integration),
            _scalar_result(pr),
            _scalar_result(existing_review),  # already exists
        ]

        await service.handle_github_review_webhook(
            PROJECT_ID,
            action="submitted",
            review_data={
                "id": 999,
                "state": "APPROVED",
                "body": "LGTM",
                "user": {"login": "ghuser"},
            },
            pr_data={"number": 42},
        )

        mock_db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_local_pr_returns_early(
        self, service: PullRequestService, mock_db: AsyncMock
    ) -> None:
        """Returns early when local PR not found."""
        integration = MagicMock()
        integration.sync_enabled = True

        mock_db.execute.side_effect = [
            _scalar_result(integration),
            _scalar_result(None),  # no local PR
        ]

        await service.handle_github_review_webhook(
            PROJECT_ID,
            action="submitted",
            review_data={
                "id": 999,
                "state": "APPROVED",
                "body": "LGTM",
                "user": {"login": "ghuser"},
            },
            pr_data={"number": 42},
        )

        mock_db.add.assert_not_called()


# ---------------------------------------------------------------------------
# handle_github_push_webhook
# ---------------------------------------------------------------------------


class TestHandleGitHubPushWebhook:
    @pytest.mark.asyncio
    async def test_push_to_main_pulls_changes(
        self, service: PullRequestService, mock_db: AsyncMock, mock_git_service: MagicMock
    ) -> None:
        """Pull latest changes when push is to the default branch."""
        integration = MagicMock()
        integration.sync_enabled = True
        integration.default_branch = "main"
        integration.last_sync_at = None

        mock_db.execute.return_value = _scalar_result(integration)
        mock_git_service.pull_branch = MagicMock()

        await service.handle_github_push_webhook(
            PROJECT_ID,
            ref="refs/heads/main",
            commits=[],
        )

        mock_git_service.pull_branch.assert_called_once_with(PROJECT_ID, "main", "origin")
        mock_db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_push_to_non_default_branch_ignored(
        self, service: PullRequestService, mock_db: AsyncMock
    ) -> None:
        """Pushes to non-default branches are ignored."""
        integration = MagicMock()
        integration.sync_enabled = True
        integration.default_branch = "main"

        mock_db.execute.return_value = _scalar_result(integration)

        await service.handle_github_push_webhook(
            PROJECT_ID,
            ref="refs/heads/feature",
            commits=[],
        )

        mock_db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_push_pull_failure_logged(
        self, service: PullRequestService, mock_db: AsyncMock, mock_git_service: MagicMock
    ) -> None:
        """Git pull failure is caught and logged, not raised."""
        integration = MagicMock()
        integration.sync_enabled = True
        integration.default_branch = "main"

        mock_db.execute.return_value = _scalar_result(integration)
        mock_git_service.pull_branch = MagicMock(side_effect=RuntimeError("network error"))

        await service.handle_github_push_webhook(
            PROJECT_ID,
            ref="refs/heads/main",
            commits=[],
        )

        # Should not raise, just log
        mock_db.commit.assert_not_awaited()


# ---------------------------------------------------------------------------
# create_github_integration
# ---------------------------------------------------------------------------


class TestCreateGitHubIntegration:
    @pytest.mark.asyncio
    async def test_create_integration_success(
        self, service: PullRequestService, mock_db: AsyncMock, mock_git_service: MagicMock
    ) -> None:
        """Owner can create a GitHub integration."""
        from ontokit.schemas.pull_request import GitHubIntegrationCreate

        project = _make_project()
        user = _make_user(OWNER_ID)

        # DB: get project, check existing integration (none), commit, refresh
        mock_db.execute.side_effect = [
            _project_result(project),
            _scalar_result(None),  # no existing integration
        ]

        # After refresh, populate attributes on the ORM object
        def _populate_integration(obj: object, *_args: object, **_kwargs: object) -> None:
            obj.id = uuid.uuid4()  # type: ignore[attr-defined]
            obj.created_at = datetime.now(UTC)  # type: ignore[attr-defined]
            obj.updated_at = None  # type: ignore[attr-defined]
            obj.installation_id = None  # type: ignore[attr-defined]
            obj.connected_by_user_id = user.id  # type: ignore[attr-defined]
            obj.sync_enabled = True  # type: ignore[attr-defined]
            obj.last_sync_at = None  # type: ignore[attr-defined]
            obj.webhooks_enabled = False  # type: ignore[attr-defined]
            obj.webhook_secret = None  # type: ignore[attr-defined]
            obj.github_hook_id = None  # type: ignore[attr-defined]

        mock_db.refresh.side_effect = _populate_integration

        create_data = GitHubIntegrationCreate(
            repo_owner="myorg",
            repo_name="myrepo",
        )
        result = await service.create_github_integration(PROJECT_ID, create_data, user)

        mock_db.add.assert_called_once()
        mock_git_service.setup_remote.assert_called_once()
        assert result.repo_owner == "myorg"

    @pytest.mark.asyncio
    async def test_create_integration_already_exists(
        self, service: PullRequestService, mock_db: AsyncMock
    ) -> None:
        """Returns 400 when integration already exists."""
        from ontokit.schemas.pull_request import GitHubIntegrationCreate

        project = _make_project()
        user = _make_user(OWNER_ID)
        existing = MagicMock()

        mock_db.execute.side_effect = [
            _project_result(project),
            _scalar_result(existing),
        ]

        create_data = GitHubIntegrationCreate(repo_owner="org", repo_name="repo")
        with pytest.raises(HTTPException) as exc_info:
            await service.create_github_integration(PROJECT_ID, create_data, user)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_create_integration_not_owner_forbidden(
        self, service: PullRequestService, mock_db: AsyncMock
    ) -> None:
        """Non-owner cannot create integration."""
        from ontokit.schemas.pull_request import GitHubIntegrationCreate

        project = _make_project()
        user = _make_user(EDITOR_ID)

        mock_db.execute.return_value = _project_result(project)

        create_data = GitHubIntegrationCreate(repo_owner="org", repo_name="repo")
        with pytest.raises(HTTPException) as exc_info:
            await service.create_github_integration(PROJECT_ID, create_data, user)
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# update_github_integration
# ---------------------------------------------------------------------------


class TestUpdateGitHubIntegration:
    @pytest.mark.asyncio
    async def test_update_integration_success(
        self, service: PullRequestService, mock_db: AsyncMock
    ) -> None:
        """Owner can update integration settings."""
        from ontokit.schemas.pull_request import GitHubIntegrationUpdate

        project = _make_project()
        user = _make_user(OWNER_ID)

        integration = MagicMock()
        integration.id = uuid.uuid4()
        integration.project_id = PROJECT_ID
        integration.repo_owner = "org"
        integration.repo_name = "repo"
        integration.default_branch = "main"
        integration.ontology_file_path = None
        integration.turtle_file_path = None
        integration.connected_by_user_id = user.id
        integration.webhooks_enabled = False
        integration.webhook_secret = None
        integration.github_hook_id = None
        integration.sync_enabled = True
        integration.last_sync_at = None
        integration.installation_id = None
        integration.created_at = datetime.now(UTC)
        integration.updated_at = None

        mock_db.execute.side_effect = [
            _project_result(project),
            _scalar_result(integration),
        ]
        mock_db.refresh = AsyncMock()

        update_data = GitHubIntegrationUpdate(default_branch="develop", sync_enabled=False)
        result = await service.update_github_integration(PROJECT_ID, update_data, user)

        assert integration.default_branch == "develop"
        assert integration.sync_enabled is False
        assert result is not None

    @pytest.mark.asyncio
    async def test_update_integration_enable_webhooks(
        self, service: PullRequestService, mock_db: AsyncMock
    ) -> None:
        """Enabling webhooks generates a secret and syncs remote config."""
        from ontokit.schemas.pull_request import GitHubIntegrationUpdate

        project = _make_project()
        user = _make_user(OWNER_ID)

        integration = MagicMock()
        integration.id = uuid.uuid4()
        integration.project_id = PROJECT_ID
        integration.repo_owner = "org"
        integration.repo_name = "repo"
        integration.default_branch = "main"
        integration.ontology_file_path = None
        integration.turtle_file_path = None
        integration.connected_by_user_id = user.id
        integration.webhooks_enabled = False
        integration.webhook_secret = None
        integration.github_hook_id = None
        integration.sync_enabled = True
        integration.last_sync_at = None
        integration.installation_id = None
        integration.created_at = datetime.now(UTC)
        integration.updated_at = None

        mock_db.execute.side_effect = [
            _project_result(project),
            _scalar_result(integration),
            _scalar_result(None),  # _sync_remote_config_for_webhooks query
        ]
        mock_db.refresh = AsyncMock()

        update_data = GitHubIntegrationUpdate(webhooks_enabled=True)
        result = await service.update_github_integration(PROJECT_ID, update_data, user)

        assert integration.webhooks_enabled is True
        assert result is not None

    @pytest.mark.asyncio
    async def test_update_integration_not_found(
        self, service: PullRequestService, mock_db: AsyncMock
    ) -> None:
        """Returns 404 when integration not found."""
        from ontokit.schemas.pull_request import GitHubIntegrationUpdate

        project = _make_project()
        user = _make_user(OWNER_ID)

        mock_db.execute.side_effect = [
            _project_result(project),
            _scalar_result(None),
        ]

        update_data = GitHubIntegrationUpdate(sync_enabled=False)
        with pytest.raises(HTTPException) as exc_info:
            await service.update_github_integration(PROJECT_ID, update_data, user)
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# get_webhook_secret
# ---------------------------------------------------------------------------


class TestGetWebhookSecret:
    @pytest.mark.asyncio
    async def test_returns_secret(self, service: PullRequestService, mock_db: AsyncMock) -> None:
        """Returns webhook secret and URL for owner."""
        project = _make_project()
        user = _make_user(OWNER_ID)

        integration = MagicMock()
        integration.webhooks_enabled = True
        integration.webhook_secret = "s3cret"

        mock_db.execute.side_effect = [
            _project_result(project),
            _scalar_result(integration),
        ]

        result = await service.get_webhook_secret(PROJECT_ID, user)
        assert result["webhook_secret"] == "s3cret"
        assert "webhook_url" in result

    @pytest.mark.asyncio
    async def test_no_integration_returns_404(
        self, service: PullRequestService, mock_db: AsyncMock
    ) -> None:
        """Returns 404 when integration not found."""
        project = _make_project()
        user = _make_user(OWNER_ID)

        mock_db.execute.side_effect = [
            _project_result(project),
            _scalar_result(None),
        ]

        with pytest.raises(HTTPException) as exc_info:
            await service.get_webhook_secret(PROJECT_ID, user)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_webhooks_not_enabled_returns_400(
        self, service: PullRequestService, mock_db: AsyncMock
    ) -> None:
        """Returns 400 when webhooks are not enabled."""
        project = _make_project()
        user = _make_user(OWNER_ID)

        integration = MagicMock()
        integration.webhooks_enabled = False

        mock_db.execute.side_effect = [
            _project_result(project),
            _scalar_result(integration),
        ]

        with pytest.raises(HTTPException) as exc_info:
            await service.get_webhook_secret(PROJECT_ID, user)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_not_owner_forbidden(
        self, service: PullRequestService, mock_db: AsyncMock
    ) -> None:
        """Non-owner cannot view webhook secret."""
        project = _make_project()
        user = _make_user(EDITOR_ID)

        mock_db.execute.return_value = _project_result(project)

        with pytest.raises(HTTPException) as exc_info:
            await service.get_webhook_secret(PROJECT_ID, user)
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# get_pr_commits — forbidden and merged PR paths
# ---------------------------------------------------------------------------


class TestGetPRCommits:
    @pytest.mark.asyncio
    async def test_private_project_forbidden(
        self, service: PullRequestService, mock_db: AsyncMock
    ) -> None:
        """Non-member cannot get PR commits on a private project."""
        project = _make_project(is_public=False)
        user = _make_user(OTHER_ID)

        mock_db.execute.return_value = _project_result(project)

        with pytest.raises(HTTPException) as exc_info:
            await service.get_pr_commits(PROJECT_ID, 1, user)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_merged_pr_uses_stored_hashes(
        self, service: PullRequestService, mock_db: AsyncMock, mock_git_service: MagicMock
    ) -> None:
        """Merged PRs use stored commit hashes instead of branch names."""
        project = _make_project()
        user = _make_user(OWNER_ID)

        pr = _make_pr(status="merged")
        pr.base_commit_hash = "base111"
        pr.head_commit_hash = "head222"

        mock_db.execute.side_effect = [
            _project_result(project),
            _pr_result(pr),
        ]

        commit = MagicMock()
        commit.hash = "abc"
        commit.short_hash = "abc"
        commit.message = "fix"
        commit.author_name = "Dev"
        commit.author_email = "dev@x.com"
        commit.timestamp = "2025-01-01T00:00:00+00:00"
        mock_git_service.get_commits_between = MagicMock(return_value=[commit])

        result = await service.get_pr_commits(PROJECT_ID, 1, user)

        mock_git_service.get_commits_between.assert_called_once_with(
            PROJECT_ID, "base111", "head222"
        )
        assert result.total == 1


# ---------------------------------------------------------------------------
# get_pr_diff — forbidden path
# ---------------------------------------------------------------------------


class TestGetPRDiff:
    @pytest.mark.asyncio
    async def test_private_project_forbidden(
        self, service: PullRequestService, mock_db: AsyncMock
    ) -> None:
        """Non-member cannot get PR diff on a private project."""
        project = _make_project(is_public=False)
        user = _make_user(OTHER_ID)

        mock_db.execute.return_value = _project_result(project)

        with pytest.raises(HTTPException) as exc_info:
            await service.get_pr_diff(PROJECT_ID, 1, user)
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# list_comments — forbidden path
# ---------------------------------------------------------------------------


class TestListComments:
    @pytest.mark.asyncio
    async def test_private_project_forbidden(
        self, service: PullRequestService, mock_db: AsyncMock
    ) -> None:
        """Non-member cannot list comments on a private project."""
        project = _make_project(is_public=False)
        user = _make_user(OTHER_ID)

        mock_db.execute.return_value = _project_result(project)

        with pytest.raises(HTTPException) as exc_info:
            await service.list_comments(PROJECT_ID, 1, user)
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# create_comment — parent validation and GitHub sync
# ---------------------------------------------------------------------------


class TestCreateComment:
    @pytest.mark.asyncio
    async def test_create_comment_private_project_forbidden(
        self, service: PullRequestService, mock_db: AsyncMock
    ) -> None:
        """Non-member cannot comment on a private project."""
        from ontokit.schemas.pull_request import CommentCreate

        project = _make_project(is_public=False)
        user = _make_user(OTHER_ID)

        mock_db.execute.side_effect = [
            _project_result(project),
            _pr_result(_make_pr()),
        ]

        comment_data = CommentCreate(body="Hello")
        with pytest.raises(HTTPException) as exc_info:
            await service.create_comment(PROJECT_ID, 1, comment_data, user)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_create_comment_parent_not_found(
        self, service: PullRequestService, mock_db: AsyncMock
    ) -> None:
        """Returns 404 when parent comment does not exist."""
        from ontokit.schemas.pull_request import CommentCreate

        project = _make_project()
        pr = _make_pr()
        user = _make_user(EDITOR_ID)

        mock_db.execute.side_effect = [
            _project_result(project),
            _pr_result(pr),
            _scalar_result(None),  # parent not found
        ]

        comment_data = CommentCreate(body="reply", parent_id=COMMENT_ID)
        with pytest.raises(HTTPException) as exc_info:
            await service.create_comment(PROJECT_ID, 1, comment_data, user)
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# create_review — GitHub sync path
# ---------------------------------------------------------------------------


class TestCreateReviewGitHubSync:
    @pytest.mark.asyncio
    async def test_review_synced_to_github(
        self, service: PullRequestService, mock_db: AsyncMock, mock_github_service: MagicMock
    ) -> None:
        """Review is synced to GitHub when PR has a github_pr_number."""
        project = _make_project()
        pr = _make_pr(author_id=EDITOR_ID, github_pr_number=42)
        user = _make_user(OWNER_ID)

        integration = MagicMock()
        integration.repo_owner = "org"
        integration.repo_name = "repo"
        integration.sync_enabled = True
        integration.connected_by_user_id = "user-123"

        token_row = MagicMock()
        token_row.encrypted_token = "encrypted-abc"

        gh_review = MagicMock()
        gh_review.id = 777

        mock_github_service.create_review = AsyncMock(return_value=gh_review)

        def _populate(obj: object) -> None:
            obj.id = uuid.uuid4()  # type: ignore[attr-defined]
            obj.created_at = datetime.now(UTC)  # type: ignore[attr-defined]

        mock_db.execute.side_effect = [
            _project_result(project),
            _pr_result(pr),
            _scalar_result(integration),  # _get_github_integration
            _scalar_result(token_row),  # UserGitHubToken
        ]
        mock_db.refresh.side_effect = _populate

        with patch(
            "ontokit.services.pull_request_service.decrypt_token",
            return_value="decrypted-token",
        ):
            result = await service.create_review(
                PROJECT_ID, 1, ReviewCreate(status="approved", body="LGTM"), user
            )

        mock_github_service.create_review.assert_awaited_once()
        assert result is not None


# ---------------------------------------------------------------------------
# _sync_merge_commits_to_prs — timestamp parse error
# ---------------------------------------------------------------------------


class TestSyncMergeCommitsTimestampError:
    @pytest.mark.asyncio
    async def test_invalid_timestamp_uses_utcnow(
        self, service: PullRequestService, mock_git_service: MagicMock, mock_db: AsyncMock
    ) -> None:
        """Invalid timestamp falls back to datetime.now(UTC)."""
        commit = _make_merge_commit(merged_branch="hotfix")
        commit.timestamp = "not-a-date"
        mock_git_service.get_history.return_value = [commit]

        merged_prs_result = _scalars_result([])
        max_number_result = _scalar_result(0)
        mock_db.execute.side_effect = [merged_prs_result, max_number_result]

        await service._sync_merge_commits_to_prs(PROJECT_ID)

        mock_db.add.assert_called_once()


# ---------------------------------------------------------------------------
# update_pull_request — GitHub sync path
# ---------------------------------------------------------------------------


class TestUpdatePullRequestGitHubSync:
    @pytest.mark.asyncio
    async def test_update_pr_syncs_to_github(
        self, service: PullRequestService, mock_db: AsyncMock, mock_github_service: MagicMock
    ) -> None:
        """update_pull_request syncs title/description to GitHub when github_pr_number is set."""
        from ontokit.schemas.pull_request import PRUpdate

        project = _make_project()
        pr = _make_pr(author_id=OWNER_ID, github_pr_number=42)
        user = _make_user(OWNER_ID)

        integration = MagicMock()
        integration.repo_owner = "org"
        integration.repo_name = "repo"
        integration.sync_enabled = True
        integration.connected_by_user_id = "user-123"

        token_row = MagicMock()
        token_row.encrypted_token = "encrypted-abc"

        mock_github_service.update_pull_request = AsyncMock()

        mock_db.execute.side_effect = [
            _project_result(project),
            _pr_result(pr),
            _scalar_result(integration),  # _get_github_integration
            _scalar_result(token_row),  # UserGitHubToken
            _project_result(project),  # _to_pr_response -> _get_project
        ]
        mock_db.refresh = AsyncMock()

        with patch(
            "ontokit.services.pull_request_service.decrypt_token",
            return_value="decrypted-token",
        ):
            result = await service.update_pull_request(
                PROJECT_ID, 1, PRUpdate(title="Updated title"), user
            )

        mock_github_service.update_pull_request.assert_awaited_once()
        assert result is not None


# ---------------------------------------------------------------------------
# merge_pull_request — GitHub sync path
# ---------------------------------------------------------------------------


class TestMergePullRequestGitHubSync:
    @pytest.mark.asyncio
    async def test_merge_syncs_to_github(
        self,
        service: PullRequestService,
        mock_db: AsyncMock,
        mock_git_service: MagicMock,
        mock_github_service: MagicMock,
    ) -> None:
        """merge_pull_request syncs merge to GitHub when github_pr_number is set."""
        project = _make_project()
        pr = _make_pr(author_id=OWNER_ID, github_pr_number=42)
        user = _make_user(OWNER_ID)

        main_branch = MagicMock()
        main_branch.name = "main"
        main_branch.commit_hash = "aaa"
        feature_branch = MagicMock()
        feature_branch.name = "feature"
        feature_branch.commit_hash = "bbb"
        mock_git_service.list_branches.return_value = [main_branch, feature_branch]

        merge_result_obj = MagicMock()
        merge_result_obj.success = True
        merge_result_obj.merge_commit_hash = "ccc"
        mock_git_service.merge_branch.return_value = merge_result_obj

        integration = MagicMock()
        integration.repo_owner = "org"
        integration.repo_name = "repo"
        integration.sync_enabled = True
        integration.connected_by_user_id = "user-123"

        token_row = MagicMock()
        token_row.encrypted_token = "encrypted-abc"

        mock_github_service.merge_pull_request = AsyncMock()

        mock_db.execute.side_effect = [
            _project_result(project),
            _pr_result(pr),
            _scalar_result(integration),  # _get_github_integration
            _scalar_result(token_row),  # UserGitHubToken
        ]

        with patch(
            "ontokit.services.pull_request_service.decrypt_token",
            return_value="decrypted-token",
        ):
            result = await service.merge_pull_request(PROJECT_ID, 1, PRMergeRequest(), user)

        assert result.success is True
        mock_github_service.merge_pull_request.assert_awaited_once()


# ---------------------------------------------------------------------------
# close / reopen — exception handling in GitHub sync
# ---------------------------------------------------------------------------


class TestCloseReopenExceptionHandling:
    @pytest.mark.asyncio
    async def test_close_github_exception_still_closes(
        self,
        service: PullRequestService,
        mock_db: AsyncMock,
        mock_github_service: MagicMock,
    ) -> None:
        """GitHub sync failure during close doesn't prevent local close."""
        project = _make_project()
        pr = _make_pr(author_id=OWNER_ID, github_pr_number=42)
        user = _make_user(OWNER_ID)

        integration = MagicMock()
        integration.repo_owner = "org"
        integration.repo_name = "repo"
        integration.sync_enabled = True
        integration.connected_by_user_id = "user-123"

        token_row = MagicMock()
        token_row.encrypted_token = "encrypted-abc"

        mock_github_service.close_pull_request = AsyncMock(side_effect=RuntimeError("GitHub down"))

        mock_db.execute.side_effect = [
            _project_result(project),
            _pr_result(pr),
            _scalar_result(integration),
            _scalar_result(token_row),
            _project_result(project),  # _to_pr_response
        ]
        mock_db.refresh = AsyncMock()

        with patch(
            "ontokit.services.pull_request_service.decrypt_token",
            return_value="decrypted-token",
        ):
            result = await service.close_pull_request(PROJECT_ID, 1, user)

        assert pr.status == "closed"
        assert result is not None

    @pytest.mark.asyncio
    async def test_reopen_github_exception_still_reopens(
        self,
        service: PullRequestService,
        mock_db: AsyncMock,
        mock_github_service: MagicMock,
    ) -> None:
        """GitHub sync failure during reopen doesn't prevent local reopen."""
        project = _make_project()
        pr = _make_pr(
            author_id=OWNER_ID,
            status=PRStatus.CLOSED.value,
            github_pr_number=42,
        )
        user = _make_user(OWNER_ID)

        integration = MagicMock()
        integration.repo_owner = "org"
        integration.repo_name = "repo"
        integration.sync_enabled = True
        integration.connected_by_user_id = "user-123"

        token_row = MagicMock()
        token_row.encrypted_token = "encrypted-abc"

        mock_github_service.reopen_pull_request = AsyncMock(side_effect=RuntimeError("GitHub down"))

        mock_db.execute.side_effect = [
            _project_result(project),
            _pr_result(pr),
            _scalar_result(integration),
            _scalar_result(token_row),
            _project_result(project),  # _to_pr_response
        ]
        mock_db.refresh = AsyncMock()

        with patch(
            "ontokit.services.pull_request_service.decrypt_token",
            return_value="decrypted-token",
        ):
            result = await service.reopen_pull_request(PROJECT_ID, 1, user)

        assert pr.status == "open"
        assert result is not None


# ---------------------------------------------------------------------------
# _get_github_token — edge cases
# ---------------------------------------------------------------------------


class TestGetGitHubToken:
    @pytest.mark.asyncio
    async def test_no_connected_user_returns_none(
        self, service: PullRequestService, mock_db: AsyncMock
    ) -> None:
        """Returns None when connected_by_user_id is missing."""
        integration = MagicMock()
        integration.sync_enabled = True
        integration.connected_by_user_id = None

        mock_db.execute.return_value = _scalar_result(integration)

        result = await service._get_github_token(PROJECT_ID)
        assert result is None

    @pytest.mark.asyncio
    async def test_no_token_row_returns_none(
        self, service: PullRequestService, mock_db: AsyncMock
    ) -> None:
        """Returns None when user has no stored token."""
        integration = MagicMock()
        integration.sync_enabled = True
        integration.connected_by_user_id = "user-123"

        mock_db.execute.side_effect = [
            _scalar_result(integration),
            _scalar_result(None),  # no token row
        ]

        result = await service._get_github_token(PROJECT_ID)
        assert result is None

    @pytest.mark.asyncio
    async def test_decrypt_failure_returns_none(
        self, service: PullRequestService, mock_db: AsyncMock
    ) -> None:
        """Returns None when token decryption fails."""
        integration = MagicMock()
        integration.sync_enabled = True
        integration.connected_by_user_id = "user-123"

        token_row = MagicMock()
        token_row.encrypted_token = "bad-encrypted"

        mock_db.execute.side_effect = [
            _scalar_result(integration),
            _scalar_result(token_row),
        ]

        with patch(
            "ontokit.services.pull_request_service.decrypt_token",
            side_effect=ValueError("bad key"),
        ):
            result = await service._get_github_token(PROJECT_ID)

        assert result is None


# ---------------------------------------------------------------------------
# get_pull_request_service factory
# ---------------------------------------------------------------------------


class TestGetPullRequestServiceFactory:
    def test_returns_service_instance(self) -> None:
        """Factory returns a PullRequestService."""
        from ontokit.services.pull_request_service import get_pull_request_service

        db = AsyncMock()
        svc = get_pull_request_service(db)
        assert isinstance(svc, PullRequestService)
