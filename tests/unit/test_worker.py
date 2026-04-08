"""Tests for ARQ worker background task functions."""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from ontokit.worker import (
    auto_submit_stale_suggestions,
    check_all_projects_normalization,
    check_normalization_status_task,
    on_job_end,
    on_job_start,
    run_batch_entity_embed_task,
    run_embedding_generation_task,
    run_lint_task,
    run_normalization_task,
    run_ontology_index_task,
    run_remote_check_task,
    run_single_entity_embed_task,
    shutdown,
    startup,
    sync_github_projects,
)


@pytest.fixture
def mock_ctx(mock_db_session: AsyncMock, mock_redis: AsyncMock) -> dict[str, Any]:
    """Create a minimal ARQ context dict with mock db and redis."""
    return {"db": mock_db_session, "redis": mock_redis}


@pytest.fixture
def project_id() -> str:
    """A stable project UUID string for tests."""
    return str(uuid.UUID("12345678-1234-5678-1234-567812345678"))


# ---------------------------------------------------------------------------
# run_ontology_index_task
# ---------------------------------------------------------------------------


class TestRunOntologyIndexTask:
    """Tests for the run_ontology_index_task background function."""

    @pytest.mark.asyncio
    async def test_project_not_found_raises(
        self, mock_ctx: dict[str, Any], project_id: str
    ) -> None:
        """Raises ValueError when the project does not exist in the DB."""
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = None
        mock_ctx["db"].execute.return_value = mock_result

        with pytest.raises(ValueError, match="not found"):
            await run_ontology_index_task(mock_ctx, project_id)

    @pytest.mark.asyncio
    async def test_project_no_source_file_raises(
        self, mock_ctx: dict[str, Any], project_id: str
    ) -> None:
        """Raises ValueError when the project has no source_file_path."""
        project = Mock()
        project.source_file_path = None
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = project
        mock_ctx["db"].execute.return_value = mock_result

        with pytest.raises(ValueError, match="has no ontology file"):
            await run_ontology_index_task(mock_ctx, project_id)

    @pytest.mark.asyncio
    async def test_successful_index_returns_completed(
        self, mock_ctx: dict[str, Any], project_id: str
    ) -> None:
        """Successful indexing returns status=completed with entity_count."""
        project = Mock()
        project.source_file_path = "ontokit/test.ttl"
        project.git_ontology_path = "test.ttl"
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = project
        mock_ctx["db"].execute.return_value = mock_result

        mock_graph = Mock()
        mock_repo = Mock()
        mock_repo.get_branch_commit_hash.return_value = "abc123"

        with (
            patch("ontokit.worker.get_storage_service"),
            patch("ontokit.worker.get_ontology_service") as mock_onto_svc,
            patch("ontokit.worker.BareGitRepositoryService") as mock_git_cls,
            patch("ontokit.services.ontology_index.OntologyIndexService") as mock_idx_cls,
        ):
            mock_git_svc = mock_git_cls.return_value
            mock_git_svc.repository_exists.return_value = True
            mock_git_svc.get_repository.return_value = mock_repo

            onto_svc = mock_onto_svc.return_value
            onto_svc.load_from_git = AsyncMock(return_value=mock_graph)

            idx_svc = mock_idx_cls.return_value
            idx_svc.full_reindex = AsyncMock(return_value=42)

            result = await run_ontology_index_task(mock_ctx, project_id, "main")

        assert result["status"] == "completed"
        assert result["entity_count"] == 42
        assert result["commit_hash"] == "abc123"

    @pytest.mark.asyncio
    async def test_index_publishes_start_and_complete(
        self, mock_ctx: dict[str, Any], project_id: str
    ) -> None:
        """Redis publish is called for both start and complete notifications."""
        project = Mock()
        project.source_file_path = "ontokit/test.ttl"
        project.git_ontology_path = "test.ttl"
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = project
        mock_ctx["db"].execute.return_value = mock_result

        with (
            patch("ontokit.worker.get_storage_service"),
            patch("ontokit.worker.get_ontology_service") as mock_onto_svc,
            patch("ontokit.worker.BareGitRepositoryService") as mock_git_cls,
            patch("ontokit.services.ontology_index.OntologyIndexService") as mock_idx_cls,
        ):
            mock_git_svc = mock_git_cls.return_value
            mock_git_svc.repository_exists.return_value = True
            mock_git_svc.get_repository.return_value = Mock(
                get_branch_commit_hash=Mock(return_value="abc")
            )
            mock_onto_svc.return_value.load_from_git = AsyncMock(return_value=Mock())
            mock_idx_cls.return_value.full_reindex = AsyncMock(return_value=5)

            await run_ontology_index_task(mock_ctx, project_id)

        # At least 2 publish calls: start + complete
        assert mock_ctx["redis"].publish.await_count >= 2

    @pytest.mark.asyncio
    async def test_index_uses_storage_fallback(
        self, mock_ctx: dict[str, Any], project_id: str
    ) -> None:
        """When git repo does not exist, falls back to storage loading."""
        project = Mock()
        project.source_file_path = "ontokit/test.ttl"
        project.git_ontology_path = None
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = project
        mock_ctx["db"].execute.return_value = mock_result

        with (
            patch("ontokit.worker.get_storage_service"),
            patch("ontokit.worker.get_ontology_service") as mock_onto_svc,
            patch("ontokit.worker.BareGitRepositoryService") as mock_git_cls,
            patch("ontokit.services.ontology_index.OntologyIndexService") as mock_idx_cls,
        ):
            mock_git_svc = mock_git_cls.return_value
            mock_git_svc.repository_exists.return_value = False

            onto_svc = mock_onto_svc.return_value
            onto_svc.load_from_storage = AsyncMock(return_value=Mock())
            mock_idx_cls.return_value.full_reindex = AsyncMock(return_value=10)

            result = await run_ontology_index_task(mock_ctx, project_id)

        assert result["commit_hash"] == "storage"
        onto_svc.load_from_storage.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_index_failure_publishes_error(
        self, mock_ctx: dict[str, Any], project_id: str
    ) -> None:
        """On failure, publishes an index_failed message and re-raises."""
        project = Mock()
        project.source_file_path = "ontokit/test.ttl"
        project.git_ontology_path = "test.ttl"
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = project
        mock_ctx["db"].execute.return_value = mock_result

        with (
            patch("ontokit.worker.get_storage_service"),
            patch("ontokit.worker.get_ontology_service") as mock_onto_svc,
            patch("ontokit.worker.BareGitRepositoryService") as mock_git_cls,
        ):
            mock_git_svc = mock_git_cls.return_value
            mock_git_svc.repository_exists.return_value = True
            mock_onto_svc.return_value.load_from_git = AsyncMock(
                side_effect=RuntimeError("parse error")
            )

            with pytest.raises(RuntimeError, match="parse error"):
                await run_ontology_index_task(mock_ctx, project_id)

        # Should have published start + failure
        assert mock_ctx["redis"].publish.await_count >= 2


