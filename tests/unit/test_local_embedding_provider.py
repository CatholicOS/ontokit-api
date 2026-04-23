"""Tests for the local embedding provider (ontokit/services/embedding_providers/local_provider.py)."""

from __future__ import annotations

import sys

import pytest

from ontokit.services.embedding_providers import local_provider
from ontokit.services.embedding_providers.local_provider import LocalEmbeddingProvider


class TestSentenceTransformersMissing:
    """sentence-transformers is an optional extra; verify the friendly error path."""

    def test_dimensions_raises_runtime_error_pointing_at_extras(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Poison sys.modules so `from sentence_transformers import ...` fails
        # with ImportError even if the package is installed in the dev env.
        monkeypatch.setitem(sys.modules, "sentence_transformers", None)
        # Reset the model cache so _get_model actually attempts the import.
        monkeypatch.setattr(local_provider, "_models", {})

        provider = LocalEmbeddingProvider(model_name="all-MiniLM-L6-v2")
        with pytest.raises(RuntimeError, match="local-embeddings") as excinfo:
            _ = provider.dimensions

        # The RuntimeError preserves the original ImportError as its cause,
        # so callers (and logs) can trace back to the real failure.
        assert isinstance(excinfo.value.__cause__, ImportError)
