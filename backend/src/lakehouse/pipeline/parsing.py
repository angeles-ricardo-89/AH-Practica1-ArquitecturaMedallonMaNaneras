import hashlib
import html as html_mod
import re

from lakehouse.log_config import get_logger
from lakehouse.schemas.silver import ConferenceRecord, DLQRejectRecord, InterventionRecord

logger = get_logger(__name__, layer="silver")

_MESES = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}

# PARTICIPANT_RE = re.compile(
#     r"<strong>\s*([A-Za-zÀ-ÿ&;0-9#,]+(?:\s+[A-Za-zÀ-ÿ&;0-9#,]+)*?)\s*:</strong>\s*(.*?)</p>",
#     re.DOTALL | re.IGNORECASE,
# )



PARTICIPANT_RE = re.compile(
    r"<strong>\s*([A-Za-zÀ-ÿ&;0-9#,]+(?:\s+[A-Za-zÀ-ÿ&;0-9#,]+)*?)\s*:</strong>\s*(.+?)</p>",
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


def _extract_title(raw_html: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", raw_html, re.DOTALL | re.IGNORECASE)
    if match:
        return html_mod.unescape(match.group(1).strip())
    return ""


def parse_conference_date(raw_html: str, source_url: str) -> str | None:
    html_match = re.search(
        r"Presidencia\s+de\s+la\s+República\s*\|\s*(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})",
        raw_html,
    )
    if html_match:
        day, month_name, year = html_match.groups()
        month = _MESES.get(month_name.lower())
        if month:
            return f"{year}-{month:02d}-{int(day):02d}"

    url_match = re.search(r"(\d{1,2})-de-(\w+)-de-(\d{4})", source_url)
    if url_match:
        day, month_name, year = url_match.groups()
        month = _MESES.get(month_name.lower())
        if month:
            return f"{year}-{month:02d}-{int(day):02d}"

    return None


def build_conference_record(
    source_url: str,
    conference_date: str,
    raw_html: str,
) -> ConferenceRecord:
    conference_id = hashlib.sha256(source_url.encode()).hexdigest()[:20]
    title = _extract_title(raw_html) or f"Conferencia {conference_date}"
    return ConferenceRecord(
        conference_id=conference_id,
        date=conference_date,
        title=title,
        url=source_url,
    )


def parse_html_to_interventions(
    raw_html: str,
    source_url: str,
    conference_date: str,
) -> list[InterventionRecord | DLQRejectRecord]:
    conference_id = hashlib.sha256(source_url.encode()).hexdigest()[:20]
    logger.info(
        "Parseando HTML a intervenciones", source_url=source_url, conference_id=conference_id
    )

    main_match = re.search(r"<main[^>]*>(.*?)</main>", raw_html, re.DOTALL | re.IGNORECASE)
    body = main_match.group(1) if main_match else raw_html

    pregunta_activa = ""
    records: list[InterventionRecord | DLQRejectRecord] = []
    chunk_index = 0

    body_decoded = html_mod.unescape(body)

    for match in PARTICIPANT_RE.finditer(body_decoded):
        participant = match.group(1).strip().upper()
        raw_text = match.group(2)

        if participant == "PREGUNTA":
            pregunta_activa = _clean_html_text(raw_text)
            logger.info("Pregunta activa detectada", pregunta=pregunta_activa)
            continue

        clean_text = _clean_html_text(raw_text)
        if not clean_text:
            dlq = DLQRejectRecord(
                source_record_id=f"{conference_id}_{chunk_index}",
                rejection_reason="empty_after_clean",
                raw_data=raw_text or "[empty content]",
            )
            records.append(dlq)
            logger.warning(
                "Intervención enviada a DLQ: texto vacío tras limpieza",
                participant=participant,
                chunk_index=chunk_index,
            )
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
            url=source_url,
        )
        records.append(record)
        chunk_index += 1

    logger.info(
        "Parseo completado",
        source_url=source_url,
        interventions=len([r for r in records if not isinstance(r, DLQRejectRecord)]),
        dlq=len([r for r in records if isinstance(r, DLQRejectRecord)]),
    )
    return records