# ---------------------------------------------------------------------------
# run_lint_task
# ---------------------------------------------------------------------------


class TestRunLintTask:
    """Tests for the run_lint_task background function."""

    @pytest.mark.asyncio
    async def test_lint_project_not_found_raises(
        self, mock_ctx: dict[str, Any], project_id: str
    ) -> None:
        """Raises ValueError when the project does not exist."""
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = None
        mock_ctx["db"].execute.return_value = mock_result

        with pytest.raises(ValueError, match="not found"):
            await run_lint_task(mock_ctx, project_id)

    @pytest.mark.asyncio
    async def test_lint_no_source_file_raises(
        self, mock_ctx: dict[str, Any], project_id: str
    ) -> None:
        """Raises ValueError when the project has no source_file_path."""
        project = Mock()
        project.source_file_path = None
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = project
        mock_ctx["db"].execute.return_value = mock_result

        with pytest.raises(ValueError, match="has no ontology file"):
            await run_lint_task(mock_ctx, project_id)

    @pytest.mark.asyncio
    async def test_lint_success_returns_completed(
        self, mock_ctx: dict[str, Any], project_id: str
    ) -> None:
        """Successful lint returns status=completed with issues count."""
        project = Mock()
        project.source_file_path = "ontokit/test.ttl"

        # First call returns project, subsequent calls are for the LintRun
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = project
        mock_ctx["db"].execute.return_value = mock_result

        mock_run = MagicMock()
        mock_run.id = uuid.uuid4()
        mock_run.status = None
        mock_run.completed_at = None
        mock_run.issues_found = None

        mock_lint_result = Mock()
        mock_lint_result.issue_type = "warning"
        mock_lint_result.rule_id = "R001"
        mock_lint_result.message = "test issue"
        mock_lint_result.subject_iri = "http://example.org/A"
        mock_lint_result.details = None

        with (
            patch("ontokit.worker.get_storage_service"),
            patch("ontokit.worker.get_ontology_service") as mock_onto_svc,
            patch("ontokit.worker.get_linter") as mock_get_linter,
            patch("ontokit.worker.LintRun", return_value=mock_run),
            patch("ontokit.worker.LintIssue"),
        ):
            onto_svc = mock_onto_svc.return_value
            onto_svc.load_from_storage = AsyncMock(return_value=Mock())
            linter = mock_get_linter.return_value
            linter.lint = AsyncMock(return_value=[mock_lint_result])

            result = await run_lint_task(mock_ctx, project_id)

        assert result["status"] == "completed"
        assert result["issues_found"] == 1

    @pytest.mark.asyncio
    async def test_lint_publishes_notifications(
        self, mock_ctx: dict[str, Any], project_id: str
    ) -> None:
        """Lint task publishes start and complete events to Redis."""
        project = Mock()
        project.source_file_path = "ontokit/test.ttl"
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = project
        mock_ctx["db"].execute.return_value = mock_result

        mock_run = MagicMock()
        mock_run.id = uuid.uuid4()

        with (
            patch("ontokit.worker.get_storage_service"),
            patch("ontokit.worker.get_ontology_service") as mock_onto_svc,
            patch("ontokit.worker.get_linter") as mock_get_linter,
            patch("ontokit.worker.LintRun", return_value=mock_run),
        ):
            mock_onto_svc.return_value.load_from_storage = AsyncMock(return_value=Mock())
            mock_get_linter.return_value.lint = AsyncMock(return_value=[])

            await run_lint_task(mock_ctx, project_id)

        assert mock_ctx["redis"].publish.await_count >= 2


# ---------------------------------------------------------------------------
# Lifecycle hooks
# ---------------------------------------------------------------------------


class TestStartupShutdown:
    """Tests for worker startup and shutdown hooks."""

    @pytest.mark.asyncio
    async def test_startup_creates_engine_and_factory(self) -> None:
        """startup populates ctx with engine and session_factory."""
        ctx: dict[str, Any] = {}
        with patch("ontokit.worker.create_async_engine") as mock_engine_fn:
            mock_engine = Mock()
            mock_engine_fn.return_value = mock_engine

            with patch("ontokit.worker.async_sessionmaker") as mock_factory_fn:
                mock_factory = Mock()
                mock_factory_fn.return_value = mock_factory

                await startup(ctx)

        assert ctx["engine"] is mock_engine
        assert ctx["session_factory"] is mock_factory

    @pytest.mark.asyncio
    async def test_shutdown_disposes_engine(self) -> None:
        """shutdown calls engine.dispose()."""
        mock_engine = AsyncMock()
        ctx: dict[str, Any] = {"engine": mock_engine}
        await shutdown(ctx)
        mock_engine.dispose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_shutdown_without_engine(self) -> None:
        """shutdown is a no-op when engine is missing from ctx."""
        ctx: dict[str, Any] = {}
        await shutdown(ctx)  # should not raise


