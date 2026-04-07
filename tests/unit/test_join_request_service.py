"""Tests for JoinRequestService (ontokit/services/join_request_service.py)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from fastapi import HTTPException

from ontokit.core.auth import CurrentUser
from ontokit.models.join_request import JoinRequestStatus
from ontokit.schemas.join_request import JoinRequestAction, JoinRequestCreate
from ontokit.services.join_request_service import JoinRequestService, get_join_request_service

PROJECT_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
REQUEST_ID = uuid.UUID("22345678-1234-5678-1234-567812345678")
OWNER_ID = "owner-user-id"
ADMIN_ID = "admin-user-id"
REQUESTER_ID = "requester-user-id"
VIEWER_ID = "viewer-user-id"


def _make_user(user_id: str = REQUESTER_ID, name: str = "Test User") -> CurrentUser:
    return CurrentUser(
        id=user_id, email="test@example.com", name=name, username="testuser", roles=[]
    )


def _make_project(*, is_public: bool = True) -> MagicMock:
    """Create a mock Project ORM object."""
    project = MagicMock()
    project.id = PROJECT_ID
    project.name = "Test Project"
    project.is_public = is_public
    return project


def _make_join_request(
    *,
    status: str = JoinRequestStatus.PENDING,
    user_id: str = REQUESTER_ID,
    responded_by: str | None = None,
) -> MagicMock:
    """Create a mock JoinRequest ORM object."""
    jr = MagicMock()
    jr.id = REQUEST_ID
    jr.project_id = PROJECT_ID
    jr.user_id = user_id
    jr.user_name = "Requester"
    jr.user_email = "requester@example.com"
    jr.message = "I would like to join this project for research purposes."
    jr.status = status
    jr.responded_by = responded_by
    jr.responded_at = None
    jr.response_message = None
    jr.created_at = datetime.now(UTC)
    jr.updated_at = None
    return jr


@pytest.fixture
def mock_db() -> AsyncMock:
    """Create an async mock of AsyncSession."""
    session = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.execute = AsyncMock()
    session.refresh = AsyncMock()
    session.add = Mock()
    session.delete = AsyncMock()
    return session


@pytest.fixture
def mock_user_service() -> MagicMock:
    """Create a mock UserService."""
    svc = MagicMock()
    svc.get_users_info = AsyncMock(return_value={})
    return svc


@pytest.fixture
def service(mock_db: AsyncMock, mock_user_service: MagicMock) -> JoinRequestService:
    return JoinRequestService(db=mock_db, user_service=mock_user_service)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


class TestFactory:
    def test_factory_returns_instance(self, mock_db: AsyncMock) -> None:
        with patch("ontokit.services.join_request_service.get_user_service"):
            svc = get_join_request_service(mock_db)
        assert isinstance(svc, JoinRequestService)


# ---------------------------------------------------------------------------
# create_request
# ---------------------------------------------------------------------------


class TestCreateRequest:
    @pytest.mark.asyncio
    async def test_create_request_for_public_project(
        self, service: JoinRequestService, mock_db: AsyncMock
    ) -> None:
        """A user can create a join request for a public project."""
        project = _make_project(is_public=True)

        # 1st execute: _get_project
        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none.return_value = project
        # 2nd execute: _get_user_role (no existing membership)
        mock_role_result = MagicMock()
        mock_role_result.scalar_one_or_none.return_value = None

        mock_db.execute.side_effect = [mock_project_result, mock_role_result]

        _make_user(user_id=REQUESTER_ID)
        JoinRequestCreate(message="I would like to join for research purposes.")

        with patch("ontokit.services.join_request_service.NotificationService"):
            result = service._to_response(_make_join_request())

        assert result.status == JoinRequestStatus.PENDING
        assert result.user_id == REQUESTER_ID

    @pytest.mark.asyncio
    async def test_create_request_for_private_project_rejected(
        self, service: JoinRequestService, mock_db: AsyncMock
    ) -> None:
        """Join requests are rejected for private projects."""
        project = _make_project(is_public=False)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = project
        mock_db.execute.return_value = mock_result

        user = _make_user(user_id=REQUESTER_ID)
        data = JoinRequestCreate(message="I want to join this private project.")

        with pytest.raises(HTTPException) as exc_info:
            await service.create_request(PROJECT_ID, data, user)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_create_request_when_already_member_rejected(
        self, service: JoinRequestService, mock_db: AsyncMock
    ) -> None:
        """A user who is already a member cannot create a join request."""
        project = _make_project(is_public=True)

        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none.return_value = project
        mock_role_result = MagicMock()
        mock_role_result.scalar_one_or_none.return_value = "viewer"

        mock_db.execute.side_effect = [mock_project_result, mock_role_result]

        user = _make_user(user_id=REQUESTER_ID)
        data = JoinRequestCreate(message="I am already a member but trying again.")

        with pytest.raises(HTTPException) as exc_info:
            await service.create_request(PROJECT_ID, data, user)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_create_request_project_not_found(
        self, service: JoinRequestService, mock_db: AsyncMock
    ) -> None:
        """Creating a request for a non-existent project raises 404."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        user = _make_user()
        data = JoinRequestCreate(message="Join me to this project please.")

        with pytest.raises(HTTPException) as exc_info:
            await service.create_request(uuid.uuid4(), data, user)
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# list_requests
# ---------------------------------------------------------------------------


