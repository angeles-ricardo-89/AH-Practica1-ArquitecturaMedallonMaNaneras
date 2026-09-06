from __future__ import annotations

import math
from typing import Any

from google import genai
from google.genai import types

from lakehouse.log_config import get_logger

logger = get_logger(__name__, layer="service")

RETRIEVAL_DOCUMENT = "RETRIEVAL_DOCUMENT"
RETRIEVAL_QUERY = "RETRIEVAL_QUERY"


class GeminiEmbeddingAdapter:
    def __init__(self, api_key: str, model: str, dimension: int = 768) -> None:
        self._api_key = api_key
        self._model = model
        self._dimension = dimension
        self._client: Any | None = None

    def _get_client(self) -> Any:
        if self._client is None:
            if not self._api_key:
                raise RuntimeError(
                    "GEMINI_API_KEY must be set to use Gemini embeddings (fail-closed)"
                )
            self._client = genai.Client(api_key=self._api_key)
        return self._client

    def _normalize(self, vector: list[float]) -> list[float]:
        norm = math.sqrt(sum(x * x for x in vector))
        if norm == 0:
            return vector
        return [x / norm for x in vector]

    def _validate_dimension(self, vector: list[float]) -> list[float]:
        if len(vector) != self._dimension:
            raise RuntimeError(
                f"Gemini embedding dimension mismatch: expected {self._dimension}, "
                f"got {len(vector)}"
            )
        return vector

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        client = self._get_client()
        config = types.EmbedContentConfig(
            task_type=RETRIEVAL_DOCUMENT,
            output_dimensionality=self._dimension,
        )
        response = client.models.embed_content(model=self._model, contents=texts, config=config)
        return [
            self._validate_dimension(self._normalize(list(e.values))) for e in response.embeddings
        ]

    def embed_query(self, text: str) -> list[float]:
        client = self._get_client()
        config = types.EmbedContentConfig(
            task_type=RETRIEVAL_QUERY,
            output_dimensionality=self._dimension,
        )
        response = client.models.embed_content(model=self._model, contents=[text], config=config)
        return self._validate_dimension(self._normalize(list(response.embeddings[0].values)))