class TestJobLifecycle:
    """Tests for on_job_start and on_job_end hooks."""

    @pytest.mark.asyncio
    async def test_on_job_start_creates_session(self) -> None:
        """on_job_start creates a db session from the factory."""
        mock_session = Mock()
        mock_factory = Mock(return_value=mock_session)
        ctx: dict[str, Any] = {"session_factory": mock_factory}

        await on_job_start(ctx)

        assert ctx["db"] is mock_session
        mock_factory.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_job_end_closes_session(self) -> None:
        """on_job_end closes the db session."""
        mock_session = AsyncMock()
        ctx: dict[str, Any] = {"db": mock_session}

        await on_job_end(ctx)

        mock_session.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_on_job_end_without_session(self) -> None:
        """on_job_end is a no-op when db is missing from ctx."""
        ctx: dict[str, Any] = {}
        await on_job_end(ctx)  # should not raise


# ---------------------------------------------------------------------------
# run_normalization_task
# ---------------------------------------------------------------------------


class TestRunNormalizationTask:
    """Tests for the run_normalization_task background function."""

    @pytest.mark.asyncio
    async def test_normalization_success(self, mock_ctx: dict[str, Any], project_id: str) -> None:
        """Successful normalization returns status=completed."""
        project = Mock()
        project.source_file_path = "ontokit/test.ttl"
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = project
        mock_ctx["db"].execute.return_value = mock_result

        mock_run = MagicMock()
        mock_run.id = uuid.uuid4()
        mock_run.commit_hash = "abc123"

        with (
            patch("ontokit.worker.get_storage_service"),
            patch("ontokit.worker.NormalizationService") as mock_norm_cls,
        ):
            norm_svc = mock_norm_cls.return_value
            norm_svc.run_normalization = AsyncMock(
                return_value=(mock_run, b"original", b"normalized")
            )

            result = await run_normalization_task(
                mock_ctx, project_id, user_id="user-1", user_name="Test", user_email="t@t.com"
            )

        assert result["status"] == "completed"
        assert result["run_id"] == str(mock_run.id)

    @pytest.mark.asyncio
    async def test_normalization_project_not_found(
        self, mock_ctx: dict[str, Any], project_id: str
    ) -> None:
        """Returns status=failed when project not found."""
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = None
        mock_ctx["db"].execute.return_value = mock_result

        result = await run_normalization_task(mock_ctx, project_id)

        assert result["status"] == "failed"
        assert "not found" in result["error"]


# ---------------------------------------------------------------------------
# check_normalization_status_task
# ---------------------------------------------------------------------------


class TestCheckNormalizationStatusTask:
    """Tests for the check_normalization_status_task background function."""

    @pytest.mark.asyncio
    async def test_check_normalization_success(
        self, mock_ctx: dict[str, Any], project_id: str
    ) -> None:
        """Returns needs_normalization status when check succeeds."""
        project = Mock()
        project.source_file_path = "ontokit/test.ttl"
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = project
        mock_ctx["db"].execute.return_value = mock_result

        with (
            patch("ontokit.worker.get_storage_service"),
            patch("ontokit.worker.NormalizationService") as mock_norm_cls,
        ):
            norm_svc = mock_norm_cls.return_value
            norm_svc.check_normalization_status = AsyncMock(
                return_value={"needs_normalization": True, "last_run": None}
            )

            result = await check_normalization_status_task(mock_ctx, project_id)

        assert result["needs_normalization"] is True

    @pytest.mark.asyncio
    async def test_check_normalization_project_not_found(
        self, mock_ctx: dict[str, Any], project_id: str
    ) -> None:
        """Returns needs_normalization=False when project not found."""
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = None
        mock_ctx["db"].execute.return_value = mock_result

        result = await check_normalization_status_task(mock_ctx, project_id)

        assert result["needs_normalization"] is False
        assert "not found" in result.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_check_normalization_no_source_file(
        self, mock_ctx: dict[str, Any], project_id: str
    ) -> None:
        """Returns needs_normalization=False when project has no source file."""
        project = Mock()
        project.source_file_path = None
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = project
        mock_ctx["db"].execute.return_value = mock_result

        result = await check_normalization_status_task(mock_ctx, project_id)

        assert result["needs_normalization"] is False


# ---------------------------------------------------------------------------
# run_remote_check_task
# ---------------------------------------------------------------------------


class TestRunRemoteCheckTask:
    """Tests for the run_remote_check_task background function."""

    @pytest.mark.asyncio
    async def test_remote_check_no_sync_config(
        self, mock_ctx: dict[str, Any], project_id: str
    ) -> None:
        """Returns failed when no remote sync config exists."""
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = None
        mock_ctx["db"].execute.return_value = mock_result

        result = await run_remote_check_task(mock_ctx, project_id)

        assert result["status"] == "failed"
        assert "not configured" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_remote_check_success_with_changes(
        self, mock_ctx: dict[str, Any], project_id: str
    ) -> None:
        """Returns has_changes=True when remote differs from local."""
        mock_config = MagicMock()
        mock_config.id = uuid.uuid4()
        mock_config.repo_owner = "owner"
        mock_config.repo_name = "repo"
        mock_config.file_path = "ontology.ttl"
        mock_config.branch = "main"
        mock_config.status = "idle"

        mock_project = MagicMock()
        mock_project.source_file_path = "projects/123/ontology.ttl"

        mock_integration = MagicMock()
        mock_integration.connected_by_user_id = "user-1"

        mock_token_row = MagicMock()
        mock_token_row.encrypted_token = "encrypted"

        # Sequence of execute calls
        mock_config_result = Mock()
        mock_config_result.scalar_one_or_none.return_value = mock_config
        mock_project_result = Mock()
        mock_project_result.scalar_one_or_none.return_value = mock_project
        mock_integration_result = Mock()
        mock_integration_result.scalar_one_or_none.return_value = mock_integration
        mock_token_result = Mock()
        mock_token_result.scalar_one_or_none.return_value = mock_token_row

        mock_ctx["db"].execute.side_effect = [
            mock_config_result,
            mock_project_result,
            mock_integration_result,
            mock_token_result,
        ]

        with (
            patch("ontokit.worker.decrypt_token", return_value="decrypted-pat"),
            patch("ontokit.worker.get_storage_service") as mock_storage_fn,
            patch("ontokit.services.github_service.get_github_service") as mock_gh_fn,
        ):
            mock_storage = MagicMock()
            mock_storage.bucket = "projects"
            mock_storage.download_file = AsyncMock(return_value=b"old content")
            mock_storage_fn.return_value = mock_storage

            mock_gh_svc = MagicMock()
            mock_gh_svc.get_file_content = AsyncMock(return_value=b"new content")
            mock_gh_fn.return_value = mock_gh_svc

            result = await run_remote_check_task(mock_ctx, project_id)

        assert result["status"] == "completed"
        assert result["has_changes"] is True


