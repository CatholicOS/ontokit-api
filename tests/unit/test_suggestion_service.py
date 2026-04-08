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
