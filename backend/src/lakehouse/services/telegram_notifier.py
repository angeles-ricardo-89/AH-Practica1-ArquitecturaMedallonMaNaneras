from __future__ import annotations

import httpx

from lakehouse.log_config import get_logger

logger = get_logger(__name__, layer="service")

_TELEGRAM_API = "https://api.telegram.org"
_QUESTION_LIMIT = 500
_ANSWER_LIMIT = 3000


def build_notification(question: str, answer: str) -> str:
    question = question[:_QUESTION_LIMIT]
    answer = answer[:_ANSWER_LIMIT]
    return f"Nueva consulta en el chat\n\nPregunta: {question}\nRespuesta: {answer}"


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str) -> None:
        self._token = token
        self._chat_id = chat_id

    @property
    def is_enabled(self) -> bool:
        return bool(self._token and self._chat_id)

    def send(self, text: str) -> bool:
        if not self.is_enabled:
            return False
        url = f"{_TELEGRAM_API}/bot{self._token}/sendMessage"
        payload = {"chat_id": self._chat_id, "text": text}
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.post(url, json=payload)
        except Exception:
            logger.exception("Telegram: error de red enviando notificacion")
            return False

        if resp.status_code != 200:
            logger.warning("Telegram: envio fallido (status=%s)", resp.status_code)
            return False

        try:
            ok = bool(resp.json().get("ok"))
        except ValueError:
            logger.warning("Telegram: respuesta no JSON")
            return False

        if not ok:
            logger.warning("Telegram: devolvio ok=false")
        return ok