# ---------------------------------------------------------------------------
# run_embedding_generation_task
# ---------------------------------------------------------------------------


class TestRunEmbeddingGenerationTask:
    """Tests for the run_embedding_generation_task background function."""

    @pytest.mark.asyncio
    async def test_embedding_generation_success(
        self, mock_ctx: dict[str, Any], project_id: str
    ) -> None:
        """Successful embedding generation returns status=completed."""
        job_id = str(uuid.uuid4())

        with patch("ontokit.services.embedding_service.EmbeddingService") as mock_cls:
            mock_svc = mock_cls.return_value
            mock_svc.embed_project = AsyncMock()

            result = await run_embedding_generation_task(mock_ctx, project_id, "main", job_id)

        assert result["status"] == "completed"
        assert result["project_id"] == project_id
        assert result["branch"] == "main"
        assert result["job_id"] == job_id

    @pytest.mark.asyncio
    async def test_embedding_generation_failure(
        self, mock_ctx: dict[str, Any], project_id: str
    ) -> None:
        """Embedding generation failure re-raises the exception."""
        job_id = str(uuid.uuid4())

        with patch("ontokit.services.embedding_service.EmbeddingService") as mock_cls:
            mock_svc = mock_cls.return_value
            mock_svc.embed_project = AsyncMock(side_effect=RuntimeError("embed failed"))

            with pytest.raises(RuntimeError, match="embed failed"):
                await run_embedding_generation_task(mock_ctx, project_id, "main", job_id)


# ---------------------------------------------------------------------------
# sync_github_projects
# ---------------------------------------------------------------------------


class TestSyncGithubProjects:
    """Tests for the sync_github_projects cron function."""

    @pytest.mark.asyncio
    async def test_sync_no_integrations(self, mock_ctx: dict[str, Any]) -> None:
        """Returns zeroes when no integrations exist."""
        mock_result = Mock()
        mock_result.scalars.return_value.all.return_value = []
        mock_ctx["db"].execute.return_value = mock_result

        with patch("ontokit.worker.BareGitRepositoryService"):
            result = await sync_github_projects(mock_ctx)

        assert result["total"] == 0
        assert result["synced"] == 0
        assert result["errors"] == 0

    @pytest.mark.asyncio
    async def test_sync_skips_integration_without_connected_user(
        self, mock_ctx: dict[str, Any]
    ) -> None:
        """Skips integrations that have no connected_by_user_id."""
        integration = MagicMock()
        integration.project_id = uuid.uuid4()
        integration.connected_by_user_id = None

        mock_result = Mock()
        mock_result.scalars.return_value.all.return_value = [integration]
        mock_ctx["db"].execute.return_value = mock_result

        with patch("ontokit.worker.BareGitRepositoryService"):
            result = await sync_github_projects(mock_ctx)

        assert result["total"] == 1
        assert result["synced"] == 0
        assert result["errors"] == 0

    @pytest.mark.asyncio
    async def test_sync_skips_when_no_token_row(self, mock_ctx: dict[str, Any]) -> None:
        """Skips integrations when user has no GitHub token stored."""
        integration = MagicMock()
        integration.project_id = uuid.uuid4()
        integration.connected_by_user_id = "user-1"

        mock_integrations_result = Mock()
        mock_integrations_result.scalars.return_value.all.return_value = [integration]

        # Second execute returns no token row
        mock_token_result = Mock()
        mock_token_result.scalar_one_or_none.return_value = None

        mock_ctx["db"].execute.side_effect = [mock_integrations_result, mock_token_result]

        with patch("ontokit.worker.BareGitRepositoryService"):
            result = await sync_github_projects(mock_ctx)

        assert result["total"] == 1
        assert result["synced"] == 0

    @pytest.mark.asyncio
    async def test_sync_skips_when_decrypt_fails(self, mock_ctx: dict[str, Any]) -> None:
        """Skips integrations when token decryption fails."""
        integration = MagicMock()
        integration.project_id = uuid.uuid4()
        integration.connected_by_user_id = "user-1"

        mock_integrations_result = Mock()
        mock_integrations_result.scalars.return_value.all.return_value = [integration]

        mock_token_row = MagicMock()
        mock_token_row.encrypted_token = "bad-token"
        mock_token_result = Mock()
        mock_token_result.scalar_one_or_none.return_value = mock_token_row

        mock_ctx["db"].execute.side_effect = [mock_integrations_result, mock_token_result]

        with (
            patch("ontokit.worker.BareGitRepositoryService"),
            patch("ontokit.worker.decrypt_token", side_effect=RuntimeError("decrypt failed")),
        ):
            result = await sync_github_projects(mock_ctx)

        assert result["total"] == 1
        assert result["synced"] == 0

    @pytest.mark.asyncio
    async def test_sync_successful_sync(self, mock_ctx: dict[str, Any]) -> None:
        """Successfully syncs a project and increments synced count."""
        integration = MagicMock()
        integration.project_id = uuid.uuid4()
        integration.connected_by_user_id = "user-1"

        mock_integrations_result = Mock()
        mock_integrations_result.scalars.return_value.all.return_value = [integration]

        mock_token_row = MagicMock()
        mock_token_row.encrypted_token = "encrypted"
        mock_token_result = Mock()
        mock_token_result.scalar_one_or_none.return_value = mock_token_row

        mock_ctx["db"].execute.side_effect = [mock_integrations_result, mock_token_result]

        with (
            patch("ontokit.worker.BareGitRepositoryService"),
            patch("ontokit.worker.decrypt_token", return_value="pat-123"),
            patch("ontokit.worker.sync_github_project", new_callable=AsyncMock) as mock_sync,
        ):
            mock_sync.return_value = {"status": "ok"}
            result = await sync_github_projects(mock_ctx)

        assert result["total"] == 1
        assert result["synced"] == 1
        assert result["errors"] == 0

    @pytest.mark.asyncio
    async def test_sync_counts_errors_on_sync_failure(self, mock_ctx: dict[str, Any]) -> None:
        """Counts errors when sync_github_project raises."""
        integration = MagicMock()
        integration.project_id = uuid.uuid4()
        integration.connected_by_user_id = "user-1"

        mock_integrations_result = Mock()
        mock_integrations_result.scalars.return_value.all.return_value = [integration]

        mock_token_row = MagicMock()
        mock_token_row.encrypted_token = "encrypted"
        mock_token_result = Mock()
        mock_token_result.scalar_one_or_none.return_value = mock_token_row

        mock_ctx["db"].execute.side_effect = [mock_integrations_result, mock_token_result]

        with (
            patch("ontokit.worker.BareGitRepositoryService"),
            patch("ontokit.worker.decrypt_token", return_value="pat-123"),
            patch(
                "ontokit.worker.sync_github_project",
                new_callable=AsyncMock,
                side_effect=RuntimeError("sync boom"),
            ),
        ):
            result = await sync_github_projects(mock_ctx)

        assert result["errors"] == 1
        assert result["synced"] == 0

    @pytest.mark.asyncio
    async def test_sync_outer_exception_reraises(self, mock_ctx: dict[str, Any]) -> None:
        """Re-raises when the outer try block fails (e.g. DB query fails)."""
        mock_ctx["db"].execute.side_effect = RuntimeError("db down")

        with pytest.raises(RuntimeError, match="db down"):
            await sync_github_projects(mock_ctx)


