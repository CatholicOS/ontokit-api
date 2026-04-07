"""Tests for ProjectService (ontokit/services/project_service.py)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from ontokit.core.auth import CurrentUser
from ontokit.schemas.project import MemberCreate, ProjectCreate, ProjectUpdate, TransferOwnership
from ontokit.services.project_service import ProjectService, get_project_service

PROJECT_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
OWNER_ID = "owner-user-id"
ADMIN_ID = "admin-user-id"
EDITOR_ID = "editor-user-id"
VIEWER_ID = "viewer-user-id"


def _make_member(user_id: str, role: str, project_id: uuid.UUID = PROJECT_ID) -> MagicMock:
    """Create a mock ProjectMember ORM object."""
    m = MagicMock()
    m.id = uuid.uuid4()
    m.project_id = project_id
    m.user_id = user_id
    m.role = role
    m.preferred_branch = None
    m.created_at = datetime.now(UTC)
    return m


def _make_project(
    *,
    project_id: uuid.UUID = PROJECT_ID,
    is_public: bool = True,
    owner_id: str = OWNER_ID,
    members: list[MagicMock] | None = None,
) -> MagicMock:
    """Create a mock Project ORM object."""
    project = MagicMock()
    project.id = project_id
    project.name = "Test Ontology"
    project.description = "A test project"
    project.is_public = is_public
    project.owner_id = owner_id
    project.source_file_path = f"projects/{project_id}/ontology.ttl"
    project.ontology_iri = "http://example.org/ontology"
    project.label_preferences = None
    project.normalization_report = None
    project.created_at = datetime.now(UTC)
    project.updated_at = None
    project.github_integration = None
    project.pr_approval_required = 0
    if members is None:
        members = [_make_member(owner_id, "owner", project_id)]
    project.members = members
    return project


def _make_user(
    user_id: str = OWNER_ID,
    name: str = "Test User",
    email: str = "test@example.com",
) -> CurrentUser:
    return CurrentUser(id=user_id, email=email, name=name, username="testuser", roles=[])


@pytest.fixture
def mock_db() -> AsyncMock:
    """Create an async mock of AsyncSession."""
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
    """Create a mock GitRepositoryService."""
    git = MagicMock()
    git.initialize_repository = MagicMock(return_value=MagicMock(hash="abc123"))
    git.delete_repository = MagicMock()
    git.repository_exists = MagicMock(return_value=True)
    git.get_default_branch = MagicMock(return_value="main")
    return git


@pytest.fixture
def service(mock_db: AsyncMock, mock_git_service: MagicMock) -> ProjectService:
    return ProjectService(db=mock_db, git_service=mock_git_service)


# ---------------------------------------------------------------------------
# Factory function
# ---------------------------------------------------------------------------


class TestGetProjectService:
    def test_factory_returns_instance(self, mock_db: AsyncMock) -> None:
        """get_project_service returns a ProjectService."""
        svc = get_project_service(mock_db)
        assert isinstance(svc, ProjectService)
        assert svc.db is mock_db


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


class TestCreate:
    @pytest.mark.asyncio
    async def test_create_project_success(
        self, service: ProjectService, mock_db: AsyncMock
    ) -> None:
        """Creating a project adds it to the DB and returns a response."""
        owner = _make_user()
        data = ProjectCreate(name="My Ontology", description="desc", is_public=True)

        # After commit + refresh, the project object should have attributes set.
        # The service calls self.db.add, flush, add (owner member), commit, refresh.
        # Simulate refresh by populating server-generated fields and relationships.
        def _simulate_refresh(obj: object, _attrs: list[str] | None = None) -> None:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()  # type: ignore[attr-defined]
            if getattr(obj, "created_at", None) is None:
                obj.created_at = datetime.now(UTC)  # type: ignore[attr-defined]
            # Set relationships that would normally be loaded by refresh
            if not getattr(obj, "members", None):
                obj.members = [_make_member(owner.id, "owner")]  # type: ignore[attr-defined]
            if not hasattr(obj, "github_integration"):
                obj.github_integration = None  # type: ignore[attr-defined]

        mock_db.refresh.side_effect = _simulate_refresh

        await service.create(data, owner)

        assert mock_db.add.called
        mock_db.flush.assert_awaited()
        mock_db.commit.assert_awaited()


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------


class TestGet:
    @pytest.mark.asyncio
    async def test_get_public_project_as_anonymous(
        self, service: ProjectService, mock_db: AsyncMock
    ) -> None:
        """A public project is accessible without authentication."""
        project = _make_project(is_public=True)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = project
        mock_db.execute.return_value = mock_result

        response = await service.get(project.id, None)
        assert response.is_public is True
        assert response.user_role is None

    @pytest.mark.asyncio
    async def test_get_private_project_denied_for_non_member(
        self, service: ProjectService, mock_db: AsyncMock
    ) -> None:
        """A private project returns 403 for a non-member."""
        project = _make_project(is_public=False)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = project
        mock_db.execute.return_value = mock_result

        non_member = _make_user(user_id="stranger-id")
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await service.get(PROJECT_ID, non_member)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_get_project_not_found(self, service: ProjectService, mock_db: AsyncMock) -> None:
        """A missing project returns 404."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await service.get(uuid.uuid4(), _make_user())
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------