class TestListRequests:
    @pytest.mark.asyncio
    async def test_admin_can_list_requests(
        self, service: JoinRequestService, mock_db: AsyncMock
    ) -> None:
        """An admin can list join requests for a project."""
        # _check_admin_access: _get_user_role returns "admin"
        mock_role_result = MagicMock()
        mock_role_result.scalar_one_or_none.return_value = "admin"
        # list query
        jr = _make_join_request()
        mock_list_result = MagicMock()
        mock_list_result.scalars.return_value.all.return_value = [jr]
        # count query
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 1

        mock_db.execute.side_effect = [mock_role_result, mock_list_result, mock_count_result]

        admin = _make_user(user_id=ADMIN_ID)
        result = await service.list_requests(PROJECT_ID, admin)
        assert result.total == 1

    @pytest.mark.asyncio
    async def test_editor_denied_list_requests(
        self, service: JoinRequestService, mock_db: AsyncMock
    ) -> None:
        """A non-admin user cannot list join requests."""
        mock_role_result = MagicMock()
        mock_role_result.scalar_one_or_none.return_value = "editor"
        mock_db.execute.return_value = mock_role_result

        editor = _make_user(user_id="editor-id")

        with pytest.raises(HTTPException) as exc_info:
            await service.list_requests(PROJECT_ID, editor)
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# approve_request / decline_request
# ---------------------------------------------------------------------------


class TestApproveRequest:
    @pytest.mark.asyncio
    async def test_approve_pending_request(
        self, service: JoinRequestService, mock_db: AsyncMock
    ) -> None:
        """Approving a pending request changes status and adds member."""
        # _check_admin_access
        mock_role_result = MagicMock()
        mock_role_result.scalar_one_or_none.return_value = "admin"

        jr = _make_join_request(status=JoinRequestStatus.PENDING)
        mock_jr_result = MagicMock()
        mock_jr_result.scalar_one_or_none.return_value = jr

        # _get_project for notification
        project = _make_project()
        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none.return_value = project

        mock_db.execute.side_effect = [mock_role_result, mock_jr_result, mock_project_result]

        admin = _make_user(user_id=ADMIN_ID)
        action = JoinRequestAction(response_message="Welcome!")

        with patch("ontokit.services.join_request_service.NotificationService") as mock_notif_cls:
            mock_notif_cls.return_value.create_notification = AsyncMock()
            await service.approve_request(PROJECT_ID, REQUEST_ID, action, admin)

        assert jr.status == JoinRequestStatus.APPROVED
        assert jr.responded_by == ADMIN_ID
        assert mock_db.add.called  # member was added

    @pytest.mark.asyncio
    async def test_approve_already_approved_rejected(
        self, service: JoinRequestService, mock_db: AsyncMock
    ) -> None:
        """Approving an already-approved request raises 400."""
        mock_role_result = MagicMock()
        mock_role_result.scalar_one_or_none.return_value = "admin"

        jr = _make_join_request(status=JoinRequestStatus.APPROVED)
        mock_jr_result = MagicMock()
        mock_jr_result.scalar_one_or_none.return_value = jr

        mock_db.execute.side_effect = [mock_role_result, mock_jr_result]

        admin = _make_user(user_id=ADMIN_ID)
        action = JoinRequestAction()

        with pytest.raises(HTTPException) as exc_info:
            await service.approve_request(PROJECT_ID, REQUEST_ID, action, admin)
        assert exc_info.value.status_code == 400


