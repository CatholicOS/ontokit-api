"""Tests for PullRequestService (ontokit/services/pull_request_service.py)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from fastapi import HTTPException

from ontokit.core.auth import CurrentUser
from ontokit.models.pull_request import PRStatus, ReviewStatus
from ontokit.schemas.pull_request import (
    CommentCreate,
    PRCreate,
    PRMergeRequest,
    PRUpdate,
    ReviewCreate,
)
from ontokit.services.pull_request_service import PullRequestService

PROJECT_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
PR_ID = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
REVIEW_ID = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
COMMENT_ID = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
OWNER_ID = "owner-user-id"
EDITOR_ID = "editor-user-id"
VIEWER_ID = "viewer-user-id"
OTHER_ID = "other-user-id"


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------


def _make_member(user_id: str, role: str) -> MagicMock:
    m = MagicMock()
    m.id = uuid.uuid4()
    m.project_id = PROJECT_ID
    m.user_id = user_id
    m.role = role
    m.preferred_branch = None
    m.created_at = datetime.now(UTC)
    return m


def _make_project(
    *,
    is_public: bool = True,
    owner_id: str = OWNER_ID,
    members: list[MagicMock] | None = None,
    pr_approval_required: int = 0,
) -> MagicMock:
    project = MagicMock()
    project.id = PROJECT_ID
    project.name = "Test Ontology"
    project.description = "A test project"
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
    pr_number: int = 1,
    author_id: str = EDITOR_ID,
    status: str = PRStatus.OPEN.value,
    source_branch: str = "feature",
    target_branch: str = "main",
    reviews: list[MagicMock] | None = None,
    comments: list[MagicMock] | None = None,
    github_pr_number: int | None = None,
    merged_by: str | None = None,
    merged_at: datetime | None = None,
    merge_commit_hash: str | None = None,
    base_commit_hash: str | None = None,
    head_commit_hash: str | None = None,
) -> MagicMock:
    pr = MagicMock()
    pr.id = PR_ID
    pr.project_id = PROJECT_ID
    pr.pr_number = pr_number
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
    pr.merged_by = merged_by
    pr.merged_at = merged_at
    pr.merge_commit_hash = merge_commit_hash
    pr.base_commit_hash = base_commit_hash
    pr.head_commit_hash = head_commit_hash
    pr.created_at = datetime.now(UTC)
    pr.updated_at = None
    pr.reviews = reviews or []
    pr.comments = comments or []
    return pr


def _make_review(
    *,
    reviewer_id: str = OWNER_ID,
    review_status: str = ReviewStatus.APPROVED.value,
    body: str | None = "LGTM",
) -> MagicMock:
    review = MagicMock()
    review.id = REVIEW_ID
    review.pull_request_id = PR_ID
    review.reviewer_id = reviewer_id
    review.status = review_status
    review.body = body
    review.github_review_id = None
    review.created_at = datetime.now(UTC)
    return review


def _make_comment(
    *,
    author_id: str = EDITOR_ID,
    body: str = "Nice change",
    parent_id: uuid.UUID | None = None,
) -> MagicMock:
    comment = MagicMock()
    comment.id = COMMENT_ID
    comment.pull_request_id = PR_ID
    comment.author_id = author_id
    comment.author_name = "Editor User"
    comment.author_email = "editor@example.com"
    comment.body = body
    comment.parent_id = parent_id
    comment.github_comment_id = None
    comment.created_at = datetime.now(UTC)
    comment.updated_at = None
    comment.replies = []
    return comment


def _make_user(
    user_id: str = OWNER_ID,
    name: str = "Test User",
    email: str = "test@example.com",
) -> CurrentUser:
    return CurrentUser(id=user_id, email=email, name=name, username="testuser", roles=[])


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
    git.get_commits_between = MagicMock(return_value=[])
    git.merge_branch = MagicMock()
    git.delete_branch = MagicMock()
    git.diff_versions = MagicMock()
    git.get_history = MagicMock(return_value=[])
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


def _setup_project_lookup(mock_db: AsyncMock, project: MagicMock) -> None:
    """Configure mock_db.execute to return a project for _get_project."""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = project
    mock_db.execute.return_value = mock_result


def _setup_project_and_pr_lookup(
    mock_db: AsyncMock,
    project: MagicMock,
    pr: MagicMock | None = None,
) -> None:
    """Configure mock_db.execute to return project on first call and PR on second."""
    project_result = MagicMock()
    project_result.scalar_one_or_none.return_value = project

    pr_result = MagicMock()
    pr_result.scalar_one_or_none.return_value = pr

    mock_db.execute.side_effect = [project_result, pr_result]


def _setup_multi_execute(mock_db: AsyncMock, *results: MagicMock | None) -> None:
    """Configure mock_db.execute to return a sequence of results."""
    side_effects = []
    for r in results:
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = r
        mock_result.scalar.return_value = r
        mock_result.scalars.return_value.all.return_value = r if isinstance(r, list) else []
        side_effects.append(mock_result)
    mock_db.execute.side_effect = side_effects


# ---------------------------------------------------------------------------
# create_pull_request
# ---------------------------------------------------------------------------


class TestCreatePullRequest:
    @pytest.mark.asyncio
    async def test_create_pr_success(
        self, service: PullRequestService, mock_db: AsyncMock, mock_git_service: MagicMock
    ) -> None:
        """Editors can create a PR when source and target branches exist."""
        project = _make_project()
        user = _make_user(EDITOR_ID, "Editor User", "editor@example.com")

        # Branch setup
        main_branch = MagicMock(name="main_branch")
        main_branch.name = "main"
        feature_branch = MagicMock(name="feature_branch")
        feature_branch.name = "feature"
        mock_git_service.list_branches.return_value = [main_branch, feature_branch]
        mock_git_service.get_commits_between.return_value = []

        # DB calls: _get_project, max(pr_number), flush, _get_github_token, commit,
        # refresh, notify, _to_pr_response (_get_project again)
        project_result = MagicMock()
        project_result.scalar_one_or_none.return_value = project

        max_result = MagicMock()
        max_result.scalar.return_value = 0

        # _get_github_token: _get_github_integration returns None
        gh_integration_result = MagicMock()
        gh_integration_result.scalar_one_or_none.return_value = None

        # For _to_pr_response -> _get_project
        project_result_2 = MagicMock()
        project_result_2.scalar_one_or_none.return_value = project

        # Use project_result as fallback for any extra _get_project lookups
        mock_db.execute.side_effect = [
            project_result,  # _get_project
            max_result,  # max(pr_number)
            gh_integration_result,  # _get_github_token -> _get_github_integration
            project_result_2,  # _to_pr_response -> _get_project
            project_result,  # additional _get_project calls
            project_result,
            project_result,
            project_result,
        ]

        # refresh sets relationships on the newly created PR
        def _simulate_refresh(obj: object, _attrs: list[str] | None = None) -> None:
            if not hasattr(obj, "reviews") or obj.reviews is None:
                obj.reviews = []  # type: ignore[attr-defined]
            if not hasattr(obj, "comments") or obj.comments is None:
                obj.comments = []  # type: ignore[attr-defined]
            if not hasattr(obj, "id") or obj.id is None:
                obj.id = PR_ID  # type: ignore[attr-defined]
            if not hasattr(obj, "created_at") or obj.created_at is None:
                obj.created_at = datetime.now(UTC)  # type: ignore[attr-defined]
            if not hasattr(obj, "project_id"):
                obj.project_id = PROJECT_ID  # type: ignore[attr-defined]
            if not hasattr(obj, "updated_at"):
                obj.updated_at = None  # type: ignore[attr-defined]
            if not hasattr(obj, "github_pr_number"):
                obj.github_pr_number = None  # type: ignore[attr-defined]
            if not hasattr(obj, "github_pr_url"):
                obj.github_pr_url = None  # type: ignore[attr-defined]
            if not hasattr(obj, "merged_by"):
                obj.merged_by = None  # type: ignore[attr-defined]
            if not hasattr(obj, "merged_at"):
                obj.merged_at = None  # type: ignore[attr-defined]
            if not hasattr(obj, "author_name"):
                obj.author_name = "Editor User"  # type: ignore[attr-defined]
            if not hasattr(obj, "author_email"):
                obj.author_email = "editor@example.com"  # type: ignore[attr-defined]

        mock_db.refresh.side_effect = _simulate_refresh

        pr_create = PRCreate(
            title="My PR", description="Changes", source_branch="feature", target_branch="main"
        )

        result = await service.create_pull_request(PROJECT_ID, pr_create, user)

        assert result.title == "My PR"
        assert result.source_branch == "feature"
        assert result.target_branch == "main"
        mock_db.add.assert_called()
        mock_db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_create_pr_source_branch_not_found(
        self, service: PullRequestService, mock_db: AsyncMock, mock_git_service: MagicMock
    ) -> None:
        """Creating a PR with nonexistent source branch raises 400."""
        project = _make_project()
        user = _make_user(EDITOR_ID)

        main_branch = MagicMock()
        main_branch.name = "main"
        mock_git_service.list_branches.return_value = [main_branch]

        _setup_project_lookup(mock_db, project)

        pr_create = PRCreate(title="My PR", source_branch="nonexistent", target_branch="main")

        with pytest.raises(HTTPException) as exc_info:
            await service.create_pull_request(PROJECT_ID, pr_create, user)
        assert exc_info.value.status_code == 400
        assert "does not exist" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_create_pr_same_branches_raises(
        self, service: PullRequestService, mock_db: AsyncMock, mock_git_service: MagicMock
    ) -> None:
        """Source and target branches must be different."""
        project = _make_project()
        user = _make_user(EDITOR_ID)

        main_branch = MagicMock()
        main_branch.name = "main"
        mock_git_service.list_branches.return_value = [main_branch]

        _setup_project_lookup(mock_db, project)

        pr_create = PRCreate(title="My PR", source_branch="main", target_branch="main")

        with pytest.raises(HTTPException) as exc_info:
            await service.create_pull_request(PROJECT_ID, pr_create, user)
        assert exc_info.value.status_code == 400
        assert "must be different" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_create_pr_viewer_forbidden(
        self, service: PullRequestService, mock_db: AsyncMock
    ) -> None:
        """Viewers cannot create pull requests."""
        project = _make_project()
        user = _make_user(VIEWER_ID)

        _setup_project_lookup(mock_db, project)

        pr_create = PRCreate(title="My PR", source_branch="feature", target_branch="main")

        with pytest.raises(HTTPException) as exc_info:
            await service.create_pull_request(PROJECT_ID, pr_create, user)
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# get_pull_request
# ---------------------------------------------------------------------------


class TestGetPullRequest:
    @pytest.mark.asyncio
    async def test_get_pr_found(
        self,
        service: PullRequestService,
        mock_db: AsyncMock,
        mock_git_service: MagicMock,  # noqa: ARG002
    ) -> None:
        """Getting an existing PR returns a response."""
        project = _make_project()
        pr = _make_pr()
        user = _make_user(EDITOR_ID)

        project_result = MagicMock()
        project_result.scalar_one_or_none.return_value = project
        pr_result = MagicMock()
        pr_result.scalar_one_or_none.return_value = pr
        # _to_pr_response calls _get_project again
        project_result_2 = MagicMock()
        project_result_2.scalar_one_or_none.return_value = project

        mock_db.execute.side_effect = [project_result, pr_result, project_result_2]

        result = await service.get_pull_request(PROJECT_ID, 1, user)
        assert result.pr_number == 1
        assert result.title == "Test PR"

    @pytest.mark.asyncio
    async def test_get_pr_not_found(self, service: PullRequestService, mock_db: AsyncMock) -> None:
        """Getting a nonexistent PR raises 404."""
        project = _make_project()
        user = _make_user(EDITOR_ID)

        _setup_project_and_pr_lookup(mock_db, project, None)

        with pytest.raises(HTTPException) as exc_info:
            await service.get_pull_request(PROJECT_ID, 999, user)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_pr_private_project_no_access(
        self, service: PullRequestService, mock_db: AsyncMock
    ) -> None:
        """Users who are not members of a private project cannot view PRs."""
        project = _make_project(is_public=False)
        user = _make_user(OTHER_ID)

        _setup_project_lookup(mock_db, project)

        with pytest.raises(HTTPException) as exc_info:
            await service.get_pull_request(PROJECT_ID, 1, user)
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# list_pull_requests
# ---------------------------------------------------------------------------


class TestListPullRequests:
    @pytest.mark.asyncio
    async def test_list_prs_success(
        self, service: PullRequestService, mock_db: AsyncMock, mock_git_service: MagicMock
    ) -> None:
        """Listing PRs for a public project returns items."""
        project = _make_project()
        pr = _make_pr()
        user = _make_user(EDITOR_ID)

        project_result = MagicMock()
        project_result.scalar_one_or_none.return_value = project

        # _sync_merge_commits_to_prs: get_history returns empty
        mock_git_service.get_history.return_value = []

        # Execute calls: _get_project, sync (existing merged PRs), sync (max PR number),
        # list query (count), list query (results), _to_pr_response -> _get_project
        sync_merged_result = MagicMock()
        sync_merged_result.scalars.return_value.all.return_value = []

        sync_max_result = MagicMock()
        sync_max_result.scalar.return_value = 0

        mock_db.scalar = AsyncMock(return_value=1)

        list_result = MagicMock()
        list_result.scalars.return_value.all.return_value = [pr]

        project_result_2 = MagicMock()
        project_result_2.scalar_one_or_none.return_value = project

        mock_db.execute.side_effect = [
            project_result,  # _get_project
            sync_merged_result,  # _sync: existing merged PRs
            sync_max_result,  # _sync: max PR number
            list_result,  # list query with pagination
            project_result_2,  # _to_pr_response -> _get_project
        ]

        result = await service.list_pull_requests(PROJECT_ID, user)
        assert len(result.items) == 1
        assert result.items[0].pr_number == 1

    @pytest.mark.asyncio
    async def test_list_prs_private_project_no_access(
        self, service: PullRequestService, mock_db: AsyncMock
    ) -> None:
        """Non-members cannot list PRs in a private project."""
        project = _make_project(is_public=False)
        user = _make_user(OTHER_ID)

        _setup_project_lookup(mock_db, project)

        with pytest.raises(HTTPException) as exc_info:
            await service.list_pull_requests(PROJECT_ID, user)
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# update_pull_request
# ---------------------------------------------------------------------------


class TestUpdatePullRequest:
    @pytest.mark.asyncio
    async def test_update_pr_by_author(
        self,
        service: PullRequestService,
        mock_db: AsyncMock,
        mock_git_service: MagicMock,  # noqa: ARG002
    ) -> None:
        """The PR author can update title and description."""
        project = _make_project()
        pr = _make_pr(author_id=EDITOR_ID)
        user = _make_user(EDITOR_ID)

        project_result = MagicMock()
        project_result.scalar_one_or_none.return_value = project
        pr_result = MagicMock()
        pr_result.scalar_one_or_none.return_value = pr
        # _to_pr_response -> _get_project
        project_result_2 = MagicMock()
        project_result_2.scalar_one_or_none.return_value = project

        mock_db.execute.side_effect = [project_result, pr_result, project_result_2]

        pr_update = PRUpdate(title="Updated Title")
        await service.update_pull_request(PROJECT_ID, 1, pr_update, user)

        assert pr.title == "Updated Title"
        mock_db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_update_pr_non_author_non_admin_forbidden(
        self, service: PullRequestService, mock_db: AsyncMock
    ) -> None:
        """A non-author, non-admin user cannot update a PR."""
        project = _make_project()
        pr = _make_pr(author_id=EDITOR_ID)
        user = _make_user(VIEWER_ID)

        _setup_project_and_pr_lookup(mock_db, project, pr)

        pr_update = PRUpdate(title="New Title")
        with pytest.raises(HTTPException) as exc_info:
            await service.update_pull_request(PROJECT_ID, 1, pr_update, user)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_update_closed_pr_raises(
        self, service: PullRequestService, mock_db: AsyncMock
    ) -> None:
        """Updating a closed PR raises 400."""
        project = _make_project()
        pr = _make_pr(status=PRStatus.CLOSED.value)
        user = _make_user(EDITOR_ID)

        _setup_project_and_pr_lookup(mock_db, project, pr)

        pr_update = PRUpdate(title="New Title")
        with pytest.raises(HTTPException) as exc_info:
            await service.update_pull_request(PROJECT_ID, 1, pr_update, user)
        assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# close_pull_request
# ---------------------------------------------------------------------------


class TestClosePullRequest:
    @pytest.mark.asyncio
    async def test_close_pr_by_author(
        self,
        service: PullRequestService,
        mock_db: AsyncMock,
        mock_git_service: MagicMock,  # noqa: ARG002
    ) -> None:
        """The PR author can close their open PR."""
        project = _make_project()
        pr = _make_pr(author_id=EDITOR_ID)
        user = _make_user(EDITOR_ID)

        project_result = MagicMock()
        project_result.scalar_one_or_none.return_value = project
        pr_result = MagicMock()
        pr_result.scalar_one_or_none.return_value = pr
        project_result_2 = MagicMock()
        project_result_2.scalar_one_or_none.return_value = project

        mock_db.execute.side_effect = [project_result, pr_result, project_result_2]

        await service.close_pull_request(PROJECT_ID, 1, user)
        assert pr.status == PRStatus.CLOSED.value
        mock_db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_close_already_closed_raises(
        self, service: PullRequestService, mock_db: AsyncMock
    ) -> None:
        """Closing an already-closed PR raises 400."""
        project = _make_project()
        pr = _make_pr(status=PRStatus.CLOSED.value)
        user = _make_user(EDITOR_ID)

        _setup_project_and_pr_lookup(mock_db, project, pr)

        with pytest.raises(HTTPException) as exc_info:
            await service.close_pull_request(PROJECT_ID, 1, user)
        assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# reopen_pull_request
# ---------------------------------------------------------------------------


class TestReopenPullRequest:
    @pytest.mark.asyncio
    async def test_reopen_closed_pr(
        self,
        service: PullRequestService,
        mock_db: AsyncMock,
        mock_git_service: MagicMock,  # noqa: ARG002
    ) -> None:
        """A closed PR can be reopened by its author."""
        project = _make_project()
        pr = _make_pr(author_id=EDITOR_ID, status=PRStatus.CLOSED.value)
        user = _make_user(EDITOR_ID)

        project_result = MagicMock()
        project_result.scalar_one_or_none.return_value = project
        pr_result = MagicMock()
        pr_result.scalar_one_or_none.return_value = pr
        project_result_2 = MagicMock()
        project_result_2.scalar_one_or_none.return_value = project

        mock_db.execute.side_effect = [project_result, pr_result, project_result_2]

        await service.reopen_pull_request(PROJECT_ID, 1, user)
        assert pr.status == PRStatus.OPEN.value
        mock_db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_reopen_open_pr_raises(
        self, service: PullRequestService, mock_db: AsyncMock
    ) -> None:
        """Reopening an already-open PR raises 400."""
        project = _make_project()
        pr = _make_pr(status=PRStatus.OPEN.value)
        user = _make_user(EDITOR_ID)

        _setup_project_and_pr_lookup(mock_db, project, pr)

        with pytest.raises(HTTPException) as exc_info:
            await service.reopen_pull_request(PROJECT_ID, 1, user)
        assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# merge_pull_request
# ---------------------------------------------------------------------------


class TestMergePullRequest:
    @pytest.mark.asyncio
    async def test_merge_pr_success(
        self,
        service: PullRequestService,
        mock_db: AsyncMock,
        mock_git_service: MagicMock,
    ) -> None:
        """An owner can merge an open PR with sufficient approvals."""
        project = _make_project(pr_approval_required=0)
        pr = _make_pr(author_id=EDITOR_ID)
        user = _make_user(OWNER_ID)

        # Branch map for commit hashes
        main_branch = MagicMock()
        main_branch.name = "main"
        main_branch.commit_hash = "aaa111"
        feature_branch = MagicMock()
        feature_branch.name = "feature"
        feature_branch.commit_hash = "bbb222"
        mock_git_service.list_branches.return_value = [main_branch, feature_branch]

        merge_result = MagicMock()
        merge_result.success = True
        merge_result.merge_commit_hash = "ccc333"
        mock_git_service.merge_branch.return_value = merge_result

        project_result = MagicMock()
        project_result.scalar_one_or_none.return_value = project
        pr_result = MagicMock()
        pr_result.scalar_one_or_none.return_value = pr
        gh_integration_result = MagicMock()
        gh_integration_result.scalar_one_or_none.return_value = None

        mock_db.execute.side_effect = [project_result, pr_result, gh_integration_result]

        merge_req = PRMergeRequest(merge_message="Merge it", delete_source_branch=False)
        result = await service.merge_pull_request(PROJECT_ID, 1, merge_req, user)

        assert result.success is True
        assert result.merge_commit_hash == "ccc333"
        assert pr.status == PRStatus.MERGED.value

    @pytest.mark.asyncio
    async def test_merge_pr_editor_forbidden(
        self, service: PullRequestService, mock_db: AsyncMock
    ) -> None:
        """Only owners and admins can merge PRs."""
        project = _make_project()
        pr = _make_pr()
        user = _make_user(EDITOR_ID)

        _setup_project_and_pr_lookup(mock_db, project, pr)

        merge_req = PRMergeRequest()
        with pytest.raises(HTTPException) as exc_info:
            await service.merge_pull_request(PROJECT_ID, 1, merge_req, user)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_merge_pr_insufficient_approvals(
        self,
        service: PullRequestService,
        mock_db: AsyncMock,
    ) -> None:
        """Merge fails if the PR lacks the required number of approvals."""
        project = _make_project(pr_approval_required=2)
        pr = _make_pr(reviews=[_make_review()])  # only 1 approval
        user = _make_user(OWNER_ID)

        _setup_project_and_pr_lookup(mock_db, project, pr)

        merge_req = PRMergeRequest()
        with pytest.raises(HTTPException) as exc_info:
            await service.merge_pull_request(PROJECT_ID, 1, merge_req, user)
        assert exc_info.value.status_code == 400
        assert "approvals" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_merge_closed_pr_raises(
        self, service: PullRequestService, mock_db: AsyncMock
    ) -> None:
        """Merging a closed PR raises 400."""
        project = _make_project()
        pr = _make_pr(status=PRStatus.CLOSED.value)
        user = _make_user(OWNER_ID)

        _setup_project_and_pr_lookup(mock_db, project, pr)

        merge_req = PRMergeRequest()
        with pytest.raises(HTTPException) as exc_info:
            await service.merge_pull_request(PROJECT_ID, 1, merge_req, user)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_merge_conflict_raises_409(
        self,
        service: PullRequestService,
        mock_db: AsyncMock,
        mock_git_service: MagicMock,
    ) -> None:
        """When the git merge fails, a 409 Conflict is returned."""
        project = _make_project()
        pr = _make_pr()
        user = _make_user(OWNER_ID)

        main_branch = MagicMock()
        main_branch.name = "main"
        main_branch.commit_hash = "a1"
        feature_branch = MagicMock()
        feature_branch.name = "feature"
        feature_branch.commit_hash = "b2"
        mock_git_service.list_branches.return_value = [main_branch, feature_branch]
        merge_result = MagicMock()
        merge_result.success = False
        merge_result.message = "Conflicts detected"
        mock_git_service.merge_branch.return_value = merge_result

        _setup_project_and_pr_lookup(mock_db, project, pr)

        merge_req = PRMergeRequest()
        with pytest.raises(HTTPException) as exc_info:
            await service.merge_pull_request(PROJECT_ID, 1, merge_req, user)
        assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# create_review
# ---------------------------------------------------------------------------


class TestCreateReview:
    @pytest.mark.asyncio
    async def test_create_review_success(
        self,
        service: PullRequestService,
        mock_db: AsyncMock,
        mock_git_service: MagicMock,  # noqa: ARG002
    ) -> None:
        """An owner can approve a PR via review."""
        project = _make_project()
        pr = _make_pr()
        user = _make_user(OWNER_ID)

        project_result = MagicMock()
        project_result.scalar_one_or_none.return_value = project
        pr_result = MagicMock()
        pr_result.scalar_one_or_none.return_value = pr
        gh_integration_result = MagicMock()
        gh_integration_result.scalar_one_or_none.return_value = None

        mock_db.execute.side_effect = [project_result, pr_result, gh_integration_result]

        # The db.refresh sets properties on the new review object
        def _simulate_refresh(obj: object, _attrs: list[str] | None = None) -> None:
            if not hasattr(obj, "id") or obj.id is None:
                obj.id = REVIEW_ID  # type: ignore[attr-defined]
            if not hasattr(obj, "created_at") or obj.created_at is None:
                obj.created_at = datetime.now(UTC)  # type: ignore[attr-defined]
            if not hasattr(obj, "pull_request_id"):
                obj.pull_request_id = PR_ID  # type: ignore[attr-defined]
            if not hasattr(obj, "github_review_id"):
                obj.github_review_id = None  # type: ignore[attr-defined]

        mock_db.refresh.side_effect = _simulate_refresh

        review_create = ReviewCreate(status="approved", body="LGTM")
        result = await service.create_review(PROJECT_ID, 1, review_create, user)

        assert result.status == "approved"
        mock_db.add.assert_called()
        mock_db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_create_review_editor_cannot_approve(
        self, service: PullRequestService, mock_db: AsyncMock
    ) -> None:
        """Editors cannot approve or request changes, only comment."""
        project = _make_project()
        pr = _make_pr()
        user = _make_user(EDITOR_ID)

        _setup_project_and_pr_lookup(mock_db, project, pr)

        review_create = ReviewCreate(status="approved", body="LGTM")
        with pytest.raises(HTTPException) as exc_info:
            await service.create_review(PROJECT_ID, 1, review_create, user)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_create_review_on_closed_pr_raises(
        self, service: PullRequestService, mock_db: AsyncMock
    ) -> None:
        """Cannot review a closed PR."""
        project = _make_project()
        pr = _make_pr(status=PRStatus.CLOSED.value)
        user = _make_user(OWNER_ID)

        _setup_project_and_pr_lookup(mock_db, project, pr)

        review_create = ReviewCreate(status="commented", body="note")
        with pytest.raises(HTTPException) as exc_info:
            await service.create_review(PROJECT_ID, 1, review_create, user)
        assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# create_comment
# ---------------------------------------------------------------------------


class TestCreateComment:
    @pytest.mark.asyncio
    async def test_create_comment_success(
        self,
        service: PullRequestService,
        mock_db: AsyncMock,
        mock_git_service: MagicMock,  # noqa: ARG002
    ) -> None:
        """Any project member can comment on a PR."""
        project = _make_project()
        pr = _make_pr()
        user = _make_user(EDITOR_ID)

        project_result = MagicMock()
        project_result.scalar_one_or_none.return_value = project
        pr_result = MagicMock()
        pr_result.scalar_one_or_none.return_value = pr
        gh_integration_result = MagicMock()
        gh_integration_result.scalar_one_or_none.return_value = None

        mock_db.execute.side_effect = [project_result, pr_result, gh_integration_result]

        def _simulate_refresh(obj: object, _attrs: list[str] | None = None) -> None:
            if not hasattr(obj, "id") or obj.id is None:
                obj.id = COMMENT_ID  # type: ignore[attr-defined]
            if not hasattr(obj, "created_at") or obj.created_at is None:
                obj.created_at = datetime.now(UTC)  # type: ignore[attr-defined]
            if not hasattr(obj, "pull_request_id"):
                obj.pull_request_id = PR_ID  # type: ignore[attr-defined]
            if not hasattr(obj, "replies"):
                obj.replies = []  # type: ignore[attr-defined]
            if not hasattr(obj, "github_comment_id"):
                obj.github_comment_id = None  # type: ignore[attr-defined]
            if not hasattr(obj, "parent_id"):
                obj.parent_id = None  # type: ignore[attr-defined]
            if not hasattr(obj, "updated_at"):
                obj.updated_at = None  # type: ignore[attr-defined]
            if not hasattr(obj, "author_name"):
                obj.author_name = "Editor User"  # type: ignore[attr-defined]
            if not hasattr(obj, "author_email"):
                obj.author_email = "editor@example.com"  # type: ignore[attr-defined]

        mock_db.refresh.side_effect = _simulate_refresh

        comment_create = CommentCreate(body="Great work!")
        result = await service.create_comment(PROJECT_ID, 1, comment_create, user)

        assert result.body == "Great work!"
        mock_db.add.assert_called()
        mock_db.commit.assert_awaited()


# ---------------------------------------------------------------------------
# list_reviews
# ---------------------------------------------------------------------------


class TestListReviews:
    @pytest.mark.asyncio
    async def test_list_reviews_success(
        self, service: PullRequestService, mock_db: AsyncMock
    ) -> None:
        """Listing reviews for a PR returns all reviews."""
        project = _make_project()
        review = _make_review()
        pr = _make_pr(reviews=[review])
        user = _make_user(EDITOR_ID)

        project_result = MagicMock()
        project_result.scalar_one_or_none.return_value = project
        pr_result = MagicMock()
        pr_result.scalar_one_or_none.return_value = pr

        mock_db.execute.side_effect = [project_result, pr_result]

        result = await service.list_reviews(PROJECT_ID, 1, user)
        assert result.total == 1
        assert result.items[0].status == "approved"


# ---------------------------------------------------------------------------
# list_comments
# ---------------------------------------------------------------------------


class TestListComments:
    @pytest.mark.asyncio
    async def test_list_comments_success(
        self, service: PullRequestService, mock_db: AsyncMock
    ) -> None:
        """Listing comments returns top-level comments with replies."""
        project = _make_project()
        comment = _make_comment()
        pr = _make_pr(comments=[comment])
        user = _make_user(EDITOR_ID)

        project_result = MagicMock()
        project_result.scalar_one_or_none.return_value = project
        pr_result = MagicMock()
        pr_result.scalar_one_or_none.return_value = pr

        comments_result = MagicMock()
        comments_result.scalars.return_value.all.return_value = [comment]

        mock_db.execute.side_effect = [project_result, pr_result, comments_result]

        result = await service.list_comments(PROJECT_ID, 1, user)
        assert result.total == 1
        assert result.items[0].body == "Nice change"


# ---------------------------------------------------------------------------
# get_pr_diff
# ---------------------------------------------------------------------------


class TestGetPRDiff:
    @pytest.mark.asyncio
    async def test_get_diff_success(
        self,
        service: PullRequestService,
        mock_db: AsyncMock,
        mock_git_service: MagicMock,
    ) -> None:
        """Getting the diff for an open PR uses branch names."""
        project = _make_project()
        pr = _make_pr()
        user = _make_user(EDITOR_ID)

        change = MagicMock()
        change.change_type = "M"
        change.path = "ontology.ttl"
        change.old_path = None
        change.additions = 5
        change.deletions = 2
        change.patch = "@@ -1,3 +1,5 @@"

        diff_info = MagicMock()
        diff_info.changes = [change]
        diff_info.total_additions = 5
        diff_info.total_deletions = 2
        diff_info.files_changed = 1
        mock_git_service.diff_versions.return_value = diff_info

        project_result = MagicMock()
        project_result.scalar_one_or_none.return_value = project
        pr_result = MagicMock()
        pr_result.scalar_one_or_none.return_value = pr

        mock_db.execute.side_effect = [project_result, pr_result]

        result = await service.get_pr_diff(PROJECT_ID, 1, user)
        assert result.files_changed == 1
        assert result.files[0].path == "ontology.ttl"
        assert result.files[0].change_type == "modified"

    @pytest.mark.asyncio
    async def test_get_diff_merged_pr_empty_on_deleted_branch(
        self,
        service: PullRequestService,
        mock_db: AsyncMock,
        mock_git_service: MagicMock,
    ) -> None:
        """A merged PR with deleted branches and no stored hashes returns empty diff."""
        project = _make_project()
        pr = _make_pr(status=PRStatus.MERGED.value)
        user = _make_user(EDITOR_ID)

        mock_git_service.diff_versions.side_effect = ValueError("branch not found")

        project_result = MagicMock()
        project_result.scalar_one_or_none.return_value = project
        pr_result = MagicMock()
        pr_result.scalar_one_or_none.return_value = pr

        mock_db.execute.side_effect = [project_result, pr_result]

        result = await service.get_pr_diff(PROJECT_ID, 1, user)
        assert result.files_changed == 0
        assert result.files == []


# ---------------------------------------------------------------------------
# get_pr_commits
# ---------------------------------------------------------------------------


class TestGetPRCommits:
    @pytest.mark.asyncio
    async def test_get_commits_success(
        self,
        service: PullRequestService,
        mock_db: AsyncMock,
        mock_git_service: MagicMock,
    ) -> None:
        """Getting commits for an open PR returns commit list."""
        project = _make_project()
        pr = _make_pr()
        user = _make_user(EDITOR_ID)

        commit = MagicMock()
        commit.hash = "abc123def456"
        commit.short_hash = "abc123d"
        commit.message = "Add feature"
        commit.author_name = "Editor"
        commit.author_email = "editor@example.com"
        commit.timestamp = "2025-01-15T10:00:00+00:00"
        mock_git_service.get_commits_between.return_value = [commit]

        project_result = MagicMock()
        project_result.scalar_one_or_none.return_value = project
        pr_result = MagicMock()
        pr_result.scalar_one_or_none.return_value = pr

        mock_db.execute.side_effect = [project_result, pr_result]

        result = await service.get_pr_commits(PROJECT_ID, 1, user)
        assert result.total == 1
        assert result.items[0].hash == "abc123def456"

    @pytest.mark.asyncio
    async def test_get_commits_branch_deleted_returns_empty(
        self,
        service: PullRequestService,
        mock_db: AsyncMock,
        mock_git_service: MagicMock,
    ) -> None:
        """When a branch is deleted, an empty commit list is returned."""
        project = _make_project()
        pr = _make_pr()
        user = _make_user(EDITOR_ID)

        mock_git_service.get_commits_between.side_effect = ValueError("branch not found")

        project_result = MagicMock()
        project_result.scalar_one_or_none.return_value = project
        pr_result = MagicMock()
        pr_result.scalar_one_or_none.return_value = pr

        mock_db.execute.side_effect = [project_result, pr_result]

        result = await service.get_pr_commits(PROJECT_ID, 1, user)
        assert result.total == 0
        assert result.items == []


# ---------------------------------------------------------------------------
# _to_pr_response
# ---------------------------------------------------------------------------


class TestToPrResponse:
    @pytest.mark.asyncio
    async def test_to_pr_response_basic(
        self,
        service: PullRequestService,
        mock_db: AsyncMock,
        mock_git_service: MagicMock,
    ) -> None:
        """_to_pr_response converts a PR ORM model to a PRResponse schema."""
        project = _make_project(pr_approval_required=0)
        pr = _make_pr()

        mock_git_service.get_commits_between.return_value = []

        project_result = MagicMock()
        project_result.scalar_one_or_none.return_value = project
        mock_db.execute.return_value = project_result

        result = await service._to_pr_response(pr, PROJECT_ID)
        assert result.pr_number == 1
        assert result.title == "Test PR"
        assert result.source_branch == "feature"
        assert result.target_branch == "main"
        assert result.review_count == 0
        assert result.approval_count == 0
        assert result.can_merge is True  # 0 approvals required, 0 approvals

    @pytest.mark.asyncio
    async def test_to_pr_response_with_reviews(
        self,
        service: PullRequestService,
        mock_db: AsyncMock,
        mock_git_service: MagicMock,
    ) -> None:
        """_to_pr_response counts reviews and approvals correctly."""
        project = _make_project(pr_approval_required=1)
        review = _make_review(review_status="approved")
        pr = _make_pr(reviews=[review])

        mock_git_service.get_commits_between.return_value = []

        project_result = MagicMock()
        project_result.scalar_one_or_none.return_value = project
        mock_db.execute.return_value = project_result

        result = await service._to_pr_response(pr, PROJECT_ID)
        assert result.review_count == 1
        assert result.approval_count == 1
        assert result.can_merge is True

    @pytest.mark.asyncio
    async def test_to_pr_response_closed_cannot_merge(
        self,
        service: PullRequestService,
        mock_db: AsyncMock,
        mock_git_service: MagicMock,
    ) -> None:
        """A closed PR cannot be merged even with approvals."""
        project = _make_project(pr_approval_required=0)
        pr = _make_pr(status="closed")

        mock_git_service.get_commits_between.return_value = []

        project_result = MagicMock()
        project_result.scalar_one_or_none.return_value = project
        mock_db.execute.return_value = project_result

        result = await service._to_pr_response(pr, PROJECT_ID)
        assert result.can_merge is False

    @pytest.mark.asyncio
    async def test_to_pr_response_author_lookup_when_name_missing(
        self,
        service: PullRequestService,
        mock_db: AsyncMock,
        mock_git_service: MagicMock,
        mock_user_service: MagicMock,
    ) -> None:
        """When author_name is missing, user_service is queried."""
        project = _make_project()
        pr = _make_pr()
        pr.author_name = None
        pr.author_email = None

        mock_user_service.get_user_info = AsyncMock(
            return_value={"name": "Looked Up", "email": "looked@up.com"}
        )
        mock_git_service.get_commits_between.return_value = []

        project_result = MagicMock()
        project_result.scalar_one_or_none.return_value = project
        mock_db.execute.return_value = project_result

        result = await service._to_pr_response(pr, PROJECT_ID)
        assert result.author is not None
        assert result.author.name == "Looked Up"
        assert result.author.email == "looked@up.com"


# ---------------------------------------------------------------------------
# get_pr_diff (additional cases)
# ---------------------------------------------------------------------------


class TestGetPRDiffExtended:
    @pytest.mark.asyncio
    async def test_get_diff_merged_pr_uses_commit_hashes(
        self,
        service: PullRequestService,
        mock_db: AsyncMock,
        mock_git_service: MagicMock,
    ) -> None:
        """A merged PR with stored hashes uses those for diff, not branch names."""
        project = _make_project()
        pr = _make_pr(
            status="merged",
            base_commit_hash="aaa111",
            head_commit_hash="bbb222",
        )
        user = _make_user(EDITOR_ID)

        diff_info = MagicMock()
        diff_info.changes = []
        diff_info.total_additions = 0
        diff_info.total_deletions = 0
        diff_info.files_changed = 0
        mock_git_service.diff_versions.return_value = diff_info

        project_result = MagicMock()
        project_result.scalar_one_or_none.return_value = project
        pr_result = MagicMock()
        pr_result.scalar_one_or_none.return_value = pr
        mock_db.execute.side_effect = [project_result, pr_result]

        result = await service.get_pr_diff(PROJECT_ID, 1, user)
        assert result.files_changed == 0
        mock_git_service.diff_versions.assert_called_once_with(PROJECT_ID, "aaa111", "bbb222")

    @pytest.mark.asyncio
    async def test_get_diff_open_pr_error_raises_400(
        self,
        service: PullRequestService,
        mock_db: AsyncMock,
        mock_git_service: MagicMock,
    ) -> None:
        """An open PR whose diff raises ValueError returns 400."""
        project = _make_project()
        pr = _make_pr(status="open")
        user = _make_user(EDITOR_ID)

        mock_git_service.diff_versions.side_effect = ValueError("cannot diff")

        project_result = MagicMock()
        project_result.scalar_one_or_none.return_value = project
        pr_result = MagicMock()
        pr_result.scalar_one_or_none.return_value = pr
        mock_db.execute.side_effect = [project_result, pr_result]

        with pytest.raises(HTTPException) as exc_info:
            await service.get_pr_diff(PROJECT_ID, 1, user)
        assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# get_open_pr_summary
# ---------------------------------------------------------------------------


class TestGetOpenPRSummary:
    @pytest.mark.asyncio
    async def test_summary_superadmin(
        self,
        service: PullRequestService,
        mock_db: AsyncMock,
    ) -> None:
        """Superadmin gets summary across all projects."""
        user = _make_user(OWNER_ID)
        user = CurrentUser(
            id=OWNER_ID,
            email="admin@example.com",
            name="Admin",
            username="admin",
            roles=["superadmin"],
        )

        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_db.execute.return_value = mock_result

        result = await service.get_open_pr_summary(user)
        assert result.total_open == 0
        assert result.by_project == []

    @pytest.mark.asyncio
    async def test_summary_regular_user(
        self,
        service: PullRequestService,
        mock_db: AsyncMock,
    ) -> None:
        """Regular user gets summary only for projects they manage."""
        user = _make_user(OWNER_ID)

        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_db.execute.return_value = mock_result

        result = await service.get_open_pr_summary(user)
        assert result.total_open == 0


# ---------------------------------------------------------------------------
# handle_github_pr_webhook
# ---------------------------------------------------------------------------


class TestHandleGitHubPRWebhook:
    @pytest.mark.asyncio
    async def test_webhook_no_integration_returns_early(
        self,
        service: PullRequestService,
        mock_db: AsyncMock,
    ) -> None:
        """When no GitHub integration exists, webhook handler returns early."""
        gh_result = MagicMock()
        gh_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = gh_result

        # Should not raise
        await service.handle_github_pr_webhook(PROJECT_ID, "opened", {"number": 1, "title": "Test"})

    @pytest.mark.asyncio
    async def test_webhook_closed_merged(
        self,
        service: PullRequestService,
        mock_db: AsyncMock,
    ) -> None:
        """Webhook with action=closed and merged=true sets PR to merged."""
        integration = MagicMock()
        integration.sync_enabled = True

        pr = _make_pr(github_pr_number=42)

        gh_result = MagicMock()
        gh_result.scalar_one_or_none.return_value = integration
        pr_result = MagicMock()
        pr_result.scalar_one_or_none.return_value = pr

        mock_db.execute.side_effect = [gh_result, pr_result]

        await service.handle_github_pr_webhook(PROJECT_ID, "closed", {"number": 42, "merged": True})
        assert pr.status == "merged"
        mock_db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_webhook_closed_not_merged(
        self,
        service: PullRequestService,
        mock_db: AsyncMock,
    ) -> None:
        """Webhook with action=closed and merged=false sets PR to closed."""
        integration = MagicMock()
        integration.sync_enabled = True

        pr = _make_pr(github_pr_number=42)

        gh_result = MagicMock()
        gh_result.scalar_one_or_none.return_value = integration
        pr_result = MagicMock()
        pr_result.scalar_one_or_none.return_value = pr

        mock_db.execute.side_effect = [gh_result, pr_result]

        await service.handle_github_pr_webhook(
            PROJECT_ID, "closed", {"number": 42, "merged": False}
        )
        assert pr.status == "closed"

    @pytest.mark.asyncio
    async def test_webhook_reopened(
        self,
        service: PullRequestService,
        mock_db: AsyncMock,
    ) -> None:
        """Webhook with action=reopened sets PR back to open."""
        integration = MagicMock()
        integration.sync_enabled = True

        pr = _make_pr(status="closed", github_pr_number=42)

        gh_result = MagicMock()
        gh_result.scalar_one_or_none.return_value = integration
        pr_result = MagicMock()
        pr_result.scalar_one_or_none.return_value = pr

        mock_db.execute.side_effect = [gh_result, pr_result]

        await service.handle_github_pr_webhook(PROJECT_ID, "reopened", {"number": 42})
        assert pr.status == "open"

    @pytest.mark.asyncio
    async def test_webhook_edited(
        self,
        service: PullRequestService,
        mock_db: AsyncMock,
    ) -> None:
        """Webhook with action=edited updates title and description."""
        integration = MagicMock()
        integration.sync_enabled = True

        pr = _make_pr(github_pr_number=42)

        gh_result = MagicMock()
        gh_result.scalar_one_or_none.return_value = integration
        pr_result = MagicMock()
        pr_result.scalar_one_or_none.return_value = pr

        mock_db.execute.side_effect = [gh_result, pr_result]

        await service.handle_github_pr_webhook(
            PROJECT_ID,
            "edited",
            {"number": 42, "title": "New Title", "body": "New Body"},
        )
        assert pr.title == "New Title"
        assert pr.description == "New Body"


# ---------------------------------------------------------------------------
# handle_github_push_webhook
# ---------------------------------------------------------------------------


class TestHandleGitHubPushWebhook:
    @pytest.mark.asyncio
    async def test_push_no_integration_returns_early(
        self,
        service: PullRequestService,
        mock_db: AsyncMock,
    ) -> None:
        """When no GitHub integration exists, push webhook does nothing."""
        gh_result = MagicMock()
        gh_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = gh_result

        await service.handle_github_push_webhook(PROJECT_ID, "refs/heads/main", [])

    @pytest.mark.asyncio
    async def test_push_wrong_branch_returns_early(
        self,
        service: PullRequestService,
        mock_db: AsyncMock,
    ) -> None:
        """Push to a non-default branch does nothing."""
        integration = MagicMock()
        integration.sync_enabled = True
        integration.default_branch = "main"

        gh_result = MagicMock()
        gh_result.scalar_one_or_none.return_value = integration
        mock_db.execute.return_value = gh_result

        await service.handle_github_push_webhook(PROJECT_ID, "refs/heads/feature", [])
        mock_db.commit.assert_not_awaited()


# ---------------------------------------------------------------------------
# _sync_merge_commits_to_prs
# ---------------------------------------------------------------------------


class TestSyncMergeCommitsToPrs:
    @pytest.mark.asyncio
    async def test_sync_no_history_does_nothing(
        self,
        service: PullRequestService,
        mock_db: AsyncMock,
        mock_git_service: MagicMock,
    ) -> None:
        """When git history is empty, no PRs are created."""
        mock_git_service.get_history.return_value = []

        merged_result = MagicMock()
        merged_result.scalars.return_value.all.return_value = []
        max_result = MagicMock()
        max_result.scalar.return_value = 0

        mock_db.execute.side_effect = [merged_result, max_result]

        await service._sync_merge_commits_to_prs(PROJECT_ID)
        # No commit because nothing was created/updated
        mock_db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_sync_history_exception_returns_early(
        self,
        service: PullRequestService,
        mock_db: AsyncMock,  # noqa: ARG002
        mock_git_service: MagicMock,
    ) -> None:
        """When get_history raises, sync returns without error."""
        mock_git_service.get_history.side_effect = Exception("git error")

        # Should not raise
        await service._sync_merge_commits_to_prs(PROJECT_ID)


# ---------------------------------------------------------------------------
# get_github_integration / create_github_integration / update_github_integration
# ---------------------------------------------------------------------------


class TestGitHubIntegration:
    @pytest.mark.asyncio
    async def test_get_github_integration_not_admin(
        self,
        service: PullRequestService,
        mock_db: AsyncMock,
    ) -> None:
        """Non-admin users cannot view GitHub integration."""
        project = _make_project()
        user = _make_user(VIEWER_ID)

        _setup_project_lookup(mock_db, project)

        with pytest.raises(HTTPException) as exc_info:
            await service.get_github_integration(PROJECT_ID, user)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_get_github_integration_admin_none(
        self,
        service: PullRequestService,
        mock_db: AsyncMock,
    ) -> None:
        """Admin viewing a project with no GitHub integration returns None."""
        project = _make_project()
        user = _make_user(OWNER_ID)

        project_result = MagicMock()
        project_result.scalar_one_or_none.return_value = project
        gh_result = MagicMock()
        gh_result.scalar_one_or_none.return_value = None
        mock_db.execute.side_effect = [project_result, gh_result]

        result = await service.get_github_integration(PROJECT_ID, user)
        assert result is None

    @pytest.mark.asyncio
    async def test_create_github_integration_non_owner(
        self,
        service: PullRequestService,
        mock_db: AsyncMock,
    ) -> None:
        """Only the owner can create GitHub integration."""
        project = _make_project()
        user = _make_user(EDITOR_ID)

        _setup_project_lookup(mock_db, project)

        from ontokit.schemas.pull_request import GitHubIntegrationCreate

        create_data = GitHubIntegrationCreate(repo_owner="org", repo_name="repo")
        with pytest.raises(HTTPException) as exc_info:
            await service.create_github_integration(PROJECT_ID, create_data, user)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_update_github_integration_not_found(
        self,
        service: PullRequestService,
        mock_db: AsyncMock,
    ) -> None:
        """Updating a nonexistent integration raises 404."""
        project = _make_project()
        user = _make_user(OWNER_ID)

        project_result = MagicMock()
        project_result.scalar_one_or_none.return_value = project
        gh_result = MagicMock()
        gh_result.scalar_one_or_none.return_value = None
        mock_db.execute.side_effect = [project_result, gh_result]

        from ontokit.schemas.pull_request import GitHubIntegrationUpdate

        update_data = GitHubIntegrationUpdate(default_branch="develop")
        with pytest.raises(HTTPException) as exc_info:
            await service.update_github_integration(PROJECT_ID, update_data, user)
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# get_pr_settings / update_pr_settings
# ---------------------------------------------------------------------------


class TestPRSettings:
    @pytest.mark.asyncio
    async def test_get_pr_settings_forbidden_for_editor(
        self,
        service: PullRequestService,
        mock_db: AsyncMock,
    ) -> None:
        """Editors cannot view PR settings."""
        project = _make_project()
        user = _make_user(EDITOR_ID)

        _setup_project_lookup(mock_db, project)

        with pytest.raises(HTTPException) as exc_info:
            await service.get_pr_settings(PROJECT_ID, user)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_get_pr_settings_admin_success(
        self,
        service: PullRequestService,
        mock_db: AsyncMock,
    ) -> None:
        """Admins can view PR settings."""
        project = _make_project(pr_approval_required=2)
        user = _make_user(OWNER_ID)

        project_result = MagicMock()
        project_result.scalar_one_or_none.return_value = project
        gh_result = MagicMock()
        gh_result.scalar_one_or_none.return_value = None
        mock_db.execute.side_effect = [project_result, gh_result]

        result = await service.get_pr_settings(PROJECT_ID, user)
        assert result.pr_approval_required == 2
        assert result.github_integration is None

    @pytest.mark.asyncio
    async def test_update_pr_settings_non_owner_forbidden(
        self,
        service: PullRequestService,
        mock_db: AsyncMock,
    ) -> None:
        """Only the owner can update PR settings."""
        project = _make_project()
        user = _make_user(EDITOR_ID)

        _setup_project_lookup(mock_db, project)

        from ontokit.schemas.pull_request import PRSettingsUpdate

        update_data = PRSettingsUpdate(pr_approval_required=1)
        with pytest.raises(HTTPException) as exc_info:
            await service.update_pr_settings(PROJECT_ID, update_data, user)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_update_pr_settings_success(
        self,
        service: PullRequestService,
        mock_db: AsyncMock,
    ) -> None:
        """Owner can update PR settings."""
        project = _make_project()
        user = _make_user(OWNER_ID)

        project_result = MagicMock()
        project_result.scalar_one_or_none.return_value = project
        gh_result = MagicMock()
        gh_result.scalar_one_or_none.return_value = None
        mock_db.execute.side_effect = [project_result, gh_result]

        from ontokit.schemas.pull_request import PRSettingsUpdate

        update_data = PRSettingsUpdate(pr_approval_required=3)
        result = await service.update_pr_settings(PROJECT_ID, update_data, user)
        assert result.pr_approval_required == 3
        mock_db.commit.assert_awaited()
