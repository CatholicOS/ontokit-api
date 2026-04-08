"""Tests for EmbeddingService (ontokit/services/embedding_service.py)."""

# ruff: noqa: ARG002

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
    session.rollback = AsyncMock()
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
        added = mock_db.add.call_args[0][0]
        assert added.auto_embed_on_save is True
        assert added.project_id == PROJECT_ID
        mock_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_updates_existing_config(
        self, service: EmbeddingService, mock_db: AsyncMock
    ) -> None:
        """Updates an existing ProjectEmbeddingConfig without calling db.add."""
        existing = _make_config_row(provider="local", auto_embed_on_save=False)
        result = MagicMock()
        result.scalar_one_or_none.return_value = existing
        mock_db.execute.return_value = result

        update = MagicMock()
        update.provider = None
        update.model_name = None
        update.dimensions = None
        update.api_key = None
        update.auto_embed_on_save = True

        await service.update_config(PROJECT_ID, update)
        mock_db.add.assert_not_called()
        mock_db.commit.assert_awaited_once()
        assert existing.auto_embed_on_save is True


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


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


class TestHelperUtilities:
    """Tests for module-level helper functions."""

    def test_get_fernet(self) -> None:
        """_get_fernet returns a Fernet instance derived from settings.secret_key."""
        from unittest.mock import patch

        from ontokit.services.embedding_service import _get_fernet

        mock_settings = MagicMock()
        mock_settings.secret_key = "test-secret-key-for-unit-tests"

        with patch("ontokit.core.config.settings", mock_settings):
            fernet = _get_fernet()
            assert fernet is not None

    def test_encrypt_and_decrypt_round_trip(self) -> None:
        """Encrypting then decrypting a secret returns the original plaintext."""
        from unittest.mock import patch

        from ontokit.services.embedding_service import _decrypt_secret, _encrypt_secret

        mock_settings = MagicMock()
        mock_settings.secret_key = "test-secret-key-for-unit-tests"

        with patch("ontokit.core.config.settings", mock_settings):
            plaintext = "my-api-key-12345"
            encrypted = _encrypt_secret(plaintext)
            assert encrypted != plaintext
            decrypted = _decrypt_secret(encrypted)
            assert decrypted == plaintext

    def test_vec_to_str(self) -> None:
        """_vec_to_str converts a list of floats to a string."""
        from ontokit.services.embedding_service import _vec_to_str

        vec = [0.1, 0.2, 0.3]
        result = _vec_to_str(vec)
        assert result == str(vec)


# ---------------------------------------------------------------------------
# _get_provider
# ---------------------------------------------------------------------------


class TestGetProvider:
    """Tests for _get_provider()."""

    @pytest.mark.asyncio
    async def test_returns_local_provider_when_no_config(
        self, service: EmbeddingService, mock_db: AsyncMock
    ) -> None:
        """Uses local provider defaults when no config exists."""
        from unittest.mock import patch

        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = result

        mock_provider = MagicMock()
        with patch(
            "ontokit.services.embedding_service.get_embedding_provider",
            return_value=mock_provider,
        ) as mock_get:
            provider = await service._get_provider(PROJECT_ID)
            mock_get.assert_called_once_with("local", "all-MiniLM-L6-v2", None)
            assert provider is mock_provider

    @pytest.mark.asyncio
    async def test_returns_configured_provider_with_api_key(
        self, service: EmbeddingService, mock_db: AsyncMock
    ) -> None:
        """Uses configured provider and decrypts API key."""
        from unittest.mock import patch

        cfg = _make_config_row(provider="openai", model_name="text-embedding-3-small")
        cfg.api_key_encrypted = "encrypted-key-value"
        result = MagicMock()
        result.scalar_one_or_none.return_value = cfg
        mock_db.execute.return_value = result

        mock_provider = MagicMock()
        with (
            patch(
                "ontokit.services.embedding_service.get_embedding_provider",
                return_value=mock_provider,
            ) as mock_get,
            patch(
                "ontokit.services.embedding_service._decrypt_secret",
                return_value="decrypted-api-key",
            ),
        ):
            provider = await service._get_provider(PROJECT_ID)
            mock_get.assert_called_once_with(
                "openai", "text-embedding-3-small", "decrypted-api-key"
            )
            assert provider is mock_provider

    @pytest.mark.asyncio
    async def test_returns_provider_without_api_key(
        self, service: EmbeddingService, mock_db: AsyncMock
    ) -> None:
        """Provider with no API key passes None."""
        from unittest.mock import patch

        cfg = _make_config_row(provider="local", model_name="all-MiniLM-L6-v2")
        cfg.api_key_encrypted = None
        result = MagicMock()
        result.scalar_one_or_none.return_value = cfg
        mock_db.execute.return_value = result

        mock_provider = MagicMock()
        with patch(
            "ontokit.services.embedding_service.get_embedding_provider",
            return_value=mock_provider,
        ) as mock_get:
            await service._get_provider(PROJECT_ID)
            mock_get.assert_called_once_with("local", "all-MiniLM-L6-v2", None)


