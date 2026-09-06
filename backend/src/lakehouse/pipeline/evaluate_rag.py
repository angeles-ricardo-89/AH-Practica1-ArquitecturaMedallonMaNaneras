import json
import re
from pathlib import Path
from typing import NotRequired, TypedDict

import httpx

from lakehouse.config import Settings
from lakehouse.log_config import ProgressReporter, get_logger
from lakehouse.services.context_builder import ContextBuilder
from lakehouse.services.rag_search import search_sources
from lakehouse.services.token_estimator import estimate_tokens

logger = get_logger(__name__, layer="qa")

GOLDEN_DATASET_PATH = Path(__file__).resolve().parents[3] / "data" / "golden_dataset.json"

FIDELITY_JUDGE_PROMPT = (
    "Eres un juez de calidad de respuestas RAG. Tu tarea es evaluar si la respuesta "
    "generada es FIEL a las fuentes proporcionadas. La fidelidad mide si la respuesta "
    "se basa en la informacion contenida en las fuentes, sin inventar datos, numeros, "
    "nombres o afirmaciones que no aparezcan en ellas.\n\n"
    "Criterios de evaluacion:\n"
    "- 100: La respuesta se basa enteramente en las fuentes. No contiene informacion "
    "que no este presente en ellas.\n"
    "- 70-95: La respuesta se basa en las fuentes, con algun detalle menor que "
    "extrapola ligeramente pero no contradice las fuentes.\n"
    "- 40-65: Buena parte de la respuesta es fiel, pero contiene varias "
    "afirmaciones no respaldadas por las fuentes.\n"
    "- 10-35: La respuesta contiene mas invencion que informacion de las fuentes.\n"
    "- 0: La respuesta contradice directamente las fuentes o es completamente inventada.\n\n"
    "IMPORTANTE: Si la respuesta indica que no hay informacion en las fuentes y "
    "efectivamente las fuentes no contienen informacion relevante para la pregunta, "
    "la fidelidad es 100. Si las fuentes SI contienen informacion pero la respuesta "
    "dice que no, la fidelidad es baja.\n\n"
    "Se indulgente con afirmaciones generales o de sentido comun que no contradigan "
    "las fuentes. Penaliza solo informacion concreta que no encuentres respaldada.\n\n"
    "Devuelve UNICAMENTE un numero del 0 al 100."
)

COVERAGE_JUDGE_PROMPT = (
    "Eres un juez de cobertura de respuestas. Evalua que tan completa es la respuesta "
    "generada en comparacion con la respuesta de referencia. La cobertura mide si la "
    "respuesta generada cubre los temas y datos clave de la referencia.\n\n"
    "Criterios de evaluacion:\n"
    "- 100: Cubre todos los temas clave de la referencia con precision.\n"
    "- 50-99: Cubre la mayoria de los temas, pero omite algunos detalles importantes.\n"
    "- 1-49: Cubre pocos temas de la referencia.\n"
    "- 0: No cubre ningun tema de la referencia o la respuesta es vacia.\n\n"
    "Devuelve UNICAMENTE un numero del 0 al 100."
)


class EvalResult(TypedDict):
    id: int
    question: str
    answer: str
    fidelity: float
    relevance: float
    coverage: float
    error: NotRequired[str]


RELEVANCE_JUDGE_PROMPT = (
    "Eres un juez de relevancia. Evalua que tan relevante es la respuesta generada "
    "para la pregunta del usuario. Devuelve UNICAMENTE un numero del 0 al 100 que "
    "represente el porcentaje de relevancia."
)

RAG_SYSTEM_PROMPT = (
    "Eres un asistente especializado en las conferencias matutinas "
    "(Mananeras) del Gobierno de Mexico. Responde preguntas basandote "
    "en las fuentes proporcionadas. Si no encuentras informacion en las "
    "fuentes, indica que no tienes informacion al respecto."
)


