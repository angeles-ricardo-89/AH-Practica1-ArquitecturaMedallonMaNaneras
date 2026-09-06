from __future__ import annotations

from typing import Any

from google import genai
from google.genai import types

from lakehouse.log_config import get_logger

logger = get_logger(__name__, layer="service")

_ROLE_MAP = {
    "user": "user",
    "assistant": "model",
    "model": "model",
    "tool": "user",
}


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

    def _prepare(self, messages: list[dict[str, str]]) -> tuple[list[types.Content], str | None]:
        """Mapea roles OpenAI-style a Gemini y extrae el system prompt.

        Gemini solo acepta roles ``user`` y ``model``; el system prompt se pasa
        como ``system_instruction`` (no como mensaje).
        """
        system_parts: list[str] = []
        contents: list[types.Content] = []
        for message in messages:
            role = str(message.get("role", "user"))
            content = str(message.get("content", ""))
            if role == "system":
                system_parts.append(content)
                continue
            gemini_role = _ROLE_MAP.get(role, "user")
            contents.append(types.Content(role=gemini_role, parts=[types.Part(text=content)]))
        system_instruction = "\n".join(system_parts) if system_parts else None
        return contents, system_instruction

    def generate(
        self,
        messages: list[dict[str, str]],
        *,
        max_output_tokens: int | None = None,
        temperature: float | None = None,
        response_mime_type: str | None = None,
    ) -> str:
        client = self._get_client()
        contents, system_instruction = self._prepare(messages)
        config = types.GenerateContentConfig(
            max_output_tokens=max_output_tokens,
            temperature=temperature,
            response_mime_type=response_mime_type,
            system_instruction=system_instruction,
        )
        response = client.models.generate_content(
            model=self._model, contents=contents, config=config
        )
        return response.text
