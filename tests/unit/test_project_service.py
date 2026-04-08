"""Tests for ProjectService (ontokit/services/project_service.py)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from fastapi import HTTPException

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


def _make_simulate_refresh(
    owner_id: str = OWNER_ID,
    *,
    extended: bool = False,
) -> Any:
    """Return a side_effect callable for mock_db.refresh that populates ORM fields.

    Use ``extended=True`` for import/create tests that need extra fields like
    source_file_path, ontology_iri, etc.
    """

    def _refresh(obj: Any, _attrs: list[str] | None = None) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        if getattr(obj, "created_at", None) is None:
            obj.created_at = datetime.now(UTC)
        if not getattr(obj, "members", None):
            obj.members = [_make_member(owner_id, "owner")]
        if not hasattr(obj, "github_integration"):
            obj.github_integration = None
        if extended:
            if not hasattr(obj, "source_file_path"):
                obj.source_file_path = "projects/xyz/ontology.ttl"
            if not hasattr(obj, "ontology_iri"):
                obj.ontology_iri = "http://ex.org/ont"
            if not hasattr(obj, "normalization_report"):
                obj.normalization_report = None
            if not hasattr(obj, "updated_at"):
                obj.updated_at = None
            if not hasattr(obj, "label_preferences"):
                obj.label_preferences = None
            if not hasattr(obj, "pr_approval_required"):
                obj.pr_approval_required = 0

    return _refresh


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

        mock_db.refresh.side_effect = _make_simulate_refresh(owner.id)

        result = await service.create(data, owner)

        assert mock_db.add.call_count == 2  # project + owner member
        mock_db.flush.assert_awaited()
        mock_db.commit.assert_awaited()
        assert result.name == "My Ontology"
        assert result.description == "desc"
        assert result.is_public is True
        assert result.owner_id == OWNER_ID


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
    async def test_get_private_project_as_member(
        self, service: ProjectService, mock_db: AsyncMock
    ) -> None:
        """A private project is accessible to a member."""
        project = _make_project(
            is_public=False,
            members=[_make_member(OWNER_ID, "owner"), _make_member(EDITOR_ID, "editor")],
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = project
        mock_db.execute.return_value = mock_result

        member = _make_user(user_id=EDITOR_ID)
        response = await service.get(project.id, member)
        assert response.is_public is False
        assert response.user_role == "editor"

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
        with pytest.raises(HTTPException) as exc_info:
            await service.get(PROJECT_ID, non_member)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_get_project_not_found(self, service: ProjectService, mock_db: AsyncMock) -> None:
        """A missing project returns 404."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

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

        mock_db.refresh.side_effect = _make_simulate_refresh(owner.id)

        # Patch at the definition module — project_service uses inline imports
        # (`from ontokit.services.user_service import get_user_service` inside
        # function bodies), so the symbol is resolved from user_service at call
        # time, not bound to project_service's namespace.
        with patch("ontokit.services.user_service.get_user_service") as mock_us:
            mock_user_service = MagicMock()
            mock_user_service.get_user_info = AsyncMock(
                return_value={"id": "new-user-id", "name": "New User", "email": "new@test.com"}
            )
            mock_us.return_value = mock_user_service

            result = await service.add_member(PROJECT_ID, member_data, owner)

        assert mock_db.add.called
        mock_db.commit.assert_awaited()
        mock_user_service.get_user_info.assert_awaited_once()
        assert result.user_id == "new-user-id"
        assert result.role == "editor"

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

        with pytest.raises(HTTPException) as exc_info:
            await service.remove_member(PROJECT_ID, OWNER_ID, admin)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_owner_can_remove_member(
        self, service: ProjectService, mock_db: AsyncMock
    ) -> None:
        """Owner can successfully remove a non-owner member."""
        members = [
            _make_member(OWNER_ID, "owner"),
            _make_member(EDITOR_ID, "editor"),
        ]
        project = _make_project(members=members)
        mock_result_project = MagicMock()
        mock_result_project.scalar_one_or_none.return_value = project

        editor_member = _make_member(EDITOR_ID, "editor")
        mock_result_member = MagicMock()
        mock_result_member.scalar_one_or_none.return_value = editor_member

        mock_db.execute.side_effect = [mock_result_project, mock_result_member]

        owner = _make_user(user_id=OWNER_ID)
        await service.remove_member(PROJECT_ID, EDITOR_ID, owner)

        mock_db.delete.assert_awaited()
        mock_db.commit.assert_awaited()

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

        with pytest.raises(HTTPException) as exc_info:
            await service.remove_member(PROJECT_ID, VIEWER_ID, editor)
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# transfer_ownership
# ---------------------------------------------------------------------------


class TestTransferOwnership:
    @pytest.mark.asyncio
    async def test_transfer_ownership_success(
        self, service: ProjectService, mock_db: AsyncMock
    ) -> None:
        """Owner can transfer ownership to an admin member."""
        owner_member = _make_member(OWNER_ID, "owner")
        admin_member = _make_member(ADMIN_ID, "admin")
        project = _make_project(members=[owner_member, admin_member])
        mock_result_project = MagicMock()
        mock_result_project.scalar_one_or_none.return_value = project
        mock_db.execute.return_value = mock_result_project

        # After commit + refresh, list_members calls _get_project again
        mock_db.execute.side_effect = [
            mock_result_project,  # _get_project (in transfer_ownership)
            mock_result_project,  # _get_project (in list_members)
        ]

        owner = _make_user(user_id=OWNER_ID)
        transfer = TransferOwnership(new_owner_id=ADMIN_ID)

        with patch("ontokit.services.user_service.get_user_service") as mock_us:
            mock_user_svc = MagicMock()
            mock_user_svc.get_users_info = AsyncMock(return_value={})
            mock_us.return_value = mock_user_svc

            await service.transfer_ownership(PROJECT_ID, transfer, owner)

        mock_db.commit.assert_awaited()
        assert admin_member.role == "owner"
        assert owner_member.role == "admin"

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


