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
