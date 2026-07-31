from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from .models import CorridaEvaluacion, Estado, ResultadoCriterio, Evidencia
from .criterios.bronce import evaluar_bronce
from .criterios.plata import evaluar_plata
from .criterios.idempotencia import evaluar_idempotencia
from .criterios.oro import evaluar_oro
from .reporte import generar_reporte


RUN_DIR_BASE = Path(__file__).resolve().parents[2] / "runs"
PROJECT_ROOT = Path(__file__).resolve().parents[3]
BACKEND_DIR = PROJECT_ROOT / "backend"
TEMP_DIR = Path(__file__).resolve().parents[2] / ".tmp"
CACHE_DIR = Path(__file__).resolve().parents[2] / ".cache"


def _get_git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "-1"],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=10,
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except Exception:
        return None


def _preparar_directorio() -> tuple[Path, str]:
    run_id = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
    run_dir = RUN_DIR_BASE / run_id
    (run_dir / "logs").mkdir(parents=True, exist_ok=True)
    (run_dir / "evidencias").mkdir(parents=True, exist_ok=True)
    (run_dir / "comandos").mkdir(parents=True, exist_ok=True)
    return run_dir, run_id


def _escribir_log(run_dir: Path, nivel: str, test_id: str, mensaje: str):
    timestamp = datetime.now(UTC).isoformat()
    linea = f"{timestamp} | {nivel:8s} | {test_id:6s} | {mensaje}\n"
    with open(run_dir / "logs" / "evaluacion.log", "a") as f:
        f.write(linea)


def _guardar_evidencias(run_dir: Path, resultados: list[ResultadoCriterio]):
    for r in resultados:
        for ev in r.hallazgos_evidencia:
            target = run_dir / ev.path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(ev.contenido, encoding="utf-8")
            r.evidence.append(ev.path)


def _sanitizar_secretos(texto: str) -> str:
    import re
    texto = re.sub(r'(password|passwd|pwd|secret|token|api_key|apikey)\s*[:=]\s*\S+',
                   r'\1: ***', texto, flags=re.IGNORECASE)
    texto = re.sub(r'postgresql://[^@]+@', r'postgresql://***@', texto)
    return texto


def _guardar_comandos(run_dir: Path, corrida: CorridaEvaluacion):
    lines = []
    for e in corrida.ejecuciones:
        lines.append(f"# Comando: {e.comando}")
        lines.append(f"# Codigo salida: {e.codigo_salida}")
        lines.append(f"# Duracion: {e.duracion_ms}ms")
        if e.excepcion:
            lines.append(f"# Excepcion: {e.excepcion}")
        lines.append("--- STDOUT ---")
        lines.append(_sanitizar_secretos(e.stdout))
        lines.append("--- STDERR ---")
        lines.append(_sanitizar_secretos(e.stderr))
        lines.append("")
    (run_dir / "comandos" / "ejecuciones.log").write_text("\n".join(lines), encoding="utf-8")


def _validar_rutas_permitidas():
    ok = True
    for root, dirs, files in os.walk(PROJECT_ROOT):
        root_path = Path(root)
        if "/.git/" in root or "/.venv/" in root or "/__pycache__/" in root or "/.worktrees/" in root:
            continue
        rel = root_path.relative_to(PROJECT_ROOT)
        if str(rel).startswith("evaluacion/"):
            continue
        if str(rel) == ".":
            continue
        for f in files:
            fpath = root_path / f
            if fpath == PROJECT_ROOT / "Makefile":
                continue
            mtime = os.path.getmtime(fpath)
            import time
            if time.time() - mtime < 300:
                print(f"ADVERTENCIA: Archivo modificado recientemente fuera de evaluacion/: {fpath}")
                ok = False
    return ok


def main():
    run_dir, run_id = _preparar_directorio()
    os.environ["TMPDIR"] = str(TEMP_DIR)
    os.environ["UV_CACHE_DIR"] = str(CACHE_DIR)

    corrida = CorridaEvaluacion(
        run_id=run_id,
        started_at=datetime.now(UTC),
        commit=_get_git_commit(),
        directorio=str(run_dir),
    )

    _escribir_log(run_dir, "INFO", "SYS", f"Iniciando evaluacion: {run_id}")
    _escribir_log(run_dir, "INFO", "SYS", f"Directorio: {run_dir}")

    corrida.supuestos.append(
        "El pipeline usa el sitio gob.mx/presidencia como fuente de datos publica"
    )
    corrida.supuestos.append(
        "La tabla bronze.raw_html usa content_hash como clave natural (SHA-256)"
    )
    corrida.supuestos.append(
        "Silver almacena datos en DuckDB, Gold en PostgreSQL con pgvector"
    )
    corrida.supuestos.append(
        "Se usan articulos max_articles=2 para acelerar la evaluacion"
    )
    corrida.limitaciones.append(
        "Gold requiere Ollama en localhost:11434 y PostgreSQL via Docker"
    )
    corrida.limitaciones.append(
        "La evaluacion no modifica datos productivos; usa DuckDB temporal aislada"
    )

    _escribir_log(run_dir, "INFO", "SYS", "Evaluando criterios Bronze...")
    bronce = evaluar_bronce(run_dir, corrida)
    _guardar_evidencias(run_dir, bronce)
    corrida.resultados.extend(bronce)

    _escribir_log(run_dir, "INFO", "SYS", "Evaluando criterios Silver...")
    plata = evaluar_plata(run_dir, corrida)
    _guardar_evidencias(run_dir, plata)
    corrida.resultados.extend(plata)

    _escribir_log(run_dir, "INFO", "SYS", "Evaluando criterios Idempotencia...")
    idemp = evaluar_idempotencia(run_dir, corrida)
    _guardar_evidencias(run_dir, idemp)
    corrida.resultados.extend(idemp)

    _escribir_log(run_dir, "INFO", "SYS", "Evaluando criterios Gold...")
    oro = evaluar_oro(run_dir, corrida)
    _guardar_evidencias(run_dir, oro)
    corrida.resultados.extend(oro)

    corrida.score_total = sum(r.score for r in corrida.resultados)
    corrida.finished_at = datetime.now(UTC)

    _guardar_comandos(run_dir, corrida)

    _escribir_log(run_dir, "RESULT", "SYS", f"Puntuacion total: {corrida.score_total:.1f}/{corrida.max_score:.0f}")
    for r in corrida.resultados:
        _escribir_log(run_dir, "RESULT", r.id, f"{r.estado.value} ({r.score:.1f}/{r.max_score:.1f})")

    generar_reporte(corrida, run_dir)

    print(f"\nEvaluacion completada: {run_id}")
    print(f"  Directorio: {run_dir}")
    print(f"  Puntuacion: {corrida.score_total:.1f} / {corrida.max_score:.0f}")
    print(f"  Reporte:    {run_dir}/reporte.html")
    print(f"  JSON:       {run_dir}/resultado.json")

    if corrida.score_total < corrida.max_score:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
