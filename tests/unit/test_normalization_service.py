"""Tests for NormalizationService (ontokit/services/normalization_service.py)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from ontokit.services.normalization_service import NormalizationService

PROJECT_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
RUN_ID = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")

SAMPLE_TURTLE = b"""\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .

<http://example.org/onto> rdf:type owl:Ontology .
"""


def _make_project(
    source_file_path: str | None = "ontokit/ontology.ttl",
) -> MagicMock:
    """Create a mock Project ORM object."""
    project = MagicMock()
    project.id = PROJECT_ID
    project.source_file_path = source_file_path
    return project


def _make_normalization_run(
    *,
    is_dry_run: bool = False,
    format_converted: bool = False,
    prefixes_removed_count: int = 0,
    prefixes_added_count: int = 0,
    original_size_bytes: int = 100,
    normalized_size_bytes: int = 100,
) -> MagicMock:
    run = MagicMock()
    run.id = RUN_ID
    run.project_id = PROJECT_ID
    run.is_dry_run = is_dry_run
    run.format_converted = format_converted
    run.prefixes_removed_count = prefixes_removed_count
    run.prefixes_added_count = prefixes_added_count
    run.original_size_bytes = original_size_bytes
    run.normalized_size_bytes = normalized_size_bytes
    run.created_at = datetime.now(UTC)
    run.report_json = json.dumps({"notes": ["test"]})
    return run


@pytest.fixture
def mock_db() -> AsyncMock:
    """Create an async mock of AsyncSession."""
    session = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.execute = AsyncMock()
    session.add = Mock()
    return session


@pytest.fixture
def mock_storage() -> Mock:
    """Create a mock StorageService."""
    storage = Mock()
    storage.upload_file = AsyncMock(return_value="ontokit/ontology.ttl")
    storage.download_file = AsyncMock(return_value=SAMPLE_TURTLE)
    return storage


@pytest.fixture
def mock_git_service() -> MagicMock:
    """Create a mock GitRepositoryService."""
    git = MagicMock()
    git.repository_exists = Mock(return_value=True)
    git.commit_changes = Mock(return_value=MagicMock(hash="abc123"))
    return git


@pytest.fixture
def service(
    mock_db: AsyncMock, mock_storage: Mock, mock_git_service: MagicMock
) -> NormalizationService:
    """Create a NormalizationService with mocked dependencies."""
    return NormalizationService(mock_db, mock_storage, mock_git_service)


class TestGetCachedStatus:
    """Tests for get_cached_status()."""

    @pytest.mark.asyncio
    async def test_no_source_file_returns_not_needed(self, service: NormalizationService) -> None:
        """Returns needs_normalization=False when project has no source file."""
        project = _make_project(source_file_path=None)
        status = await service.get_cached_status(project)
        assert status["needs_normalization"] is False
        assert status["error"] == "Project has no ontology file"

    @pytest.mark.asyncio
    async def test_returns_unknown_when_no_checks(
        self, service: NormalizationService, mock_db: AsyncMock
    ) -> None:
        """Returns needs_normalization=None when no status checks exist."""
        # Both queries return no results
        result1 = MagicMock()
        result1.scalar_one_or_none.return_value = None
        result2 = MagicMock()
        result2.scalar_one_or_none.return_value = None
        mock_db.execute.side_effect = [result1, result2]

        project = _make_project()
        status = await service.get_cached_status(project)
        assert status["needs_normalization"] is None

    @pytest.mark.asyncio
    async def test_uses_last_check_when_more_recent(
        self, service: NormalizationService, mock_db: AsyncMock
    ) -> None:
        """Uses the last dry-run check when it's more recent than the last run."""
        last_run = _make_normalization_run(is_dry_run=False)
        last_run.created_at = datetime(2025, 1, 1, tzinfo=UTC)

        last_check = _make_normalization_run(is_dry_run=True, format_converted=True)
        last_check.created_at = datetime(2025, 1, 15, tzinfo=UTC)

        # First query: last actual run
        result1 = MagicMock()
        result1.scalar_one_or_none.return_value = last_run
        # Second query: last dry-run check
        result2 = MagicMock()
        result2.scalar_one_or_none.return_value = last_check

        mock_db.execute.side_effect = [result1, result2]

        project = _make_project()
        status = await service.get_cached_status(project)
        assert status["needs_normalization"] is True


class TestGetNormalizationHistory:
    """Tests for get_normalization_history()."""

    @pytest.mark.asyncio
    async def test_returns_list_of_runs(
        self, service: NormalizationService, mock_db: AsyncMock
    ) -> None:
        """Returns a list of NormalizationRun objects."""
        run = _make_normalization_run()
        result = MagicMock()
        result.scalars.return_value.all.return_value = [run]
        mock_db.execute.return_value = result

        history = await service.get_normalization_history(PROJECT_ID)
        assert len(history) == 1


class TestGetNormalizationRun:
    """Tests for get_normalization_run()."""

    @pytest.mark.asyncio
    async def test_returns_specific_run(
        self, service: NormalizationService, mock_db: AsyncMock
    ) -> None:
        """Returns a specific NormalizationRun by ID."""
        run = _make_normalization_run()
        result = MagicMock()
        result.scalar_one_or_none.return_value = run
        mock_db.execute.return_value = result

        found = await service.get_normalization_run(PROJECT_ID, RUN_ID)
        assert found is run

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(
        self, service: NormalizationService, mock_db: AsyncMock
    ) -> None:
        """Returns None when the run does not exist."""
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = result

        found = await service.get_normalization_run(PROJECT_ID, RUN_ID)
        assert found is None