# ---------------------------------------------------------------------------
# list_accessible
# ---------------------------------------------------------------------------


class TestListAccessible:
    @pytest.mark.asyncio
    async def test_list_public_filter(self, service: ProjectService, mock_db: AsyncMock) -> None:
        """filter_type='public' returns only public projects."""
        project = _make_project(is_public=True)

        mock_db.scalar = AsyncMock(side_effect=[1, 1])  # unfiltered_total, total
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [project]
        mock_db.execute.return_value = mock_result

        user = _make_user()
        result = await service.list_accessible(user, skip=0, limit=20, filter_type="public")

        assert result.total >= 0
        assert result.skip == 0
        assert result.limit == 20

    @pytest.mark.asyncio
    async def test_list_private_filter(self, service: ProjectService, mock_db: AsyncMock) -> None:
        """filter_type='private' returns only private projects user is member of."""
        project = _make_project(is_public=False)

        mock_db.scalar = AsyncMock(side_effect=[1, 1])
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [project]
        mock_db.execute.return_value = mock_result

        user = _make_user()
        result = await service.list_accessible(user, skip=0, limit=20, filter_type="private")

        assert result.skip == 0

    @pytest.mark.asyncio
    async def test_list_mine_filter(self, service: ProjectService, mock_db: AsyncMock) -> None:
        """filter_type='mine' returns projects user is a member of."""
        project = _make_project()

        mock_db.scalar = AsyncMock(side_effect=[1, 1])
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [project]
        mock_db.execute.return_value = mock_result

        user = _make_user()
        result = await service.list_accessible(user, skip=0, limit=20, filter_type="mine")

        assert result.skip == 0

    @pytest.mark.asyncio
    async def test_list_no_filter(self, service: ProjectService, mock_db: AsyncMock) -> None:
        """filter_type=None returns all accessible projects."""
        project = _make_project(is_public=True)

        mock_db.scalar = AsyncMock(side_effect=[1, 1])
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [project]
        mock_db.execute.return_value = mock_result

        user = _make_user()
        result = await service.list_accessible(user, skip=0, limit=20, filter_type=None)

        assert len(result.items) == 1
        assert result.items[0].name == "Test Ontology"

    @pytest.mark.asyncio
    async def test_list_anonymous_user(self, service: ProjectService, mock_db: AsyncMock) -> None:
        """Anonymous user sees only public projects."""
        project = _make_project(is_public=True)

        mock_db.scalar = AsyncMock(side_effect=[1, 1])
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [project]
        mock_db.execute.return_value = mock_result

        result = await service.list_accessible(None, skip=0, limit=20)

        assert len(result.items) == 1

    @pytest.mark.asyncio
    async def test_list_anonymous_mine_filter_empty(
        self, service: ProjectService, mock_db: AsyncMock
    ) -> None:
        """Anonymous user with filter_type='mine' gets empty results."""
        mock_db.scalar = AsyncMock(side_effect=[0, 0])
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        result = await service.list_accessible(None, skip=0, limit=20, filter_type="mine")

        assert result.total == 0
        assert result.items == []

    @pytest.mark.asyncio
    async def test_list_anonymous_private_filter_empty(
        self, service: ProjectService, mock_db: AsyncMock
    ) -> None:
        """Anonymous user with filter_type='private' gets empty results."""
        mock_db.scalar = AsyncMock(side_effect=[0, 0])
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        result = await service.list_accessible(None, skip=0, limit=20, filter_type="private")

        assert result.total == 0
        assert result.items == []

    @pytest.mark.asyncio
    async def test_list_with_search(self, service: ProjectService, mock_db: AsyncMock) -> None:
        """search param filters projects by name/description."""
        project = _make_project()
        project.name = "Ontology of Animals"

        mock_db.scalar = AsyncMock(side_effect=[1, 1])
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [project]
        mock_db.execute.return_value = mock_result

        user = _make_user()
        result = await service.list_accessible(user, skip=0, limit=20, search="Animals")

        assert len(result.items) == 1

    @pytest.mark.asyncio
    async def test_list_pagination(self, service: ProjectService, mock_db: AsyncMock) -> None:
        """Pagination parameters are forwarded correctly in the response."""
        mock_db.scalar = AsyncMock(side_effect=[5, 5])
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        user = _make_user()
        result = await service.list_accessible(user, skip=2, limit=3)

        assert result.skip == 2
        assert result.limit == 3


# ---------------------------------------------------------------------------
# update_member
# ---------------------------------------------------------------------------


