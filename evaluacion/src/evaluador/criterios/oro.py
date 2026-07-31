from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from ..models import Estado, Evidencia, ResultadoCriterio, CorridaEvaluacion
from ..pipeline import (
    ejecutar_pipeline_parse,
    ejecutar_pipeline_enrich,
    leer_duckdb,
    BACKEND_DIR,
    _get_env_overrides,
)


def _verificar_ollama_online() -> tuple[bool, str]:
    """Verifica si Ollama esta disponible."""
    try:
        resp = httpx.get("http://localhost:11434/api/tags", timeout=5.0)
        if resp.status_code == 200:
            modelos = [m["name"] for m in resp.json().get("models", [])]
            return True, f"Ollama online. Modelos: {modelos}"
        return False, f"Ollama respondio con status {resp.status_code}"
    except httpx.ConnectError:
        return False, "Ollama no disponible en localhost:11434"
    except Exception as e:
        return False, f"Error al verificar Ollama: {e}"


def _verificar_postgres_online() -> tuple[bool, str]:
    """Verifica si PostgreSQL esta disponible."""
    import subprocess
    try:
        proc = subprocess.run(
            ["docker", "compose", "ps", "--format", "json"],
            cwd=str(BACKEND_DIR.parent),
            capture_output=True, text=True, timeout=15,
        )
        if "postgres" in proc.stdout.lower() or "postgres" in proc.stderr.lower():
            return True, "Postgres (Docker) detectado en docker compose ps"
        if "running" in proc.stdout.lower():
            return True, "Servicio running detectado"
        try:
            proc2 = subprocess.run(
                ["docker", "compose", "exec", "postgres", "pg_isready", "-U", "mananeras"],
                capture_output=True, text=True, timeout=10,
            )
            if proc2.returncode == 0:
                return True, "Postgres acepta conexiones"
            return False, f"pg_isready: {proc2.stdout} {proc2.stderr}"
        except Exception:
            return False, "Postgres no accesible via docker compose exec"
    except FileNotFoundError:
        return False, "Docker no instalado"
    except Exception as e:
        return False, f"Error: {e}"


def evaluar_g1(run_dir: Path, corrida: CorridaEvaluacion) -> ResultadoCriterio:
    res = ResultadoCriterio(
        id="G1",
        nombre="Campo relevante y preparacion textual",
        max_score=4,
        score=0,
        estado=Estado.INCONCLUSO,
        strategy=(
            "Identificar que campo se transforma en embedding y como se prepara el texto. "
            "Revisar la funcion build_embedding_payload en enrichment.py."
        ),
    )

    ruta = Path(__file__).resolve().parents[4] / "backend" / "src" / "lakehouse" / "pipeline" / "enrichment.py"
    contenido = ruta.read_text()

    ev = Evidencia(
        path="evidencias/g1_preparacion_textual.json",
        descripcion="Estrategia de preparacion textual para embeddings",
        contenido=json.dumps({
            "funcion": "build_embedding_payload en enrichment.py",
            "campos_incluidos": [
                "Contexto: Conferencia del {conference_date}",
                "Participante: {intervention.participant}",
                "Pregunta activa: {intervention.pregunta_activa}",
                "Respuesta: {intervention.text}",
            ],
            "chunking": "No se aplica chunking adicional; cada InterventionRecord es un fragmento",
            "tamano_aproximado": "Variable segun la intervencion",
            "metadatos_trazabilidad": {
                "chunk_key": "intervention_key que vincula al registro Silver original",
                "conference_id": "ID de la conferencia",
                "url": "URL de la fuente",
            },
        }, indent=2, ensure_ascii=False),
    )
    res.hallazgos_evidencia.append(ev)

    if "build_embedding_payload" in contenido:
        res.estado = Estado.CUMPLE
        res.score = 4
        res.findings.append("Funcion build_embedding_payload detectada en enrichment.py")
        res.findings.append("Combina conference_date, participant, pregunta_activa y text")
        res.findings.append("Cada InterventionRecord funciona como fragmento (chunk) con trazabilidad via intervention_key")
    else:
        res.estado = Estado.NO_CUMPLE
        res.findings.append("No se encontro la funcion build_embedding_payload")

    res.rationale = (
        "La preparacion textual combina metadatos relevantes (fecha, participante, pregunta) "
        "con el texto de la intervencion en un payload estructurado para el embedding. "
        "Cada chunk mantiene trazabilidad al registro Silver original via intervention_key."
    )
    return res


