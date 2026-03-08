"""Voyage AI embedding provider."""

import logging

import httpx

from ontokit.services.embedding_providers.base import EmbeddingProvider

logger = logging.getLogger(__name__)

_MODEL_DIMS = {
    "voyage-3-lite": 1024,
    "voyage-3": 1024,
    "voyage-code-3": 1024,
}


class VoyageEmbeddingProvider(EmbeddingProvider):
    def __init__(self, model_name: str = "voyage-3-lite", api_key: str | None = None):
        self._model_name = model_name
        self._api_key = api_key
        if not api_key:
            raise ValueError("Voyage API key is required")

    @property
    def dimensions(self) -> int:
        return _MODEL_DIMS.get(self._model_name, 1024)

    @property
    def provider_name(self) -> str:
        return "voyage"

    @property
    def model_id(self) -> str:
        return self._model_name

    async def embed_text(self, text: str) -> list[float]:
        results = await self.embed_batch([text])
        return results[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        async with httpx.AsyncClient(timeout=60.0) as client:
            all_embeddings: list[list[float]] = []
            for i in range(0, len(texts), 128):
                batch = texts[i : i + 128]
                try:
                    resp = await client.post(
                        "https://api.voyageai.com/v1/embeddings",
                        headers={
                            "Authorization": f"Bearer {self._api_key}",
                            "Content-Type": "application/json",
                        },
                        json={"input": batch, "model": self._model_name},
                    )
                    resp.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    raise ValueError(
                        f"Voyage API error: {exc.response.status_code} "
                        f"{exc.response.text}"
                    ) from None
                except httpx.HTTPError as exc:
                    raise ValueError(
                        f"Voyage API request failed: {type(exc).__name__}"
                    ) from None
                data = resp.json()
                items = data["data"]
                if len(items) != len(batch):
                    raise ValueError(
                        f"Voyage API returned {len(items)} embeddings "
                        f"for {len(batch)} inputs"
                    )
                # Use index field to preserve input ordering
                batch_result: list[list[float]] = [[] for _ in batch]
                for item in items:
                    batch_result[item["index"]] = item["embedding"]
                all_embeddings.extend(batch_result)
            return all_embeddings