class TestUpdate:
    @pytest.mark.asyncio
    async def test_update_project_as_owner(
        self, service: ProjectService, mock_db: AsyncMock
    ) -> None:
        """Owner can update project settings."""
        project = _make_project(is_public=True)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = project
        mock_db.execute.return_value = mock_result

        owner = _make_user(user_id=OWNER_ID)
        update_data = ProjectUpdate(name="New Name")

        await service.update(PROJECT_ID, update_data, owner)
        mock_db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_update_project_denied_for_editor(
        self, service: ProjectService, mock_db: AsyncMock
    ) -> None:
        """An editor cannot update project settings."""
        members = [
            _make_member(OWNER_ID, "owner"),
            _make_member(EDITOR_ID, "editor"),
        ]
        project = _make_project(is_public=True, members=members)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = project
        mock_db.execute.return_value = mock_result

        editor = _make_user(user_id=EDITOR_ID)
        update_data = ProjectUpdate(name="Hacked Name")

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await service.update(PROJECT_ID, update_data, editor)
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


class TestDelete:
    @pytest.mark.asyncio
    async def test_delete_project_as_owner(
        self, service: ProjectService, mock_db: AsyncMock
    ) -> None:
        """Owner can delete a project."""
        project = _make_project()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = project
        mock_db.execute.return_value = mock_result

        owner = _make_user(user_id=OWNER_ID)
        await service.delete(PROJECT_ID, owner)

        mock_db.delete.assert_awaited()
        mock_db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_delete_project_denied_for_admin(
        self, service: ProjectService, mock_db: AsyncMock
    ) -> None:
        """Admin cannot delete a project (owner only)."""
        members = [
            _make_member(OWNER_ID, "owner"),
            _make_member(ADMIN_ID, "admin"),
        ]
        project = _make_project(members=members)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = project
        mock_db.execute.return_value = mock_result

        admin = _make_user(user_id=ADMIN_ID)

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await service.delete(PROJECT_ID, admin)
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# _can_view
# ---------------------------------------------------------------------------


class TestCanView:
    def test_public_project_visible_to_anyone(self, service: ProjectService) -> None:
        """Public projects are visible to all users."""
        project = _make_project(is_public=True)
        assert service._can_view(project, None) is True

    def test_private_project_hidden_from_anonymous(self, service: ProjectService) -> None:
        """Private projects are hidden from anonymous users."""
        project = _make_project(is_public=False)
        assert service._can_view(project, None) is False

    def test_private_project_visible_to_member(self, service: ProjectService) -> None:
        """Private projects are visible to members."""
        project = _make_project(is_public=False)
        member = _make_user(user_id=OWNER_ID)
        assert service._can_view(project, member) is True

    def test_private_project_hidden_from_non_member(self, service: ProjectService) -> None:
        """Private projects are hidden from non-members."""
        project = _make_project(is_public=False)
        stranger = _make_user(user_id="stranger-id")
        assert service._can_view(project, stranger) is False


# ---------------------------------------------------------------------------
# add_member
# ---------------------------------------------------------------------------


class TestAddMember:
    @pytest.mark.asyncio
    async def test_add_member_as_owner(self, service: ProjectService, mock_db: AsyncMock) -> None:
        """Owner can add a new member."""
        project = _make_project()
        # First execute: _get_project, second: existing member check
        mock_result_project = MagicMock()
        mock_result_project.scalar_one_or_none.return_value = project
        mock_result_no_existing = MagicMock()
        mock_result_no_existing.scalar_one_or_none.return_value = None
        mock_db.execute.side_effect = [mock_result_project, mock_result_no_existing]

        owner = _make_user(user_id=OWNER_ID)
        member_data = MemberCreate(user_id="new-user-id", role="editor")

        def _simulate_refresh(obj: object, _attrs: list[str] | None = None) -> None:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()  # type: ignore[attr-defined]
            if getattr(obj, "created_at", None) is None:
                obj.created_at = datetime.now(UTC)  # type: ignore[attr-defined]

        mock_db.refresh.side_effect = _simulate_refresh

        with patch("ontokit.services.user_service.get_user_service") as mock_us:
            mock_user_service = MagicMock()
            mock_user_service.get_user_info = AsyncMock(
                return_value={"id": "new-user-id", "name": "New User", "email": "new@test.com"}
            )
            mock_us.return_value = mock_user_service

            await service.add_member(PROJECT_ID, member_data, owner)

        assert mock_db.add.called
        mock_db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_add_member_as_owner_role_rejected(
        self, service: ProjectService, mock_db: AsyncMock
    ) -> None:
        """Cannot add a member with owner role."""
        project = _make_project()
        mock_result_project = MagicMock()
        mock_result_project.scalar_one_or_none.return_value = project
        mock_result_no_existing = MagicMock()
        mock_result_no_existing.scalar_one_or_none.return_value = None
        mock_db.execute.side_effect = [mock_result_project, mock_result_no_existing]

        owner = _make_user(user_id=OWNER_ID)
        member_data = MemberCreate(user_id="new-user-id", role="owner")

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await service.add_member(PROJECT_ID, member_data, owner)
        assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# remove_member
