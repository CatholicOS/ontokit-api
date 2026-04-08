"""Tests for SuggestionService (ontokit/services/suggestion_service.py)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from fastapi import HTTPException

from ontokit.core.auth import CurrentUser
from ontokit.models.suggestion_session import SuggestionSession, SuggestionSessionStatus
from ontokit.services.suggestion_service import SuggestionService

PROJECT_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(
    user_id: str = "test-user-id",
    name: str = "Test User",
    email: str = "test@example.com",
) -> CurrentUser:
    return CurrentUser(id=user_id, email=email, name=name, username="testuser")


def _make_project(project_id: uuid.UUID = PROJECT_ID, is_public: bool = True) -> MagicMock:
    project = MagicMock()
    project.id = project_id
    project.name = "Test Project"
    project.is_public = is_public
    project.source_file_path = None

    member = MagicMock()
    member.user_id = "test-user-id"
    member.role = "editor"
    project.members = [member]
    return project


def _make_session(
    *,
    session_id: str = "s_abc12345",
    user_id: str = "test-user-id",
    status: str = SuggestionSessionStatus.ACTIVE.value,
    changes_count: int = 0,
    branch: str = "suggest/test-use/s_abc12345",
    entities_modified: str | None = None,
    pr_number: int | None = None,
    pr_id: uuid.UUID | None = None,
    last_activity: datetime | None = None,
) -> MagicMock:
    session = MagicMock(spec=SuggestionSession)
    session.id = uuid.uuid4()
    session.project_id = PROJECT_ID
    session.session_id = session_id
    session.user_id = user_id
    session.user_name = "Test User"
    session.user_email = "test@example.com"
    session.branch = branch
    session.status = status
    session.changes_count = changes_count
    session.entities_modified = entities_modified
    session.beacon_token = "tok_test"
    session.pr_number = pr_number
    session.pr_id = pr_id
    session.reviewer_id = None
    session.reviewer_name = None
    session.reviewer_email = None
    session.reviewer_feedback = None
    session.reviewed_at = None
    session.revision = 1
    session.summary = None
    session.created_at = datetime.now(UTC)
    session.last_activity = last_activity or datetime.now(UTC)
    return session


@pytest.fixture
def mock_db() -> AsyncMock:
    """Create an async mock of AsyncSession."""
    session = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.execute = AsyncMock()
    session.refresh = AsyncMock()
    session.add = Mock()
    return session


@pytest.fixture
def mock_git() -> MagicMock:
    """Create a mock git service."""
    git = MagicMock()
    git.create_branch = MagicMock()
    git.delete_branch = MagicMock()
    git.get_default_branch = MagicMock(return_value="main")
    return git


@pytest.fixture
def service(mock_db: AsyncMock, mock_git: MagicMock) -> SuggestionService:
    return SuggestionService(db=mock_db, git_service=mock_git)


# ---------------------------------------------------------------------------
# _parse_entities_modified / _update_entities_modified
# ---------------------------------------------------------------------------


class TestParseEntitiesModified:
    def test_returns_empty_list_when_none(self, service: SuggestionService) -> None:
        """Returns empty list when entities_modified is None."""
        session = _make_session(entities_modified=None)
        assert service._parse_entities_modified(session) == []

    def test_returns_parsed_list(self, service: SuggestionService) -> None:
        """Returns parsed list from valid JSON."""
        session = _make_session(entities_modified=json.dumps(["Person", "Organization"]))
        assert service._parse_entities_modified(session) == ["Person", "Organization"]

    def test_returns_empty_list_on_invalid_json(self, service: SuggestionService) -> None:
        """Returns empty list for invalid JSON."""
        session = _make_session(entities_modified="not-json")
        assert service._parse_entities_modified(session) == []


class TestUpdateEntitiesModified:
    def test_adds_new_label(self, service: SuggestionService) -> None:
        """Adds a new label to the entities_modified list."""
        session = _make_session(entities_modified=json.dumps(["Person"]))
        service._update_entities_modified(session, "Organization")
        result = json.loads(session.entities_modified)
        assert "Organization" in result
        assert "Person" in result

    def test_does_not_duplicate(self, service: SuggestionService) -> None:
        """Does not add a duplicate label."""
        session = _make_session(entities_modified=json.dumps(["Person"]))
        service._update_entities_modified(session, "Person")
        result = json.loads(session.entities_modified)
        assert result == ["Person"]


# ---------------------------------------------------------------------------
# _get_git_ontology_path
# ---------------------------------------------------------------------------


class TestGetGitOntologyPath:
    def test_default_path(self, service: SuggestionService) -> None:
        """Returns 'ontology.ttl' when project has no source_file_path."""
        project = _make_project()
        project.source_file_path = None
        assert service._get_git_ontology_path(project) == "ontology.ttl"

    def test_custom_path(self, service: SuggestionService) -> None:
        """Returns normalized path from project settings."""
        project = _make_project()
        project.source_file_path = "src/ontology.owl"
        assert service._get_git_ontology_path(project) == "src/ontology.owl"

    def test_rejects_path_traversal(self, service: SuggestionService) -> None:
        """Raises HTTPException for path traversal attempt."""
        project = _make_project()
        project.source_file_path = "../../etc/passwd"
        with pytest.raises(HTTPException) as exc_info:
            service._get_git_ontology_path(project)
        assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# _can_suggest / _get_user_role
# ---------------------------------------------------------------------------


class TestCanSuggest:
    def test_editor_can_suggest(self, service: SuggestionService) -> None:
        """Editor role can suggest."""
        user = _make_user()
        assert service._can_suggest("editor", user) is True

    def test_viewer_cannot_suggest(self, service: SuggestionService) -> None:
        """Viewer role cannot suggest."""
        user = _make_user()
        assert service._can_suggest("viewer", user) is False

    def test_none_role_cannot_suggest(self, service: SuggestionService) -> None:
        """None role (non-member) cannot suggest."""
        user = _make_user()
        assert service._can_suggest(None, user) is False

    def test_superadmin_can_always_suggest(self, service: SuggestionService) -> None:
        """Superadmin bypasses role check."""
        user = _make_user()
        with patch.object(
            type(user), "is_superadmin", new_callable=lambda: property(lambda _s: True)
        ):
            assert service._can_suggest(None, user) is True


class TestGetUserRole:
    def test_returns_role_for_member(self, service: SuggestionService) -> None:
        """Returns the role for a project member."""
        project = _make_project()
        user = _make_user()
        assert service._get_user_role(project, user) == "editor"

    def test_returns_none_for_non_member(self, service: SuggestionService) -> None:
        """Returns None for a non-member."""
        project = _make_project()
        user = _make_user(user_id="other-user")
        assert service._get_user_role(project, user) is None


# ---------------------------------------------------------------------------
# create_session
# ---------------------------------------------------------------------------


class TestCreateSession:
    @pytest.mark.asyncio
    async def test_creates_new_session(
        self,
        service: SuggestionService,
        mock_db: AsyncMock,
        mock_git: MagicMock,
    ) -> None:
        """Creates a new session when no active session exists."""
        project = _make_project()

        # First execute: _get_project
        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none.return_value = project

        # Second execute: check existing active session
        mock_existing_result = MagicMock()
        mock_existing_result.scalar_one_or_none.return_value = None

        mock_db.execute.side_effect = [mock_project_result, mock_existing_result]

        def _simulate_refresh(obj: object, _attrs: list[str] | None = None) -> None:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()  # type: ignore[attr-defined]
            if getattr(obj, "created_at", None) is None:
                obj.created_at = datetime.now(UTC)  # type: ignore[attr-defined]

        mock_db.refresh.side_effect = _simulate_refresh

        user = _make_user()
        with patch("ontokit.services.suggestion_service.create_beacon_token", return_value="tok"):
            result = await service.create_session(PROJECT_ID, user)

        assert result.session_id is not None
        assert result.branch.startswith("suggest/")
        mock_git.create_branch.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_existing_active_session(
        self,
        service: SuggestionService,
        mock_db: AsyncMock,
    ) -> None:
        """Returns existing active session without creating a new one."""
        project = _make_project()
        existing = _make_session()

        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none.return_value = project

        mock_existing_result = MagicMock()
        mock_existing_result.scalar_one_or_none.return_value = existing

        mock_db.execute.side_effect = [mock_project_result, mock_existing_result]

        user = _make_user()
        result = await service.create_session(PROJECT_ID, user)
        assert result.session_id == existing.session_id

    @pytest.mark.asyncio
    async def test_forbidden_for_non_member(
        self,
        service: SuggestionService,
        mock_db: AsyncMock,
    ) -> None:
        """Raises 403 when user has no suggest permission."""
        project = _make_project()
        # Make user not a member
        project.members = []

        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none.return_value = project
        mock_db.execute.return_value = mock_project_result

        user = _make_user(user_id="other-user")
        with pytest.raises(HTTPException) as exc_info:
            await service.create_session(PROJECT_ID, user)
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# list_sessions
# ---------------------------------------------------------------------------


class TestListSessions:
    @pytest.mark.asyncio
    async def test_returns_user_sessions(
        self,
        service: SuggestionService,
        mock_db: AsyncMock,
    ) -> None:
        """Lists sessions for the current user."""
        session = _make_session()

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [session]
        mock_db.execute.return_value = mock_result

        user = _make_user()
        result = await service.list_sessions(PROJECT_ID, user)
        assert len(result.items) == 1
        assert result.items[0].session_id == session.session_id

    @pytest.mark.asyncio
    async def test_returns_empty_list(
        self,
        service: SuggestionService,
        mock_db: AsyncMock,
    ) -> None:
        """Returns empty list when no sessions exist."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        user = _make_user()
        result = await service.list_sessions(PROJECT_ID, user)
        assert result.items == []