class TestUpdateMember:
    @pytest.mark.asyncio
    async def test_update_member_success(self, service: ProjectService, mock_db: AsyncMock) -> None:
        """Owner can update a member's role."""
        members = [_make_member(OWNER_ID, "owner"), _make_member(EDITOR_ID, "editor")]
        project = _make_project(members=members)

        mock_result_project = MagicMock()
        mock_result_project.scalar_one_or_none.return_value = project

        editor_member = _make_member(EDITOR_ID, "editor")
        mock_result_member = MagicMock()
        mock_result_member.scalar_one_or_none.return_value = editor_member

        mock_db.execute.side_effect = [mock_result_project, mock_result_member]

        owner = _make_user(user_id=OWNER_ID)

        with patch("ontokit.services.user_service.get_user_service") as mock_us:
            mock_user_service = MagicMock()
            mock_user_service.get_user_info = AsyncMock(
                return_value={"id": EDITOR_ID, "name": "Editor", "email": "editor@test.com"}
            )
            mock_us.return_value = mock_user_service

            from ontokit.schemas.project import MemberUpdate

            await service.update_member(PROJECT_ID, EDITOR_ID, MemberUpdate(role="admin"), owner)

        assert editor_member.role == "admin"
        mock_db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_update_member_cannot_change_owner_role(
        self, service: ProjectService, mock_db: AsyncMock
    ) -> None:
        """Cannot change the role of the project owner."""
        members = [_make_member(OWNER_ID, "owner"), _make_member(ADMIN_ID, "admin")]
        project = _make_project(members=members)

        mock_result_project = MagicMock()
        mock_result_project.scalar_one_or_none.return_value = project

        owner_member = _make_member(OWNER_ID, "owner")
        mock_result_member = MagicMock()
        mock_result_member.scalar_one_or_none.return_value = owner_member

        mock_db.execute.side_effect = [mock_result_project, mock_result_member]

        admin = _make_user(user_id=ADMIN_ID)
        from ontokit.schemas.project import MemberUpdate

        with pytest.raises(HTTPException) as exc_info:
            await service.update_member(PROJECT_ID, OWNER_ID, MemberUpdate(role="admin"), admin)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_update_member_cannot_set_owner_role(
        self, service: ProjectService, mock_db: AsyncMock
    ) -> None:
        """Cannot set a member's role to 'owner' via update_member."""
        members = [_make_member(OWNER_ID, "owner"), _make_member(EDITOR_ID, "editor")]
        project = _make_project(members=members)

        mock_result_project = MagicMock()
        mock_result_project.scalar_one_or_none.return_value = project

        editor_member = _make_member(EDITOR_ID, "editor")
        mock_result_member = MagicMock()
        mock_result_member.scalar_one_or_none.return_value = editor_member

        mock_db.execute.side_effect = [mock_result_project, mock_result_member]

        owner = _make_user(user_id=OWNER_ID)
        from ontokit.schemas.project import MemberUpdate

        with pytest.raises(HTTPException) as exc_info:
            await service.update_member(PROJECT_ID, EDITOR_ID, MemberUpdate(role="owner"), owner)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_update_member_not_found(
        self, service: ProjectService, mock_db: AsyncMock
    ) -> None:
        """Updating a non-existent member returns 404."""
        project = _make_project()
        mock_result_project = MagicMock()
        mock_result_project.scalar_one_or_none.return_value = project

        mock_result_member = MagicMock()
        mock_result_member.scalar_one_or_none.return_value = None

        mock_db.execute.side_effect = [mock_result_project, mock_result_member]

        owner = _make_user(user_id=OWNER_ID)
        from ontokit.schemas.project import MemberUpdate

        with pytest.raises(HTTPException) as exc_info:
            await service.update_member(
                PROJECT_ID, "ghost-user", MemberUpdate(role="editor"), owner
            )
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# list_members
# ---------------------------------------------------------------------------


class TestListMembers:
    @pytest.mark.asyncio
    async def test_list_members_success(self, service: ProjectService, mock_db: AsyncMock) -> None:
        """List members returns all members sorted by role."""
        members = [
            _make_member(OWNER_ID, "owner"),
            _make_member(EDITOR_ID, "editor"),
        ]
        project = _make_project(members=members)

        mock_result_project = MagicMock()
        mock_result_project.scalar_one_or_none.return_value = project
        mock_db.execute.return_value = mock_result_project

        user = _make_user(user_id=OWNER_ID)
        result = await service.list_members(PROJECT_ID, user)

        assert result.total == 2
        # Owner should come first in sorted order
        assert result.items[0].role == "owner"
        assert result.items[1].role == "editor"


# ---------------------------------------------------------------------------
# set_branch_preference / get_branch_preference
# ---------------------------------------------------------------------------