# ---------------------------------------------------------------------------
# check_all_projects_normalization
# ---------------------------------------------------------------------------


class TestCheckAllProjectsNormalization:
    """Tests for the check_all_projects_normalization cron function."""

    @pytest.mark.asyncio
    async def test_check_all_no_projects(self, mock_ctx: dict[str, Any]) -> None:
        """Returns zero counts when no projects have ontology files."""
        mock_result = Mock()
        mock_result.scalars.return_value.all.return_value = []
        mock_ctx["db"].execute.return_value = mock_result

        with (
            patch("ontokit.worker.get_storage_service"),
            patch("ontokit.worker.NormalizationService"),
        ):
            result = await check_all_projects_normalization(mock_ctx)

        assert result["total_projects"] == 0
        assert result["projects_needing_normalization"] == 0

    @pytest.mark.asyncio
    async def test_check_all_finds_projects_needing_normalization(
        self, mock_ctx: dict[str, Any]
    ) -> None:
        """Identifies projects needing normalization and publishes updates."""
        project1 = MagicMock()
        project1.id = uuid.uuid4()
        project2 = MagicMock()
        project2.id = uuid.uuid4()

        mock_result = Mock()
        mock_result.scalars.return_value.all.return_value = [project1, project2]
        mock_ctx["db"].execute.return_value = mock_result

        with (
            patch("ontokit.worker.get_storage_service"),
            patch("ontokit.worker.NormalizationService") as mock_norm_cls,
        ):
            norm_svc = mock_norm_cls.return_value
            norm_svc.check_normalization_status = AsyncMock(
                side_effect=[
                    {"needs_normalization": True, "last_run": None},
                    {"needs_normalization": False, "last_run": None},
                ]
            )

            result = await check_all_projects_normalization(mock_ctx)

        assert result["total_projects"] == 2
        assert result["projects_needing_normalization"] == 1
        # Publishes for the project that needs normalization
        mock_ctx["redis"].publish.assert_awaited()

    @pytest.mark.asyncio
    async def test_check_all_handles_per_project_error(self, mock_ctx: dict[str, Any]) -> None:
        """Continues checking other projects when one fails."""
        project1 = MagicMock()
        project1.id = uuid.uuid4()
        project2 = MagicMock()
        project2.id = uuid.uuid4()

        mock_result = Mock()
        mock_result.scalars.return_value.all.return_value = [project1, project2]
        mock_ctx["db"].execute.return_value = mock_result

        with (
            patch("ontokit.worker.get_storage_service"),
            patch("ontokit.worker.NormalizationService") as mock_norm_cls,
        ):
            norm_svc = mock_norm_cls.return_value
            norm_svc.check_normalization_status = AsyncMock(
                side_effect=[
                    RuntimeError("check failed"),
                    {"needs_normalization": False, "last_run": None},
                ]
            )

            result = await check_all_projects_normalization(mock_ctx)

        # First project errored but second was processed
        assert result["total_projects"] == 2
        assert result["projects_needing_normalization"] == 0

    @pytest.mark.asyncio
    async def test_check_all_outer_exception_reraises(self, mock_ctx: dict[str, Any]) -> None:
        """Re-raises when the outer try block fails."""
        mock_ctx["db"].execute.side_effect = RuntimeError("db down")

        with pytest.raises(RuntimeError, match="db down"):
            await check_all_projects_normalization(mock_ctx)


