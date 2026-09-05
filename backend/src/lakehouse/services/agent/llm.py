from __future__ import annotations

from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from lakehouse.config import Settings


def _post(
    settings: Settings, messages: list[dict], *, json_mode: bool, max_tokens: int
) -> str:
    payload = {
        "model": settings.llamacpp_model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.1,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    with httpx.Client(timeout=60.0) as client:
        resp = client.post(
            f"{settings.llamacpp_base_url}/chat/completions",
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


def chat_json(settings: Settings, messages: list[dict], max_tokens: int = 2048) -> str:
    return _post(settings, messages, json_mode=True, max_tokens=max_tokens)


def chat_text(settings: Settings, messages: list[dict], max_tokens: int = 4096) -> str:
    return _post(settings, messages, json_mode=False, max_tokens=max_tokens)
