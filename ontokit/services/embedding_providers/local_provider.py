"""Local embedding provider using sentence-transformers."""

import asyncio
import logging

from ontokit.services.embedding_providers.base import EmbeddingProvider

logger = logging.getLogger(__name__)

# Lazy-loaded model cache
_models: dict[str, object] = {}


def _get_model(model_name: str) -> object:
    """Get or load a sentence-transformers model (cached)."""
    if model_name not in _models:
        from sentence_transformers import SentenceTransformer

        logger.info(f"Loading sentence-transformers model: {model_name}")
        _models[model_name] = SentenceTransformer(model_name)
    return _models[model_name]


class LocalEmbeddingProvider(EmbeddingProvider):
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self._model_name = model_name
        self._dims: int | None = None

    @property
    def dimensions(self) -> int:
        if self._dims is None:
            model = _get_model(self._model_name)
            self._dims = model.get_sentence_embedding_dimension()  # type: ignore[attr-defined]
        return self._dims

    @property
    def provider_name(self) -> str:
        return "local"

    @property
    def model_id(self) -> str:
        return self._model_name

    async def embed_text(self, text: str) -> list[float]:
        results = await self.embed_batch([text])
        return results[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        def _encode() -> list[list[float]]:
            model = _get_model(self._model_name)
            embeddings = model.encode(texts, batch_size=64, show_progress_bar=False)  # type: ignore[attr-defined]
            return [emb.tolist() for emb in embeddings]

        return await asyncio.to_thread(_encode)