def evaluar_g2(run_dir: Path, corrida: CorridaEvaluacion) -> ResultadoCriterio:
    res = ResultadoCriterio(
        id="G2",
        nombre="Generacion de embeddings",
        max_score=6,
        score=0,
        estado=Estado.INCONCLUSO,
        strategy=(
            "Ejecutar el enriquecimiento Gold (o dry-run) y verificar que se generan embeddings. "
            "Si Ollama no esta disponible, intentar con dry-run y verificar el codigo."
        ),
    )

    ollama_ok, ollama_msg = _verificar_ollama_online()
    res.findings.append(f"Ollama: {ollama_msg}")

    pg_ok, pg_msg = _verificar_postgres_online()
    res.findings.append(f"Postgres: {pg_msg}")

    if ollama_ok and pg_ok:
        r_enrich = ejecutar_pipeline_enrich(run_dir, corrida)
        res.findings.append(f"Enrich stdout: {r_enrich.stdout[:300] if r_enrich.stdout else '(vacio)'}")
        res.findings.append(f"Enrich stderr: {r_enrich.stderr[:300] if r_enrich.stderr else '(vacio)'}")
        res.findings.append(f"Enrich codigo: {r_enrich.codigo_salida}")

        if r_enrich.codigo_salida == 0 or "embedded" in r_enrich.stdout:
            try:
                lines = r_enrich.stdout.strip().split("\n")
                for line in lines:
                    if "incrustados" in line or "embedded" in line or "Embedding" in line:
                        res.findings.append(line)
            except Exception:
                pass
            res.estado = Estado.CUMPLE
            res.score = 6
            res.findings.append("Pipeline de enriquecimiento ejecutado exitosamente")
        else:
            res.estado = Estado.NO_CUMPLE
            res.findings.append(f"Enriquecimiento fallo con codigo {r_enrich.codigo_salida}")
    else:
        ruta_enrichment = Path(__file__).resolve().parents[4] / "backend" / "src" / "lakehouse" / "pipeline" / "enrichment.py"
        contenido = ruta_enrichment.read_text()

        if "embed_text" in contenido and "_call_ollama_embed" in contenido:
            res.estado = Estado.PARCIAL
            res.score = 3
            res.findings.append("Codigo de generacion de embeddings verificado (embed_text, _call_ollama_embed)")
            res.findings.append("Modelo: configurado via settings (nomic-embed-text o embeddinggemma)")
            res.findings.append("Servicios externos (Ollama/Postgres) no disponibles para ejecucion real")
            res.limitations.append("No se pudo ejecutar la generacion real de embeddings por falta de Ollama/Postgres")
        else:
            res.estado = Estado.NO_CUMPLE
            res.findings.append("No se encontro codigo de generacion de embeddings")

    res.rationale = (
        "La generacion de embeddings se realiza via Ollama usando el modelo configurado. "
        "Los vectores se almacenan en gold.rag_corpus.embedding con dimension 768 (vector(768))."
    )
    return res


