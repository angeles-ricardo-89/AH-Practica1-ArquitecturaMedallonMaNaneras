from pydantic import BaseModel, Field

from lakehouse.services.token_estimator import estimate_tokens


class TokenUsage(BaseModel):
    prompt: int = Field(default=0, ge=0)
    completion: int = Field(default=0, ge=0)


class ContextBuilder:
    def __init__(self, max_context_tokens: int = 8192) -> None:
        self.max_context_tokens = max_context_tokens

    def build(
        self,
        query: str,
        system_prompt: str,
        sources: list | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> tuple[str, TokenUsage]:
        sources = sources or []
        history = history or []

        sources_text = self._format_sources(sources)

        system_and_query = f"{system_prompt}\n\n{sources_text}\n\n{query}"
        system_and_query_tokens = estimate_tokens(system_and_query)

        if system_and_query_tokens > self.max_context_tokens:
            system_prompt_tokens = estimate_tokens(system_prompt)
            available = self.max_context_tokens - system_prompt_tokens
            sources_text = self._truncate_to_tokens(sources_text, available // 2)

        system_and_query = f"{system_prompt}\n\n{sources_text}\n\n{query}"
        base_tokens = estimate_tokens(system_and_query)

        max_history_tokens = self.max_context_tokens - base_tokens
        max_history_tokens = max(max_history_tokens, 0)

        context = f"{system_prompt}\n\n"
        if sources_text.strip():
            context += f"Fuentes:\n{sources_text}\n\n"
        context += self._truncate_history_to_tokens(history, max_history_tokens)
        context += f"Pregunta: {query}"

        prompt_tokens = estimate_tokens(context)
        usage = TokenUsage(prompt=prompt_tokens, completion=0)
        return context, usage

    def _format_sources(self, sources: list) -> str:
        lines = []
        for i, src in enumerate(sources, 1):
            lines.append(f"[{i}] {src.participant} ({src.conference_date}): {src.chunk_text}")
        return "\n".join(lines)

    def _format_history(self, history: list[dict[str, str]]) -> str:
        lines = []
        for msg in history:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            lines.append(f"{role}: {content}")
        return "\n".join(lines)

    def _truncate_to_tokens(self, text: str, max_tokens: int) -> str:
        if max_tokens <= 0:
            return ""
        chars = max_tokens * 4
        return text[:chars]

    def _truncate_history_to_tokens(
        self,
        history: list[dict[str, str]],
        max_tokens: int,
    ) -> str:
        if not history or max_tokens <= 0:
            return ""
        lines = []
        total_tokens = 0
        for msg in reversed(history):
            text = f"{msg.get('role', 'unknown')}: {msg.get('content', '')}\n"
            tokens = estimate_tokens(text)
            if total_tokens + tokens > max_tokens:
                break
            lines.insert(0, text)
            total_tokens += tokens
        return "Historial:\n" + "".join(lines) + "\n" if lines else ""
