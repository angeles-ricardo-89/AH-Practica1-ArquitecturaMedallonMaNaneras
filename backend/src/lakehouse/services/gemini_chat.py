from __future__ import annotations

from typing import Any

from google import genai
from google.genai import types

from lakehouse.log_config import get_logger

logger = get_logger(__name__, layer="service")


class GeminiChatAdapter:
    def __init__(self, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model
        self._client: Any | None = None

    def _get_client(self) -> Any:
        if self._client is None:
            if not self._api_key:
                raise RuntimeError("GEMINI_API_KEY must be set to use Gemini chat (fail-closed)")
            self._client = genai.Client(api_key=self._api_key)
        return self._client

    def generate(
        self,
        messages: list[dict[str, str]],
        *,
        max_output_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        client = self._get_client()
        contents = [
            types.Content(role=m["role"], parts=[types.Part(text=m["content"])]) for m in messages
        ]
        config = types.GenerateContentConfig(
            max_output_tokens=max_output_tokens,
            temperature=temperature,
        )
        response = client.models.generate_content(
            model=self._model, contents=contents, config=config
        )
        return response.text