# ---------------------------------------------------------------------------
# auto_submit_stale_suggestions
# ---------------------------------------------------------------------------


class TestAutoSubmitStaleSuggestions:
    """Tests for the auto_submit_stale_suggestions cron function."""

    @pytest.mark.asyncio
    async def test_auto_submit_success(self, mock_ctx: dict[str, Any]) -> None:
        """Returns count of auto-submitted sessions."""
        with patch("ontokit.services.suggestion_service.SuggestionService") as mock_cls:
            mock_svc = mock_cls.return_value
            mock_svc.auto_submit_stale_sessions = AsyncMock(return_value=3)

            result = await auto_submit_stale_suggestions(mock_ctx)

        assert result["auto_submitted"] == 3

    @pytest.mark.asyncio
    async def test_auto_submit_failure_reraises(self, mock_ctx: dict[str, Any]) -> None:
        """Re-raises when the suggestion service fails."""
        with patch("ontokit.services.suggestion_service.SuggestionService") as mock_cls:
            mock_svc = mock_cls.return_value
            mock_svc.auto_submit_stale_sessions = AsyncMock(
                side_effect=RuntimeError("submit failed")
            )

            with pytest.raises(RuntimeError, match="submit failed"):
                await auto_submit_stale_suggestions(mock_ctx)


# ---------------------------------------------------------------------------
# run_single_entity_embed_task
# ---------------------------------------------------------------------------


class TestRunSingleEntityEmbedTask:
    """Tests for the run_single_entity_embed_task background function."""

    @pytest.mark.asyncio
    async def test_single_embed_success(self, mock_ctx: dict[str, Any], project_id: str) -> None:
        """Successful single entity embed returns status=completed."""
        with patch("ontokit.services.embedding_service.EmbeddingService") as mock_cls:
            mock_svc = mock_cls.return_value
            mock_svc.embed_single_entity = AsyncMock()

            result = await run_single_entity_embed_task(
                mock_ctx, project_id, "main", "http://example.org/Entity1"
            )

        assert result["status"] == "completed"
        assert result["entity_iri"] == "http://example.org/Entity1"

    @pytest.mark.asyncio
    async def test_single_embed_failure_reraises(
        self, mock_ctx: dict[str, Any], project_id: str
    ) -> None:
        """Re-raises when embedding fails."""
        with patch("ontokit.services.embedding_service.EmbeddingService") as mock_cls:
            mock_svc = mock_cls.return_value
            mock_svc.embed_single_entity = AsyncMock(side_effect=RuntimeError("embed err"))

            with pytest.raises(RuntimeError, match="embed err"):
                await run_single_entity_embed_task(
                    mock_ctx, project_id, "main", "http://example.org/Entity1"
                )


# ---------------------------------------------------------------------------
# run_batch_entity_embed_task
# ---------------------------------------------------------------------------


class TestRunBatchEntityEmbedTask:
    """Tests for the run_batch_entity_embed_task background function."""

    @pytest.mark.asyncio
    async def test_batch_embed_success(self, mock_ctx: dict[str, Any], project_id: str) -> None:
        """Successful batch embed returns entity_count and status=completed."""
        iris = ["http://example.org/A", "http://example.org/B"]

        with patch("ontokit.services.embedding_service.EmbeddingService") as mock_cls:
            mock_svc = mock_cls.return_value
            mock_svc.embed_single_entity = AsyncMock()

            result = await run_batch_entity_embed_task(mock_ctx, project_id, "main", iris)

        assert result["status"] == "completed"
        assert result["entity_count"] == 2
        assert mock_svc.embed_single_entity.await_count == 2

    @pytest.mark.asyncio
    async def test_batch_embed_failure_reraises(
        self, mock_ctx: dict[str, Any], project_id: str
    ) -> None:
        """Re-raises when batch embedding fails."""
        with patch("ontokit.services.embedding_service.EmbeddingService") as mock_cls:
            mock_svc = mock_cls.return_value
            mock_svc.embed_single_entity = AsyncMock(side_effect=RuntimeError("batch err"))

            with pytest.raises(RuntimeError, match="batch err"):
                await run_batch_entity_embed_task(
                    mock_ctx, project_id, "main", ["http://example.org/A"]
                )


# ---------------------------------------------------------------------------
# run_ontology_index_task – additional edge cases
# ---------------------------------------------------------------------------


class TestRunOntologyIndexTaskEdgeCases:
    """Additional edge cases for run_ontology_index_task."""

    @pytest.mark.asyncio
    async def test_commit_hash_unknown_on_git_error(
        self, mock_ctx: dict[str, Any], project_id: str
    ) -> None:
        """Falls back to commit_hash='unknown' when get_branch_commit_hash raises."""
        project = Mock()
        project.source_file_path = "ontokit/test.ttl"
        project.git_ontology_path = "test.ttl"
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = project
        mock_ctx["db"].execute.return_value = mock_result

        with (
            patch("ontokit.worker.get_storage_service"),
            patch("ontokit.worker.get_ontology_service") as mock_onto_svc,
            patch("ontokit.worker.BareGitRepositoryService") as mock_git_cls,
            patch("ontokit.services.ontology_index.OntologyIndexService") as mock_idx_cls,
        ):
            mock_git_svc = mock_git_cls.return_value
            mock_git_svc.repository_exists.return_value = True
            mock_repo = Mock()
            mock_repo.get_branch_commit_hash.side_effect = RuntimeError("ref not found")
            mock_git_svc.get_repository.return_value = mock_repo

            mock_onto_svc.return_value.load_from_git = AsyncMock(return_value=Mock())
            mock_idx_cls.return_value.full_reindex = AsyncMock(return_value=7)

            result = await run_ontology_index_task(mock_ctx, project_id, "main")

        assert result["commit_hash"] == "unknown"


