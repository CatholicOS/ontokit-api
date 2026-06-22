"""Unit tests for LocalEmbeddingProvider.dimensions."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ontokit.services.embedding_providers.local_provider import LocalEmbeddingProvider


@patch("ontokit.services.embedding_providers.local_provider._get_model")
def test_dimensions_returns_model_dimension(mock_get_model: MagicMock) -> None:
    """dimensions reports the model's embedding dimension."""
    model = MagicMock()
    model.get_sentence_embedding_dimension.return_value = 384
    mock_get_model.return_value = model

    provider = LocalEmbeddingProvider("some-model")
    assert provider.dimensions == 384


@patch("ontokit.services.embedding_providers.local_provider._get_model")
def test_dimensions_is_cached(mock_get_model: MagicMock) -> None:
    """dimensions is computed once and cached on subsequent access."""
    model = MagicMock()
    model.get_sentence_embedding_dimension.return_value = 384
    mock_get_model.return_value = model

    provider = LocalEmbeddingProvider("some-model")
    assert provider.dimensions == 384
    assert provider.dimensions == 384
    mock_get_model.assert_called_once()


@patch("ontokit.services.embedding_providers.local_provider._get_model")
def test_dimensions_raises_when_model_reports_none(mock_get_model: MagicMock) -> None:
    """A model that reports no embedding dimension raises rather than returning None."""
    model = MagicMock()
    model.get_sentence_embedding_dimension.return_value = None
    mock_get_model.return_value = model

    provider = LocalEmbeddingProvider("some-model")
    with pytest.raises(RuntimeError, match="did not report an embedding dimension"):
        _ = provider.dimensions