class TestBranchPreference:
    @pytest.mark.asyncio
    async def test_set_branch_preference_success(
        self, service: ProjectService, mock_db: AsyncMock
    ) -> None:
        """Setting branch preference updates the member row."""
        member = _make_member(OWNER_ID, "owner")
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = member
        mock_db.execute.return_value = mock_result

        await service.set_branch_preference(PROJECT_ID, OWNER_ID, "develop")

        assert member.preferred_branch == "develop"
        mock_db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_set_branch_preference_no_member(
        self, service: ProjectService, mock_db: AsyncMock
    ) -> None:
        """Setting branch preference for a non-member is a no-op."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        await service.set_branch_preference(PROJECT_ID, "ghost-user", "develop")

        mock_db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_get_branch_preference_success(
        self, service: ProjectService, mock_db: AsyncMock
    ) -> None:
        """Getting branch preference returns the stored branch."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = "develop"
        mock_db.execute.return_value = mock_result

        result = await service.get_branch_preference(PROJECT_ID, OWNER_ID)
        assert result == "develop"

    @pytest.mark.asyncio
    async def test_get_branch_preference_none(
        self, service: ProjectService, mock_db: AsyncMock
    ) -> None:
        """Getting branch preference for a non-member returns None."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        result = await service.get_branch_preference(PROJECT_ID, "ghost-user")
        assert result is None


# ---------------------------------------------------------------------------
# create_from_import
# ---------------------------------------------------------------------------


class TestCreateFromImport:
    @pytest.mark.asyncio
    async def test_import_success(self, service: ProjectService, mock_db: AsyncMock) -> None:
        """Importing an ontology file creates project + uploads to storage."""
        owner = _make_user()
        storage = AsyncMock()
        storage.upload_file = AsyncMock(return_value="projects/xyz/ontology.ttl")

        turtle_content = (
            b"@prefix owl: <http://www.w3.org/2002/07/owl#> .\n<http://ex.org/ont> a owl:Ontology ."
        )

        mock_db.refresh.side_effect = _make_simulate_refresh(owner.id, extended=True)

        result = await service.create_from_import(
            file_content=turtle_content,
            filename="test.ttl",
            is_public=True,
            owner=owner,
            storage=storage,
        )

        assert result.name is not None
        storage.upload_file.assert_awaited_once()
        mock_db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_import_unsupported_format(
        self,
        service: ProjectService,
        mock_db: AsyncMock,  # noqa: ARG002
    ) -> None:
        """Importing an unsupported file format raises 400."""
        owner = _make_user()
        storage = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await service.create_from_import(
                file_content=b"not an ontology",
                filename="test.docx",
                is_public=True,
                owner=owner,
                storage=storage,
            )
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_import_parse_error(self, service: ProjectService, mock_db: AsyncMock) -> None:  # noqa: ARG002
        """Importing a malformed ontology file raises 422."""
        owner = _make_user()
        storage = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await service.create_from_import(
                file_content=b"@prefix invalid turtle syntax {{{",
                filename="broken.ttl",
                is_public=True,
                owner=owner,
                storage=storage,
            )
        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_import_storage_failure(
        self, service: ProjectService, mock_db: AsyncMock
    ) -> None:
        """Storage upload failure raises 503 and rolls back."""
        from ontokit.services.storage import StorageError

        owner = _make_user()
        storage = AsyncMock()
        storage.upload_file = AsyncMock(side_effect=StorageError("connection refused"))

        turtle_content = (
            b"@prefix owl: <http://www.w3.org/2002/07/owl#> .\n<http://ex.org/ont> a owl:Ontology ."
        )

        with pytest.raises(HTTPException) as exc_info:
            await service.create_from_import(
                file_content=turtle_content,
                filename="test.ttl",
                is_public=True,
                owner=owner,
                storage=storage,
            )
        assert exc_info.value.status_code == 503
        mock_db.rollback.assert_awaited()

    @pytest.mark.asyncio
    async def test_import_with_name_override(
        self, service: ProjectService, mock_db: AsyncMock
    ) -> None:
        """name_override takes precedence over extracted metadata."""
        owner = _make_user()
        storage = AsyncMock()
        storage.upload_file = AsyncMock(return_value="projects/xyz/ontology.ttl")

        turtle_content = (
            b"@prefix owl: <http://www.w3.org/2002/07/owl#> .\n<http://ex.org/ont> a owl:Ontology ."
        )

        mock_db.refresh.side_effect = _make_simulate_refresh(owner.id, extended=True)

        result = await service.create_from_import(
            file_content=turtle_content,
            filename="test.ttl",
            is_public=True,
            owner=owner,
            storage=storage,
            name_override="Custom Name",
        )

        assert result.name == "Custom Name"


# ---------------------------------------------------------------------------
# create_from_github
# ---------------------------------------------------------------------------


class TestCreateFromGithub:
    @pytest.mark.asyncio
    async def test_github_import_success(
        self, service: ProjectService, mock_db: AsyncMock, mock_git_service: MagicMock
    ) -> None:
        """Importing from GitHub creates project + GitHub integration."""
        owner = _make_user()
        storage = AsyncMock()
        storage.upload_file = AsyncMock(return_value="projects/xyz/ontology.ttl")
        mock_git_service.clone_from_github = MagicMock()
        mock_git_service.commit_changes = MagicMock(return_value=MagicMock(hash="def456"))

        turtle_content = (
            b"@prefix owl: <http://www.w3.org/2002/07/owl#> .\n<http://ex.org/ont> a owl:Ontology ."
        )

        mock_db.refresh.side_effect = _make_simulate_refresh(owner.id, extended=True)

        result = await service.create_from_github(
            file_content=turtle_content,
            filename="ontology.ttl",
            repo_owner="testorg",
            repo_name="testrepo",
            ontology_file_path="src/ontology.ttl",
            default_branch="main",
            is_public=True,
            owner=owner,
            storage=storage,
            github_token="test-token",
        )

        assert result.name is not None
        storage.upload_file.assert_awaited_once()
        # 3 adds: project, owner member, github integration
        # 4 adds: project, owner member, github integration, normalization run
        assert mock_db.add.call_count == 4

    @pytest.mark.asyncio
    async def test_github_import_clone_failure_falls_back(
        self, service: ProjectService, mock_db: AsyncMock, mock_git_service: MagicMock
    ) -> None:
        """Clone failure falls back to local git init."""
        owner = _make_user()
        storage = AsyncMock()
        storage.upload_file = AsyncMock(return_value="projects/xyz/ontology.ttl")
        mock_git_service.clone_from_github = MagicMock(side_effect=Exception("clone failed"))

        turtle_content = (
            b"@prefix owl: <http://www.w3.org/2002/07/owl#> .\n<http://ex.org/ont> a owl:Ontology ."
        )

        mock_db.refresh.side_effect = _make_simulate_refresh(owner.id, extended=True)

        result = await service.create_from_github(
            file_content=turtle_content,
            filename="ontology.ttl",
            repo_owner="testorg",
            repo_name="testrepo",
            ontology_file_path="src/ontology.ttl",
            default_branch="main",
            is_public=True,
            owner=owner,
            storage=storage,
            github_token="test-token",
        )

        # Should still succeed despite clone failure
        assert result.name is not None
        mock_git_service.initialize_repository.assert_called_once()

    @pytest.mark.asyncio
    async def test_github_import_storage_failure(
        self, service: ProjectService, mock_db: AsyncMock
    ) -> None:
        """Storage failure during GitHub import raises 503."""
        from ontokit.services.storage import StorageError

        owner = _make_user()
        storage = AsyncMock()
        storage.upload_file = AsyncMock(side_effect=StorageError("connection refused"))

        turtle_content = (
            b"@prefix owl: <http://www.w3.org/2002/07/owl#> .\n<http://ex.org/ont> a owl:Ontology ."
        )

        with pytest.raises(HTTPException) as exc_info:
            await service.create_from_github(
                file_content=turtle_content,
                filename="ontology.ttl",
                repo_owner="testorg",
                repo_name="testrepo",
                ontology_file_path="src/ontology.ttl",
                default_branch="main",
                is_public=True,
                owner=owner,
                storage=storage,
                github_token="test-token",
            )
        assert exc_info.value.status_code == 503
        mock_db.rollback.assert_awaited()


# ---------------------------------------------------------------------------
# _sync_metadata_to_rdf
# ---------------------------------------------------------------------------


class TestSyncMetadataToRdf:
    @pytest.mark.asyncio
    async def test_sync_skips_when_no_source_file(self, service: ProjectService) -> None:
        """No-op when project has no source file."""
        project = _make_project()
        project.source_file_path = None
        user = _make_user()
        storage = AsyncMock()

        result = await service._sync_metadata_to_rdf(
            project=project, new_name="New", new_description=None, user=user, storage=storage
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_sync_updates_rdf_and_commits(
        self, service: ProjectService, mock_git_service: MagicMock
    ) -> None:
        """Metadata changes update storage and commit to git."""
        project = _make_project()
        project.source_file_path = "ontologies/projects/abc/ontology.ttl"
        project.github_integration = None
        user = _make_user()
        storage = AsyncMock()

        turtle_content = (
            b"@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
            b"@prefix dc: <http://purl.org/dc/elements/1.1/> .\n"
            b'<http://ex.org/ont> a owl:Ontology ; dc:title "Old Title" .\n'
        )
        mock_git_service.get_file_at_version = MagicMock(
            return_value=turtle_content.decode("utf-8")
        )
        mock_git_service.commit_changes = MagicMock(
            return_value=MagicMock(hash="abc123", short_hash="abc123")
        )

        result = await service._sync_metadata_to_rdf(
            project=project, new_name="New Title", new_description=None, user=user, storage=storage
        )

        storage.upload_file.assert_awaited_once()
        mock_git_service.commit_changes.assert_called_once()
        assert result == "abc123"

    @pytest.mark.asyncio
    async def test_sync_no_changes_needed(
        self, service: ProjectService, mock_git_service: MagicMock
    ) -> None:
        """Returns None when OntologyMetadataUpdater reports no changes."""
        project = _make_project()
        project.source_file_path = "ontologies/projects/abc/ontology.ttl"
        project.github_integration = None
        user = _make_user()
        storage = AsyncMock()

        # Turtle with no title/description metadata to update
        turtle_content = (
            b"@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
            b"<http://ex.org/ont> a owl:Ontology .\n"
        )
        mock_git_service.get_file_at_version = MagicMock(
            return_value=turtle_content.decode("utf-8")
        )

        result = await service._sync_metadata_to_rdf(
            project=project, new_name=None, new_description=None, user=user, storage=storage
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_sync_storage_download_failure(
        self, service: ProjectService, mock_git_service: MagicMock
    ) -> None:
        """Storage download failure returns None (graceful)."""
        from ontokit.services.storage import StorageError

        project = _make_project()
        project.source_file_path = "ontologies/projects/abc/ontology.ttl"
        project.github_integration = None
        user = _make_user()
        storage = AsyncMock()

        mock_git_service.repository_exists = MagicMock(return_value=False)
        storage.download_file = AsyncMock(side_effect=StorageError("not found"))

        result = await service._sync_metadata_to_rdf(
            project=project, new_name="New", new_description=None, user=user, storage=storage
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_sync_falls_back_to_minio_when_git_fails(
        self, service: ProjectService, mock_git_service: MagicMock
    ) -> None:
        """Falls back to MinIO download when git read fails."""
        project = _make_project()
        project.source_file_path = "ontologies/projects/abc/ontology.ttl"
        project.github_integration = None
        user = _make_user()
        storage = AsyncMock()

        turtle_content = (
            b"@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
            b"@prefix dc: <http://purl.org/dc/elements/1.1/> .\n"
            b'<http://ex.org/ont> a owl:Ontology ; dc:title "Old" .\n'
        )
        mock_git_service.get_file_at_version = MagicMock(side_effect=Exception("git error"))
        storage.download_file = AsyncMock(return_value=turtle_content)
        mock_git_service.commit_changes = MagicMock(
            return_value=MagicMock(hash="def456", short_hash="def456")
        )

        result = await service._sync_metadata_to_rdf(
            project=project, new_name="Updated", new_description=None, user=user, storage=storage
        )

        storage.download_file.assert_awaited_once()
        assert result == "def456"


# ---------------------------------------------------------------------------
# update with metadata sync
# ---------------------------------------------------------------------------


class TestUpdateWithMetadataSync:
    @pytest.mark.asyncio
    async def test_update_name_triggers_rdf_sync(
        self, service: ProjectService, mock_db: AsyncMock, mock_git_service: MagicMock
    ) -> None:
        """Changing name with storage triggers _sync_metadata_to_rdf."""
        project = _make_project()
        project.name = "Old Name"
        project.source_file_path = "ontologies/projects/abc/ontology.ttl"
        project.github_integration = None
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = project
        mock_db.execute.return_value = mock_result

        turtle_content = (
            b"@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
            b"@prefix dc: <http://purl.org/dc/elements/1.1/> .\n"
            b'<http://ex.org/ont> a owl:Ontology ; dc:title "Old Name" .\n'
        )
        mock_git_service.get_file_at_version = MagicMock(
            return_value=turtle_content.decode("utf-8")
        )
        mock_git_service.commit_changes = MagicMock(
            return_value=MagicMock(hash="sync123", short_hash="sync123")
        )

        owner = _make_user(user_id=OWNER_ID)
        storage = AsyncMock()
        storage.upload_file = AsyncMock()
        update_data = ProjectUpdate(name="New Name")

        await service.update(PROJECT_ID, update_data, owner, storage=storage)

        mock_git_service.commit_changes.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_label_preferences(
        self, service: ProjectService, mock_db: AsyncMock
    ) -> None:
        """Updating label_preferences stores JSON."""
        project = _make_project()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = project
        mock_db.execute.return_value = mock_result

        owner = _make_user(user_id=OWNER_ID)
        update_data = ProjectUpdate(label_preferences=["rdfs:label@en"])

        await service.update(PROJECT_ID, update_data, owner)

        import json

        assert project.label_preferences == json.dumps(["rdfs:label@en"])


# ---------------------------------------------------------------------------
# delete with git cleanup
# ---------------------------------------------------------------------------


class TestDeleteGitCleanup:
    @pytest.mark.asyncio
    async def test_delete_cleans_up_git_repo(
        self, service: ProjectService, mock_db: AsyncMock, mock_git_service: MagicMock
    ) -> None:
        """Deleting a project also deletes the git repository."""
        project = _make_project()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = project
        mock_db.execute.return_value = mock_result

        owner = _make_user(user_id=OWNER_ID)
        await service.delete(PROJECT_ID, owner)

        mock_git_service.delete_repository.assert_called_once_with(PROJECT_ID)

    @pytest.mark.asyncio
    async def test_delete_git_failure_is_graceful(
        self, service: ProjectService, mock_db: AsyncMock, mock_git_service: MagicMock
    ) -> None:
        """Git repo deletion failure doesn't prevent project deletion."""
        project = _make_project()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = project
        mock_db.execute.return_value = mock_result
        mock_git_service.delete_repository = MagicMock(side_effect=Exception("git error"))

        owner = _make_user(user_id=OWNER_ID)
        # Should not raise
        await service.delete(PROJECT_ID, owner)
        mock_db.delete.assert_awaited()

    @pytest.mark.asyncio
    async def test_superadmin_can_delete(self, service: ProjectService, mock_db: AsyncMock) -> None:
        """Superadmin can delete any project."""
        project = _make_project()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = project
        mock_db.execute.return_value = mock_result

        superadmin = _make_user(user_id="superadmin-id")

        with patch("ontokit.core.auth.settings") as mock_settings:
            mock_settings.superadmin_ids = ["superadmin-id"]
            await service.delete(PROJECT_ID, superadmin)

        mock_db.delete.assert_awaited()