# ---------------------------------------------------------------------------
# embed_project
# ---------------------------------------------------------------------------


class TestEmbedProject:
    """Tests for embed_project()."""

    @pytest.mark.asyncio
    async def test_embed_project_creates_job_and_embeds_entities(
        self, service: EmbeddingService, mock_db: AsyncMock
    ) -> None:
        """Full happy-path: loads graph, embeds entities, updates job status."""
        from unittest.mock import patch

        from rdflib import Graph, URIRef
        from rdflib import Literal as RDFLiteral
        from rdflib.namespace import OWL, RDF, RDFS

        job_id = uuid.uuid4()

        # No existing job
        job_result = MagicMock()
        job_result.scalar_one_or_none.return_value = None

        # Project lookup
        mock_project = MagicMock()
        mock_project.source_file_path = "ontology.ttl"
        mock_project.git_ontology_path = None
        proj_result = MagicMock()
        proj_result.scalar_one_or_none.return_value = mock_project

        # Provider config
        cfg = _make_config_row()
        cfg_result = MagicMock()
        cfg_result.scalar_one_or_none.return_value = cfg

        # Existing embedding check returns None (new entity)
        existing_result = MagicMock()
        existing_result.scalar_one_or_none.return_value = None

        # Build a small test graph
        g = Graph()
        test_uri = URIRef("http://example.org/MyClass")
        g.add((test_uri, RDF.type, OWL.Class))
        g.add((test_uri, RDFS.label, RDFLiteral("My Class")))

        mock_provider = AsyncMock()
        mock_provider.provider_name = "local"
        mock_provider.model_id = "all-MiniLM-L6-v2"
        mock_provider.embed_batch = AsyncMock(return_value=[[0.1, 0.2, 0.3]])

        mock_ontology = MagicMock()
        mock_ontology.load_from_git = AsyncMock(return_value=g)

        mock_git = MagicMock()

        # Set up execute side effects (commits use mock_db.commit, not execute)
        mock_db.execute.side_effect = [
            job_result,  # select EmbeddingJob
            proj_result,  # select Project
            cfg_result,  # _get_provider -> select config
            existing_result,  # existing embedding check (upsert)
            MagicMock(),  # delete prune
            cfg_result,  # select config for last_full_embed_at
        ]

        with (
            patch(
                "ontokit.services.embedding_service.get_embedding_provider",
                return_value=mock_provider,
            ),
            patch(
                "ontokit.services.embedding_service.build_embedding_text",
                return_value="My Class: an OWL class",
            ),
            patch(
                "ontokit.services.embedding_service._get_entity_type",
                return_value="class",
            ),
            patch(
                "ontokit.services.embedding_service._is_deprecated",
                return_value=False,
            ),
            patch(
                "ontokit.services.ontology.get_ontology_service",
                return_value=mock_ontology,
            ),
            patch(
                "ontokit.git.bare_repository.BareGitRepositoryService",
                return_value=mock_git,
            ),
            patch(
                "ontokit.services.storage.get_storage_service",
                return_value=MagicMock(),
            ),
        ):
            await service.embed_project(PROJECT_ID, BRANCH, job_id)

        # Job was added to the session
        mock_db.add.assert_called()
        # Multiple commits occurred
        assert mock_db.commit.await_count >= 2

    @pytest.mark.asyncio
    async def test_embed_project_uses_existing_job(
        self, service: EmbeddingService, mock_db: AsyncMock
    ) -> None:
        """When job already exists, updates its status to running."""
        from unittest.mock import patch

        from rdflib import Graph

        job_id = uuid.uuid4()

        existing_job = MagicMock()
        existing_job.id = job_id
        existing_job.status = "pending"
        job_result = MagicMock()
        job_result.scalar_one_or_none.return_value = existing_job

        mock_project = MagicMock()
        mock_project.source_file_path = "ontology.ttl"
        mock_project.git_ontology_path = None
        proj_result = MagicMock()
        proj_result.scalar_one_or_none.return_value = mock_project

        cfg_result = MagicMock()
        cfg_result.scalar_one_or_none.return_value = _make_config_row()

        # Empty graph
        g = Graph()

        mock_ontology = MagicMock()
        mock_ontology.load_from_git = AsyncMock(return_value=g)

        mock_db.execute.side_effect = [
            job_result,  # select EmbeddingJob (found)
            proj_result,  # select Project
            cfg_result,  # _get_provider
            MagicMock(),  # delete (prune all - no entities)
            cfg_result,  # config for last_full_embed_at
        ]

        mock_provider = AsyncMock()
        mock_provider.provider_name = "local"
        mock_provider.model_id = "all-MiniLM-L6-v2"

        with (
            patch(
                "ontokit.services.embedding_service.get_embedding_provider",
                return_value=mock_provider,
            ),
            patch(
                "ontokit.services.ontology.get_ontology_service",
                return_value=mock_ontology,
            ),
            patch(
                "ontokit.git.bare_repository.BareGitRepositoryService",
                return_value=MagicMock(),
            ),
            patch(
                "ontokit.services.storage.get_storage_service",
                return_value=MagicMock(),
            ),
        ):
            await service.embed_project(PROJECT_ID, BRANCH, job_id)

        # Job should end as "completed" (it was set to "running" then "completed")
        assert existing_job.status == "completed"
        # db.add should NOT be called for the job (it already existed)
        for call in mock_db.add.call_args_list:
            added_obj = call[0][0]
            assert getattr(added_obj, "id", None) != existing_job.id

    @pytest.mark.asyncio
    async def test_embed_project_no_project_raises(
        self, service: EmbeddingService, mock_db: AsyncMock
    ) -> None:
        """Raises ValueError when project not found."""
        from unittest.mock import patch

        job_id = uuid.uuid4()

        job_result = MagicMock()
        job_result.scalar_one_or_none.return_value = None

        proj_result = MagicMock()
        proj_result.scalar_one_or_none.return_value = None

        mock_db.execute.side_effect = [
            job_result,  # select EmbeddingJob
            proj_result,  # select Project -> None
            MagicMock(),  # rollback update
        ]

        with (
            patch(
                "ontokit.services.ontology.get_ontology_service",
                return_value=MagicMock(),
            ),
            patch(
                "ontokit.git.bare_repository.BareGitRepositoryService",
                return_value=MagicMock(),
            ),
            patch(
                "ontokit.services.storage.get_storage_service",
                return_value=MagicMock(),
            ),
            pytest.raises(ValueError, match="Project not found"),
        ):
            await service.embed_project(PROJECT_ID, BRANCH, job_id)

    @pytest.mark.asyncio
    async def test_embed_project_failure_marks_job_failed(
        self, service: EmbeddingService, mock_db: AsyncMock
    ) -> None:
        """On exception, job status is set to 'failed' with error message."""
        from unittest.mock import patch

        job_id = uuid.uuid4()

        existing_job = MagicMock()
        existing_job.id = job_id
        job_result = MagicMock()
        job_result.scalar_one_or_none.return_value = existing_job

        # Project raises an error during loading
        proj_result = MagicMock()
        proj_result.scalar_one_or_none.return_value = None  # no project

        mock_db.execute.side_effect = [
            job_result,  # select EmbeddingJob
            proj_result,  # select Project -> None
            MagicMock(),  # raw UPDATE for failure status
        ]
        mock_db.rollback = AsyncMock()

        with (
            patch(
                "ontokit.services.ontology.get_ontology_service",
                return_value=MagicMock(),
            ),
            patch(
                "ontokit.git.bare_repository.BareGitRepositoryService",
                return_value=MagicMock(),
            ),
            patch(
                "ontokit.services.storage.get_storage_service",
                return_value=MagicMock(),
            ),
            pytest.raises(ValueError),
        ):
            await service.embed_project(PROJECT_ID, BRANCH, job_id)

        mock_db.rollback.assert_awaited_once()
        # Third execute call is the raw UPDATE setting status='failed'
        assert mock_db.execute.call_count == 3
        update_stmt = mock_db.execute.call_args_list[2][0][0]
        compiled = update_stmt.compile(compile_kwargs={"literal_binds": True})
        compiled_str = str(compiled)
        assert "failed" in compiled_str
        mock_db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_embed_project_updates_existing_embedding(
        self, service: EmbeddingService, mock_db: AsyncMock
    ) -> None:
        """When an embedding already exists for an entity, updates it."""
        from unittest.mock import patch

        from rdflib import Graph, URIRef
        from rdflib import Literal as RDFLiteral
        from rdflib.namespace import OWL, RDF, RDFS

        job_id = uuid.uuid4()

        job_result = MagicMock()
        job_result.scalar_one_or_none.return_value = None

        mock_project = MagicMock()
        mock_project.source_file_path = "ontology.ttl"
        mock_project.git_ontology_path = "onto.ttl"
        proj_result = MagicMock()
        proj_result.scalar_one_or_none.return_value = mock_project

        cfg = _make_config_row()
        cfg_result = MagicMock()
        cfg_result.scalar_one_or_none.return_value = cfg

        # Existing embedding (update path)
        existing_emb = MagicMock()
        existing_emb_result = MagicMock()
        existing_emb_result.scalar_one_or_none.return_value = existing_emb

        g = Graph()
        test_uri = URIRef("http://example.org/ExistingClass")
        g.add((test_uri, RDF.type, OWL.Class))
        g.add((test_uri, RDFS.label, RDFLiteral("Existing Class")))

        mock_provider = AsyncMock()
        mock_provider.provider_name = "local"
        mock_provider.model_id = "all-MiniLM-L6-v2"
        mock_provider.embed_batch = AsyncMock(return_value=[[0.4, 0.5, 0.6]])

        mock_ontology = MagicMock()
        mock_ontology.load_from_git = AsyncMock(return_value=g)

        mock_db.execute.side_effect = [
            job_result,  # select EmbeddingJob
            proj_result,  # select Project
            cfg_result,  # _get_provider
            existing_emb_result,  # existing embedding check -> found
            MagicMock(),  # delete prune
            cfg_result,  # config for last_full_embed_at
        ]

        with (
            patch(
                "ontokit.services.embedding_service.get_embedding_provider",
                return_value=mock_provider,
            ),
            patch(
                "ontokit.services.embedding_service.build_embedding_text",
                return_value="Existing Class text",
            ),
            patch(
                "ontokit.services.embedding_service._get_entity_type",
                return_value="class",
            ),
            patch(
                "ontokit.services.embedding_service._is_deprecated",
                return_value=False,
            ),
            patch(
                "ontokit.services.ontology.get_ontology_service",
                return_value=mock_ontology,
            ),
            patch(
                "ontokit.git.bare_repository.BareGitRepositoryService",
                return_value=MagicMock(),
            ),
            patch(
                "ontokit.services.storage.get_storage_service",
                return_value=MagicMock(),
            ),
        ):
            await service.embed_project(PROJECT_ID, BRANCH, job_id)

        # The existing embedding object should have been updated
        assert existing_emb.embedding == [0.4, 0.5, 0.6]
        assert existing_emb.provider == "local"

    @pytest.mark.asyncio
    async def test_embed_project_falls_back_to_storage_on_default_branch(
        self, service: EmbeddingService, mock_db: AsyncMock
    ) -> None:
        """Falls back to load_from_storage when git load fails on default branch."""
        from unittest.mock import patch

        from rdflib import Graph

        job_id = uuid.uuid4()

        job_result = MagicMock()
        job_result.scalar_one_or_none.return_value = None

        mock_project = MagicMock()
        mock_project.source_file_path = "ontology.ttl"
        mock_project.git_ontology_path = None
        proj_result = MagicMock()
        proj_result.scalar_one_or_none.return_value = mock_project

        cfg_result = MagicMock()
        cfg_result.scalar_one_or_none.return_value = _make_config_row()

        g = Graph()  # empty graph

        mock_ontology = MagicMock()
        mock_ontology.load_from_git = AsyncMock(side_effect=FileNotFoundError("not found"))
        mock_ontology.load_from_storage = AsyncMock(return_value=g)

        mock_git = MagicMock()
        mock_git.get_default_branch.return_value = "main"

        mock_provider = AsyncMock()
        mock_provider.provider_name = "local"
        mock_provider.model_id = "all-MiniLM-L6-v2"

        mock_db.execute.side_effect = [
            job_result,  # select EmbeddingJob
            proj_result,  # select Project
            cfg_result,  # _get_provider
            MagicMock(),  # delete prune (no entities)
            cfg_result,  # config for last_full_embed_at
        ]

        with (
            patch(
                "ontokit.services.embedding_service.get_embedding_provider",
                return_value=mock_provider,
            ),
            patch(
                "ontokit.services.ontology.get_ontology_service",
                return_value=mock_ontology,
            ),
            patch(
                "ontokit.git.bare_repository.BareGitRepositoryService",
                return_value=mock_git,
            ),
            patch(
                "ontokit.services.storage.get_storage_service",
                return_value=MagicMock(),
            ),
        ):
            await service.embed_project(PROJECT_ID, BRANCH, job_id)

        mock_ontology.load_from_storage.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_embed_project_non_default_branch_does_not_fallback(
        self, service: EmbeddingService, mock_db: AsyncMock
    ) -> None:
        """Non-default branch does NOT fall back to storage; re-raises."""
        from unittest.mock import patch

        job_id = uuid.uuid4()

        existing_job = MagicMock()
        existing_job.id = job_id
        job_result = MagicMock()
        job_result.scalar_one_or_none.return_value = existing_job

        mock_project = MagicMock()
        mock_project.source_file_path = "ontology.ttl"
        mock_project.git_ontology_path = None
        proj_result = MagicMock()
        proj_result.scalar_one_or_none.return_value = mock_project

        mock_ontology = MagicMock()
        mock_ontology.load_from_git = AsyncMock(side_effect=FileNotFoundError("not found"))

        mock_git = MagicMock()
        mock_git.get_default_branch.return_value = "main"

        mock_db.execute.side_effect = [
            job_result,  # select EmbeddingJob
            proj_result,  # select Project
            MagicMock(),  # rollback update
        ]
        mock_db.rollback = AsyncMock()

        with (
            patch(
                "ontokit.services.ontology.get_ontology_service",
                return_value=mock_ontology,
            ),
            patch(
                "ontokit.git.bare_repository.BareGitRepositoryService",
                return_value=mock_git,
            ),
            patch(
                "ontokit.services.storage.get_storage_service",
                return_value=MagicMock(),
            ),
            pytest.raises(FileNotFoundError),
        ):
            await service.embed_project(PROJECT_ID, "feature-branch", job_id)