# ---------------------------------------------------------------------------
# run_lint_task – failure path
# ---------------------------------------------------------------------------


class TestRunLintTaskFailure:
    """Tests for the run_lint_task failure/exception path."""

    @pytest.mark.asyncio
    async def test_lint_failure_updates_run_and_publishes(
        self, mock_ctx: dict[str, Any], project_id: str
    ) -> None:
        """When lint fails after run creation, updates status to FAILED and publishes error."""
        project = Mock()
        project.source_file_path = "ontokit/test.ttl"
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = project
        mock_ctx["db"].execute.return_value = mock_result

        mock_run = MagicMock()
        mock_run.id = uuid.uuid4()
        mock_run.status = None
        mock_run.completed_at = None
        mock_run.error_message = None

        with (
            patch("ontokit.worker.get_storage_service"),
            patch("ontokit.worker.get_ontology_service") as mock_onto_svc,
            patch("ontokit.worker.LintRun", return_value=mock_run),
        ):
            mock_onto_svc.return_value.load_from_storage = AsyncMock(
                side_effect=RuntimeError("parse error")
            )

            with pytest.raises(RuntimeError, match="parse error"):
                await run_lint_task(mock_ctx, project_id)

        # Run status should be set to FAILED
        assert mock_run.status == "failed"
        assert mock_run.error_message == "parse error"
        # Published: start + failed
        assert mock_ctx["redis"].publish.await_count >= 2


# ---------------------------------------------------------------------------
# check_normalization_status_task – exception path
# ---------------------------------------------------------------------------


class TestCheckNormalizationStatusTaskException:
    """Tests for exception handling in check_normalization_status_task."""

    @pytest.mark.asyncio
    async def test_check_normalization_exception_returns_error(
        self, mock_ctx: dict[str, Any], project_id: str
    ) -> None:
        """Returns error dict when normalization check raises an exception."""
        project = Mock()
        project.source_file_path = "ontokit/test.ttl"
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = project
        mock_ctx["db"].execute.return_value = mock_result

        with (
            patch("ontokit.worker.get_storage_service"),
            patch("ontokit.worker.NormalizationService") as mock_norm_cls,
        ):
            norm_svc = mock_norm_cls.return_value
            norm_svc.check_normalization_status = AsyncMock(side_effect=RuntimeError("check boom"))

            result = await check_normalization_status_task(mock_ctx, project_id)

        assert result["needs_normalization"] is False
        assert "check boom" in result["error"]


# ---------------------------------------------------------------------------
# run_normalization_task – no source file
# ---------------------------------------------------------------------------


class TestRunNormalizationTaskNoSourceFile:
    """Tests for run_normalization_task when project has no source file."""

    @pytest.mark.asyncio
    async def test_normalization_no_source_file(
        self, mock_ctx: dict[str, Any], project_id: str
    ) -> None:
        """Returns status=failed when project has no source_file_path."""
        project = Mock()
        project.source_file_path = None
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = project
        mock_ctx["db"].execute.return_value = mock_result

        result = await run_normalization_task(mock_ctx, project_id)

        assert result["status"] == "failed"
        assert "no ontology file" in result["error"].lower()


# ---------------------------------------------------------------------------
# run_remote_check_task – additional paths
# ---------------------------------------------------------------------------