# ---------------------------------------------------------------------------
# list_members with access_token
# ---------------------------------------------------------------------------


class TestListMembersWithToken:
    @pytest.mark.asyncio
    async def test_list_members_with_access_token(
        self, service: ProjectService, mock_db: AsyncMock
    ) -> None:
        """With access_token, fetches info for other members from Zitadel."""
        members = [
            _make_member(OWNER_ID, "owner"),
            _make_member(EDITOR_ID, "editor"),
        ]
        project = _make_project(members=members)

        mock_result_project = MagicMock()
        mock_result_project.scalar_one_or_none.return_value = project
        mock_db.execute.return_value = mock_result_project

        user = _make_user(user_id=OWNER_ID)

        with patch("ontokit.services.user_service.get_user_service") as mock_us:
            mock_user_service = MagicMock()
            mock_user_service.get_users_info = AsyncMock(
                return_value={
                    EDITOR_ID: {"id": EDITOR_ID, "name": "Editor", "email": "editor@test.com"}
                }
            )
            mock_us.return_value = mock_user_service

            result = await service.list_members(PROJECT_ID, user, access_token="token123")

        assert result.total == 2
        mock_user_service.get_users_info.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_list_members_private_project_denied(
        self, service: ProjectService, mock_db: AsyncMock
    ) -> None:
        """Non-member cannot list members of a private project."""
        project = _make_project(is_public=False)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = project
        mock_db.execute.return_value = mock_result

        stranger = _make_user(user_id="stranger-id")

        with pytest.raises(HTTPException) as exc_info:
            await service.list_members(PROJECT_ID, stranger)
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# add_member edge cases
# ---------------------------------------------------------------------------