# ---------------------------------------------------------------------------
# discard
# ---------------------------------------------------------------------------


class TestDiscard:
    @pytest.mark.asyncio
    async def test_discards_active_session(
        self,
        service: SuggestionService,
        mock_db: AsyncMock,
        mock_git: MagicMock,
    ) -> None:
        """Discards an active session and deletes the branch."""
        session = _make_session(status=SuggestionSessionStatus.ACTIVE.value)
        project = _make_project()

        # _get_session, _verify_ownership (inline), _verify_project_access -> _get_project
        mock_session_result = MagicMock()
        mock_session_result.scalar_one_or_none.return_value = session
        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none.return_value = project

        mock_db.execute.side_effect = [mock_session_result, mock_project_result]

        user = _make_user()
        await service.discard(PROJECT_ID, session.session_id, user)

        assert session.status == SuggestionSessionStatus.DISCARDED.value
        mock_git.delete_branch.assert_called_once()

    @pytest.mark.asyncio
    async def test_cannot_discard_submitted_session(
        self,
        service: SuggestionService,
        mock_db: AsyncMock,
    ) -> None:
        """Raises 400 when trying to discard a submitted session."""
        session = _make_session(status=SuggestionSessionStatus.SUBMITTED.value)
        project = _make_project()

        mock_session_result = MagicMock()
        mock_session_result.scalar_one_or_none.return_value = session
        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none.return_value = project

        mock_db.execute.side_effect = [mock_session_result, mock_project_result]

        user = _make_user()
        with pytest.raises(HTTPException) as exc_info:
            await service.discard(PROJECT_ID, session.session_id, user)
        assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# auto_submit_stale_sessions
# ---------------------------------------------------------------------------


class TestAutoSubmitStaleSessions:
    @pytest.mark.asyncio
    async def test_no_stale_sessions(
        self,
        service: SuggestionService,
        mock_db: AsyncMock,
    ) -> None:
        """Returns 0 when no stale sessions are found."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        count = await service.auto_submit_stale_sessions()
        assert count == 0

    @pytest.mark.asyncio
    async def test_skips_already_claimed_session(
        self,
        service: SuggestionService,
        mock_db: AsyncMock,
    ) -> None:
        """Skips sessions claimed by another worker (rowcount=0)."""
        stale_session = _make_session(
            changes_count=3,
            last_activity=datetime.now(UTC) - timedelta(hours=1),
        )

        mock_stale_result = MagicMock()
        mock_stale_result.scalars.return_value.all.return_value = [stale_session]

        mock_claim_result = MagicMock()
        mock_claim_result.rowcount = 0

        mock_db.execute.side_effect = [mock_stale_result, mock_claim_result]

        count = await service.auto_submit_stale_sessions()
        assert count == 0


# ---------------------------------------------------------------------------
# _verify_ownership
# ---------------------------------------------------------------------------


class TestVerifyOwnership:
    def test_owner_passes(self, service: SuggestionService) -> None:
        """No exception when user owns the session."""
        session = _make_session(user_id="test-user-id")
        user = _make_user(user_id="test-user-id")
        service._verify_ownership(session, user)  # should not raise

    def test_non_owner_raises(self, service: SuggestionService) -> None:
        """Raises 403 when user does not own the session."""
        session = _make_session(user_id="other-user")
        user = _make_user(user_id="test-user-id")
        with pytest.raises(HTTPException) as exc_info:
            service._verify_ownership(session, user)
        assert exc_info.value.status_code == 403

    def test_superadmin_bypasses(self, service: SuggestionService) -> None:
        """Superadmin can access any session."""
        session = _make_session(user_id="other-user")
        user = _make_user(user_id="admin-id")
        with patch.object(
            type(user), "is_superadmin", new_callable=lambda: property(lambda _s: True)
        ):
            service._verify_ownership(session, user)  # should not raise


# ---------------------------------------------------------------------------
# _build_summary
# ---------------------------------------------------------------------------


class TestBuildSummary:
    @pytest.mark.asyncio
    async def test_builds_summary_without_pr(
        self,
        service: SuggestionService,
        mock_db: AsyncMock,  # noqa: ARG002
    ) -> None:
        """Builds a summary for a session without a linked PR."""
        session = _make_session(
            entities_modified=json.dumps(["Person"]),
            changes_count=2,
        )
        session.pr_id = None
        session.reviewer_id = None

        result = await service._build_summary(session)
        assert result.session_id == session.session_id
        assert result.entities_modified == ["Person"]
        assert result.changes_count == 2
        assert result.pr_url is None

    @pytest.mark.asyncio
    async def test_builds_summary_with_pr(
        self,
        service: SuggestionService,
        mock_db: AsyncMock,
    ) -> None:
        """Builds a summary for a session with a linked PR."""
        pr_id = uuid.uuid4()
        session = _make_session(
            entities_modified=json.dumps(["Person"]),
            changes_count=1,
            pr_number=1,
            pr_id=pr_id,
        )
        session.reviewer_id = None

        mock_pr = MagicMock()
        mock_pr.github_pr_url = "https://github.com/org/repo/pull/1"

        mock_pr_result = MagicMock()
        mock_pr_result.scalar_one_or_none.return_value = mock_pr
        mock_db.execute.return_value = mock_pr_result

        result = await service._build_summary(session)
        assert result.pr_url == "https://github.com/org/repo/pull/1"

    @pytest.mark.asyncio
    async def test_builds_summary_with_reviewer(
        self,
        service: SuggestionService,
        mock_db: AsyncMock,  # noqa: ARG002
    ) -> None:
        """Builds a summary that includes reviewer info."""
        session = _make_session(entities_modified=json.dumps(["Person"]))
        session.pr_id = None
        session.reviewer_id = "reviewer-id"
        session.reviewer_name = "Reviewer"
        session.reviewer_email = "reviewer@example.com"

        result = await service._build_summary(session)
        assert result.reviewer is not None
        assert result.reviewer.id == "reviewer-id"


# ---------------------------------------------------------------------------
# _get_project (line 71 – 404 branch)
# ---------------------------------------------------------------------------


class TestGetProject:
    @pytest.mark.asyncio
    async def test_project_not_found(
        self,
        service: SuggestionService,
        mock_db: AsyncMock,
    ) -> None:
        """Raises 404 when project does not exist."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        with pytest.raises(HTTPException) as exc_info:
            await service._get_project(PROJECT_ID)
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# _get_session (line 122 – 404 branch)
# ---------------------------------------------------------------------------