# ---------------------------------------------------------------------------


class TestRemoveMember:
    @pytest.mark.asyncio
    async def test_cannot_remove_owner(self, service: ProjectService, mock_db: AsyncMock) -> None:
        """An admin cannot remove the project owner."""
        project = _make_project(
            members=[_make_member(OWNER_ID, "owner"), _make_member(ADMIN_ID, "admin")]
        )
        mock_result_project = MagicMock()
        mock_result_project.scalar_one_or_none.return_value = project

        owner_member = _make_member(OWNER_ID, "owner")
        mock_result_member = MagicMock()
        mock_result_member.scalar_one_or_none.return_value = owner_member

        mock_db.execute.side_effect = [mock_result_project, mock_result_member]

        admin = _make_user(user_id=ADMIN_ID)

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await service.remove_member(PROJECT_ID, OWNER_ID, admin)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_editor_cannot_remove_others(
        self, service: ProjectService, mock_db: AsyncMock
    ) -> None:
        """An editor cannot remove other members."""
        members = [
            _make_member(OWNER_ID, "owner"),
            _make_member(EDITOR_ID, "editor"),
            _make_member(VIEWER_ID, "viewer"),
        ]
        project = _make_project(members=members)
        mock_result_project = MagicMock()
        mock_result_project.scalar_one_or_none.return_value = project
        mock_db.execute.return_value = mock_result_project

        editor = _make_user(user_id=EDITOR_ID)

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await service.remove_member(PROJECT_ID, VIEWER_ID, editor)
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# transfer_ownership
# ---------------------------------------------------------------------------


class TestTransferOwnership:
    @pytest.mark.asyncio
    async def test_transfer_to_non_admin_rejected(
        self, service: ProjectService, mock_db: AsyncMock
    ) -> None:
        """Ownership can only be transferred to an admin member."""
        editor_member = _make_member(EDITOR_ID, "editor")
        members = [
            _make_member(OWNER_ID, "owner"),
            editor_member,
        ]
        project = _make_project(members=members)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = project
        mock_db.execute.return_value = mock_result

        owner = _make_user(user_id=OWNER_ID)
        transfer = TransferOwnership(new_owner_id=EDITOR_ID)

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await service.transfer_ownership(PROJECT_ID, transfer, owner)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_transfer_denied_for_non_owner(
        self, service: ProjectService, mock_db: AsyncMock
    ) -> None:
        """Only the owner can transfer ownership."""
        members = [
            _make_member(OWNER_ID, "owner"),
            _make_member(ADMIN_ID, "admin"),
        ]
        project = _make_project(members=members)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = project
        mock_db.execute.return_value = mock_result

        admin = _make_user(user_id=ADMIN_ID)
        transfer = TransferOwnership(new_owner_id=ADMIN_ID)

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await service.transfer_ownership(PROJECT_ID, transfer, admin)
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# _to_response
# ---------------------------------------------------------------------------


class TestToResponse:
    def test_to_response_public_project(self, service: ProjectService) -> None:
        """_to_response correctly maps a public project."""
        project = _make_project(is_public=True)
        user = _make_user(user_id=OWNER_ID)

        response = service._to_response(project, user)

        assert response.id == PROJECT_ID
        assert response.name == "Test Ontology"
        assert response.is_public is True
        assert response.user_role == "owner"
        assert response.member_count == 1

    def test_to_response_anonymous_user(self, service: ProjectService) -> None:
        """_to_response with None user has no role."""
        project = _make_project(is_public=True)

        response = service._to_response(project, None)

        assert response.user_role is None
        assert response.is_superadmin is False

    def test_to_response_with_label_preferences(self, service: ProjectService) -> None:
        """_to_response deserializes label_preferences from JSON."""
        project = _make_project()
        project.label_preferences = '["rdfs:label@en", "skos:prefLabel"]'
        user = _make_user(user_id=OWNER_ID)

        response = service._to_response(project, user)

        assert response.label_preferences == ["rdfs:label@en", "skos:prefLabel"]