class TestAddMemberEdgeCases:
    @pytest.mark.asyncio
    async def test_add_member_denied_for_editor(
        self, service: ProjectService, mock_db: AsyncMock
    ) -> None:
        """Editor cannot add members."""
        members = [_make_member(OWNER_ID, "owner"), _make_member(EDITOR_ID, "editor")]
        project = _make_project(members=members)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = project
        mock_db.execute.return_value = mock_result

        editor = _make_user(user_id=EDITOR_ID)
        member_data = MemberCreate(user_id="new-user-id", role="viewer")

        with pytest.raises(HTTPException) as exc_info:
            await service.add_member(PROJECT_ID, member_data, editor)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_add_already_existing_member(
        self, service: ProjectService, mock_db: AsyncMock
    ) -> None:
        """Adding an already-existing member raises 400."""
        project = _make_project()
        mock_result_project = MagicMock()
        mock_result_project.scalar_one_or_none.return_value = project
        mock_result_existing = MagicMock()
        mock_result_existing.scalar_one_or_none.return_value = _make_member(EDITOR_ID, "editor")
        mock_db.execute.side_effect = [mock_result_project, mock_result_existing]

        owner = _make_user(user_id=OWNER_ID)
        member_data = MemberCreate(user_id=EDITOR_ID, role="editor")

        with pytest.raises(HTTPException) as exc_info:
            await service.add_member(PROJECT_ID, member_data, owner)
        assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# update_member edge cases
# ---------------------------------------------------------------------------


class TestUpdateMemberEdgeCases:
    @pytest.mark.asyncio
    async def test_admin_cannot_promote_to_admin(
        self, service: ProjectService, mock_db: AsyncMock
    ) -> None:
        """Admin cannot promote others to admin (owner only)."""
        members = [_make_member(OWNER_ID, "owner"), _make_member(ADMIN_ID, "admin")]
        project = _make_project(members=members)

        mock_result_project = MagicMock()
        mock_result_project.scalar_one_or_none.return_value = project

        editor_member = _make_member(EDITOR_ID, "editor")
        mock_result_member = MagicMock()
        mock_result_member.scalar_one_or_none.return_value = editor_member

        mock_db.execute.side_effect = [mock_result_project, mock_result_member]

        admin = _make_user(user_id=ADMIN_ID)
        from ontokit.schemas.project import MemberUpdate

        with pytest.raises(HTTPException) as exc_info:
            await service.update_member(PROJECT_ID, EDITOR_ID, MemberUpdate(role="admin"), admin)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_editor_cannot_update_roles(
        self, service: ProjectService, mock_db: AsyncMock
    ) -> None:
        """Editor cannot update member roles."""
        members = [_make_member(OWNER_ID, "owner"), _make_member(EDITOR_ID, "editor")]
        project = _make_project(members=members)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = project
        mock_db.execute.return_value = mock_result

        editor = _make_user(user_id=EDITOR_ID)
        from ontokit.schemas.project import MemberUpdate

        with pytest.raises(HTTPException) as exc_info:
            await service.update_member(PROJECT_ID, VIEWER_ID, MemberUpdate(role="editor"), editor)
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# remove_member edge cases
# ---------------------------------------------------------------------------