def _call_llamacpp(prompt: str, system_prompt: str, settings: Settings) -> str:
    with httpx.Client(timeout=120.0) as client:
        payload = {
            "model": settings.llamacpp_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": 2048,
            "temperature": 0.1,
        }
        resp = client.post(
            f"{settings.llamacpp_base_url}/chat/completions",
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


def _extract_sources_text(context: str) -> str:
    parts = context.split("\n\nFuentes:\n", 1)
    if len(parts) < 2:
        return ""
    rest = parts[1]
    end_markers = ["\n\nHistorial:", "\n\nPregunta:"]
    for marker in end_markers:
        if marker in rest:
            rest = rest.split(marker, 1)[0]
            break
    return rest.strip()


def _call_chat_rag(query: str, settings: Settings, top_k: int = 8) -> tuple[str, str, str]:
    sources = search_sources(query, top_k)
    builder = ContextBuilder(max_context_tokens=settings.max_context_tokens)
    context, _ = builder.build(
        query=query,
        system_prompt=RAG_SYSTEM_PROMPT,
        sources=sources,
    )
    sources_text = _extract_sources_text(context)
    with httpx.Client(timeout=120.0) as client:
        payload = {
            "model": settings.llamacpp_model,
            "messages": [
                {"role": "system", "content": RAG_SYSTEM_PROMPT},
                {"role": "user", "content": context},
            ],
            "max_tokens": 2048,
            "temperature": 0.1,
        }
        resp = client.post(
            f"{settings.llamacpp_base_url}/chat/completions",
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"], context, sources_text


def _format_sources_for_judge(sources_text: str, max_tokens: int = 5000) -> str:
    if estimate_tokens(sources_text) <= max_tokens:
        return sources_text
    max_chars = max_tokens * 4
    truncated = sources_text[:max_chars]
    last_newline = truncated.rfind("\n")
    if last_newline > max_chars // 2:
        truncated = truncated[:last_newline]
    return truncated + "\n\n[fuentes truncadas por limite de tokens]"


def _parse_score(text: str) -> float:
    cleaned = text.strip()
    for prefix in [
        "fidelidad:",
        "relevancia:",
        "cobertura:",
        "puntuacion:",
        "puntaje:",
        "score:",
    ]:
        if cleaned.lower().startswith(prefix):
            cleaned = cleaned[len(prefix) :].strip()
    numbers = re.findall(r"\d+\.?\d*", cleaned)
    for num in numbers:
        try:
            val = float(num)
            if 0 <= val <= 100:
                return val
        except ValueError:
            continue
    return 50.0


def evaluate_rag(output_path: Path | None = None) -> dict:
    settings = Settings()

    if not GOLDEN_DATASET_PATH.exists():
        msg = f"Golden dataset not found at {GOLDEN_DATASET_PATH}"
        logger.error(msg)
        return {"status": "error", "message": msg}

    golden = json.loads(GOLDEN_DATASET_PATH.read_text())

    results: list[EvalResult] = []
    reporter = ProgressReporter(total=len(golden), label="qa")
    for idx, item in enumerate(golden):
        qid = item["id"]
        question = item["question"]
        reference = item["reference_answer"]
        reporter.update(idx + 1)

        logger.info("Evaluating question %d: %s", qid, question[:60])

        sources_text = ""
        try:
            answer, __, sources_text = _call_chat_rag(question, settings)
        except Exception:
            logger.exception("Chat failed for question %d", qid)
            answer = ""

        if not answer:
            results.append(
                {
                    "id": qid,
                    "question": question,
                    "answer": "",
                    "fidelity": 0.0,
                    "relevance": 0.0,
                    "coverage": 0.0,
                    "error": "chat_failed",
                }
            )
            continue

        try:
            sources_for_judge = _format_sources_for_judge(sources_text)
            fidelity_raw = _call_llamacpp(
                prompt=(
                    f"Pregunta: {question}\n\nFuentes:\n{sources_for_judge}\n\nRespuesta: {answer}"
                ),
                system_prompt=FIDELITY_JUDGE_PROMPT,
                settings=settings,
            )
            fidelity = _parse_score(fidelity_raw)
        except Exception:
            logger.exception("Fidelity judge failed for question %d", qid)
            fidelity = 0.0

        try:
            coverage_raw = _call_llamacpp(
                prompt=(f"Pregunta: {question}\n\nReferencia: {reference}\n\nRespuesta: {answer}"),
                system_prompt=COVERAGE_JUDGE_PROMPT,
                settings=settings,
            )
            coverage = _parse_score(coverage_raw)
        except Exception:
            logger.exception("Coverage judge failed for question %d", qid)
            coverage = 0.0

        try:
            relevance_raw = _call_llamacpp(
                prompt=f"Pregunta: {question}\n\nRespuesta: {answer}",
                system_prompt=RELEVANCE_JUDGE_PROMPT,
                settings=settings,
            )
            relevance = _parse_score(relevance_raw)
        except Exception:
            logger.exception("Relevance judge failed for question %d", qid)
            relevance = 0.0

        results.append(
            {
                "id": qid,
                "question": question,
                "answer": answer,
                "fidelity": fidelity,
                "relevance": relevance,
                "coverage": coverage,
            }
        )

    reporter.finish()
    total = len(results)
    scored = [r for r in results if "error" not in r]
    avg_fidelity = sum(r["fidelity"] for r in scored) / len(scored) if scored else 0.0
    avg_relevance = sum(r["relevance"] for r in scored) / len(scored) if scored else 0.0
    avg_coverage = sum(r["coverage"] for r in scored) / len(scored) if scored else 0.0

    output_path = output_path or (
        Path(GOLDEN_DATASET_PATH).resolve().parent
        / "lakehouse"
        / "logs"
        / "evaluate_rag_results.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    report = {
        "status": "completed",
        "total": total,
        "scored": len(scored),
        "failed": total - len(scored),
        "avg_fidelity": round(avg_fidelity, 2),
        "avg_relevance": round(avg_relevance, 2),
        "avg_coverage": round(avg_coverage, 2),
        "fidelity_passed": avg_fidelity >= 90.0,
        "relevance_passed": avg_relevance >= 80.0,
        "coverage_passed": avg_coverage >= 70.0,
        "results": results,
        "output_path": str(output_path),
    }

    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))

    logger.info(
        "Evaluation complete: fidelity=%.2f%%, relevance=%.2f%%, coverage=%.2f%%",
        avg_fidelity,
        avg_relevance,
        avg_coverage,
    )

    return report
