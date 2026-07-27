import json
from datetime import UTC, datetime
from pathlib import Path


def read_status(filepath: str) -> dict:
    path = Path(filepath)
    if not path.exists():
        return {"status": "unknown"}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {"status": "unknown"}


def write_status(filepath: str, status: str) -> None:
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    data: dict[str, str | int] = {
        "status": status,
        "last_run": now,
    }
    if status == "ok":
        data["last_success"] = now
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))