class TestRemoveMemberEdgeCases:
    @pytest.mark.asyncio
    async def test_remove_member_not_found(
        self, service: ProjectService, mock_db: AsyncMock
    ) -> None:
        """Removing a non-existent member raises 404."""
        project = _make_project()
        mock_result_project = MagicMock()
        mock_result_project.scalar_one_or_none.return_value = project
        mock_result_member = MagicMock()
        mock_result_member.scalar_one_or_none.return_value = None
        mock_db.execute.side_effect = [mock_result_project, mock_result_member]

        owner = _make_user(user_id=OWNER_ID)

        with pytest.raises(HTTPException) as exc_info:
            await service.remove_member(PROJECT_ID, "ghost-user", owner)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_admin_cannot_remove_other_admin(
        self, service: ProjectService, mock_db: AsyncMock
    ) -> None:
        """Admin cannot remove another admin."""
        admin2_id = "admin2-user-id"
        members = [
            _make_member(OWNER_ID, "owner"),
            _make_member(ADMIN_ID, "admin"),
            _make_member(admin2_id, "admin"),
        ]
        project = _make_project(members=members)
        mock_result_project = MagicMock()
        mock_result_project.scalar_one_or_none.return_value = project

        admin2_member = _make_member(admin2_id, "admin")
        mock_result_member = MagicMock()
        mock_result_member.scalar_one_or_none.return_value = admin2_member
        mock_db.execute.side_effect = [mock_result_project, mock_result_member]

        admin = _make_user(user_id=ADMIN_ID)

        with pytest.raises(HTTPException) as exc_info:
            await service.remove_member(PROJECT_ID, admin2_id, admin)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_self_removal_allowed(self, service: ProjectService, mock_db: AsyncMock) -> None:
        """A member can remove themselves."""
        members = [_make_member(OWNER_ID, "owner"), _make_member(EDITOR_ID, "editor")]
        project = _make_project(members=members)
        mock_result_project = MagicMock()
        mock_result_project.scalar_one_or_none.return_value = project

        editor_member = _make_member(EDITOR_ID, "editor")
        mock_result_member = MagicMock()
        mock_result_member.scalar_one_or_none.return_value = editor_member
        mock_db.execute.side_effect = [mock_result_project, mock_result_member]

        editor = _make_user(user_id=EDITOR_ID)
        await service.remove_member(PROJECT_ID, EDITOR_ID, editor)

        mock_db.delete.assert_awaited()


# ---------------------------------------------------------------------------
# transfer_ownership edge cases
# ---------------------------------------------------------------------------


class TestTransferOwnershipEdgeCases:
    @pytest.mark.asyncio
    async def test_transfer_to_non_member(
        self, service: ProjectService, mock_db: AsyncMock
    ) -> None:
        """Transferring to a non-member raises 404."""
        project = _make_project()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = project
        mock_db.execute.return_value = mock_result

        owner = _make_user(user_id=OWNER_ID)
        transfer = TransferOwnership(new_owner_id="non-member-id")

        with pytest.raises(HTTPException) as exc_info:
            await service.transfer_ownership(PROJECT_ID, transfer, owner)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_transfer_github_integration_no_token_blocked(
        self, service: ProjectService, mock_db: AsyncMock
    ) -> None:
        """Transfer blocked when new owner lacks GitHub token (without force)."""
        admin_member = _make_member(ADMIN_ID, "admin")
        project = _make_project(members=[_make_member(OWNER_ID, "owner"), admin_member])
        project.github_integration = MagicMock()  # has GitHub integration

        mock_result_project = MagicMock()
        mock_result_project.scalar_one_or_none.return_value = project

        mock_no_token = MagicMock()
        mock_no_token.scalar_one_or_none.return_value = None

        mock_db.execute.side_effect = [mock_result_project, mock_no_token]

        owner = _make_user(user_id=OWNER_ID)
        transfer = TransferOwnership(new_owner_id=ADMIN_ID)

        with pytest.raises(HTTPException) as exc_info:
            await service.transfer_ownership(PROJECT_ID, transfer, owner)
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_transfer_github_integration_force_deletes(
        self, service: ProjectService, mock_db: AsyncMock
    ) -> None:
        """Force transfer deletes GitHub integration when new owner has no token."""
        admin_member = _make_member(ADMIN_ID, "admin")
        owner_member = _make_member(OWNER_ID, "owner")
        project = _make_project(members=[owner_member, admin_member])
        project.github_integration = MagicMock()

        mock_result_project = MagicMock()
        mock_result_project.scalar_one_or_none.return_value = project

        mock_no_token = MagicMock()
        mock_no_token.scalar_one_or_none.return_value = None

        # _get_project, first token check (pre-transfer), second token check (post-transfer),
        # then list_members call at the end
        mock_members_result = MagicMock()
        mock_members_result.scalar_one_or_none.return_value = project
        mock_db.execute.side_effect = [
            mock_result_project,
            mock_no_token,
            mock_no_token,
            mock_members_result,
        ]

        owner = _make_user(user_id=OWNER_ID)
        transfer = TransferOwnership(new_owner_id=ADMIN_ID)

        with patch.object(service, "list_members", new_callable=AsyncMock) as mock_list:
            mock_list.return_value = MagicMock()
            await service.transfer_ownership(PROJECT_ID, transfer, owner, force=True)

        mock_db.delete.assert_awaited()
        assert admin_member.role == "owner"
        assert owner_member.role == "admin"

    @pytest.mark.asyncio
    async def test_transfer_github_integration_preserved_with_token(
        self, service: ProjectService, mock_db: AsyncMock
    ) -> None:
        """Transfer preserves GitHub integration when new owner has a token."""
        admin_member = _make_member(ADMIN_ID, "admin")
        owner_member = _make_member(OWNER_ID, "owner")
        project = _make_project(members=[owner_member, admin_member])
        github_int = MagicMock()
        project.github_integration = github_int

        mock_result_project = MagicMock()
        mock_result_project.scalar_one_or_none.return_value = project

        mock_has_token = MagicMock()
        mock_has_token.scalar_one_or_none.return_value = MagicMock()  # token exists

        mock_db.execute.side_effect = [
            mock_result_project,
            mock_has_token,
            mock_has_token,
        ]

        owner = _make_user(user_id=OWNER_ID)
        transfer = TransferOwnership(new_owner_id=ADMIN_ID)

        with patch.object(service, "list_members", new_callable=AsyncMock) as mock_list:
            mock_list.return_value = MagicMock()
            await service.transfer_ownership(PROJECT_ID, transfer, owner)

        assert github_int.connected_by_user_id == ADMIN_ID
        assert admin_member.role == "owner"

    @pytest.mark.asyncio
    async def test_superadmin_can_transfer(
        self, service: ProjectService, mock_db: AsyncMock
    ) -> None:
        """Superadmin can transfer ownership even if not the owner."""
        admin_member = _make_member(ADMIN_ID, "admin")
        owner_member = _make_member(OWNER_ID, "owner")
        project = _make_project(members=[owner_member, admin_member])

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = project
        mock_db.execute.return_value = mock_result

        superadmin = _make_user(user_id="superadmin-id")
        transfer = TransferOwnership(new_owner_id=ADMIN_ID)

        with (
            patch("ontokit.core.auth.settings") as mock_settings,
            patch.object(service, "list_members", new_callable=AsyncMock) as mock_list,
        ):
            mock_settings.superadmin_ids = ["superadmin-id"]
            mock_list.return_value = MagicMock()
            await service.transfer_ownership(PROJECT_ID, transfer, superadmin)

        assert admin_member.role == "owner"
        assert owner_member.role == "admin"