# ---------------------------------------------------------------------------
# embed_single_entity
# ---------------------------------------------------------------------------


class TestEmbedSingleEntity:
    """Tests for embed_single_entity()."""

    @pytest.mark.asyncio
    async def test_skips_when_ontology_not_loaded(
        self, service: EmbeddingService, mock_db: AsyncMock
    ) -> None:
        """Returns early when ontology is not loaded for the project/branch."""
        from unittest.mock import patch

        mock_ontology = MagicMock()
        mock_ontology.is_loaded.return_value = False

        with patch(
            "ontokit.services.ontology.get_ontology_service",
            return_value=mock_ontology,
        ):
            await service.embed_single_entity(PROJECT_ID, BRANCH, "http://example.org/Foo")

        # No DB operations should have occurred beyond what the fixture provides
        mock_db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_skips_unknown_entity_type(
        self, service: EmbeddingService, mock_db: AsyncMock
    ) -> None:
        """Returns early when entity type is 'unknown'."""
        from unittest.mock import patch

        from rdflib import Graph

        mock_ontology = MagicMock()
        mock_ontology.is_loaded.return_value = True
        mock_ontology._get_graph = AsyncMock(return_value=Graph())

        with (
            patch(
                "ontokit.services.ontology.get_ontology_service",
                return_value=mock_ontology,
            ),
            patch(
                "ontokit.services.embedding_service._get_entity_type",
                return_value="unknown",
            ),
        ):
            await service.embed_single_entity(PROJECT_ID, BRANCH, "http://example.org/Foo")

        mock_db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_creates_new_embedding(
        self, service: EmbeddingService, mock_db: AsyncMock
    ) -> None:
        """Creates a new EntityEmbedding when none exists."""
        from unittest.mock import patch

        from rdflib import Graph, URIRef
        from rdflib import Literal as RDFLiteral
        from rdflib.namespace import RDFS

        g = Graph()
        uri = URIRef("http://example.org/Foo")
        g.add((uri, RDFS.label, RDFLiteral("Foo")))

        mock_ontology = MagicMock()
        mock_ontology.is_loaded.return_value = True
        mock_ontology._get_graph = AsyncMock(return_value=g)

        mock_provider = AsyncMock()
        mock_provider.provider_name = "local"
        mock_provider.model_id = "all-MiniLM-L6-v2"
        mock_provider.embed_text = AsyncMock(return_value=[0.1, 0.2, 0.3])

        # _get_provider config query
        cfg_result = MagicMock()
        cfg_result.scalar_one_or_none.return_value = _make_config_row()

        # Existing embedding query -> None
        existing_result = MagicMock()
        existing_result.scalar_one_or_none.return_value = None

        mock_db.execute.side_effect = [cfg_result, existing_result]

        with (
            patch(
                "ontokit.services.ontology.get_ontology_service",
                return_value=mock_ontology,
            ),
            patch(
                "ontokit.services.embedding_service._get_entity_type",
                return_value="class",
            ),
            patch(
                "ontokit.services.embedding_service.build_embedding_text",
                return_value="Foo entity text",
            ),
            patch(
                "ontokit.services.embedding_service._is_deprecated",
                return_value=False,
            ),
            patch(
                "ontokit.services.embedding_service.get_embedding_provider",
                return_value=mock_provider,
            ),
        ):
            await service.embed_single_entity(PROJECT_ID, BRANCH, "http://example.org/Foo")

        mock_db.add.assert_called_once()
        mock_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_updates_existing_embedding(
        self, service: EmbeddingService, mock_db: AsyncMock
    ) -> None:
        """Updates an existing EntityEmbedding rather than creating a new one."""
        from unittest.mock import patch

        from rdflib import Graph

        g = Graph()

        mock_ontology = MagicMock()
        mock_ontology.is_loaded.return_value = True
        mock_ontology._get_graph = AsyncMock(return_value=g)

        mock_provider = AsyncMock()
        mock_provider.provider_name = "local"
        mock_provider.model_id = "all-MiniLM-L6-v2"
        mock_provider.embed_text = AsyncMock(return_value=[0.7, 0.8, 0.9])

        cfg_result = MagicMock()
        cfg_result.scalar_one_or_none.return_value = _make_config_row()

        existing_emb = MagicMock()
        existing_result = MagicMock()
        existing_result.scalar_one_or_none.return_value = existing_emb

        mock_db.execute.side_effect = [cfg_result, existing_result]

        with (
            patch(
                "ontokit.services.ontology.get_ontology_service",
                return_value=mock_ontology,
            ),
            patch(
                "ontokit.services.embedding_service._get_entity_type",
                return_value="property",
            ),
            patch(
                "ontokit.services.embedding_service.build_embedding_text",
                return_value="property text",
            ),
            patch(
                "ontokit.services.embedding_service._is_deprecated",
                return_value=True,
            ),
            patch(
                "ontokit.services.embedding_service.get_embedding_provider",
                return_value=mock_provider,
            ),
        ):
            await service.embed_single_entity(PROJECT_ID, BRANCH, "http://example.org/Bar")

        # Should NOT call db.add (update path)
        mock_db.add.assert_not_called()
        assert existing_emb.embedding == [0.7, 0.8, 0.9]
        assert existing_emb.deprecated is True
        mock_db.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# semantic_search