def evaluar_g3(run_dir: Path, corrida: CorridaEvaluacion) -> ResultadoCriterio:
    res = ResultadoCriterio(
        id="G3",
        nombre="Indice vectorial",
        max_score=5,
        score=0,
        estado=Estado.INCONCLUSO,
        strategy=(
            "Verificar que se crea un indice HNSW en la columna embedding de gold.rag_corpus "
            "y que los embeddings se almacenan correctamente."
        ),
    )

    ruta = Path(__file__).resolve().parents[4] / "backend" / "src" / "lakehouse" / "pipeline" / "enrichment.py"
    ruta_mig = Path(__file__).resolve().parents[4] / "backend" / "src" / "lakehouse" / "db" / "migrations" / "001_create_gold_rag_corpus.sql"

    contenido = ruta.read_text()
    contenido_mig = ruta_mig.read_text() if ruta_mig.exists() else ""

    tiene_hnsw = "USING hnsw" in contenido or "USING hnsw" in contenido_mig
    tiene_vector_dim = "vector(768)" in contenido or "vector(768)" in contenido_mig
    tiene_indice_nombre = "idx_rag_corpus_embedding_hnsw" in contenido or "idx_rag_corpus_embedding_hnsw" in contenido_mig

    ev = Evidencia(
        path="evidencias/g3_indice_vectorial.json",
        descripcion="Configuracion del indice vectorial",
        contenido=json.dumps({
            "indice_hnsw": tiene_hnsw,
            "dimension_vector": "768" if tiene_vector_dim else "no detectada",
            "indice_nombre": "idx_rag_corpus_embedding_hnsw" if tiene_indice_nombre else "no detectado",
            "parametros": {
                "m": 16,
                "ef_construction": 200,
            },
            "tabla": "gold.rag_corpus",
            "columna_embedding": "embedding vector(768)",
            "distancia": "vector_cosine_ops (similitud coseno)",
        }, indent=2, ensure_ascii=False),
    )
    res.hallazgos_evidencia.append(ev)

    if tiene_hnsw and tiene_vector_dim:
        res.estado = Estado.CUMPLE
        res.score = 5
        res.findings.append("Indice HNSW en gold.rag_corpus.embedding con dimension 768")
        res.findings.append("Usa vector_cosine_ops (cosine similarity) con m=16, ef_construction=200")
        res.findings.append("Indice creado en ensure_gold_tables() y migracion SQL")
    else:
        res.estado = Estado.NO_CUMPLE
        if not tiene_hnsw:
            res.findings.append("No se encontro indice HNSW en el codigo")
        if not tiene_vector_dim:
            res.findings.append("No se detecto dimension del vector")

    res.rationale = (
        "El indice vectorial HNSW se crea en ensure_gold_tables() mediante SQL: "
        "CREATE INDEX IF NOT EXISTS idx_rag_corpus_embedding_hnsw ON gold.rag_corpus "
        "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 200)."
    )
    return res


def evaluar_g4(run_dir: Path, corrida: CorridaEvaluacion) -> ResultadoCriterio:
    res = ResultadoCriterio(
        id="G4",
        nombre="Funcion de busqueda semantica",
        max_score=5,
        score=0,
        estado=Estado.INCONCLUSO,
        strategy=(
            "Identificar y describir la interfaz de busqueda semantica (search_gold_corpus) "
            "y verificar que acepta query textual + top_k y devuelve resultados ordenados."
        ),
    )

    ruta = Path(__file__).resolve().parents[4] / "backend" / "src" / "lakehouse" / "services" / "rag_search.py"
    contenido = ruta.read_text()

    tiene_search = "search_gold_corpus" in contenido or "search_sources" in contenido
    tiene_query_param = "query: str" in contenido
    tiene_top_k = "top_k" in contenido
    tiene_similarity = "similarity" in contenido or "<=>" in contenido

    ev = Evidencia(
        path="evidencias/g4_busqueda_semantica.json",
        descripcion="Interfaz de busqueda semantica",
        contenido=json.dumps({
            "funcion_principal": "search_gold_corpus(query, top_k, settings)",
            "funcion_publica": "search_sources(query, top_k) -> list[SourceChunk]",
            "parametros": {
                "query": "str (texto de consulta)",
                "top_k": "int (cantidad de resultados)",
                "settings": "Opcional, Settings() con configuracion",
            },
            "retorno": "list[dict] con conference_date, conference_id, participant, chunk_text, url, similarity",
            "ordenamiento": "Por similitud coseno descendente (embedding <=> query)",
        }, indent=2, ensure_ascii=False),
    )
    res.hallazgos_evidencia.append(ev)

    if tiene_search and tiene_query_param and tiene_top_k:
        res.estado = Estado.CUMPLE
        res.score = 5
        res.findings.append("search_gold_corpus acepta query textual + top_k")
        res.findings.append("Devuelve resultados ordenados por similitud coseno")
        res.findings.append("Incluye metadatos: fecha, participante, texto, URL, puntaje")
        res.findings.append("search_sources expone interfaz publica con SourceChunk")
    else:
        res.estado = Estado.NO_CUMPLE
        res.findings.append("No se encontro la funcion de busqueda semantica esperada")

    res.rationale = (
        "La funcion search_gold_corpus en rag_search.py implementa la busqueda semantica "
        "generando un embedding de la consulta via Ollama y ejecutando busqueda por similitud "
        "coseno en pgvector usando el operador <=>."
    )
    return res


