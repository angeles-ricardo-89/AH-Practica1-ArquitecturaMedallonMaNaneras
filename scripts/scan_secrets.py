#!/usr/bin/env python3
"""Escáner determinista de secretos en archivos rastreados por git.

Uso:
    scripts/scan_secrets.py [REPO_ROOT]

Recorre la salida de `git ls-files` desde REPO_ROOT (por defecto, la raíz
del repo derivada de la ubicación del script) y aplica patrones regex por
línea. Exit 0 sin hallazgos; exit 1 si encuentra algún secreto; exit 2 si
no se puede inspeccionar el repo (git ausente o raíz inexistente).
"""

import re
import subprocess
import sys
from pathlib import Path

SECRET_PATTERNS = [
    ("gemini-api-key", re.compile(r"GEMINI_API_KEY\s*=\s*[A-Za-z0-9_-]{20,}")),
    ("db-url-with-creds", re.compile(r"DATABASE_URL\s*=\s*postgres(ql)?://[^@\s]+@")),
    (
        "jwt-secret",
        re.compile(r"(?:jwt_secret|csrf_secret)\s*=\s*[A-Za-z0-9+/=]{32,}", re.IGNORECASE),
    ),
    (
        "password-assignment",
        re.compile(r"password\s*=\s*[^\s\"'${}().\[\]]{8,}", re.IGNORECASE),
    ),
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
]

TEMPLATE_SECRET_KEY = re.compile(
    r"(?:^|_)(?:secret|token|key|jwt|csrf|dsn|password)(?:_|$)|database[_-]?url",
    re.IGNORECASE,
)

TEMPLATE_ALLOWED_VALUES = {
    "POSTGRES_PASSWORD": {"mananeras"},
}

QUOTED_ASSIGNMENT = re.compile(r'(?<![=<>!])(=\s*)(["\'])([^"\']*)\2')

DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[1]


def tracked_files(root: Path) -> list[str] | None:
    try:
        result = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=root,
            capture_output=True,
        )
    except FileNotFoundError:
        print(
            "scan_secrets: no se pudo ejecutar 'git ls-files' (git ausente o raiz inexistente)",
            file=sys.stderr,
        )
        return None
    if result.returncode != 0:
        print("scan_secrets: no se pudo ejecutar 'git ls-files'", file=sys.stderr)
        return None
    return [p.decode("utf-8", "replace") for p in result.stdout.split(b"\0") if p]


def is_excluded(rel: str) -> bool:
    if rel.startswith("docs/"):
        return True
    return rel.endswith(".lock")


def strip_quoted_values(line: str) -> str:
    return QUOTED_ASSIGNMENT.sub(r"\1\3", line)


def is_placeholder_value(line: str) -> bool:
    _, sep, value = line.partition("=")
    if not sep:
        return False
    value = value.strip()
    if value == "":
        return True
    if "changeme" in value.lower():
        return True
    return value.startswith("<") and value.endswith(">")


def scan_file(path: Path, rel: str) -> list[str]:
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return []
    findings = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        line = strip_quoted_values(line)
        if is_placeholder_value(line):
            continue
        for label, pattern in SECRET_PATTERNS:
            if pattern.search(line):
                findings.append(f"{rel}:{lineno}:{label}")
    return findings


def scan_env_template(path: Path, rel: str) -> list[str]:
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return []
    findings = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = strip_quoted_values(line).strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, sep, value = stripped.partition("=")
        key = key.strip()
        if not sep or not key:
            continue
        if not TEMPLATE_SECRET_KEY.search(key):
            continue
        value = value.strip()
        allowed = TEMPLATE_ALLOWED_VALUES.get(key.upper())
        if allowed is not None and value.lower() in allowed:
            continue
        if is_placeholder_value(f"{key}={value}"):
            continue
        findings.append(f"{rel}:{lineno}:template-non-placeholder")
    return findings


def scan_repo(root: Path) -> list[str]:
    rel_files = tracked_files(root)
    if rel_files is None:
        sys.exit(2)
    findings = []
    for rel in rel_files:
        full = root / rel
        if Path(rel).name == ".env.template":
            findings.extend(scan_env_template(full, rel))
        elif not is_excluded(rel):
            findings.extend(scan_file(full, rel))
    return sorted(findings)


def main(argv: list[str]) -> int:
    root = Path(argv[1]).resolve() if len(argv) > 1 else DEFAULT_REPO_ROOT
    findings = scan_repo(root)
    for finding in findings:
        print(finding)
    if findings:
        print(f"scan_secrets: {len(findings)} hallazgo(s)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