# ---------------------------------------------------------------------------


class TestSemanticSearch:
    """Tests for semantic_search()."""

    @pytest.mark.asyncio
    async def test_returns_text_fallback_when_no_embeddings(
        self, service: EmbeddingService, mock_db: AsyncMock
    ) -> None:
        """Returns text_fallback mode when no embeddings exist."""
        from unittest.mock import patch

        count_result = MagicMock()
        count_result.scalar.return_value = 0

        mock_db.execute.side_effect = [count_result]

        with patch("ontokit.services.embedding_service.Vector", new="not-None"):
            result = await service.semantic_search(PROJECT_ID, BRANCH, "test query")

        assert result.search_mode == "text_fallback"
        assert result.results == []

    @pytest.mark.asyncio
    async def test_raises_when_pgvector_not_installed(
        self, service: EmbeddingService, mock_db: AsyncMock
    ) -> None:
        """Raises RuntimeError when Vector is None (pgvector not installed)."""
        from unittest.mock import patch

        with (
            patch("ontokit.services.embedding_service.Vector", new=None),
            pytest.raises(RuntimeError, match="pgvector is not installed"),
        ):
            await service.semantic_search(PROJECT_ID, BRANCH, "test query")

    @pytest.mark.asyncio
    async def test_returns_semantic_results(
        self, service: EmbeddingService, mock_db: AsyncMock
    ) -> None:
        """Returns semantic search results filtered by threshold."""
        from unittest.mock import patch

        count_result = MagicMock()
        count_result.scalar.return_value = 10

        # Provider config
        cfg_result = MagicMock()
        cfg_result.scalar_one_or_none.return_value = _make_config_row()

        mock_provider = AsyncMock()
        mock_provider.embed_text = AsyncMock(return_value=[0.1, 0.2, 0.3])

        # Search results
        row_above = MagicMock()
        row_above.entity_iri = "http://example.org/Match"
        row_above.label = "Match"
        row_above.entity_type = "class"
        row_above.score = 0.85
        row_above.deprecated = False

        row_below = MagicMock()
        row_below.score = 0.1  # below threshold

        search_result = MagicMock()
        search_result.__iter__ = Mock(return_value=iter([row_above, row_below]))

        mock_db.execute.side_effect = [count_result, cfg_result, search_result]

        with (
            patch("ontokit.services.embedding_service.Vector", new="not-None"),
            patch(
                "ontokit.services.embedding_service.get_embedding_provider",
                return_value=mock_provider,
            ),
        ):
            result = await service.semantic_search(PROJECT_ID, BRANCH, "find match", threshold=0.3)

        assert result.search_mode == "semantic"
        assert len(result.results) == 1
        assert result.results[0].iri == "http://example.org/Match"
        assert result.results[0].score == 0.85


