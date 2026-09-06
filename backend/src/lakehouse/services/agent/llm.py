from __future__ import annotations

from typing import TYPE_CHECKING

import httpx

from lakehouse.services.gemini_chat import GeminiChatAdapter

if TYPE_CHECKING:
    from lakehouse.config import Settings


def active_chat_model(settings: Settings) -> str:
    """Modelo generativo activo segun entorno (Gemini en produccion)."""
    if settings.is_production:
        return settings.gemini_chat_model
    return settings.llamacpp_model


def _post(
    settings: Settings,
    messages: list[dict],
    *,
    json_mode: bool,
    max_tokens: int,
    temperature: float,
) -> str:
    payload = {
        "model": settings.llamacpp_model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
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


def _dispatch(
    settings: Settings,
    messages: list[dict],
    *,
    json_mode: bool,
    max_tokens: int,
    temperature: float,
) -> str:
    """Genera el texto con el proveedor activo: Gemini en produccion, llama.cpp local."""
    if settings.is_production:
        adapter = GeminiChatAdapter(settings.gemini_api_key, settings.gemini_chat_model)
        return adapter.generate(
            messages,
            max_output_tokens=max_tokens,
            temperature=temperature,
            response_mime_type="application/json" if json_mode else None,
        )
    return _post(
        settings,
        messages,
        json_mode=json_mode,
        max_tokens=max_tokens,
        temperature=temperature,
    )


def chat_json(
    settings: Settings,
    messages: list[dict],
    max_tokens: int = 2048,
    temperature: float = 0.1,
) -> str:
    return _dispatch(
        settings, messages, json_mode=True, max_tokens=max_tokens, temperature=temperature
    )


def chat_text(
    settings: Settings,
    messages: list[dict],
    max_tokens: int = 4096,
    temperature: float = 0.1,
) -> str:
    return _dispatch(
        settings, messages, json_mode=False, max_tokens=max_tokens, temperature=temperature
    )