class TestGetSession:
    @pytest.mark.asyncio
    async def test_session_not_found(
        self,
        service: SuggestionService,
        mock_db: AsyncMock,
    ) -> None:
        """Raises 404 when session does not exist."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        with pytest.raises(HTTPException) as exc_info:
            await service._get_session(PROJECT_ID, "nonexistent")
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# _verify_project_access (line 95 – 403 branch)
# ---------------------------------------------------------------------------


class TestVerifyProjectAccess:
    @pytest.mark.asyncio
    async def test_raises_403_when_no_permission(
        self,
        service: SuggestionService,
        mock_db: AsyncMock,
    ) -> None:
        """Raises 403 when user cannot suggest."""
        project = _make_project()
        project.members = []  # no members -> no role

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = project
        mock_db.execute.return_value = mock_result

        user = _make_user(user_id="unknown-user")
        with pytest.raises(HTTPException) as exc_info:
            await service._verify_project_access(PROJECT_ID, user)
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# _can_review / _verify_reviewer_access
# ---------------------------------------------------------------------------


class TestCanReview:
    def test_editor_can_review(self, service: SuggestionService) -> None:
        user = _make_user()
        assert service._can_review("editor", user) is True

    def test_viewer_cannot_review(self, service: SuggestionService) -> None:
        user = _make_user()
        assert service._can_review("viewer", user) is False

    def test_superadmin_can_review(self, service: SuggestionService) -> None:
        user = _make_user()
        with patch.object(
            type(user), "is_superadmin", new_callable=lambda: property(lambda _s: True)
        ):
            assert service._can_review(None, user) is True

    def test_suggester_cannot_review(self, service: SuggestionService) -> None:
        user = _make_user()
        assert service._can_review("suggester", user) is False


class TestVerifyReviewerAccess:
    @pytest.mark.asyncio
    async def test_raises_403_for_non_reviewer(
        self,
        service: SuggestionService,
        mock_db: AsyncMock,
    ) -> None:
        """Raises 403 when user lacks review permissions."""
        project = _make_project()
        project.members = []

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = project
        mock_db.execute.return_value = mock_result

        user = _make_user(user_id="unknown-user")
        with pytest.raises(HTTPException) as exc_info:
            await service._verify_reviewer_access(PROJECT_ID, user)
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# save
# ---------------------------------------------------------------------------


class TestSave:
    @pytest.mark.asyncio
    async def test_save_success(
        self,
        service: SuggestionService,
        mock_db: AsyncMock,
        mock_git: MagicMock,
    ) -> None:
        """Saves content to the suggestion branch."""
        session = _make_session(
            status=SuggestionSessionStatus.ACTIVE.value,
            changes_count=0,
        )
        project = _make_project()

        mock_session_result = MagicMock()
        mock_session_result.scalar_one_or_none.return_value = session
        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none.return_value = project

        # _get_session, _verify_project_access -> _get_project, save -> _get_project
        mock_db.execute.side_effect = [
            mock_session_result,
            mock_project_result,
            mock_project_result,
        ]

        commit_info = MagicMock()
        commit_info.hash = "abc123"
        mock_git.commit_to_branch = MagicMock(return_value=commit_info)

        from ontokit.schemas.suggestion import SuggestionSaveRequest

        data = SuggestionSaveRequest(
            content="@prefix : <http://example.org/> .",
            entity_iri="http://example.org/Person",
            entity_label="Person",
        )

        user = _make_user()
        result = await service.save(PROJECT_ID, session.session_id, data, user)

        assert result.commit_hash == "abc123"
        assert result.branch == session.branch
        assert result.changes_count == 1
        mock_git.commit_to_branch.assert_called_once()

    @pytest.mark.asyncio
    async def test_save_non_active_session_raises_400(
        self,
        service: SuggestionService,
        mock_db: AsyncMock,
    ) -> None:
        """Raises 400 when session is not active."""
        session = _make_session(status=SuggestionSessionStatus.SUBMITTED.value)
        project = _make_project()

        mock_session_result = MagicMock()
        mock_session_result.scalar_one_or_none.return_value = session
        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none.return_value = project

        mock_db.execute.side_effect = [mock_session_result, mock_project_result]

        from ontokit.schemas.suggestion import SuggestionSaveRequest

        data = SuggestionSaveRequest(
            content="content",
            entity_iri="http://example.org/X",
            entity_label="X",
        )

        user = _make_user()
        with pytest.raises(HTTPException) as exc_info:
            await service.save(PROJECT_ID, session.session_id, data, user)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_save_git_failure_raises_500(
        self,
        service: SuggestionService,
        mock_db: AsyncMock,
        mock_git: MagicMock,
    ) -> None:
        """Raises 500 when git commit fails."""
        session = _make_session(
            status=SuggestionSessionStatus.ACTIVE.value,
            changes_count=0,
        )
        project = _make_project()

        mock_session_result = MagicMock()
        mock_session_result.scalar_one_or_none.return_value = session
        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none.return_value = project

        mock_db.execute.side_effect = [
            mock_session_result,
            mock_project_result,
            mock_project_result,
        ]

        mock_git.commit_to_branch = MagicMock(side_effect=RuntimeError("git error"))

        from ontokit.schemas.suggestion import SuggestionSaveRequest

        data = SuggestionSaveRequest(
            content="content",
            entity_iri="http://example.org/X",
            entity_label="X",
        )

        user = _make_user()
        with pytest.raises(HTTPException) as exc_info:
            await service.save(PROJECT_ID, session.session_id, data, user)
        assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_save_metadata_commit_failure_raises_500(
        self,
        service: SuggestionService,
        mock_db: AsyncMock,
        mock_git: MagicMock,
    ) -> None:
        """Raises 500 when DB metadata commit fails after git success."""
        session = _make_session(
            status=SuggestionSessionStatus.ACTIVE.value,
            changes_count=0,
        )
        project = _make_project()

        mock_session_result = MagicMock()
        mock_session_result.scalar_one_or_none.return_value = session
        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none.return_value = project

        mock_db.execute.side_effect = [
            mock_session_result,
            mock_project_result,
            mock_project_result,
        ]

        commit_info = MagicMock()
        commit_info.hash = "abc123"
        mock_git.commit_to_branch = MagicMock(return_value=commit_info)

        # Make db.commit fail
        mock_db.commit.side_effect = RuntimeError("DB error")

        from ontokit.schemas.suggestion import SuggestionSaveRequest

        data = SuggestionSaveRequest(
            content="content",
            entity_iri="http://example.org/X",
            entity_label="X",
        )

        user = _make_user()
        with pytest.raises(HTTPException) as exc_info:
            await service.save(PROJECT_ID, session.session_id, data, user)
        assert exc_info.value.status_code == 500
        assert "metadata" in exc_info.value.detail


# ---------------------------------------------------------------------------
# submit
# ---------------------------------------------------------------------------


class TestSubmit:
    @pytest.mark.asyncio
    async def test_submit_success(
        self,
        service: SuggestionService,
        mock_db: AsyncMock,
        mock_git: MagicMock,
    ) -> None:
        """Submits a session by creating a PR."""
        session = _make_session(
            status=SuggestionSessionStatus.ACTIVE.value,
            changes_count=3,
            entities_modified=json.dumps(["Person", "Organization"]),
        )
        project = _make_project()

        mock_session_result = MagicMock()
        mock_session_result.scalar_one_or_none.return_value = session
        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none.return_value = project
        # For existing PR check (none found)
        mock_no_pr_result = MagicMock()
        mock_no_pr_result.scalar_one_or_none.return_value = None

        mock_db.execute.side_effect = [
            mock_session_result,  # _get_session
            mock_project_result,  # _verify_project_access -> _get_project
            mock_no_pr_result,  # existing PR check
            mock_project_result,  # _get_project for notification
        ]

        mock_git.get_default_branch = MagicMock(return_value="main")

        mock_pr_response = MagicMock()
        mock_pr_response.pr_number = 42
        mock_pr_response.id = uuid.uuid4()
        mock_pr_response.github_pr_url = "https://github.com/org/repo/pull/42"
        mock_pr_response.title = "Suggestion: Update Person, Organization"

        from ontokit.schemas.suggestion import SuggestionSubmitRequest

        data = SuggestionSubmitRequest(summary="My changes")
        user = _make_user()

        with (
            patch(
                "ontokit.services.suggestion_service.get_pull_request_service"
            ) as mock_pr_svc_factory,
            patch("ontokit.services.suggestion_service.NotificationService") as mock_notif_cls,
        ):
            mock_pr_svc = AsyncMock()
            mock_pr_svc.create_pull_request = AsyncMock(return_value=mock_pr_response)
            mock_pr_svc_factory.return_value = mock_pr_svc
            mock_notif = AsyncMock()
            mock_notif_cls.return_value = mock_notif

            result = await service.submit(PROJECT_ID, session.session_id, data, user)

        assert result.pr_number == 42
        assert result.status == "submitted"

    @pytest.mark.asyncio
    async def test_submit_no_changes_raises_400(
        self,
        service: SuggestionService,
        mock_db: AsyncMock,
    ) -> None:
        """Raises 400 when session has no changes."""
        session = _make_session(
            status=SuggestionSessionStatus.ACTIVE.value,
            changes_count=0,
        )
        project = _make_project()

        mock_session_result = MagicMock()
        mock_session_result.scalar_one_or_none.return_value = session
        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none.return_value = project

        mock_db.execute.side_effect = [mock_session_result, mock_project_result]

        from ontokit.schemas.suggestion import SuggestionSubmitRequest

        data = SuggestionSubmitRequest(summary=None)
        user = _make_user()

        with pytest.raises(HTTPException) as exc_info:
            await service.submit(PROJECT_ID, session.session_id, data, user)
        assert exc_info.value.status_code == 400
        assert "No changes" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_submit_non_active_raises_400(
        self,
        service: SuggestionService,
        mock_db: AsyncMock,
    ) -> None:
        """Raises 400 when session is not active."""
        session = _make_session(
            status=SuggestionSessionStatus.SUBMITTED.value,
            changes_count=5,
        )
        project = _make_project()

        mock_session_result = MagicMock()
        mock_session_result.scalar_one_or_none.return_value = session
        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none.return_value = project

        mock_db.execute.side_effect = [mock_session_result, mock_project_result]

        from ontokit.schemas.suggestion import SuggestionSubmitRequest

        data = SuggestionSubmitRequest()
        user = _make_user()

        with pytest.raises(HTTPException) as exc_info:
            await service.submit(PROJECT_ID, session.session_id, data, user)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_submit_existing_pr_idempotent(
        self,
        service: SuggestionService,
        mock_db: AsyncMock,
    ) -> None:
        """Returns existing PR if branch already has one (idempotency)."""
        pr_id = uuid.uuid4()
        session = _make_session(
            status=SuggestionSessionStatus.ACTIVE.value,
            changes_count=2,
            entities_modified=json.dumps(["Person"]),
        )
        project = _make_project()

        mock_session_result = MagicMock()
        mock_session_result.scalar_one_or_none.return_value = session
        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none.return_value = project

        existing_pr = MagicMock()
        existing_pr.pr_number = 10
        existing_pr.id = pr_id
        existing_pr.github_pr_url = "https://github.com/org/repo/pull/10"

        mock_existing_pr_result = MagicMock()
        mock_existing_pr_result.scalar_one_or_none.return_value = existing_pr

        mock_db.execute.side_effect = [
            mock_session_result,  # _get_session
            mock_project_result,  # _verify_project_access
            mock_existing_pr_result,  # existing PR check
        ]

        from ontokit.schemas.suggestion import SuggestionSubmitRequest

        data = SuggestionSubmitRequest(summary="test")
        user = _make_user()

        result = await service.submit(PROJECT_ID, session.session_id, data, user)
        assert result.pr_number == 10
        assert result.status == "submitted"

    @pytest.mark.asyncio
    async def test_submit_fallback_to_direct_pr_on_403(
        self,
        service: SuggestionService,
        mock_db: AsyncMock,
        mock_git: MagicMock,
    ) -> None:
        """Falls back to _create_pr_directly when PR service returns 403."""
        session = _make_session(
            status=SuggestionSessionStatus.ACTIVE.value,
            changes_count=2,
            entities_modified=json.dumps(["Person"]),
        )
        project = _make_project()

        mock_session_result = MagicMock()
        mock_session_result.scalar_one_or_none.return_value = session
        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none.return_value = project
        mock_no_pr_result = MagicMock()
        mock_no_pr_result.scalar_one_or_none.return_value = None
        # For _create_pr_directly: max pr_number query
        mock_max_result = MagicMock()
        mock_max_result.scalar.return_value = 5

        mock_db.execute.side_effect = [
            mock_session_result,  # _get_session
            mock_project_result,  # _verify_project_access
            mock_no_pr_result,  # existing PR check
            mock_max_result,  # max pr_number
            mock_project_result,  # _get_project for notification
        ]

        mock_git.get_default_branch = MagicMock(return_value="main")

        # Make the PR service raise 403
        mock_direct_pr = MagicMock()
        mock_direct_pr.pr_number = 6
        mock_direct_pr.id = uuid.uuid4()
        mock_direct_pr.github_pr_url = None
        mock_direct_pr.title = "Suggestion: Update Person"

        from ontokit.schemas.suggestion import SuggestionSubmitRequest

        data = SuggestionSubmitRequest(summary="changes")
        user = _make_user()

        with (
            patch(
                "ontokit.services.suggestion_service.get_pull_request_service"
            ) as mock_pr_svc_factory,
            patch("ontokit.services.suggestion_service.NotificationService") as mock_notif_cls,
        ):
            mock_pr_svc = AsyncMock()
            mock_pr_svc.create_pull_request = AsyncMock(
                side_effect=HTTPException(status_code=403, detail="Forbidden")
            )
            mock_pr_svc_factory.return_value = mock_pr_svc
            mock_notif = AsyncMock()
            mock_notif_cls.return_value = mock_notif

            # Mock _create_pr_directly to return a PR
            mock_db.flush = AsyncMock()
            mock_db.refresh = AsyncMock(
                side_effect=lambda obj: setattr(obj, "id", mock_direct_pr.id)
            )

            result = await service.submit(PROJECT_ID, session.session_id, data, user)

        assert result.pr_number == 6
        assert result.status == "submitted"


# ---------------------------------------------------------------------------
# approve
# ---------------------------------------------------------------------------


class TestApprove:
    @pytest.mark.asyncio
    async def test_approve_success(
        self,
        service: SuggestionService,
        mock_db: AsyncMock,
    ) -> None:
        """Approves a submitted session and merges the PR."""
        session = _make_session(
            status=SuggestionSessionStatus.SUBMITTED.value,
            pr_number=5,
        )
        project = _make_project()
        # Editor role for reviewer
        project.members[0].role = "admin"

        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none.return_value = project
        mock_session_result = MagicMock()
        mock_session_result.scalar_one_or_none.return_value = session

        mock_db.execute.side_effect = [mock_project_result, mock_session_result]

        user = _make_user()

        with patch(
            "ontokit.services.suggestion_service.get_pull_request_service"
        ) as mock_pr_svc_factory:
            mock_pr_svc = AsyncMock()
            mock_pr_svc.merge_pull_request = AsyncMock()
            mock_pr_svc_factory.return_value = mock_pr_svc

            await service.approve(PROJECT_ID, session.session_id, user)

        assert session.status == SuggestionSessionStatus.MERGED.value
        assert session.reviewer_id == user.id
        mock_db.commit.assert_called()

    @pytest.mark.asyncio
    async def test_approve_wrong_status_raises_400(
        self,
        service: SuggestionService,
        mock_db: AsyncMock,
    ) -> None:
        """Raises 400 when session is not submitted."""
        session = _make_session(status=SuggestionSessionStatus.ACTIVE.value)
        project = _make_project()
        project.members[0].role = "admin"

        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none.return_value = project
        mock_session_result = MagicMock()
        mock_session_result.scalar_one_or_none.return_value = session

        mock_db.execute.side_effect = [mock_project_result, mock_session_result]

        user = _make_user()
        with pytest.raises(HTTPException) as exc_info:
            await service.approve(PROJECT_ID, session.session_id, user)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_approve_auto_submitted_session(
        self,
        service: SuggestionService,
        mock_db: AsyncMock,
    ) -> None:
        """Can approve an auto-submitted session."""
        session = _make_session(
            status=SuggestionSessionStatus.AUTO_SUBMITTED.value,
            pr_number=7,
        )
        project = _make_project()
        project.members[0].role = "admin"

        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none.return_value = project
        mock_session_result = MagicMock()
        mock_session_result.scalar_one_or_none.return_value = session

        mock_db.execute.side_effect = [mock_project_result, mock_session_result]

        user = _make_user()

        with patch(
            "ontokit.services.suggestion_service.get_pull_request_service"
        ) as mock_pr_svc_factory:
            mock_pr_svc = AsyncMock()
            mock_pr_svc.merge_pull_request = AsyncMock()
            mock_pr_svc_factory.return_value = mock_pr_svc

            await service.approve(PROJECT_ID, session.session_id, user)

        assert session.status == SuggestionSessionStatus.MERGED.value

    @pytest.mark.asyncio
    async def test_approve_without_pr(
        self,
        service: SuggestionService,
        mock_db: AsyncMock,
    ) -> None:
        """Approves a session that has no PR number (skips merge)."""
        session = _make_session(
            status=SuggestionSessionStatus.SUBMITTED.value,
            pr_number=None,
        )
        project = _make_project()
        project.members[0].role = "admin"

        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none.return_value = project
        mock_session_result = MagicMock()
        mock_session_result.scalar_one_or_none.return_value = session

        mock_db.execute.side_effect = [mock_project_result, mock_session_result]

        user = _make_user()
        await service.approve(PROJECT_ID, session.session_id, user)

        assert session.status == SuggestionSessionStatus.MERGED.value

    @pytest.mark.asyncio
    async def test_approve_merge_failure_still_merges(
        self,
        service: SuggestionService,
        mock_db: AsyncMock,
    ) -> None:
        """Marks session merged even if PR merge raises HTTPException."""
        session = _make_session(
            status=SuggestionSessionStatus.SUBMITTED.value,
            pr_number=5,
        )
        project = _make_project()
        project.members[0].role = "admin"

        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none.return_value = project
        mock_session_result = MagicMock()
        mock_session_result.scalar_one_or_none.return_value = session

        mock_db.execute.side_effect = [mock_project_result, mock_session_result]

        user = _make_user()

        with patch(
            "ontokit.services.suggestion_service.get_pull_request_service"
        ) as mock_pr_svc_factory:
            mock_pr_svc = AsyncMock()
            mock_pr_svc.merge_pull_request = AsyncMock(
                side_effect=HTTPException(status_code=409, detail="conflict")
            )
            mock_pr_svc_factory.return_value = mock_pr_svc

            await service.approve(PROJECT_ID, session.session_id, user)

        assert session.status == SuggestionSessionStatus.MERGED.value


# ---------------------------------------------------------------------------
# reject
# ---------------------------------------------------------------------------


class TestReject:
    @pytest.mark.asyncio
    async def test_reject_success(
        self,
        service: SuggestionService,
        mock_db: AsyncMock,
    ) -> None:
        """Rejects a submitted session with a reason."""
        session = _make_session(status=SuggestionSessionStatus.SUBMITTED.value)
        project = _make_project()
        project.members[0].role = "admin"

        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none.return_value = project
        mock_session_result = MagicMock()
        mock_session_result.scalar_one_or_none.return_value = session

        mock_db.execute.side_effect = [mock_project_result, mock_session_result]

        from ontokit.schemas.suggestion import SuggestionRejectRequest

        data = SuggestionRejectRequest(reason="Not aligned with ontology design")
        user = _make_user()

        await service.reject(PROJECT_ID, session.session_id, data, user)

        assert session.status == SuggestionSessionStatus.REJECTED.value
        assert session.reviewer_feedback == "Not aligned with ontology design"
        assert session.reviewer_id == user.id

    @pytest.mark.asyncio
    async def test_reject_wrong_status_raises_400(
        self,
        service: SuggestionService,
        mock_db: AsyncMock,
    ) -> None:
        """Raises 400 when session is not submitted."""
        session = _make_session(status=SuggestionSessionStatus.ACTIVE.value)
        project = _make_project()
        project.members[0].role = "admin"

        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none.return_value = project
        mock_session_result = MagicMock()
        mock_session_result.scalar_one_or_none.return_value = session

        mock_db.execute.side_effect = [mock_project_result, mock_session_result]

        from ontokit.schemas.suggestion import SuggestionRejectRequest

        data = SuggestionRejectRequest(reason="Bad")
        user = _make_user()

        with pytest.raises(HTTPException) as exc_info:
            await service.reject(PROJECT_ID, session.session_id, data, user)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_reject_auto_submitted_session(
        self,
        service: SuggestionService,
        mock_db: AsyncMock,
    ) -> None:
        """Can reject an auto-submitted session."""
        session = _make_session(status=SuggestionSessionStatus.AUTO_SUBMITTED.value)
        project = _make_project()
        project.members[0].role = "admin"

        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none.return_value = project
        mock_session_result = MagicMock()
        mock_session_result.scalar_one_or_none.return_value = session

        mock_db.execute.side_effect = [mock_project_result, mock_session_result]

        from ontokit.schemas.suggestion import SuggestionRejectRequest

        data = SuggestionRejectRequest(reason="Not needed")
        user = _make_user()

        await service.reject(PROJECT_ID, session.session_id, data, user)
        assert session.status == SuggestionSessionStatus.REJECTED.value


# ---------------------------------------------------------------------------
# request_changes
# ---------------------------------------------------------------------------


class TestRequestChanges:
    @pytest.mark.asyncio
    async def test_request_changes_success(
        self,
        service: SuggestionService,
        mock_db: AsyncMock,
    ) -> None:
        """Requests changes on a submitted session."""
        session = _make_session(status=SuggestionSessionStatus.SUBMITTED.value)
        project = _make_project()
        project.members[0].role = "admin"

        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none.return_value = project
        mock_session_result = MagicMock()
        mock_session_result.scalar_one_or_none.return_value = session

        mock_db.execute.side_effect = [mock_project_result, mock_session_result]

        from ontokit.schemas.suggestion import SuggestionRequestChangesRequest

        data = SuggestionRequestChangesRequest(feedback="Please fix the label")
        user = _make_user()

        await service.request_changes(PROJECT_ID, session.session_id, data, user)

        assert session.status == SuggestionSessionStatus.CHANGES_REQUESTED.value
        assert session.reviewer_feedback == "Please fix the label"
        assert session.reviewer_id == user.id

    @pytest.mark.asyncio
    async def test_request_changes_wrong_status_raises_400(
        self,
        service: SuggestionService,
        mock_db: AsyncMock,
    ) -> None:
        """Raises 400 when session is not in submitted state."""
        session = _make_session(status=SuggestionSessionStatus.ACTIVE.value)
        project = _make_project()
        project.members[0].role = "admin"

        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none.return_value = project
        mock_session_result = MagicMock()
        mock_session_result.scalar_one_or_none.return_value = session

        mock_db.execute.side_effect = [mock_project_result, mock_session_result]

        from ontokit.schemas.suggestion import SuggestionRequestChangesRequest

        data = SuggestionRequestChangesRequest(feedback="Fix it")
        user = _make_user()

        with pytest.raises(HTTPException) as exc_info:
            await service.request_changes(PROJECT_ID, session.session_id, data, user)
        assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# resubmit
# ---------------------------------------------------------------------------


class TestResubmit:
    @pytest.mark.asyncio
    async def test_resubmit_success(
        self,
        service: SuggestionService,
        mock_db: AsyncMock,
    ) -> None:
        """Resubmits a session after changes were requested."""
        session = _make_session(
            status=SuggestionSessionStatus.CHANGES_REQUESTED.value,
            pr_number=10,
        )
        project = _make_project()

        mock_session_result = MagicMock()
        mock_session_result.scalar_one_or_none.return_value = session
        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none.return_value = project

        mock_db.execute.side_effect = [mock_session_result, mock_project_result]

        from ontokit.schemas.suggestion import SuggestionResubmitRequest

        data = SuggestionResubmitRequest(summary="Fixed the labels")
        user = _make_user()

        result = await service.resubmit(PROJECT_ID, session.session_id, data, user)

        assert result.pr_number == 10
        assert result.status == "submitted"
        assert session.status == SuggestionSessionStatus.SUBMITTED.value
        assert session.revision == 2
        assert session.summary == "Fixed the labels"
        assert session.reviewer_feedback is None
        assert session.reviewed_at is None

    @pytest.mark.asyncio
    async def test_resubmit_wrong_status_raises_400(
        self,
        service: SuggestionService,
        mock_db: AsyncMock,
    ) -> None:
        """Raises 400 when session is not in changes-requested state."""
        session = _make_session(status=SuggestionSessionStatus.SUBMITTED.value)
        project = _make_project()

        mock_session_result = MagicMock()
        mock_session_result.scalar_one_or_none.return_value = session
        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none.return_value = project

        mock_db.execute.side_effect = [mock_session_result, mock_project_result]

        from ontokit.schemas.suggestion import SuggestionResubmitRequest

        data = SuggestionResubmitRequest(summary="try again")
        user = _make_user()

        with pytest.raises(HTTPException) as exc_info:
            await service.resubmit(PROJECT_ID, session.session_id, data, user)
        assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# beacon_save
# ---------------------------------------------------------------------------


class TestBeaconSave:
    @pytest.mark.asyncio
    async def test_beacon_save_success(
        self,
        service: SuggestionService,
        mock_db: AsyncMock,
        mock_git: MagicMock,
    ) -> None:
        """Beacon save commits content to the suggestion branch."""
        session = _make_session(
            status=SuggestionSessionStatus.ACTIVE.value,
            changes_count=1,
        )
        project = _make_project()

        mock_session_result = MagicMock()
        mock_session_result.scalar_one_or_none.return_value = session
        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none.return_value = project

        # _get_session, _verify_project_access -> _get_project, _get_project for filename
        mock_db.execute.side_effect = [
            mock_session_result,
            mock_project_result,
            mock_project_result,
        ]

        mock_git.commit_to_branch = MagicMock()

        from ontokit.schemas.suggestion import SuggestionBeaconRequest

        data = SuggestionBeaconRequest(
            session_id=session.session_id,
            content="@prefix : <http://example.org/> .",
        )

        with patch(
            "ontokit.services.suggestion_service.verify_beacon_token",
            return_value=session.session_id,
        ):
            await service.beacon_save(PROJECT_ID, data, "valid-token")

        assert session.changes_count == 2
        mock_git.commit_to_branch.assert_called_once()

    @pytest.mark.asyncio
    async def test_beacon_save_invalid_token_raises_401(
        self,
        service: SuggestionService,
    ) -> None:
        """Raises 401 when beacon token is invalid."""
        from ontokit.schemas.suggestion import SuggestionBeaconRequest

        data = SuggestionBeaconRequest(session_id="s_abc12345", content="data")

        with patch(
            "ontokit.services.suggestion_service.verify_beacon_token",
            return_value=None,
        ):
            with pytest.raises(HTTPException) as exc_info:
                await service.beacon_save(PROJECT_ID, data, "bad-token")
            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_beacon_save_token_mismatch_raises_403(
        self,
        service: SuggestionService,
    ) -> None:
        """Raises 403 when token session_id does not match data."""
        from ontokit.schemas.suggestion import SuggestionBeaconRequest

        data = SuggestionBeaconRequest(session_id="s_abc12345", content="data")

        with patch(
            "ontokit.services.suggestion_service.verify_beacon_token",
            return_value="s_other_session",
        ):
            with pytest.raises(HTTPException) as exc_info:
                await service.beacon_save(PROJECT_ID, data, "token")
            assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_beacon_save_non_active_silently_returns(
        self,
        service: SuggestionService,
        mock_db: AsyncMock,
        mock_git: MagicMock,
    ) -> None:
        """Silently returns when session is not active."""
        session = _make_session(status=SuggestionSessionStatus.SUBMITTED.value)

        mock_session_result = MagicMock()
        mock_session_result.scalar_one_or_none.return_value = session
        mock_db.execute.return_value = mock_session_result

        from ontokit.schemas.suggestion import SuggestionBeaconRequest

        data = SuggestionBeaconRequest(session_id=session.session_id, content="data")

        with patch(
            "ontokit.services.suggestion_service.verify_beacon_token",
            return_value=session.session_id,
        ):
            await service.beacon_save(PROJECT_ID, data, "token")

        mock_git.commit_to_branch.assert_not_called()

    @pytest.mark.asyncio
    async def test_beacon_save_git_failure_silently_returns(
        self,
        service: SuggestionService,
        mock_db: AsyncMock,
        mock_git: MagicMock,
    ) -> None:
        """Beacon save is fire-and-forget: git failures are swallowed."""
        session = _make_session(
            status=SuggestionSessionStatus.ACTIVE.value,
            changes_count=1,
        )
        project = _make_project()

        mock_session_result = MagicMock()
        mock_session_result.scalar_one_or_none.return_value = session
        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none.return_value = project

        mock_db.execute.side_effect = [
            mock_session_result,
            mock_project_result,
            mock_project_result,
        ]

        mock_git.commit_to_branch = MagicMock(side_effect=RuntimeError("disk full"))

        from ontokit.schemas.suggestion import SuggestionBeaconRequest

        data = SuggestionBeaconRequest(session_id=session.session_id, content="data")

        with patch(
            "ontokit.services.suggestion_service.verify_beacon_token",
            return_value=session.session_id,
        ):
            # Should not raise
            await service.beacon_save(PROJECT_ID, data, "token")

        # changes_count should NOT have been incremented
        assert session.changes_count == 1


# ---------------------------------------------------------------------------
# auto_submit_stale_sessions (extended)
# ---------------------------------------------------------------------------


class TestAutoSubmitStaleSessionsExtended:
    @pytest.mark.asyncio
    async def test_auto_submits_stale_session(
        self,
        service: SuggestionService,
        mock_db: AsyncMock,
        mock_git: MagicMock,
    ) -> None:
        """Auto-submits a stale session by creating a PR."""
        stale_session = _make_session(
            changes_count=3,
            last_activity=datetime.now(UTC) - timedelta(hours=1),
            entities_modified=json.dumps(["Person"]),
        )
        project = _make_project()
        # Need user_id to match project member for access check
        project.members[0].user_id = stale_session.user_id

        mock_stale_result = MagicMock()
        mock_stale_result.scalars.return_value.all.return_value = [stale_session]

        mock_claim_result = MagicMock()
        mock_claim_result.rowcount = 1

        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none.return_value = project

        mock_no_pr_result = MagicMock()
        mock_no_pr_result.scalar_one_or_none.return_value = None

        mock_db.execute.side_effect = [
            mock_stale_result,  # select stale sessions
            mock_claim_result,  # claim session UPDATE
            mock_project_result,  # _verify_project_access -> _get_project
            mock_no_pr_result,  # existing PR check
            mock_project_result,  # _get_project for notification
        ]

        mock_git.get_default_branch = MagicMock(return_value="main")

        mock_pr_response = MagicMock()
        mock_pr_response.pr_number = 99
        mock_pr_response.id = uuid.uuid4()
        mock_pr_response.github_pr_url = None
        mock_pr_response.title = "Suggestion: Update Person"

        with (
            patch(
                "ontokit.services.suggestion_service.get_pull_request_service"
            ) as mock_pr_svc_factory,
            patch("ontokit.services.suggestion_service.NotificationService") as mock_notif_cls,
        ):
            mock_pr_svc = AsyncMock()
            mock_pr_svc.create_pull_request = AsyncMock(return_value=mock_pr_response)
            mock_pr_svc_factory.return_value = mock_pr_svc
            mock_notif = AsyncMock()
            mock_notif_cls.return_value = mock_notif

            count = await service.auto_submit_stale_sessions()

        assert count == 1

    @pytest.mark.asyncio
    async def test_auto_submit_discards_session_on_access_loss(
        self,
        service: SuggestionService,
        mock_db: AsyncMock,
    ) -> None:
        """Discards session when user lost project access."""
        stale_session = _make_session(
            changes_count=2,
            last_activity=datetime.now(UTC) - timedelta(hours=1),
        )

        mock_stale_result = MagicMock()
        mock_stale_result.scalars.return_value.all.return_value = [stale_session]

        mock_claim_result = MagicMock()
        mock_claim_result.rowcount = 1

        # _verify_project_access -> project with no matching member
        project = _make_project()
        project.members = []
        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none.return_value = project

        mock_db.execute.side_effect = [
            mock_stale_result,
            mock_claim_result,
            mock_project_result,  # _verify_project_access
        ]

        count = await service.auto_submit_stale_sessions()
        assert count == 0
        assert stale_session.status == SuggestionSessionStatus.DISCARDED.value

    @pytest.mark.asyncio
    async def test_auto_submit_reverts_on_pr_failure(
        self,
        service: SuggestionService,
        mock_db: AsyncMock,
        mock_git: MagicMock,
    ) -> None:
        """Reverts session to ACTIVE when PR creation fails."""
        stale_session = _make_session(
            changes_count=2,
            last_activity=datetime.now(UTC) - timedelta(hours=1),
            entities_modified=json.dumps(["Person"]),
        )
        project = _make_project()
        project.members[0].user_id = stale_session.user_id

        mock_stale_result = MagicMock()
        mock_stale_result.scalars.return_value.all.return_value = [stale_session]

        mock_claim_result = MagicMock()
        mock_claim_result.rowcount = 1

        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none.return_value = project

        mock_no_pr_result = MagicMock()
        mock_no_pr_result.scalar_one_or_none.return_value = None

        mock_db.execute.side_effect = [
            mock_stale_result,
            mock_claim_result,
            mock_project_result,  # _verify_project_access
            mock_no_pr_result,  # existing PR check
        ]

        mock_git.get_default_branch = MagicMock(return_value="main")

        with (
            patch(
                "ontokit.services.suggestion_service.get_pull_request_service"
            ) as mock_pr_svc_factory,
        ):
            mock_pr_svc = AsyncMock()
            mock_pr_svc.create_pull_request = AsyncMock(
                side_effect=RuntimeError("PR creation failed")
            )
            mock_pr_svc_factory.return_value = mock_pr_svc

            count = await service.auto_submit_stale_sessions()

        assert count == 0
        assert stale_session.status == SuggestionSessionStatus.ACTIVE.value


# ---------------------------------------------------------------------------
# list_pending
# ---------------------------------------------------------------------------


class TestListPending:
    @pytest.mark.asyncio
    async def test_list_pending_sessions(
        self,
        service: SuggestionService,
        mock_db: AsyncMock,
    ) -> None:
        """Lists pending sessions for reviewers."""
        session = _make_session(status=SuggestionSessionStatus.SUBMITTED.value)
        session.reviewer_id = None
        project = _make_project()
        project.members[0].role = "admin"

        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none.return_value = project

        mock_sessions_result = MagicMock()
        mock_sessions_result.scalars.return_value.all.return_value = [session]

        mock_db.execute.side_effect = [mock_project_result, mock_sessions_result]

        user = _make_user()
        result = await service.list_pending(PROJECT_ID, user)
        assert len(result.items) == 1

    @pytest.mark.asyncio
    async def test_list_pending_forbidden_for_viewer(
        self,
        service: SuggestionService,
        mock_db: AsyncMock,
    ) -> None:
        """Raises 403 when viewer tries to list pending sessions."""
        project = _make_project()
        project.members[0].role = "viewer"

        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none.return_value = project
        mock_db.execute.return_value = mock_project_result

        user = _make_user()
        with pytest.raises(HTTPException) as exc_info:
            await service.list_pending(PROJECT_ID, user)
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# create_session – additional edge cases (lines 193-261)
# ---------------------------------------------------------------------------


class TestCreateSessionEdgeCases:
    @pytest.mark.asyncio
    async def test_create_branch_failure_raises_500(
        self,
        service: SuggestionService,
        mock_db: AsyncMock,
        mock_git: MagicMock,
    ) -> None:
        """Raises 500 when git branch creation fails."""
        project = _make_project()

        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none.return_value = project
        mock_existing_result = MagicMock()
        mock_existing_result.scalar_one_or_none.return_value = None

        mock_db.execute.side_effect = [mock_project_result, mock_existing_result]
        mock_git.create_branch.side_effect = RuntimeError("git error")

        user = _make_user()
        with (
            patch(
                "ontokit.services.suggestion_service.create_beacon_token",
                return_value="tok",
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            await service.create_session(PROJECT_ID, user)
        assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_integrity_error_returns_existing(
        self,
        service: SuggestionService,
        mock_db: AsyncMock,
        mock_git: MagicMock,
    ) -> None:
        """Returns existing session after IntegrityError (race condition)."""
        from sqlalchemy.exc import IntegrityError

        project = _make_project()
        existing = _make_session()

        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none.return_value = project
        mock_existing_result = MagicMock()
        mock_existing_result.scalar_one_or_none.return_value = None

        # After rollback, re-query finds the existing session
        mock_refetch_result = MagicMock()
        mock_refetch_result.scalar_one_or_none.return_value = existing

        mock_db.execute.side_effect = [
            mock_project_result,
            mock_existing_result,
            mock_refetch_result,
        ]
        mock_db.commit.side_effect = IntegrityError("dup", {}, Exception())

        user = _make_user()
        with patch(
            "ontokit.services.suggestion_service.create_beacon_token",
            return_value="tok",
        ):
            result = await service.create_session(PROJECT_ID, user)

        assert result.session_id == existing.session_id
        mock_git.delete_branch.assert_called_once()

    @pytest.mark.asyncio
    async def test_integrity_error_no_existing_raises_500(
        self,
        service: SuggestionService,
        mock_db: AsyncMock,
        mock_git: MagicMock,  # noqa: ARG002
    ) -> None:
        """Raises 500 after IntegrityError when no existing session found."""
        from sqlalchemy.exc import IntegrityError

        project = _make_project()

        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none.return_value = project
        mock_existing_result = MagicMock()
        mock_existing_result.scalar_one_or_none.return_value = None

        # After rollback, re-query finds nothing
        mock_refetch_result = MagicMock()
        mock_refetch_result.scalar_one_or_none.return_value = None

        mock_db.execute.side_effect = [
            mock_project_result,
            mock_existing_result,
            mock_refetch_result,
        ]
        mock_db.commit.side_effect = IntegrityError("dup", {}, Exception())

        user = _make_user()
        with (
            patch(
                "ontokit.services.suggestion_service.create_beacon_token",
                return_value="tok",
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            await service.create_session(PROJECT_ID, user)
        assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_generic_exception_cleans_up_branch(
        self,
        service: SuggestionService,
        mock_db: AsyncMock,
        mock_git: MagicMock,
    ) -> None:
        """Cleans up branch and re-raises on generic commit exception."""
        project = _make_project()

        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none.return_value = project
        mock_existing_result = MagicMock()
        mock_existing_result.scalar_one_or_none.return_value = None

        mock_db.execute.side_effect = [mock_project_result, mock_existing_result]
        mock_db.commit.side_effect = RuntimeError("unexpected")

        user = _make_user()
        with (
            patch(
                "ontokit.services.suggestion_service.create_beacon_token",
                return_value="tok",
            ),
            pytest.raises(RuntimeError, match="unexpected"),
        ):
            await service.create_session(PROJECT_ID, user)

        mock_git.delete_branch.assert_called_once()

    @pytest.mark.asyncio
    async def test_refresh_failure_refetches(
        self,
        service: SuggestionService,
        mock_db: AsyncMock,
        mock_git: MagicMock,  # noqa: ARG002
    ) -> None:
        """Re-fetches session from DB when refresh fails after commit."""
        project = _make_project()
        db_session_obj = _make_session()

        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none.return_value = project
        mock_existing_result = MagicMock()
        mock_existing_result.scalar_one_or_none.return_value = None

        # After refresh failure, re-fetch returns the session
        mock_refetch_result = MagicMock()
        mock_refetch_result.scalar_one.return_value = db_session_obj

        mock_db.execute.side_effect = [
            mock_project_result,
            mock_existing_result,
            mock_refetch_result,
        ]

        # commit succeeds, refresh fails
        commit_call_count = 0
        original_commit = AsyncMock()

        async def commit_side_effect() -> None:
            nonlocal commit_call_count
            commit_call_count += 1
            await original_commit()

        mock_db.commit.side_effect = commit_side_effect
        mock_db.refresh.side_effect = RuntimeError("refresh failed")

        user = _make_user()
        with patch(
            "ontokit.services.suggestion_service.create_beacon_token",
            return_value="tok",
        ):
            result = await service.create_session(PROJECT_ID, user)

        assert result.session_id == db_session_obj.session_id


# ---------------------------------------------------------------------------
# _create_pr_for_session – title truncation / many entities
# ---------------------------------------------------------------------------


class TestCreatePrForSession:
    @pytest.mark.asyncio
    async def test_title_with_more_than_5_entities(
        self,
        service: SuggestionService,
        mock_db: AsyncMock,
        mock_git: MagicMock,
    ) -> None:
        """Title shows first 5 entities and a '+N more' suffix."""
        entities = [f"Entity{i}" for i in range(8)]
        session = _make_session(
            status=SuggestionSessionStatus.ACTIVE.value,
            changes_count=8,
            entities_modified=json.dumps(entities),
        )
        project = _make_project()

        mock_no_pr_result = MagicMock()
        mock_no_pr_result.scalar_one_or_none.return_value = None
        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none.return_value = project

        mock_db.execute.side_effect = [mock_no_pr_result, mock_project_result]

        mock_git.get_default_branch = MagicMock(return_value="main")

        mock_pr_response = MagicMock()
        mock_pr_response.pr_number = 1
        mock_pr_response.id = uuid.uuid4()
        mock_pr_response.github_pr_url = None
        mock_pr_response.title = "Suggestion"

        user = _make_user()

        with (
            patch(
                "ontokit.services.suggestion_service.get_pull_request_service"
            ) as mock_pr_svc_factory,
            patch("ontokit.services.suggestion_service.NotificationService") as mock_notif_cls,
        ):
            mock_pr_svc = AsyncMock()
            mock_pr_svc.create_pull_request = AsyncMock(return_value=mock_pr_response)
            mock_pr_svc_factory.return_value = mock_pr_svc
            mock_notif = AsyncMock()
            mock_notif_cls.return_value = mock_notif

            await service._create_pr_for_session(PROJECT_ID, session, user, "summary", "submitted")

        # Verify the PR was created with the right title structure
        call_args = mock_pr_svc.create_pull_request.call_args
        pr_create_arg = call_args[0][1]  # second positional arg
        assert "(+3 more)" in pr_create_arg.title

    @pytest.mark.asyncio
    async def test_empty_entities_title(
        self,
        service: SuggestionService,
        mock_db: AsyncMock,
        mock_git: MagicMock,
    ) -> None:
        """Title is just 'Suggestion' when no entities are modified."""
        session = _make_session(
            status=SuggestionSessionStatus.ACTIVE.value,
            changes_count=1,
            entities_modified=json.dumps([]),
        )
        project = _make_project()

        mock_no_pr_result = MagicMock()
        mock_no_pr_result.scalar_one_or_none.return_value = None
        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none.return_value = project

        mock_db.execute.side_effect = [mock_no_pr_result, mock_project_result]

        mock_git.get_default_branch = MagicMock(return_value="main")

        mock_pr_response = MagicMock()
        mock_pr_response.pr_number = 1
        mock_pr_response.id = uuid.uuid4()
        mock_pr_response.github_pr_url = None
        mock_pr_response.title = "Suggestion"

        user = _make_user()

        with (
            patch(
                "ontokit.services.suggestion_service.get_pull_request_service"
            ) as mock_pr_svc_factory,
            patch("ontokit.services.suggestion_service.NotificationService") as mock_notif_cls,
        ):
            mock_pr_svc = AsyncMock()
            mock_pr_svc.create_pull_request = AsyncMock(return_value=mock_pr_response)
            mock_pr_svc_factory.return_value = mock_pr_svc
            mock_notif = AsyncMock()
            mock_notif_cls.return_value = mock_notif

            await service._create_pr_for_session(PROJECT_ID, session, user, None, "submitted")

        call_args = mock_pr_svc.create_pull_request.call_args
        pr_create_arg = call_args[0][1]
        assert pr_create_arg.title == "Suggestion"


# ---------------------------------------------------------------------------
# discard – branch deletion failure (line 752-753)
# ---------------------------------------------------------------------------


class TestDiscardEdgeCases:
    @pytest.mark.asyncio
    async def test_discard_continues_on_branch_delete_failure(
        self,
        service: SuggestionService,
        mock_db: AsyncMock,
        mock_git: MagicMock,
    ) -> None:
        """Still marks session discarded even if branch deletion fails."""
        session = _make_session(status=SuggestionSessionStatus.ACTIVE.value)
        project = _make_project()

        mock_session_result = MagicMock()
        mock_session_result.scalar_one_or_none.return_value = session
        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none.return_value = project

        mock_db.execute.side_effect = [mock_session_result, mock_project_result]
        mock_git.delete_branch.side_effect = RuntimeError("branch not found")

        user = _make_user()
        await service.discard(PROJECT_ID, session.session_id, user)

        assert session.status == SuggestionSessionStatus.DISCARDED.value


# ---------------------------------------------------------------------------
# get_suggestion_service factory (line 900)
# ---------------------------------------------------------------------------


class TestGetSuggestionServiceFactory:
    def test_returns_service_instance(self) -> None:
        """Factory returns a SuggestionService instance."""
        from ontokit.services.suggestion_service import get_suggestion_service

        mock_db = AsyncMock()
        svc = get_suggestion_service(mock_db)
        assert isinstance(svc, SuggestionService)