# ---------------------------------------------------------------------------
# find_similar
# ---------------------------------------------------------------------------


class TestFindSimilar:
    """Tests for find_similar()."""

    @pytest.mark.asyncio
    async def test_raises_when_pgvector_not_installed(
        self, service: EmbeddingService, mock_db: AsyncMock
    ) -> None:
        """Raises RuntimeError when Vector is None."""
        from unittest.mock import patch

        with (
            patch("ontokit.services.embedding_service.Vector", new=None),
            pytest.raises(RuntimeError, match="pgvector is not installed"),
        ):
            await service.find_similar(PROJECT_ID, BRANCH, "http://example.org/X")

    @pytest.mark.asyncio
    async def test_returns_empty_when_entity_not_embedded(
        self, service: EmbeddingService, mock_db: AsyncMock
    ) -> None:
        """Returns empty list when the source entity has no embedding."""
        from unittest.mock import patch

        emb_result = MagicMock()
        emb_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = emb_result

        with patch("ontokit.services.embedding_service.Vector", new="not-None"):
            results = await service.find_similar(PROJECT_ID, BRANCH, "http://example.org/Missing")

        assert results == []

    @pytest.mark.asyncio
    async def test_returns_similar_entities(
        self, service: EmbeddingService, mock_db: AsyncMock
    ) -> None:
        """Returns similar entities above threshold."""
        from unittest.mock import patch

        # Source entity embedding
        source_emb = MagicMock()
        source_emb.embedding = [0.1, 0.2, 0.3]
        emb_result = MagicMock()
        emb_result.scalar_one_or_none.return_value = source_emb

        # Similar results
        row_match = MagicMock()
        row_match.entity_iri = "http://example.org/Similar"
        row_match.label = "Similar"
        row_match.entity_type = "class"
        row_match.score = 0.92
        row_match.deprecated = False

        row_low = MagicMock()
        row_low.score = 0.2  # below default threshold 0.5

        search_result = MagicMock()
        search_result.__iter__ = Mock(return_value=iter([row_match, row_low]))

        mock_db.execute.side_effect = [emb_result, search_result]

        with patch("ontokit.services.embedding_service.Vector", new="not-None"):
            results = await service.find_similar(PROJECT_ID, BRANCH, "http://example.org/Source")

        assert len(results) == 1
        assert results[0].iri == "http://example.org/Similar"
        assert results[0].score == 0.92


