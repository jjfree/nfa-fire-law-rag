import hashlib
import math
import re
from abc import ABC, abstractmethod

from app.config import get_settings


class Embedder(ABC):
    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError


class HashEmbedder(Embedder):
    """Dependency-free deterministic fallback.

    Uses Unicode character n-gram feature hashing. It is not a substitute for a trained
    multilingual embedding model, but it keeps the complete pgvector pipeline runnable
    without external credentials and performs reasonably for overlapping Chinese terms.
    """

    def __init__(self, dim: int = 384):
        self.dim = dim

    @staticmethod
    def _grams(text: str) -> list[str]:
        text = re.sub(r"\s+", "", text.lower())
        grams: list[str] = []
        for n in (1, 2, 3):
            grams.extend(text[i : i + n] for i in range(max(0, len(text) - n + 1)))
        return grams

    def _one(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for gram in self._grams(text):
            digest = hashlib.blake2b(gram.encode("utf-8"), digest_size=8).digest()
            value = int.from_bytes(digest, "little")
            idx = value % self.dim
            sign = -1.0 if (value >> 63) else 1.0
            vec[idx] += sign
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(text) for text in texts]


class OpenAIEmbedder(Embedder):
    def __init__(self, api_key: str, model: str, dim: int):
        from openai import OpenAI

        if not api_key:
            raise ValueError("OPENAI_API_KEY is required when EMBEDDING_PROVIDER=openai")
        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        result = self.client.embeddings.create(model=self.model, input=texts, dimensions=self.dim)
        return [item.embedding for item in result.data]


def get_embedder() -> Embedder:
    settings = get_settings()
    if settings.embedding_provider.lower() == "openai":
        return OpenAIEmbedder(
            api_key=settings.openai_api_key,
            model=settings.openai_embedding_model,
            dim=settings.embedding_dim,
        )
    return HashEmbedder(settings.embedding_dim)