# ---------------------------------------------------------------------------
# _get_git_ontology_path
# ---------------------------------------------------------------------------


class TestGetGitOntologyPath:
    def test_github_integration_turtle_path(self, service: ProjectService) -> None:
        """Uses turtle_file_path when available."""
        project = _make_project()
        project.github_integration = MagicMock()
        project.github_integration.turtle_file_path = "src/ontology.ttl"
        project.github_integration.ontology_file_path = "src/ontology.owl"

        result = service._get_git_ontology_path(project)
        assert result == "src/ontology.ttl"

    def test_github_integration_ontology_path_fallback(self, service: ProjectService) -> None:
        """Falls back to ontology_file_path when no turtle_file_path."""
        project = _make_project()
        project.github_integration = MagicMock()
        project.github_integration.turtle_file_path = None
        project.github_integration.ontology_file_path = "src/ontology.owl"

        result = service._get_git_ontology_path(project)
        assert result == "src/ontology.owl"

    def test_source_file_path_basename(self, service: ProjectService) -> None:
        """Uses basename of source_file_path when no GitHub integration."""
        project = _make_project()
        project.github_integration = None
        project.source_file_path = "projects/abc/ontology.ttl"

        result = service._get_git_ontology_path(project)
        assert result == "ontology.ttl"

    def test_default_fallback(self, service: ProjectService) -> None:
        """Returns 'ontology.ttl' when nothing else is available."""
        project = _make_project()
        project.github_integration = None
        project.source_file_path = None

        result = service._get_git_ontology_path(project)
        assert result == "ontology.ttl"


# ---------------------------------------------------------------------------
# _to_response edge cases
# ---------------------------------------------------------------------------


class TestToResponseEdgeCases:
    def test_normalization_report_deserialized(self, service: ProjectService) -> None:
        """_to_response deserializes normalization_report from JSON."""
        project = _make_project()
        project.normalization_report = (
            '{"original_format": "xml", "original_filename": "test.owl",'
            ' "original_size_bytes": 1000, "normalized_size_bytes": 800,'
            ' "triple_count": 50, "prefixes_before": [], "prefixes_after": [],'
            ' "prefixes_removed": [], "prefixes_added": [],'
            ' "format_converted": true, "blank_node_count": 0,'
            ' "used_canonical_bnodes": false, "notes": []}'
        )
        user = _make_user(user_id=OWNER_ID)

        response = service._to_response(project, user)
        assert response.normalization_report is not None
        assert response.normalization_report.original_format == "xml"

    def test_invalid_normalization_report_returns_none(self, service: ProjectService) -> None:
        """Malformed normalization_report JSON returns None."""
        project = _make_project()
        project.normalization_report = "not valid json"
        user = _make_user(user_id=OWNER_ID)

        response = service._to_response(project, user)
        assert response.normalization_report is None

    def test_invalid_label_preferences_returns_none(self, service: ProjectService) -> None:
        """Malformed label_preferences JSON returns None."""
        project = _make_project()
        project.label_preferences = "{bad json"
        user = _make_user(user_id=OWNER_ID)

        response = service._to_response(project, user)
        assert response.label_preferences is None

    def test_git_ontology_path_in_response(self, service: ProjectService) -> None:
        """Response includes git_ontology_path when source_file_path is set."""
        project = _make_project()
        project.source_file_path = "projects/abc/ontology.ttl"
        project.github_integration = None
        user = _make_user(user_id=OWNER_ID)

        response = service._to_response(project, user)
        assert response.git_ontology_path == "ontology.ttl"