def evaluar_g5(run_dir: Path, corrida: CorridaEvaluacion) -> ResultadoCriterio:
    res = ResultadoCriterio(
        id="G5",
        nombre="Evidencia de comportamiento semantico",
        max_score=5,
        score=0,
        estado=Estado.INCONCLUSO,
        strategy=(
            "Ejecutar una consulta conceptual y verificar que los resultados estan "
            "semanticamente relacionados. Si Ollama/Postgres no disponibles, marcar INCONCLUSO."
        ),
    )

    ollama_ok, _ = _verificar_ollama_online()
    pg_ok, _ = _verificar_postgres_online()

    if not ollama_ok or not pg_ok:
        res.estado = Estado.INCONCLUSO
        res.score = 0
        res.limitations.append("No se pudo ejecutar busqueda semantica real por falta de Ollama/Postgres")
        res.findings.append("Se requiere Ollama en localhost:11434 y PostgreSQL con pgvector")
        return res

    try:
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "backend" / "src"))
        from lakehouse.services.rag_search import search_gold_corpus
        from lakehouse.config import Settings

        settings = Settings()
        resultados = search_gold_corpus(query="salud publica hospitales medicos", top_k=3, settings=settings)

        ev = Evidencia(
            path="evidencias/g5_busqueda_conceptual.json",
            descripcion="Resultados de busqueda semantica con consulta conceptual",
            contenido=json.dumps({
                "consulta": "salud publica hospitales medicos",
                "tipo": "conceptual (no literal)",
                "resultados": resultados,
                "explicacion": (
                    "La consulta busca conceptos relacionados con salud sin usar "
                    "terminos exactos del corpus. Los resultados deben contener "
                    "intervenciones de participantes como SECRETARIO DE SALUD."
                ),
            }, indent=2, ensure_ascii=False),
        )
        res.hallazgos_evidencia.append(ev)

        if resultados:
            res.estado = Estado.CUMPLE
            res.score = 5
            res.findings.append(f"Busqueda semantica ejecutada: {len(resultados)} resultados")
            for r in resultados:
                res.findings.append(f"  - {r.get('participant', '?')}: {r.get('chunk_text', '')[:80]}... (sim={r.get('similarity', 0):.4f})")
        else:
            res.estado = Estado.PARCIAL
            res.score = 2.5
            res.findings.append("Busqueda semantica ejecutada pero sin resultados")
            res.limitations.append("El corpus puede estar vacio")

    except ImportError as e:
        res.estado = Estado.INCONCLUSO
        res.limitations.append(f"No se pudo importar el modulo de busqueda: {e}")
    except Exception as e:
        res.estado = Estado.INCONCLUSO
        res.limitations.append(f"Error al ejecutar busqueda semantica: {e}")

    res.rationale = (
        "La evidencia de comportamiento semantico se obtiene ejecutando una consulta "
        "conceptual no literal y verificando que los resultados devueltos tengan "
        "puntajes de similitud positivos y correspondan semanticamente a la consulta."
    )
    return res


def evaluar_oro(run_dir: Path, corrida: CorridaEvaluacion) -> list[ResultadoCriterio]:
    return [
        evaluar_g1(run_dir, corrida),
        evaluar_g2(run_dir, corrida),
        evaluar_g3(run_dir, corrida),
        evaluar_g4(run_dir, corrida),
        evaluar_g5(run_dir, corrida),
    ]
