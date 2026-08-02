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

P_TAG_RE = re.compile(r"<p[^>]*>(.*?)</p>", re.DOTALL | re.IGNORECASE)
STRONG_CONTENT_RE = re.compile(r"<strong>(.*?)</strong>", re.IGNORECASE)
PARTICIPANT_RE = re.compile(
    r"<strong>\s*([A-Za-zÀ-ÿ&;0-9#,]+(?:\s+[A-Za-zÀ-ÿ&;0-9#,]+)*?)\s*:</strong>\s*(.+?)</p>",
    re.DOTALL | re.IGNORECASE,
)


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


def _build_intervention_key(conference_id: str, chunk_index: int, text: str) -> str:
    text_hash = hashlib.sha256(text.encode()).hexdigest()[:6]
    return f"{conference_id}_{chunk_index:03d}_{text_hash}"


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
    body_decoded = html_mod.unescape(body)

    records: list[InterventionRecord | DLQRejectRecord] = []
    chunk_index = 0
    pregunta_activa = ""
    current_participant: str | None = None
    accumulated_texts: list[str] = []

    def flush_intervention() -> None:
        nonlocal chunk_index
        if current_participant is None or not accumulated_texts:
            return
        full_text = " ".join(accumulated_texts).strip()
        accumulated_texts.clear()
        if not full_text:
            dlq = DLQRejectRecord(
                source_record_id=f"{conference_id}_{chunk_index}",
                rejection_reason="empty_after_clean",
                raw_data="[empty accumulated content]",
            )
            records.append(dlq)
            return
        intervention_key = _build_intervention_key(conference_id, chunk_index, full_text)
        record = InterventionRecord(
            intervention_key=intervention_key,
            conference_id=conference_id,
            participant=current_participant,
            text=full_text,
            pregunta_activa=pregunta_activa,
            chunk_index=chunk_index,
            url=source_url,
        )
        records.append(record)
        chunk_index += 1

    for p_match in P_TAG_RE.finditer(body_decoded):
        p_content = p_match.group(1)
        strong_match = STRONG_CONTENT_RE.search(p_content)

        if strong_match:
            inner_strong = _clean_html_text(strong_match.group(1))
            is_pregunta = inner_strong.upper().startswith("PREGUNTA:")
            if not is_pregunta:
                colon_idx = inner_strong.find(":")
                is_pregunta = (
                    colon_idx > 0 and inner_strong[:colon_idx].strip().upper() == "PREGUNTA"
                )

            if is_pregunta:
                flush_intervention()

                pregunta_inside = inner_strong[len("PREGUNTA") :].strip()
                if pregunta_inside.startswith(":"):
                    pregunta_inside = pregunta_inside[1:].strip()

                if pregunta_inside:
                    pregunta_activa = pregunta_inside
                else:
                    r_extended = p_content + "</p>"
                    part_match = PARTICIPANT_RE.match(r_extended)
                    if part_match and part_match.group(1).strip().upper() == "PREGUNTA":
                        pregunta_activa = _clean_html_text(part_match.group(2))

                logger.info("Pregunta activa detectada", pregunta=pregunta_activa[:200])
                continue

            p_extended = p_content + "</p>"
            part_match = PARTICIPANT_RE.match(p_extended)
            if part_match:
                participant = part_match.group(1).strip().upper()
                raw_text = part_match.group(2)
                clean_text = _clean_html_text(raw_text)

                flush_intervention()
                if not clean_text:
                    dlq = DLQRejectRecord(
                        source_record_id=f"{conference_id}_{chunk_index}",
                        rejection_reason="empty_after_clean",
                        raw_data=raw_text or "[empty content]",
                    )
                    records.append(dlq)
                    current_participant = None
                else:
                    current_participant = participant
                    accumulated_texts.append(clean_text)
                continue

        if current_participant is not None:
            clean = _clean_html_text(p_content)
            if clean:
                accumulated_texts.append(clean)

    flush_intervention()

    logger.info(
        "Parseo completado",
        source_url=source_url,
        interventions=len([r for r in records if not isinstance(r, DLQRejectRecord)]),
        dlq=len([r for r in records if isinstance(r, DLQRejectRecord)]),
        parrafos_sin_strong=sum(
            1 for _ in P_TAG_RE.finditer(body_decoded) if not STRONG_CONTENT_RE.search(_.group(1))
        ),
        parrafos_con_strong=sum(
            1 for _ in P_TAG_RE.finditer(body_decoded) if STRONG_CONTENT_RE.search(_.group(1))
        ),
    )
    return records
