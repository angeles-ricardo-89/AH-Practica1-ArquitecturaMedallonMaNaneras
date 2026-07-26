import hashlib
import re

from lakehouse.schemas.silver import DLQRejectRecord, InterventionRecord

PARTICIPANT_RE = re.compile(
    r"<strong>\s*([A-Za-zÀ-ÿ]+(?:\s+[A-Za-zÀ-ÿ]+)*?)\s*:</strong>\s*(.*?)</p>",
    re.DOTALL | re.IGNORECASE,
)

STRONG_TAG_RE = re.compile(r"<strong>(.*?)</strong>")


def _detect_participant(text: str) -> str:
    match = PARTICIPANT_RE.search(text)
    if match:
        return match.group(1).strip().upper()
    return "DESCONOCIDO"


def _clean_html_text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html)).strip()


def parse_html_to_interventions(
    raw_html: str,
    source_url: str,
    conference_date: str,
) -> list[InterventionRecord | DLQRejectRecord]:
    conference_id = hashlib.sha256(source_url.encode()).hexdigest()[:20]

    main_match = re.search(r"<main[^>]*>(.*?)</main>", raw_html, re.DOTALL | re.IGNORECASE)
    body = main_match.group(1) if main_match else raw_html

    pregunta_activa = ""
    records: list[InterventionRecord | DLQRejectRecord] = []
    chunk_index = 0

    for match in PARTICIPANT_RE.finditer(body):
        participant = match.group(1).strip().upper()
        raw_text = match.group(2)

        if participant == "PREGUNTA":
            pregunta_activa = _clean_html_text(raw_text)
            continue

        clean_text = _clean_html_text(raw_text)
        if not clean_text:
            dlq = DLQRejectRecord(
                source_record_id=f"{conference_id}_{chunk_index}",
                rejection_reason="empty_after_clean",
                raw_data=raw_text,
            )
            records.append(dlq)
            continue

        text_hash = hashlib.sha256(clean_text.encode()).hexdigest()[:6]
        intervention_key = f"{conference_id}_{chunk_index:03d}_{text_hash}"

        record = InterventionRecord(
            intervention_key=intervention_key,
            conference_id=conference_id,
            participant=participant,
            text=clean_text,
            pregunta_activa=pregunta_activa,
            chunk_index=chunk_index,
        )
        records.append(record)
        chunk_index += 1

    return records
