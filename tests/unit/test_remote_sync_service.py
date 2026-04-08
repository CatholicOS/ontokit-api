"""Tests for RemoteSyncService (ontokit/services/remote_sync_service.py)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from arq.jobs import JobStatus
from fastapi import HTTPException
from pydantic import ValidationError

from ontokit.core.auth import CurrentUser
from ontokit.schemas.remote_sync import RemoteSyncConfigCreate
from ontokit.services.remote_sync_service import RemoteSyncService, get_remote_sync_service

PROJECT_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
OWNER_ID = "owner-user-id"
VIEWER_ID = "viewer-user-id"


def _make_user(user_id: str = OWNER_ID) -> CurrentUser:
    return CurrentUser(id=user_id, email="test@example.com", name="Test User", roles=[])


def _make_project_response(user_role: str | None = "owner") -> MagicMock:
    """Create a mock ProjectResponse."""
    resp = MagicMock()
    resp.user_role = user_role
    return resp


def _make_sync_config(*, status: str = "idle", project_id: uuid.UUID = PROJECT_ID) -> MagicMock:
    """Create a mock RemoteSyncConfig ORM object."""
    config = MagicMock()
    config.id = uuid.uuid4()
    config.project_id = project_id
    config.repo_owner = "CatholicOS"
    config.repo_name = "ontology-semantic-canon"
    config.branch = "main"
    config.file_path = "source/ontology.ttl"
    config.frequency = "manual"
    config.enabled = False
    config.update_mode = "review_required"
    config.status = status
    config.last_check_at = None
    config.last_update_at = None
    config.next_check_at = None
    config.remote_commit_sha = None
    config.pending_pr_id = None
    config.error_message = None
    return config


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
def service(mock_db: AsyncMock) -> RemoteSyncService:
    return RemoteSyncService(db=mock_db)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


class TestFactory:
    def test_factory_returns_instance(self, mock_db: AsyncMock) -> None:
        svc = get_remote_sync_service(mock_db)
        assert isinstance(svc, RemoteSyncService)


# ---------------------------------------------------------------------------
# _verify_access
# ---------------------------------------------------------------------------


class TestVerifyAccess:
    @pytest.mark.asyncio
    async def test_viewer_can_read(self, service: RemoteSyncService, mock_db: AsyncMock) -> None:  # noqa: ARG002
        """A viewer can access read-only endpoints (require_admin=False)."""
        with patch("ontokit.services.remote_sync_service.get_project_service") as mock_factory:
            mock_ps = MagicMock()
            mock_ps.get = AsyncMock(return_value=_make_project_response("viewer"))
            mock_factory.return_value = mock_ps

            role = await service._verify_access(PROJECT_ID, _make_user(VIEWER_ID))
            assert role == "viewer"

    @pytest.mark.asyncio
    async def test_viewer_denied_admin_endpoint(
        self,
        service: RemoteSyncService,
        mock_db: AsyncMock,  # noqa: ARG002
    ) -> None:
        """A viewer is denied access to admin-only endpoints."""
        with patch("ontokit.services.remote_sync_service.get_project_service") as mock_factory:
            mock_ps = MagicMock()
            mock_ps.get = AsyncMock(return_value=_make_project_response("viewer"))
            mock_factory.return_value = mock_ps

            with pytest.raises(HTTPException) as exc_info:
                await service._verify_access(PROJECT_ID, _make_user(VIEWER_ID), require_admin=True)
            assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_allowed_admin_endpoint(
        self,
        service: RemoteSyncService,
        mock_db: AsyncMock,  # noqa: ARG002
    ) -> None:
        """An admin can access admin-only endpoints."""
        with patch("ontokit.services.remote_sync_service.get_project_service") as mock_factory:
            mock_ps = MagicMock()
            mock_ps.get = AsyncMock(return_value=_make_project_response("admin"))
            mock_factory.return_value = mock_ps

            role = await service._verify_access(PROJECT_ID, _make_user(), require_admin=True)
            assert role == "admin"


# ---------------------------------------------------------------------------
# get_config
# ---------------------------------------------------------------------------


class TestGetConfig:
    @pytest.mark.asyncio
    async def test_returns_none_when_no_config(
        self,
        service: RemoteSyncService,
        mock_db: AsyncMock,  # noqa: ARG002
    ) -> None:
        """Returns None when no sync config exists."""
        with patch("ontokit.services.remote_sync_service.get_project_service") as mock_factory:
            mock_ps = MagicMock()
            mock_ps.get = AsyncMock(return_value=_make_project_response("owner"))
            mock_factory.return_value = mock_ps

            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = None
            mock_db.execute.return_value = mock_result

            result = await service.get_config(PROJECT_ID, _make_user())
            assert result is None


# ---------------------------------------------------------------------------
# save_config
# ---------------------------------------------------------------------------


class TestSaveConfig:
    @pytest.mark.asyncio
    async def test_create_new_config(self, service: RemoteSyncService, mock_db: AsyncMock) -> None:
        """save_config creates a new config when none exists."""
        with patch("ontokit.services.remote_sync_service.get_project_service") as mock_factory:
            mock_ps = MagicMock()
            mock_ps.get = AsyncMock(return_value=_make_project_response("owner"))
            mock_factory.return_value = mock_ps

            # First execute: verify access (handled by patch)
            # Second execute: check existing config
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = None
            mock_db.execute.return_value = mock_result

            data = RemoteSyncConfigCreate(
                repo_owner="CatholicOS",
                repo_name="test-repo",
                file_path="ontology.ttl",
            )

            # The service will call db.add, db.commit, db.refresh
            # then model_validate which will fail on a mock — that's OK,
            # we're testing the side-effects.
            with pytest.raises(ValidationError):
                await service.save_config(PROJECT_ID, data, _make_user())

            assert mock_db.add.called


# ---------------------------------------------------------------------------
# delete_config
# ---------------------------------------------------------------------------


class TestDeleteConfig:
    @pytest.mark.asyncio
    async def test_delete_nonexistent_raises_404(
        self,
        service: RemoteSyncService,
        mock_db: AsyncMock,  # noqa: ARG002
    ) -> None:
        """Deleting a non-existent config raises 404."""
        with patch("ontokit.services.remote_sync_service.get_project_service") as mock_factory:
            mock_ps = MagicMock()
            mock_ps.get = AsyncMock(return_value=_make_project_response("owner"))
            mock_factory.return_value = mock_ps

            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = None
            mock_db.execute.return_value = mock_result

            with pytest.raises(HTTPException) as exc_info:
                await service.delete_config(PROJECT_ID, _make_user())
            assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# trigger_check
# ---------------------------------------------------------------------------


class TestTriggerCheck:
    @pytest.mark.asyncio
    async def test_trigger_no_config_raises_404(
        self,
        service: RemoteSyncService,
        mock_db: AsyncMock,  # noqa: ARG002
    ) -> None:
        """Triggering a check with no config raises 404."""
        with patch("ontokit.services.remote_sync_service.get_project_service") as mock_factory:
            mock_ps = MagicMock()
            mock_ps.get = AsyncMock(return_value=_make_project_response("owner"))
            mock_factory.return_value = mock_ps

            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = None
            mock_db.execute.return_value = mock_result

            with pytest.raises(HTTPException) as exc_info:
                await service.trigger_check(PROJECT_ID, _make_user())
            assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_trigger_while_checking_raises_409(
        self,
        service: RemoteSyncService,
        mock_db: AsyncMock,  # noqa: ARG002
    ) -> None:
        """Triggering a check while one is in progress raises 409."""
        config = _make_sync_config(status="checking")

        with patch("ontokit.services.remote_sync_service.get_project_service") as mock_factory:
            mock_ps = MagicMock()
            mock_ps.get = AsyncMock(return_value=_make_project_response("owner"))
            mock_factory.return_value = mock_ps

            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = config
            mock_db.execute.return_value = mock_result

            with pytest.raises(HTTPException) as exc_info:
                await service.trigger_check(PROJECT_ID, _make_user())
            assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# get_history
# ---------------------------------------------------------------------------


class TestGetHistory:
    @pytest.mark.asyncio
    async def test_empty_history(self, service: RemoteSyncService, mock_db: AsyncMock) -> None:
        """Returns empty history when no events exist."""
        with patch("ontokit.services.remote_sync_service.get_project_service") as mock_factory:
            mock_ps = MagicMock()
            mock_ps.get = AsyncMock(return_value=_make_project_response("owner"))
            mock_factory.return_value = mock_ps

            # First execute: count query
            mock_count_result = MagicMock()
            mock_count_result.scalar.return_value = 0
            # Second execute: events query
            mock_events_result = MagicMock()
            mock_events_result.scalars.return_value.all.return_value = []
            mock_db.execute.side_effect = [mock_count_result, mock_events_result]

            result = await service.get_history(PROJECT_ID, limit=10, user=_make_user())
            assert result.total == 0
            assert result.items == []

    @pytest.mark.asyncio
    async def test_history_with_events(
        self,
        service: RemoteSyncService,
        mock_db: AsyncMock,
    ) -> None:
        """Returns history with events when they exist."""
        with patch("ontokit.services.remote_sync_service.get_project_service") as mock_factory:
            mock_ps = MagicMock()
            mock_ps.get = AsyncMock(return_value=_make_project_response("owner"))
            mock_factory.return_value = mock_ps

            mock_count_result = MagicMock()
            mock_count_result.scalar.return_value = 2

            from datetime import UTC, datetime

            event1 = MagicMock()
            event1.id = uuid.uuid4()
            event1.project_id = PROJECT_ID
            event1.config_id = uuid.uuid4()
            event1.event_type = "check_no_changes"
            event1.remote_commit_sha = "abc123"
            event1.pr_id = None
            event1.changes_summary = None
            event1.error_message = None
            event1.created_at = datetime.now(UTC)

            mock_events_result = MagicMock()
            mock_events_result.scalars.return_value.all.return_value = [event1]

            mock_db.execute.side_effect = [mock_count_result, mock_events_result]

            result = await service.get_history(PROJECT_ID, limit=10, user=_make_user())
            assert result.total == 2
            assert len(result.items) == 1


# ---------------------------------------------------------------------------
# trigger_check — success path
# ---------------------------------------------------------------------------


class TestTriggerCheckSuccess:
    @pytest.mark.asyncio
    async def test_trigger_check_success(
        self,
        service: RemoteSyncService,
        mock_db: AsyncMock,
    ) -> None:
        """Triggering a check with valid config enqueues a job."""
        config = _make_sync_config(status="idle")

        with (
            patch("ontokit.services.remote_sync_service.get_project_service") as mock_factory,
            patch("ontokit.services.remote_sync_service.get_arq_pool") as mock_pool_fn,
        ):
            mock_ps = MagicMock()
            mock_ps.get = AsyncMock(return_value=_make_project_response("owner"))
            mock_factory.return_value = mock_ps

            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = config
            mock_db.execute.return_value = mock_result

            mock_pool = AsyncMock()
            mock_pool.enqueue_job = AsyncMock(return_value=Mock(job_id="check-job-1"))
            mock_pool_fn.return_value = mock_pool

            result = await service.trigger_check(PROJECT_ID, _make_user())
            assert result.job_id == "check-job-1"
            assert result.status == "queued"
            assert config.status == "checking"

    @pytest.mark.asyncio
    async def test_trigger_check_enqueue_returns_none(
        self,
        service: RemoteSyncService,
        mock_db: AsyncMock,
    ) -> None:
        """Triggering a check when enqueue returns None raises 500."""
        config = _make_sync_config(status="idle")

        with (
            patch("ontokit.services.remote_sync_service.get_project_service") as mock_factory,
            patch("ontokit.services.remote_sync_service.get_arq_pool") as mock_pool_fn,
        ):
            mock_ps = MagicMock()
            mock_ps.get = AsyncMock(return_value=_make_project_response("owner"))
            mock_factory.return_value = mock_ps

            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = config
            mock_db.execute.return_value = mock_result

            mock_pool = AsyncMock()
            mock_pool.enqueue_job = AsyncMock(return_value=None)
            mock_pool_fn.return_value = mock_pool

            with pytest.raises(HTTPException) as exc_info:
                await service.trigger_check(PROJECT_ID, _make_user())
            assert exc_info.value.status_code == 500
            assert config.status == "error"


# ---------------------------------------------------------------------------
# get_job_status
# ---------------------------------------------------------------------------


class TestGetJobStatus:
    @pytest.mark.asyncio
    async def test_get_job_status_complete(
        self,
        service: RemoteSyncService,
        mock_db: AsyncMock,  # noqa: ARG002
    ) -> None:
        """Returns complete status for a finished job."""
        with (
            patch("ontokit.services.remote_sync_service.get_project_service") as mock_factory,
            patch("ontokit.services.remote_sync_service.get_arq_pool") as mock_pool_fn,
            patch("ontokit.services.remote_sync_service.Job") as mock_job_cls,
        ):
            mock_ps = MagicMock()
            mock_ps.get = AsyncMock(return_value=_make_project_response("owner"))
            mock_factory.return_value = mock_ps

            mock_pool_fn.return_value = AsyncMock()

            mock_job = MagicMock()
            mock_job.status = AsyncMock(return_value=JobStatus.complete)
            mock_info = MagicMock()
            mock_info.success = True
            mock_info.result = {"changes_detected": False}
            mock_job.result_info = AsyncMock(return_value=mock_info)
            mock_job_cls.return_value = mock_job

            result = await service.get_job_status(PROJECT_ID, "job-1", _make_user())
            assert result.status == "complete"
            assert result.result == {"changes_detected": False}
            assert result.error is None

    @pytest.mark.asyncio
    async def test_get_job_status_not_found(
        self,
        service: RemoteSyncService,
        mock_db: AsyncMock,  # noqa: ARG002
    ) -> None:
        """Returns not_found when job status lookup raises."""
        with (
            patch("ontokit.services.remote_sync_service.get_project_service") as mock_factory,
            patch("ontokit.services.remote_sync_service.get_arq_pool") as mock_pool_fn,
            patch("ontokit.services.remote_sync_service.Job") as mock_job_cls,
        ):
            mock_ps = MagicMock()
            mock_ps.get = AsyncMock(return_value=_make_project_response("owner"))
            mock_factory.return_value = mock_ps

            mock_pool_fn.return_value = AsyncMock()

            mock_job = MagicMock()
            mock_job.status = AsyncMock(side_effect=RuntimeError("gone"))
            mock_job_cls.return_value = mock_job

            result = await service.get_job_status(PROJECT_ID, "bad-job", _make_user())
            assert result.status == "not_found"

    @pytest.mark.asyncio
    async def test_get_job_status_failed(
        self,
        service: RemoteSyncService,
        mock_db: AsyncMock,  # noqa: ARG002
    ) -> None:
        """Returns failed status when job completed but was unsuccessful."""
        with (
            patch("ontokit.services.remote_sync_service.get_project_service") as mock_factory,
            patch("ontokit.services.remote_sync_service.get_arq_pool") as mock_pool_fn,
            patch("ontokit.services.remote_sync_service.Job") as mock_job_cls,
        ):
            mock_ps = MagicMock()
            mock_ps.get = AsyncMock(return_value=_make_project_response("owner"))
            mock_factory.return_value = mock_ps

            mock_pool_fn.return_value = AsyncMock()

            mock_job = MagicMock()
            mock_job.status = AsyncMock(return_value=JobStatus.complete)
            mock_info = MagicMock()
            mock_info.success = False
            mock_info.result = "Connection refused"
            mock_job.result_info = AsyncMock(return_value=mock_info)
            mock_job_cls.return_value = mock_job

            result = await service.get_job_status(PROJECT_ID, "fail-job", _make_user())
            assert result.status == "failed"
            assert result.error == "Connection refused"
