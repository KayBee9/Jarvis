import asyncio
from typing import Protocol

from sentence_transformers import SentenceTransformer

from app.config import get_settings


class EmbeddingProvider(Protocol):
    """Common interface for any embedding backend."""

    @property
    def dimensions(self) -> int: ...

    async def embed(self, text: str) -> list[float]: ...


class LocalProvider:
    """Runs a sentence-transformers model in-process on CPU."""

    def __init__(self, model_name: str) -> None:
        self._model = SentenceTransformer(model_name)
        self._dimensions = self._model.get_sentence_embedding_dimension()

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed(self, text: str) -> list[float]:
        vector = await asyncio.to_thread(self._model.encode, text)
        return vector.tolist()


_provider: EmbeddingProvider | None = None


def init_provider() -> EmbeddingProvider:
    """Initialize the embedding provider based on config. Call once at startup."""
    global _provider
    settings = get_settings()
    if settings.embedding_provider == "local":
        _provider = LocalProvider(settings.embedding_model)
    else:
        raise ValueError(f"Unknown embedding provider: {settings.embedding_provider}")
    return _provider


def get_provider() -> EmbeddingProvider:
    if _provider is None:
        raise RuntimeError("Embedding provider not initialized")
    return _provider