# ---------------------------------------------------------------------------
# rank_suggestions
# ---------------------------------------------------------------------------


class TestRankSuggestions:
    """Tests for rank_suggestions()."""

    @pytest.mark.asyncio
    async def test_raises_when_pgvector_not_installed(
        self, service: EmbeddingService, mock_db: AsyncMock
    ) -> None:
        """Raises RuntimeError when Vector is None."""
        from unittest.mock import patch

        body = MagicMock()
        body.candidates = ["http://example.org/A"]
        body.branch = BRANCH

        with (
            patch("ontokit.services.embedding_service.Vector", new=None),
            pytest.raises(RuntimeError, match="pgvector is not installed"),
        ):
            await service.rank_suggestions(PROJECT_ID, body)

    @pytest.mark.asyncio
    async def test_returns_empty_for_empty_candidates(
        self, service: EmbeddingService, mock_db: AsyncMock
    ) -> None:
        """Returns empty list when candidates list is empty."""
        from unittest.mock import patch

        body = MagicMock()
        body.candidates = []

        with patch("ontokit.services.embedding_service.Vector", new="not-None"):
            results = await service.rank_suggestions(PROJECT_ID, body)

        assert results == []

    @pytest.mark.asyncio
    async def test_returns_empty_when_context_not_embedded(
        self, service: EmbeddingService, mock_db: AsyncMock
    ) -> None:
        """Returns empty list when context entity has no embedding."""
        from unittest.mock import patch

        body = MagicMock()
        body.candidates = ["http://example.org/A"]
        body.branch = BRANCH
        body.context_iri = "http://example.org/Context"

        ctx_result = MagicMock()
        ctx_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = ctx_result

        with patch("ontokit.services.embedding_service.Vector", new="not-None"):
            results = await service.rank_suggestions(PROJECT_ID, body)

        assert results == []

    @pytest.mark.asyncio
    async def test_ranks_candidates_by_cosine_similarity(
        self, service: EmbeddingService, mock_db: AsyncMock
    ) -> None:
        """Ranks candidates by descending cosine similarity."""
        from unittest.mock import patch

        body = MagicMock()
        body.candidates = ["http://example.org/A", "http://example.org/B"]
        body.branch = BRANCH
        body.context_iri = "http://example.org/Context"

        # Context embedding
        ctx_emb = MagicMock()
        ctx_emb.embedding = [1.0, 0.0, 0.0]  # unit vector along x-axis
        ctx_result = MagicMock()
        ctx_result.scalar_one_or_none.return_value = ctx_emb

        # Candidate A: parallel to context -> sim=1.0
        cand_a = MagicMock()
        cand_a.entity_iri = "http://example.org/A"
        cand_a.label = "A"
        cand_a.embedding = [1.0, 0.0, 0.0]

        # Candidate B: partially aligned -> sim < 1.0
        cand_b = MagicMock()
        cand_b.entity_iri = "http://example.org/B"
        cand_b.label = "B"
        cand_b.embedding = [0.5, 0.5, 0.0]

        cand_result = MagicMock()
        cand_result.scalars.return_value.all.return_value = [cand_a, cand_b]

        mock_db.execute.side_effect = [ctx_result, cand_result]

        with patch("ontokit.services.embedding_service.Vector", new="not-None"):
            results = await service.rank_suggestions(PROJECT_ID, body)

        assert len(results) == 2
        # A should be ranked first (higher similarity)
        assert results[0].iri == "http://example.org/A"
        assert results[0].score == 1.0
        assert results[1].iri == "http://example.org/B"
        assert results[1].score < 1.0

    @pytest.mark.asyncio
    async def test_returns_empty_when_context_vec_is_zero(
        self, service: EmbeddingService, mock_db: AsyncMock
    ) -> None:
        """Returns empty list when context vector norm is zero."""
        from unittest.mock import patch

        body = MagicMock()
        body.candidates = ["http://example.org/A"]
        body.branch = BRANCH
        body.context_iri = "http://example.org/Context"

        ctx_emb = MagicMock()
        ctx_emb.embedding = [0.0, 0.0, 0.0]  # zero vector
        ctx_result = MagicMock()
        ctx_result.scalar_one_or_none.return_value = ctx_emb

        cand_result = MagicMock()
        cand_result.scalars.return_value.all.return_value = []

        mock_db.execute.side_effect = [ctx_result, cand_result]

        with patch("ontokit.services.embedding_service.Vector", new="not-None"):
            results = await service.rank_suggestions(PROJECT_ID, body)

        assert results == []

    @pytest.mark.asyncio
    async def test_skips_candidate_with_zero_norm(
        self, service: EmbeddingService, mock_db: AsyncMock
    ) -> None:
        """Candidates with zero-norm embeddings are excluded."""
        from unittest.mock import patch

        body = MagicMock()
        body.candidates = ["http://example.org/A"]
        body.branch = BRANCH
        body.context_iri = "http://example.org/Context"

        ctx_emb = MagicMock()
        ctx_emb.embedding = [1.0, 0.0, 0.0]
        ctx_result = MagicMock()
        ctx_result.scalar_one_or_none.return_value = ctx_emb

        # Candidate with zero vector
        cand_a = MagicMock()
        cand_a.entity_iri = "http://example.org/A"
        cand_a.label = "A"
        cand_a.embedding = [0.0, 0.0, 0.0]

        cand_result = MagicMock()
        cand_result.scalars.return_value.all.return_value = [cand_a]

        mock_db.execute.side_effect = [ctx_result, cand_result]

        with patch("ontokit.services.embedding_service.Vector", new="not-None"):
            results = await service.rank_suggestions(PROJECT_ID, body)

        assert results == []

    @pytest.mark.asyncio
    async def test_resolves_branch_when_none(
        self, service: EmbeddingService, mock_db: AsyncMock
    ) -> None:
        """Resolves branch from git service when body.branch is None."""
        from unittest.mock import patch

        body = MagicMock()
        body.candidates = ["http://example.org/A"]
        body.branch = None
        body.context_iri = "http://example.org/Context"

        mock_git_service = MagicMock()
        mock_git_service.get_default_branch.return_value = "main"

        # Context embedding not found
        ctx_result = MagicMock()
        ctx_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = ctx_result

        with (
            patch("ontokit.services.embedding_service.Vector", new="not-None"),
            patch(
                "ontokit.git.get_git_service",
                return_value=mock_git_service,
            ),
        ):
            results = await service.rank_suggestions(PROJECT_ID, body)

        mock_git_service.get_default_branch.assert_called_once_with(PROJECT_ID)
        assert results == []


