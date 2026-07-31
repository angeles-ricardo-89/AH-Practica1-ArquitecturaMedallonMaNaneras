from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from .models import ResultadoEjecucion, CorridaEvaluacion


BACKEND_DIR = Path(__file__).resolve().parents[3] / "backend"
PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _get_env_overrides(run_dir: Path, proyecto_nombre: str | None = None) -> dict[str, str]:
    duckdb_path = str(run_dir / "ducklake_files.duckdb")
    env = os.environ.copy()
    env["DUCKLAKE_DATA_PATH"] = duckdb_path
    env["PYTHONPATH"] = f"src:{PROJECT_ROOT}/evaluacion/src"
    env["SOURCE_ARCHIVE_URL"] = "https://www.gob.mx/presidencia/es/archivo/articulos"
    if proyecto_nombre:
        env["DOCKER_COMPOSE_PROJECT_NAME"] = proyecto_nombre
        env["COMPOSE_PROJECT_NAME"] = proyecto_nombre
    env["EVALUACION_RUN_DIR"] = str(run_dir)
    return env


def _ejecutar(
    desc: str,
    cmd: list[str],
    cwd: Path,
    env: dict[str, str],
    timeout_s: int = 300,
) -> ResultadoEjecucion:
    inicio = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        codigo = proc.returncode
        stdout = proc.stdout
        stderr = proc.stderr
        excepcion = ""
    except subprocess.TimeoutExpired as e:
        codigo = -1
        stdout = e.stdout or ""
        stderr = e.stderr or ""
        excepcion = f"Timeout after {timeout_s}s"
    except FileNotFoundError as e:
        codigo = -2
        stdout = ""
        stderr = str(e)
        excepcion = f"Comando no encontrado: {e}"
    except Exception as e:
        codigo = -3
        stdout = ""
        stderr = str(e)
        excepcion = str(e)

    duracion = int((time.monotonic() - inicio) * 1000)
    return ResultadoEjecucion(
        comando=" ".join(str(c) for c in cmd),
        codigo_salida=codigo,
        stdout=stdout,
        stderr=stderr,
        duracion_ms=duracion,
        excepcion=excepcion,
    )


def ejecutar_pipeline_ingest(run_dir: Path, corrida: CorridaEvaluacion, max_articles: int = 2) -> ResultadoEjecucion:
    env = _get_env_overrides(run_dir)
    cmd = [
        "uv", "run", "python", "-m", "lakehouse", "pipeline", "ingest",
        "--max-articles", str(max_articles),
    ]
    res = _ejecutar("Ingesta Bronze", cmd, BACKEND_DIR, env)
    corrida.ejecuciones.append(res)
    return res


def ejecutar_pipeline_parse(run_dir: Path, corrida: CorridaEvaluacion, conference_date: str | None = None) -> ResultadoEjecucion:
    env = _get_env_overrides(run_dir)
    cmd = ["uv", "run", "python", "-m", "lakehouse", "pipeline", "parse"]
    if conference_date:
        cmd.extend(["--date", conference_date])
    res = _ejecutar("Parseo Silver", cmd, BACKEND_DIR, env)
    corrida.ejecuciones.append(res)
    return res


def ejecutar_pipeline_enrich(run_dir: Path, corrida: CorridaEvaluacion) -> ResultadoEjecucion:
    env = _get_env_overrides(run_dir)
    cmd = ["uv", "run", "python", "-m", "lakehouse", "pipeline", "enrich"]
    res = _ejecutar("Enriquecimiento Gold", cmd, BACKEND_DIR, env, timeout_s=600)
    corrida.ejecuciones.append(res)
    return res


def table_exists(run_dir: Path, table: str) -> bool:
    import duckdb
    db_path = run_dir / "ducklake_files.duckdb"
    if not db_path.exists():
        return False
    conn = duckdb.connect(str(db_path))
    try:
        conn.execute(f"SELECT 1 FROM {table} LIMIT 1")
        return True
    except Exception:
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass


def detectar_staging(run_dir: Path) -> bool:
    return True


def leer_duckdb(run_dir: Path, query: str) -> list[tuple]:
    import duckdb
    db_path = run_dir / "ducklake_files.duckdb"
    if not db_path.exists():
        return []
    conn = duckdb.connect(str(db_path))
    try:
        conn.execute("SELECT 1")
    except Exception:
        try:
            conn.close()
        except Exception:
            pass
        return []
    try:
        rows = conn.execute(query).fetchall()
        return rows
    except Exception:
        return []
    finally:
        try:
            conn.close()
        except Exception:
            pass


def ejecutar_pipeline_full(run_dir: Path, corrida: CorridaEvaluacion, max_articles: int = 2) -> tuple[ResultadoEjecucion, ResultadoEjecucion, ResultadoEjecucion]:
    r1 = ejecutar_pipeline_ingest(run_dir, corrida, max_articles=max_articles)
    r2 = ejecutar_pipeline_parse(run_dir, corrida)
    r3 = ejecutar_pipeline_enrich(run_dir, corrida)
    return r1, r2, r3
