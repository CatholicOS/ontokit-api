"""Embedding provider factory."""

from ontokit.services.embedding_providers.base import EmbeddingProvider


def get_embedding_provider(
    provider: str, model_name: str, api_key: str | None = None
) -> EmbeddingProvider:
    """Create an embedding provider instance."""
    match provider:
        case "local":
            from ontokit.services.embedding_providers.local_provider import LocalEmbeddingProvider

            return LocalEmbeddingProvider(model_name)
        case "openai":
            from ontokit.services.embedding_providers.openai_provider import OpenAIEmbeddingProvider

            return OpenAIEmbeddingProvider(model_name, api_key)
        case "voyage":
            from ontokit.services.embedding_providers.voyage_provider import VoyageEmbeddingProvider

            return VoyageEmbeddingProvider(model_name, api_key)
        case _:
            raise ValueError(f"Unknown embedding provider: {provider}")
