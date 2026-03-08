"""OpenAI embedding provider."""

import logging

import httpx

from ontokit.services.embedding_providers.base import EmbeddingProvider

logger = logging.getLogger(__name__)

_MODEL_DIMS = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
}


class OpenAIEmbeddingProvider(EmbeddingProvider):
    def __init__(self, model_name: str = "text-embedding-3-small", api_key: str | None = None):
        self._model_name = model_name
        self._api_key = api_key
        if not api_key:
            raise ValueError("OpenAI API key is required")

    @property
    def dimensions(self) -> int:
        return _MODEL_DIMS.get(self._model_name, 1536)

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def model_id(self) -> str:
        return self._model_name

    async def embed_text(self, text: str) -> list[float]:
        results = await self.embed_batch([text])
        return results[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        async with httpx.AsyncClient(timeout=60.0) as client:
            all_embeddings: list[list[float]] = []
            # Batch size 2048 per OpenAI API limits
            for i in range(0, len(texts), 2048):
                batch = texts[i : i + 2048]
                try:
                    resp = await client.post(
                        "https://api.openai.com/v1/embeddings",
                        headers={"Authorization": f"Bearer {self._api_key}"},
                        json={"input": batch, "model": self._model_name},
                    )
                    resp.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    raise ValueError(
                        f"OpenAI API error: {exc.response.status_code} {exc.response.text}"
                    ) from None
                except httpx.HTTPError as exc:
                    raise ValueError(f"OpenAI API request failed: {type(exc).__name__}") from None
                data = resp.json()
                items = data["data"]
                if len(items) != len(batch):
                    raise ValueError(
                        f"OpenAI returned {len(items)} embeddings for {len(batch)} inputs"
                    )
                indexes = [item["index"] for item in items]
                if len(set(indexes)) != len(indexes):
                    raise ValueError("OpenAI response contains duplicate indexes")
                if sorted(indexes) != list(range(len(batch))):
                    raise ValueError("OpenAI response indexes are not contiguous from 0")
                sorted_data = sorted(items, key=lambda x: x["index"])
                all_embeddings.extend([item["embedding"] for item in sorted_data])
            return all_embeddings
