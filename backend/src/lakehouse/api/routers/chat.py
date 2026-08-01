import httpx
from fastapi import APIRouter

from lakehouse.config import Settings
from lakehouse.log_config import get_logger
from lakehouse.schemas.chat import ChatRequest, ChatResponse, SourceChunk
from lakehouse.services.context_builder import ContextBuilder
from lakehouse.services.rag_search import (
    _embed_query,
    search_gold_corpus_from_vector,
    search_with_date_filter,
)
from lakehouse.services.temporal_parser import TemporalParser
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

    temporal_parser = TemporalParser(settings)
    parser_result = temporal_parser.extraer(request.query)
    texto_semantico = parser_result.filter_out.texto_busqueda_semantica

    logger.info(
        "Parseo temporal completado",
        requiere_filtro=parser_result.filter_out.requiere_filtro_tiempo,
        fallback=parser_result.fallback_ocurrido,
    )

    try:
        query_embedding = _embed_query(
            texto_semantico, settings.ollama_base_url, settings.ollama_embed_model
        )
    except Exception as e:
        logger.exception("No se pudo generar embedding para la consulta")
        raise RuntimeError("Embedding backend unavailable") from e

    if parser_result.filter_out.requiere_filtro_tiempo:
        assert parser_result.filter_out.fecha_inicio is not None
        assert parser_result.filter_out.fecha_fin is not None
        results = search_with_date_filter(
            query_vector=query_embedding,
            top_k=request.top_k,
            fecha_inicio=parser_result.filter_out.fecha_inicio,
            fecha_fin=parser_result.filter_out.fecha_fin,
            settings=settings,
        )
        logger.info("Fuentes recuperadas con filtro temporal", source_count=len(results))
    else:
        results = search_gold_corpus_from_vector(query_embedding, request.top_k, settings)
        logger.info("Fuentes recuperadas para chat", source_count=len(results))

    sources = [
        SourceChunk(
            conference_date=r["conference_date"],
            conference_id=r["conference_id"],
            participant=r["participant"],
            chunk_text=r["chunk_text"],
            similarity=r["similarity"],
            conference_url=r["url"],
            pregunta_activa=r["pregunta_activa"],
        )
        for r in results
    ]

    builder = ContextBuilder(max_context_tokens=settings.max_context_tokens)
    context, token_usage = builder.build(
        query=request.query,
        system_prompt=SYSTEM_PROMPT,
        sources=sources,
        nota_fallback=parser_result.fallback_ocurrido,
        sin_resultados_rango=parser_result.filter_out.requiere_filtro_tiempo and not results,
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
                "max_tokens": 4096,
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