class TestRunRemoteCheckTaskAdditional:
    """Additional tests for run_remote_check_task covering uncovered paths."""

    @pytest.mark.asyncio
    async def test_remote_check_project_not_found(
        self, mock_ctx: dict[str, Any], project_id: str
    ) -> None:
        """Returns failed when project not found (config exists but project doesn't)."""
        mock_config = MagicMock()
        mock_config.id = uuid.uuid4()

        mock_config_result = Mock()
        mock_config_result.scalar_one_or_none.return_value = mock_config
        mock_project_result = Mock()
        mock_project_result.scalar_one_or_none.return_value = None

        mock_ctx["db"].execute.side_effect = [mock_config_result, mock_project_result]

        result = await run_remote_check_task(mock_ctx, project_id)

        assert result["status"] == "failed"
        assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_remote_check_no_token_available(
        self, mock_ctx: dict[str, Any], project_id: str
    ) -> None:
        """Returns failed when no GitHub token is available."""
        mock_config = MagicMock()
        mock_config.id = uuid.uuid4()
        mock_config.status = "idle"

        mock_project = MagicMock()
        mock_project.source_file_path = "test.ttl"

        # Integration exists but no token
        mock_integration = MagicMock()
        mock_integration.connected_by_user_id = "user-1"

        mock_config_result = Mock()
        mock_config_result.scalar_one_or_none.return_value = mock_config
        mock_project_result = Mock()
        mock_project_result.scalar_one_or_none.return_value = mock_project
        mock_integration_result = Mock()
        mock_integration_result.scalar_one_or_none.return_value = mock_integration
        mock_token_result = Mock()
        mock_token_result.scalar_one_or_none.return_value = None

        mock_ctx["db"].execute.side_effect = [
            mock_config_result,
            mock_project_result,
            mock_integration_result,
            mock_token_result,
        ]

        with patch("ontokit.worker.get_storage_service"):
            result = await run_remote_check_task(mock_ctx, project_id)

        assert result["status"] == "failed"
        assert "no github token" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_remote_check_no_changes(self, mock_ctx: dict[str, Any], project_id: str) -> None:
        """Returns has_changes=False when remote matches local."""
        mock_config = MagicMock()
        mock_config.id = uuid.uuid4()
        mock_config.repo_owner = "owner"
        mock_config.repo_name = "repo"
        mock_config.file_path = "ontology.ttl"
        mock_config.branch = "main"
        mock_config.status = "idle"

        mock_project = MagicMock()
        mock_project.source_file_path = "projects/123/ontology.ttl"

        mock_integration = MagicMock()
        mock_integration.connected_by_user_id = "user-1"

        mock_token_row = MagicMock()
        mock_token_row.encrypted_token = "encrypted"

        mock_config_result = Mock()
        mock_config_result.scalar_one_or_none.return_value = mock_config
        mock_project_result = Mock()
        mock_project_result.scalar_one_or_none.return_value = mock_project
        mock_integration_result = Mock()
        mock_integration_result.scalar_one_or_none.return_value = mock_integration
        mock_token_result = Mock()
        mock_token_result.scalar_one_or_none.return_value = mock_token_row

        mock_ctx["db"].execute.side_effect = [
            mock_config_result,
            mock_project_result,
            mock_integration_result,
            mock_token_result,
        ]

        same_content = b"identical content"

        with (
            patch("ontokit.worker.decrypt_token", return_value="decrypted-pat"),
            patch("ontokit.worker.get_storage_service") as mock_storage_fn,
            patch("ontokit.services.github_service.get_github_service") as mock_gh_fn,
        ):
            mock_storage = MagicMock()
            mock_storage.bucket = "projects"
            mock_storage.download_file = AsyncMock(return_value=same_content)
            mock_storage_fn.return_value = mock_storage

            mock_gh_svc = MagicMock()
            mock_gh_svc.get_file_content = AsyncMock(return_value=same_content)
            mock_gh_fn.return_value = mock_gh_svc

            result = await run_remote_check_task(mock_ctx, project_id)

        assert result["status"] == "completed"
        assert result["has_changes"] is False
        assert result["event_type"] == "check_no_changes"

    @pytest.mark.asyncio
    async def test_remote_check_storage_download_fails(
        self, mock_ctx: dict[str, Any], project_id: str
    ) -> None:
        """Treats content as changed when storage download fails."""
        mock_config = MagicMock()
        mock_config.id = uuid.uuid4()
        mock_config.repo_owner = "owner"
        mock_config.repo_name = "repo"
        mock_config.file_path = "ontology.ttl"
        mock_config.branch = "main"
        mock_config.status = "idle"

        mock_project = MagicMock()
        mock_project.source_file_path = "bucket/path/ontology.ttl"

        mock_integration = MagicMock()
        mock_integration.connected_by_user_id = "user-1"

        mock_token_row = MagicMock()
        mock_token_row.encrypted_token = "encrypted"

        mock_config_result = Mock()
        mock_config_result.scalar_one_or_none.return_value = mock_config
        mock_project_result = Mock()
        mock_project_result.scalar_one_or_none.return_value = mock_project
        mock_integration_result = Mock()
        mock_integration_result.scalar_one_or_none.return_value = mock_integration
        mock_token_result = Mock()
        mock_token_result.scalar_one_or_none.return_value = mock_token_row

        mock_ctx["db"].execute.side_effect = [
            mock_config_result,
            mock_project_result,
            mock_integration_result,
            mock_token_result,
        ]

        with (
            patch("ontokit.worker.decrypt_token", return_value="decrypted-pat"),
            patch("ontokit.worker.get_storage_service") as mock_storage_fn,
            patch("ontokit.services.github_service.get_github_service") as mock_gh_fn,
        ):
            mock_storage = MagicMock()
            mock_storage.bucket = "bucket"
            mock_storage.download_file = AsyncMock(side_effect=RuntimeError("download err"))
            mock_storage_fn.return_value = mock_storage

            mock_gh_svc = MagicMock()
            mock_gh_svc.get_file_content = AsyncMock(return_value=b"remote content")
            mock_gh_fn.return_value = mock_gh_svc

            result = await run_remote_check_task(mock_ctx, project_id)

        # current_content is None due to download failure, so has_changes=True
        assert result["status"] == "completed"
        assert result["has_changes"] is True

    @pytest.mark.asyncio
    async def test_remote_check_exception_records_error_event(
        self, mock_ctx: dict[str, Any], project_id: str
    ) -> None:
        """Records error event and publishes failure when remote check raises."""
        mock_config = MagicMock()
        mock_config.id = uuid.uuid4()
        mock_config.status = "idle"
        mock_config.error_message = None

        mock_project = MagicMock()
        mock_project.source_file_path = "test.ttl"

        # No integration found
        mock_integration = MagicMock()
        mock_integration.connected_by_user_id = "user-1"

        mock_token_row = MagicMock()
        mock_token_row.encrypted_token = "encrypted"

        mock_config_result = Mock()
        mock_config_result.scalar_one_or_none.return_value = mock_config
        mock_project_result = Mock()
        mock_project_result.scalar_one_or_none.return_value = mock_project
        mock_integration_result = Mock()
        mock_integration_result.scalar_one_or_none.return_value = mock_integration
        mock_token_result = Mock()
        mock_token_result.scalar_one_or_none.return_value = mock_token_row

        # For the error handler: re-fetch config
        mock_err_config_result = Mock()
        mock_err_config_result.scalar_one_or_none.return_value = mock_config

        mock_ctx["db"].execute.side_effect = [
            mock_config_result,
            mock_project_result,
            mock_integration_result,
            mock_token_result,
            mock_err_config_result,  # error handler re-fetches config
        ]

        with (
            patch("ontokit.worker.decrypt_token", return_value="pat"),
            patch("ontokit.worker.get_storage_service") as mock_storage_fn,
            patch(
                "ontokit.services.github_service.get_github_service",
            ) as mock_gh_fn,
        ):
            mock_storage_fn.return_value = MagicMock()
            mock_gh_svc = MagicMock()
            mock_gh_svc.get_file_content = AsyncMock(side_effect=RuntimeError("github api error"))
            mock_gh_fn.return_value = mock_gh_svc

            with pytest.raises(RuntimeError, match="github api error"):
                await run_remote_check_task(mock_ctx, project_id)

        # Config status should be set to error
        assert mock_config.status == "error"
        assert mock_config.error_message == "github api error"
        # Published: start + failed
        assert mock_ctx["redis"].publish.await_count >= 2