# ---------------------------------------------------------------------------
# update_config edge cases
# ---------------------------------------------------------------------------


class TestUpdateConfigEdgeCases:
    """Additional edge cases for update_config()."""

    @pytest.mark.asyncio
    async def test_model_change_invalidates_embeddings(
        self, service: EmbeddingService, mock_db: AsyncMock
    ) -> None:
        """Changing provider/model deletes old embeddings and resets marker."""
        from unittest.mock import patch

        existing = _make_config_row(provider="local", model_name="all-MiniLM-L6-v2")
        result = MagicMock()
        result.scalar_one_or_none.return_value = existing
        mock_db.execute.return_value = result

        update = MagicMock()
        update.provider = "openai"  # different provider
        update.model_name = "text-embedding-3-small"
        update.api_key = "new-key"
        update.auto_embed_on_save = None

        mock_provider_obj = MagicMock()
        mock_provider_obj.dimensions = 1536

        with (
            patch(
                "ontokit.services.embedding_service.get_embedding_provider",
                return_value=mock_provider_obj,
            ),
            patch(
                "ontokit.services.embedding_service._encrypt_secret",
                return_value="encrypted",
            ),
        ):
            await service.update_config(PROJECT_ID, update)

        assert existing.provider == "openai"
        assert existing.model_name == "text-embedding-3-small"
        assert existing.dimensions == 1536
        assert existing.last_full_embed_at is None
        assert existing.api_key_encrypted == "encrypted"

    @pytest.mark.asyncio
    async def test_api_key_only_update(self, service: EmbeddingService, mock_db: AsyncMock) -> None:
        """Updating only api_key does not invalidate embeddings."""
        from unittest.mock import patch

        existing = _make_config_row(provider="openai", model_name="text-embedding-3-small")
        existing.last_full_embed_at = datetime.now(UTC)
        result = MagicMock()
        result.scalar_one_or_none.return_value = existing
        mock_db.execute.return_value = result

        update = MagicMock()
        update.provider = None
        update.model_name = None
        update.api_key = "new-api-key"
        update.auto_embed_on_save = None

        with patch(
            "ontokit.services.embedding_service._encrypt_secret",
            return_value="new-encrypted",
        ):
            await service.update_config(PROJECT_ID, update)

        # last_full_embed_at should NOT be reset
        assert existing.last_full_embed_at is not None
        assert existing.api_key_encrypted == "new-encrypted"


# ---------------------------------------------------------------------------
# get_config with last_full_embed_at set
# ---------------------------------------------------------------------------


class TestGetConfigWithTimestamp:
    """Test get_config when last_full_embed_at is set."""

    @pytest.mark.asyncio
    async def test_returns_isoformat_timestamp(
        self, service: EmbeddingService, mock_db: AsyncMock
    ) -> None:
        """last_full_embed_at is returned as isoformat string."""
        ts = datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC)
        cfg = _make_config_row(last_full_embed_at=ts)
        result = MagicMock()
        result.scalar_one_or_none.return_value = cfg
        mock_db.execute.return_value = result

        config = await service.get_config(PROJECT_ID)
        assert config is not None
        assert config.last_full_embed_at == ts.isoformat()
