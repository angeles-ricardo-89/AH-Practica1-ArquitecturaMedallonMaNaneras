import json
import logging
import re
from pathlib import Path

import httpx

from lakehouse.config import Settings

logger = logging.getLogger(__name__)

GOLDEN_DATASET_PATH = Path(__file__).resolve().parents[3] / "data" / "golden_dataset.json"

JUDGE_SYSTEM_PROMPT = (
    "Eres un juez de calidad de respuestas. Evalúa la respuesta generada comparándola "
    "con la respuesta de referencia. Devuelve ÚNICAMENTE un número del 0 al 100 que "
    "represente el porcentaje de fidelidad (qué tan fiel es a la referencia, "
    "sin alucinaciones ni información inventada)."
)

RELEVANCE_JUDGE_PROMPT = (
    "Eres un juez de relevancia. Evalúa qué tan relevante es la respuesta generada "
    "para la pregunta del usuario. Devuelve ÚNICAMENTE un número del 0 al 100 que "
    "represente el porcentaje de relevancia."
)


def _call_llamacpp(prompt: str, system_prompt: str, settings: Settings) -> str:
    with httpx.Client(timeout=120.0) as client:
        payload = {
            "model": settings.llamacpp_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": 1024,
            "temperature": 0.1,
        }
        resp = client.post(
            f"{settings.llamacpp_base_url}/chat/completions",
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


def _call_chat(query: str, settings: Settings) -> str:
    with httpx.Client(timeout=120.0) as client:
        payload = {
            "model": settings.llamacpp_model,
            "messages": [{"role": "user", "content": query}],
            "max_tokens": 1024,
            "temperature": 0.1,
        }
        resp = client.post(
            f"{settings.llamacpp_base_url}/chat/completions",
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


def _parse_score(text: str) -> float:
    cleaned = text.strip()
    for prefix in ["fidelidad:", "relevancia:", "puntuación:", "puntaje:", "score:"]:
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


def evaluate_rag() -> dict:
    settings = Settings()

    if not GOLDEN_DATASET_PATH.exists():
        msg = f"Golden dataset not found at {GOLDEN_DATASET_PATH}"
        logger.error(msg)
        return {"status": "error", "message": msg}

    golden = json.loads(GOLDEN_DATASET_PATH.read_text())

    results = []
    for item in golden:
        qid = item["id"]
        question = item["question"]
        reference = item["reference_answer"]

        logger.info("Evaluating question %d: %s", qid, question[:60])

        try:
            answer = _call_chat(question, settings)
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
                    "error": "chat_failed",
                }
            )
            continue

        try:
            fidelity_raw = _call_llamacpp(
                prompt=f"Pregunta: {question}\n\nReferencia: {reference}\n\nRespuesta: {answer}",
                system_prompt=JUDGE_SYSTEM_PROMPT,
                settings=settings,
            )
            fidelity = _parse_score(fidelity_raw)
        except Exception:
            logger.exception("Fidelity judge failed for question %d", qid)
            fidelity = 0.0

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
            }
        )

    total = len(results)
    scored = [r for r in results if "error" not in r]
    avg_fidelity = sum(r["fidelity"] for r in scored) / len(scored) if scored else 0.0
    avg_relevance = sum(r["relevance"] for r in scored) / len(scored) if scored else 0.0

    output_path = (
        Path(GOLDEN_DATASET_PATH).resolve().parent.parent
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
        "fidelity_passed": avg_fidelity >= 90.0,
        "relevance_passed": avg_relevance >= 80.0,
        "results": results,
        "output_path": str(output_path),
    }

    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))

    logger.info(
        "Evaluation complete: fidelity=%.2f%%, relevance=%.2f%%",
        avg_fidelity,
        avg_relevance,
    )

    return report
