from pathlib import Path


def read_log(filepath: str, lines: int = 50) -> list[str]:
    path = Path(filepath)
    if not path.exists():
        return []
    try:
        text = path.read_text()
        all_lines = text.rstrip("\n").split("\n")
        return all_lines[-lines:]
    except OSError:
        return []


def count_log_lines(filepath: str) -> int:
    path = Path(filepath)
    if not path.exists():
        return 0
    try:
        text = path.read_text()
        return len(text.rstrip("\n").split("\n")) if text.strip() else 0
    except OSError:
        return 0
