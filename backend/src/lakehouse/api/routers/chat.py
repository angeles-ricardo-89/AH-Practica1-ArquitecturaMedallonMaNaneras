import httpx
from fastapi import APIRouter

from lakehouse.config import Settings
from lakehouse.log_config import get_logger
from lakehouse.schemas.chat import ChatRequest, ChatResponse, SourceChunk
from lakehouse.services.context_builder import ContextBuilder
from lakehouse.services.rag_search import search_sources
from lakehouse.services.token_estimator import estimate_tokens

logger = get_logger(__name__, layer="api")
router = APIRouter(prefix="/chat", tags=["chat"])

SYSTEM_PROMPT = (
    "Eres un asistente especializado en las conferencias matutinas "
    "(Mañaneras) del Gobierno de México. Responde preguntas basándote "
    "en las fuentes proporcionadas. Si no encuentras información en las "
    "fuentes, indica que no tienes información al respecto."
)


@router.post(
    "/",
    response_model=ChatResponse,
    summary="Chat with RAG",
    description="Send a query and get an answer with sources from the RAG corpus",
)
def chat(request: ChatRequest) -> ChatResponse:
    settings = Settings()
    logger.info(
        "Chat request recibido",
        query=request.query[:100],
        top_k=request.top_k,
    )
    sources = search_sources(request.query, request.top_k)
    logger.info("Fuentes recuperadas para chat", source_count=len(sources))
    builder = ContextBuilder(max_context_tokens=settings.max_context_tokens)
    context, token_usage = builder.build(
        query=request.query,
        system_prompt=SYSTEM_PROMPT,
        sources=sources,
    )
    logger.info("Contexto construido para LLM", tokens_estimados=token_usage)
    try:
        with httpx.Client(timeout=60.0) as client:
            payload = {
                "model": settings.llamacpp_model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": context},
                ],
                "max_tokens": 1024,
            }
            resp = client.post(
                f"{settings.llamacpp_base_url}/chat/completions",
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            answer = data["choices"][0]["message"]["content"]
            prompt_tokens = data.get("usage", {}).get("prompt_tokens", estimate_tokens(context))
            completion_tokens = data.get("usage", {}).get(
                "completion_tokens", estimate_tokens(answer)
            )
            logger.info(
                "Chat response generado",
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
    except Exception as e:
        logger.exception("Backend LLM no disponible")
        raise RuntimeError("LLM backend unavailable") from e
    return ChatResponse(
        answer=answer,
        sources=sources,
        token_usage={
            "prompt": prompt_tokens,
            "completion": completion_tokens,
        },
    )