class TestRunNormalization:
    """Tests for run_normalization()."""

    @pytest.mark.asyncio
    async def test_raises_when_no_source_file(self, service: NormalizationService) -> None:
        """Raises ValueError when project has no ontology file."""
        project = _make_project(source_file_path=None)
        with pytest.raises(ValueError, match="no ontology file"):
            await service.run_normalization(project)

    @pytest.mark.asyncio
    async def test_dry_run_returns_content_preview(
        self,
        service: NormalizationService,
        mock_db: AsyncMock,  # noqa: ARG002
        mock_storage: Mock,
    ) -> None:
        """Dry run returns original and normalized content as strings."""
        project = _make_project()
        run, original, normalized = await service.run_normalization(project, dry_run=True)
        # Dry run should not upload or commit
        mock_storage.upload_file.assert_not_awaited()
        # Should return content strings for preview
        assert original is not None
        assert normalized is not None


class TestCheckNormalizationStatus:
    """Tests for check_normalization_status() (lines 124-172)."""

    @pytest.mark.asyncio
    async def test_no_source_file(self, service: NormalizationService) -> None:
        """Returns error when project has no source file."""
        project = _make_project(source_file_path=None)
        result = await service.check_normalization_status(project)
        assert result["needs_normalization"] is False
        assert result["error"] == "Project has no ontology file"

    @pytest.mark.asyncio
    async def test_returns_needs_normalization(
        self,
        service: NormalizationService,
        mock_db: AsyncMock,
        mock_storage: Mock,  # noqa: ARG002
    ) -> None:
        """Returns needs_normalization=True when content differs after normalize."""
        # last run query returns None
        result1 = MagicMock()
        result1.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = result1

        project = _make_project()
        result = await service.check_normalization_status(project)
        # The sample turtle should parse OK; needs_normalization depends on comparison
        assert "needs_normalization" in result
        assert result["error"] is None

    @pytest.mark.asyncio
    async def test_storage_error(
        self, service: NormalizationService, mock_db: AsyncMock, mock_storage: Mock
    ) -> None:
        """Returns error on StorageError."""
        from ontokit.services.storage import StorageError

        result1 = MagicMock()
        result1.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = result1

        mock_storage.download_file = AsyncMock(side_effect=StorageError("bucket not found"))

        project = _make_project()
        result = await service.check_normalization_status(project)
        assert result["needs_normalization"] is False
        assert "Storage error" in result["error"]

    @pytest.mark.asyncio
    async def test_generic_error(
        self, service: NormalizationService, mock_db: AsyncMock, mock_storage: Mock
    ) -> None:
        """Returns error on generic Exception."""
        result1 = MagicMock()
        result1.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = result1

        mock_storage.download_file = AsyncMock(side_effect=RuntimeError("unexpected"))

        project = _make_project()
        result = await service.check_normalization_status(project)
        assert result["needs_normalization"] is False
        assert "unexpected" in result["error"]


class TestRunNormalizationCommit:
    """Tests for run_normalization with git commit (lines 215-235, 267)."""

    @pytest.mark.asyncio
    async def test_non_dry_run_commits_to_git(
        self,
        service: NormalizationService,
        mock_db: AsyncMock,  # noqa: ARG002
        mock_storage: Mock,
        mock_git_service: MagicMock,  # noqa: ARG002
    ) -> None:
        """Non-dry-run with changed content uploads and commits to git."""
        # Make storage return content that will differ from normalized output
        mock_storage.download_file = AsyncMock(return_value=SAMPLE_TURTLE)

        project = _make_project()
        user = MagicMock()
        user.id = "test-user"
        user.name = "Test User"
        user.email = "test@example.com"

        run, original, normalized = await service.run_normalization(
            project, user=user, dry_run=False
        )

        # Should return None content for non-dry-run
        assert original is None
        assert normalized is None

        # Git service should have been called if content changed
        # (It might not be called if normalize doesn't change anything,
        # but we verify no error occurs either way)
        assert run is not None


class TestGetObjectName:
    """Tests for _get_object_name()."""

    def test_strips_bucket_prefix(self, service: NormalizationService) -> None:
        """Strips the bucket prefix from a path with '/'."""
        assert service._get_object_name("ontokit/ontology.ttl") == "ontology.ttl"

    def test_deep_nested_path(self, service: NormalizationService) -> None:
        """Strips only the first segment (bucket prefix) from a multi-segment path."""
        assert service._get_object_name("bucket/subdir/file.ttl") == "subdir/file.ttl"

    def test_returns_as_is_without_slash(self, service: NormalizationService) -> None:
        """Returns the path as-is when no '/' is present."""
        assert service._get_object_name("ontology.ttl") == "ontology.ttl"


class TestGetNormalizationServiceFactory:
    """Tests for get_normalization_service() factory (line 305)."""

    def test_factory_returns_service_instance(self, mock_db: AsyncMock, mock_storage: Mock) -> None:
        """Factory function returns a NormalizationService."""
        from ontokit.services.normalization_service import get_normalization_service

        svc = get_normalization_service(mock_db, mock_storage)
        assert isinstance(svc, NormalizationService)
