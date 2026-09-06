#!/usr/bin/env python3
import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "governance" / "security-controls.yaml"
SCANNER = ROOT / "scripts" / "scan_secrets.py"
LOCKFILES = (ROOT / "backend" / "uv.lock", ROOT / "frontend" / "pnpm-lock.yaml")


def file_coverage(path: Path, marker: str) -> tuple[bool, str]:
    if not path.exists():
        return False, "archivo no existe"
    if marker not in path.read_text(encoding="utf-8"):
        return False, "falta marcador"
    return True, ""


def lockfiles_ok() -> tuple[bool, str]:
    missing = [str(p.relative_to(ROOT)) for p in LOCKFILES if not p.exists()]
    if missing:
        return False, "lockfiles ausentes: " + ", ".join(missing)
    return True, ""


def secrets_ok() -> tuple[bool, str]:
    result = subprocess.run(
        [sys.executable, str(SCANNER)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = (result.stdout + "\n" + result.stderr).strip() or "hallazgos detectados"
        return False, f"scan_secrets fallo: {detail}"
    return True, ""


def control_rows(control: dict[str, Any]) -> list[dict[str, str]]:
    cid = control["id"]
    title = control["title"]
    rows: list[dict[str, str]] = []
    for test in control.get("backend_tests", []):
        ok, detail = file_coverage(ROOT / "backend" / test, f'pytest.mark.security("{cid}")')
        rows.append(make_row(cid, title, f"backend: {test}", ok, detail))
    for test in control.get("frontend_tests", []):
        ok, detail = file_coverage(ROOT / "frontend" / test, f"// security: {cid}")
        rows.append(make_row(cid, title, f"frontend: {test}", ok, detail))
    for check in control.get("checks", []):
        if check == "lockfiles":
            ok, detail = lockfiles_ok()
            rows.append(make_row(cid, title, "chequeo: lockfiles", ok, detail))
        elif check == "secrets-scan":
            ok, detail = secrets_ok()
            rows.append(make_row(cid, title, "chequeo: secrets-scan", ok, detail))
        else:
            rows.append(make_row(cid, title, f"chequeo: {check}", False, f"{cid}: chequeo desconocido '{check}'"))
    return rows


def make_row(cid: str, title: str, prueba: str, ok: bool, detail: str) -> dict[str, str]:
    return {"id": cid, "control": title, "prueba": prueba, "estado": "OK" if ok else "FAIL", "detail": detail}


def render_matrix(rows: list[dict[str, str]]) -> str:
    cells = [("ID", "Control", "Prueba/chequeo", "Estado")]
    cells.extend((r["id"], r["control"], r["prueba"], r["estado"]) for r in rows)
    widths = [max(len(cells[r][i]) for r in range(len(cells))) for i in range(4)]
    lines: list[str] = []
    for index, line in enumerate(cells):
        lines.append("  ".join(line[i].ljust(widths[i]) for i in range(4)))
        if index == 0:
            lines.append("  ".join("-" * widths[i] for i in range(4)))
    return "\n".join(lines)


def summarize(rows: list[dict[str, str]]) -> None:
    failed = [r for r in rows if r["estado"] == "FAIL"]
    failed_controls = sorted({r["id"] for r in failed})
    print(f"GATE-SEC: {len(rows)} prueba(s)/chequeo(s), {len(failed)} con falla en {len(failed_controls)} control(es).")
    for row in failed:
        print(f'- {row["id"]}: {row["control"]} | {row["prueba"]} -> {row["detail"]}')


def load_catalog() -> list[dict[str, Any]]:
    try:
        raw = yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"GATE-SEC: catalogo no encontrado en {CATALOG}", file=sys.stderr)
        raise SystemExit(2)
    except yaml.YAMLError as exc:
        print(f"GATE-SEC: el catalogo {CATALOG} no es YAML valido: {exc}", file=sys.stderr)
        raise SystemExit(2)
    if not isinstance(raw, dict) or not isinstance(raw.get("controls"), list):
        print(f"GATE-SEC: el catalogo {CATALOG} debe definir 'controls' como lista", file=sys.stderr)
        raise SystemExit(2)
    controls: list[dict[str, Any]] = []
    for idx, entry in enumerate(raw["controls"]):
        if not isinstance(entry, dict):
            print(f"GATE-SEC: el control {idx} de {CATALOG} no es un mapeo valido", file=sys.stderr)
            raise SystemExit(2)
        missing = [k for k in ("id", "title", "control") if k not in entry]
        if missing:
            print(f"GATE-SEC: el control {idx} de {CATALOG} no define: {', '.join(missing)}", file=sys.stderr)
            raise SystemExit(2)
        controls.append(entry)
    return controls


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inspector determinista de controles de seguridad (GATE-SEC)",
        epilog="default: bloquea (exit 1 si hay huecos); --report: nunca bloquea",
    )
    parser.add_argument("--report", action="store_true", help="solo informa: exit 0 aunque haya fallas")
    parser.add_argument("--check", action="store_true", help="modo bloqueante (default): exit 1 si hay fallas")
    args = parser.parse_args()
    rows: list[dict[str, str]] = []
    for control in load_catalog():
        rows.extend(control_rows(control))
    print("GATE-SEC: cobertura de controles de seguridad")
    print(render_matrix(rows))
    print()
    summarize(rows)
    if args.report:
        return 0
    return 1 if any(r["estado"] == "FAIL" for r in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