class TestDeclineRequest:
    @pytest.mark.asyncio
    async def test_decline_pending_request(
        self, service: JoinRequestService, mock_db: AsyncMock
    ) -> None:
        """Declining a pending request changes status to declined."""
        mock_role_result = MagicMock()
        mock_role_result.scalar_one_or_none.return_value = "owner"

        jr = _make_join_request(status=JoinRequestStatus.PENDING)
        mock_jr_result = MagicMock()
        mock_jr_result.scalar_one_or_none.return_value = jr

        project = _make_project()
        mock_project_result = MagicMock()
        mock_project_result.scalar_one_or_none.return_value = project

        mock_db.execute.side_effect = [mock_role_result, mock_jr_result, mock_project_result]

        owner = _make_user(user_id=OWNER_ID)
        action = JoinRequestAction(response_message="Sorry, not at this time.")

        with patch("ontokit.services.join_request_service.NotificationService") as mock_notif_cls:
            mock_notif_cls.return_value.create_notification = AsyncMock()
            await service.decline_request(PROJECT_ID, REQUEST_ID, action, owner)

        assert jr.status == JoinRequestStatus.DECLINED
        assert jr.responded_by == OWNER_ID

    @pytest.mark.asyncio
    async def test_decline_not_found_raises_404(
        self, service: JoinRequestService, mock_db: AsyncMock
    ) -> None:
        """Declining a non-existent request raises 404."""
        mock_role_result = MagicMock()
        mock_role_result.scalar_one_or_none.return_value = "admin"

        mock_jr_result = MagicMock()
        mock_jr_result.scalar_one_or_none.return_value = None

        mock_db.execute.side_effect = [mock_role_result, mock_jr_result]

        admin = _make_user(user_id=ADMIN_ID)
        action = JoinRequestAction()

        with pytest.raises(HTTPException) as exc_info:
            await service.decline_request(PROJECT_ID, uuid.uuid4(), action, admin)
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# withdraw_request
# ---------------------------------------------------------------------------


class TestWithdrawRequest:
    @pytest.mark.asyncio
    async def test_requester_can_withdraw(
        self, service: JoinRequestService, mock_db: AsyncMock
    ) -> None:
        """The requester can withdraw their own pending request."""
        jr = _make_join_request(status=JoinRequestStatus.PENDING, user_id=REQUESTER_ID)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = jr
        mock_db.execute.return_value = mock_result

        user = _make_user(user_id=REQUESTER_ID)
        await service.withdraw_request(PROJECT_ID, REQUEST_ID, user)

        assert jr.status == JoinRequestStatus.WITHDRAWN
        assert mock_db.commit.called

    @pytest.mark.asyncio
    async def test_other_user_cannot_withdraw(
        self, service: JoinRequestService, mock_db: AsyncMock
    ) -> None:
        """Another user cannot withdraw someone else's request."""
        jr = _make_join_request(status=JoinRequestStatus.PENDING, user_id=REQUESTER_ID)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = jr
        mock_db.execute.return_value = mock_result

        other_user = _make_user(user_id="other-user-id")

        with pytest.raises(HTTPException) as exc_info:
            await service.withdraw_request(PROJECT_ID, REQUEST_ID, other_user)
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# get_my_request
# ---------------------------------------------------------------------------


class TestGetMyRequest:
    @pytest.mark.asyncio
    async def test_returns_pending_request(
        self, service: JoinRequestService, mock_db: AsyncMock
    ) -> None:
        """Returns has_pending_request=True when a pending request exists."""
        jr = _make_join_request(status=JoinRequestStatus.PENDING)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = jr
        mock_db.execute.return_value = mock_result

        user = _make_user(user_id=REQUESTER_ID)
        result = await service.get_my_request(PROJECT_ID, user)
        assert result.has_pending_request is True
        assert result.request is not None

    @pytest.mark.asyncio
    async def test_returns_no_request(
        self, service: JoinRequestService, mock_db: AsyncMock
    ) -> None:
        """Returns has_pending_request=False when no request exists."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        user = _make_user(user_id=REQUESTER_ID)
        result = await service.get_my_request(PROJECT_ID, user)
        assert result.has_pending_request is False
        assert result.request is None


# ---------------------------------------------------------------------------
# _to_response
# ---------------------------------------------------------------------------


class TestToResponse:
    def test_basic_response(self, service: JoinRequestService) -> None:
        """_to_response maps ORM fields correctly."""
        jr = _make_join_request()
        response = service._to_response(jr)
        assert response.id == REQUEST_ID
        assert response.project_id == PROJECT_ID
        assert response.status == JoinRequestStatus.PENDING
        assert response.user is not None
        assert response.user.id == REQUESTER_ID

    def test_response_with_responder(self, service: JoinRequestService) -> None:
        """_to_response includes responder info when available."""
        jr = _make_join_request(responded_by=ADMIN_ID)
        user_info: dict[str, dict[str, str | None]] = {
            ADMIN_ID: {"name": "Admin User", "email": "admin@example.com"},
        }
        response = service._to_response(jr, user_info)
        assert response.responder is not None
        assert response.responder.id == ADMIN_ID
        assert response.responder.name == "Admin User"
