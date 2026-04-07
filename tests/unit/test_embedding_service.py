"""Tests for EmbeddingService (ontokit/services/embedding_service.py)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from ontokit.services.embedding_service import EmbeddingService

PROJECT_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
BRANCH = "main"


def _make_config_row(
    *,
    provider: str = "local",
    model_name: str = "all-MiniLM-L6-v2",
    api_key_encrypted: str | None = None,
    dimensions: int = 384,
    auto_embed_on_save: bool = False,
    last_full_embed_at: datetime | None = None,
) -> MagicMock:
    """Create a mock ProjectEmbeddingConfig ORM object."""
    cfg = MagicMock()
    cfg.provider = provider
    cfg.model_name = model_name
    cfg.api_key_encrypted = api_key_encrypted
    cfg.dimensions = dimensions
    cfg.auto_embed_on_save = auto_embed_on_save
    cfg.last_full_embed_at = last_full_embed_at
    cfg.project_id = PROJECT_ID
    return cfg


@pytest.fixture
def mock_db() -> AsyncMock:
    """Create an async mock of AsyncSession."""
    session = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock()
    session.refresh = AsyncMock()
    session.add = Mock()
    return session


@pytest.fixture
def service(mock_db: AsyncMock) -> EmbeddingService:
    """Create an EmbeddingService with mocked DB."""
    return EmbeddingService(mock_db)


class TestGetConfig:
    """Tests for get_config()."""

    @pytest.mark.asyncio
    async def test_returns_none_when_no_config(
        self, service: EmbeddingService, mock_db: AsyncMock
    ) -> None:
        """Returns None when no config exists for the project."""
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = result

        config = await service.get_config(PROJECT_ID)
        assert config is None

    @pytest.mark.asyncio
    async def test_returns_config_when_exists(
        self, service: EmbeddingService, mock_db: AsyncMock
    ) -> None:
        """Returns an EmbeddingConfig when config exists."""
        cfg = _make_config_row()
        result = MagicMock()
        result.scalar_one_or_none.return_value = cfg
        mock_db.execute.return_value = result

        config = await service.get_config(PROJECT_ID)
        assert config is not None
        assert config.provider == "local"
        assert config.model_name == "all-MiniLM-L6-v2"
        assert config.api_key_set is False

    @pytest.mark.asyncio
    async def test_api_key_set_true_when_encrypted_key_present(
        self, service: EmbeddingService, mock_db: AsyncMock
    ) -> None:
        """api_key_set is True when api_key_encrypted is not None."""
        cfg = _make_config_row(api_key_encrypted="encrypted-key")
        result = MagicMock()
        result.scalar_one_or_none.return_value = cfg
        mock_db.execute.return_value = result

        config = await service.get_config(PROJECT_ID)
        assert config is not None
        assert config.api_key_set is True


class TestUpdateConfig:
    """Tests for update_config()."""

    @pytest.mark.asyncio
    async def test_creates_new_config_when_none_exists(
        self, service: EmbeddingService, mock_db: AsyncMock
    ) -> None:
        """Creates a new ProjectEmbeddingConfig when none exists."""
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = result

        update = MagicMock()
        update.provider = "local"
        update.model_name = "all-MiniLM-L6-v2"
        update.dimensions = 384
        update.api_key = None
        update.auto_embed_on_save = True

        await service.update_config(PROJECT_ID, update)
        mock_db.add.assert_called_once()
        mock_db.commit.assert_awaited_once()


class TestGetStatus:
    """Tests for get_status()."""

    @pytest.mark.asyncio
    async def test_returns_status_with_no_config(
        self, service: EmbeddingService, mock_db: AsyncMock
    ) -> None:
        """Returns default status when no config or embeddings exist."""
        # Config query -> None
        config_result = MagicMock()
        config_result.scalar_one_or_none.return_value = None

        # Embedded count -> 0
        count_result = MagicMock()
        count_result.scalar.return_value = 0

        # Active job -> None
        job_result = MagicMock()
        job_result.scalar_one_or_none.return_value = None

        # Last completed job total -> None
        last_total_result = MagicMock()
        last_total_result.scalar.return_value = None

        mock_db.execute.side_effect = [config_result, count_result, job_result, last_total_result]

        status = await service.get_status(PROJECT_ID, BRANCH)
        assert status.provider == "local"
        assert status.model_name == "all-MiniLM-L6-v2"
        assert status.embedded_entities == 0
        assert status.job_in_progress is False
        assert status.coverage_percent == 0.0

    @pytest.mark.asyncio
    async def test_returns_status_with_active_job(
        self, service: EmbeddingService, mock_db: AsyncMock
    ) -> None:
        """Returns status showing job in progress with progress percentage."""
        cfg = _make_config_row()
        config_result = MagicMock()
        config_result.scalar_one_or_none.return_value = cfg

        count_result = MagicMock()
        count_result.scalar.return_value = 50

        active_job = MagicMock()
        active_job.total_entities = 100
        active_job.embedded_entities = 50
        job_result = MagicMock()
        job_result.scalar_one_or_none.return_value = active_job

        mock_db.execute.side_effect = [config_result, count_result, job_result]

        status = await service.get_status(PROJECT_ID, BRANCH)
        assert status.job_in_progress is True
        assert status.job_progress_percent == 50.0


class TestClearEmbeddings:
    """Tests for clear_embeddings()."""

    @pytest.mark.asyncio
    async def test_deletes_embeddings_and_jobs(
        self, service: EmbeddingService, mock_db: AsyncMock
    ) -> None:
        """Deletes all embeddings and jobs, resets last_full_embed_at."""
        cfg = _make_config_row(last_full_embed_at=datetime.now(UTC))
        result = MagicMock()
        result.scalar_one_or_none.return_value = cfg
        # First two are delete calls, third is select config
        mock_db.execute.side_effect = [MagicMock(), MagicMock(), result]

        await service.clear_embeddings(PROJECT_ID)
        # Verify commit was called
        mock_db.commit.assert_awaited_once()
        # Config's last_full_embed_at should be reset
        assert cfg.last_full_embed_at is None

    @pytest.mark.asyncio
    async def test_handles_no_config_gracefully(
        self, service: EmbeddingService, mock_db: AsyncMock
    ) -> None:
        """Handles case where no config exists (just deletes embeddings/jobs)."""
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        mock_db.execute.side_effect = [MagicMock(), MagicMock(), result]

        await service.clear_embeddings(PROJECT_ID)
        mock_db.commit.assert_awaited_once()
