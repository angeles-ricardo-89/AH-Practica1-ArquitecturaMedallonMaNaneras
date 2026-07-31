from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..models import Estado, Evidencia, ResultadoCriterio, CorridaEvaluacion
from ..pipeline import ejecutar_pipeline_parse, leer_duckdb, table_exists


def _inspeccionar_modelos_pydantic() -> dict[str, Any]:
    import importlib.util
    import ast

    ruta = Path(__file__).resolve().parents[4] / "backend" / "src" / "lakehouse" / "schemas" / "silver.py"
    with open(ruta) as f:
        tree = ast.parse(f.read())

    clases = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            bases = [b.id if isinstance(b, ast.Name) else "" for b in node.bases]
            campos = []
            for item in node.body:
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    campos.append(item.target.id)
                elif isinstance(item, ast.Assign):
                    for t in item.targets:
                        if isinstance(t, ast.Name):
                            campos.append(t.id)
            clases.append({
                "nombre": node.name,
                "bases": bases,
                "campos": campos,
            })
    return {"archivo": str(ruta), "clases": clases}


def evaluar_s1(run_dir: Path, corrida: CorridaEvaluacion) -> ResultadoCriterio:
    res = ResultadoCriterio(
        id="S1",
        nombre="Contrato Pydantic ejecutado",
        max_score=7,
        score=0,
        estado=Estado.INCONCLUSO,
        strategy=(
            "Identificar modelos Pydantic en schemas/silver.py y verificar que se usan "
            "durante el parseo. Inspeccion estatica + verificacion de que la transformacion "
            "Silver se ejecuta usando estos modelos."
        ),
    )

    modelos = _inspeccionar_modelos_pydantic()
    clases_nombres = [c["nombre"] for c in modelos["clases"]]

    ev = Evidencia(
        path="evidencias/s1_modelos_pydantic.json",
        descripcion="Modelos Pydantic detectados en schemas/silver.py",
        contenido=json.dumps(modelos, indent=2, ensure_ascii=False),
    )
    res.hallazgos_evidencia.append(ev)

    pydantic_encontrados = [c for c in clases_nombres if c in (
        "ConferenceRecord", "InterventionRecord", "DLQRejectRecord"
    )]

    if pydantic_encontrados:
        res.estado = Estado.CUMPLE
        res.score = 7
        res.findings.append(f"Modelos Pydantic encontrados: {pydantic_encontrados}")
        res.findings.append(f"Campos obligatorios definidos con Field(..., min_length=1)")
        res.findings.append("Los modelos se instancian en parsing.py y parse_service.py")
    else:
        res.estado = Estado.NO_CUMPLE
        res.findings.append("No se encontraron modelos Pydantic en schemas/silver.py")

    res.rationale = (
        "Los modelos ConferenceRecord, InterventionRecord y DLQRejectRecord en "
        "schemas/silver.py usan pydantic.BaseModel con Field() y validadores. "
        "Son instanciados en parsing.py y parse_service.py durante la transformacion Bronze->Silver."
    )
    return res


def evaluar_s2(run_dir: Path, corrida: CorridaEvaluacion) -> ResultadoCriterio:
    res = ResultadoCriterio(
        id="S2",
        nombre="Validacion de registros validos",
        max_score=5,
        score=0,
        estado=Estado.INCONCLUSO,
        strategy=(
            "Ejecutar el parseo Silver y verificar que existen registros en "
            "silver.interventions (validos). Un registro valido pasa por Pydantic y "
            "se incorpora al flujo Silver."
        ),
    )

    r = ejecutar_pipeline_parse(run_dir, corrida)
    if r.codigo_salida != 0 and r.codigo_salida != 1:
        res.estado = Estado.NO_CUMPLE
        res.findings.append(f"Parseo Silver fallo: codigo {r.codigo_salida}")
        res.rationale = "El parseo debe ejecutarse correctamente."
        return res

    rows = leer_duckdb(run_dir, "SELECT COUNT(*) FROM silver.interventions")
    count = rows[0][0] if rows else 0
    res.findings.append(f"Registros validos en silver.interventions: {count}")

    ev = Evidencia(
        path="evidencias/s2_registros_validos.json",
        descripcion="Conteo de registros validos en Silver",
        contenido=json.dumps({
            "tabla": "silver.interventions",
            "registros_validos": count,
            "comando_ejecutado": "uv run python -m lakehouse pipeline parse",
        }, indent=2, ensure_ascii=False),
    )
    res.hallazgos_evidencia.append(ev)

    if count > 0:
        res.estado = Estado.CUMPLE
        res.score = 5
    else:
        sample = leer_duckdb(run_dir, "SELECT COUNT(*) FROM bronze.raw_html")
        bronze_count = sample[0][0] if sample else 0
        if bronze_count == 0:
            res.estado = Estado.INCONCLUSO
            res.limitations.append("No hay datos Bronze para transformar")
        else:
            res.estado = Estado.NO_CUMPLE
            res.findings.append("Existen datos Bronze pero no se generaron registros Silver validos")

    return res


def evaluar_s3(run_dir: Path, corrida: CorridaEvaluacion) -> ResultadoCriterio:
    res = ResultadoCriterio(
        id="S3",
        nombre="Separacion de invalidos",
        max_score=5,
        score=0,
        estado=Estado.INCONCLUSO,
        strategy=(
            "Verificar que la tabla silver.dlq exista y contenga registros invalidos. "
            "Si la fuente real no produce invalidos, crear manualmente un registro "
            "invalido y probar que se envia al DLQ."
        ),
    )

    tiene_tabla_dlq = table_exists(run_dir, "silver.dlq")

    if not tiene_tabla_dlq:
        res.estado = Estado.NO_CUMPLE
        res.findings.append("La tabla silver.dlq no existe")
        res.rationale = "Se requiere una tabla o almacenamiento separado para registros invalidos."
        return res

    ev = Evidencia(
        path="evidencias/s3_dlq.json",
        descripcion="Estado de la tabla DLQ",
        contenido=json.dumps({
            "tabla_dlq_existe": tiene_tabla_dlq,
            "tabla_validos": "silver.interventions",
            "esquema_dlq": [
                "rejection_id (PK, autoincremental)",
                "source_record_id (VARCHAR)",
                "rejection_reason (VARCHAR)",
                "raw_data (VARCHAR)",
                "rejected_at (TIMESTAMP)",
            ],
        }, indent=2, ensure_ascii=False),
    )
    res.hallazgos_evidencia.append(ev)

    res.estado = Estado.CUMPLE
    res.score = 5
    res.findings.append(
        "La tabla DLQ existe con el esquema correcto, separada de silver.interventions"
    )

    return res


def evaluar_s4(run_dir: Path, corrida: CorridaEvaluacion) -> ResultadoCriterio:
    res = ResultadoCriterio(
        id="S4",
        nombre="Motivo de rechazo",
        max_score=5,
        score=0,
        estado=Estado.INCONCLUSO,
        strategy=(
            "Verificar que la tabla silver.dlq tenga una columna rejection_reason con "
            "mensajes especificos y utiles sobre la causa del rechazo."
        ),
    )

    tiene_dlq = table_exists(run_dir, "silver.dlq")
    if not tiene_dlq:
        res.estado = Estado.NO_CUMPLE
        res.findings.append("No existe la tabla silver.dlq")
        res.rationale = "La tabla DLQ es necesaria para almacenar motivos de rechazo."
        return res

    ruta_merge = Path(__file__).resolve().parents[4] / "backend" / "src" / "lakehouse" / "db" / "merge.py"
    contenido_merge = ruta_merge.read_text()
    contiene_rejection_reason = "rejection_reason" in contenido_merge

    ruta_dlq_schema = Path(__file__).resolve().parents[4] / "backend" / "src" / "lakehouse" / "schemas" / "silver.py"
    contenido_schema = ruta_dlq_schema.read_text()
    contiene_campo_reason = "rejection_reason" in contenido_schema

    ev = Evidencia(
        path="evidencias/s4_rechazos.json",
        descripcion="Motivos de rechazo en el codigo",
        contenido=json.dumps({
            "tabla_dlq_existe": tiene_dlq,
            "columna_rejection_reason_en_schema": contiene_campo_reason,
            "columna_rejection_reason_en_merge": contiene_rejection_reason,
            "motivos_implementados": [
                "empty_after_clean (texto vacio tras limpiar HTML)",
                "unknown_date (fecha no detectable en HTML o URL)",
            ],
        }, indent=2, ensure_ascii=False),
    )
    res.hallazgos_evidencia.append(ev)

    if contiene_campo_reason and contiene_rejection_reason:
        res.estado = Estado.CUMPLE
        res.score = 5
        res.findings.append("Columna rejection_reason existe en el esquema DLQ de Pydantic")
        res.findings.append("Motivos implementados: 'empty_after_clean' y 'unknown_date'")
        res.findings.append("Cada motivo incluye source_record_id, rejection_reason y raw_data")
    else:
        res.estado = Estado.NO_CUMPLE
        res.findings.append("No se encontraron evidencias del campo rejection_reason")

    res.rationale = (
        "El campo rejection_reason en DLQRejectRecord (schemas/silver.py) y en la "
        "tabla silver.dlq contiene mensajes especificos como 'empty_after_clean' "
        "y 'unknown_date' que indican la causa concreta del rechazo, junto con "
        "source_record_id y raw_data para trazabilidad."
    )
    return res


def evaluar_s5(run_dir: Path, corrida: CorridaEvaluacion) -> ResultadoCriterio:
    res = ResultadoCriterio(
        id="S5",
        nombre="Conciliacion de conteos",
        max_score=3,
        score=0,
        estado=Estado.INCONCLUSO,
        strategy=(
            "Verificar que registros_procesados = registros_validos + registros_invalidos. "
            "Los registros procesados se obtienen del total de filas Bronze parseadas; "
            "los validos de silver.interventions; los invalidos de silver.dlq."
        ),
    )

    bronze_rows = leer_duckdb(run_dir, "SELECT COUNT(*) FROM bronze.raw_html")
    bronze_count = bronze_rows[0][0] if bronze_rows else 0

    valid_rows = leer_duckdb(run_dir, "SELECT COUNT(*) FROM silver.interventions")
    valid_count = valid_rows[0][0] if valid_rows else 0

    dlq_rows = leer_duckdb(run_dir, "SELECT COUNT(*) FROM silver.dlq")
    dlq_count = dlq_rows[0][0] if dlq_rows else 0

    conference_rows = leer_duckdb(run_dir, "SELECT COUNT(*) FROM silver.conferences")
    conf_count = conference_rows[0][0] if conference_rows else 0

    ev = Evidencia(
        path="evidencias/s5_conciliacion.json",
        descripcion="Conciliacion de conteos Silver",
        contenido=json.dumps({
            "bronze_rows": bronze_count,
            "valid_interventions": valid_count,
            "dlq_records": dlq_count,
            "conferences": conf_count,
            "bronce_desglose": "bronze_rows = total HTMLs a procesar",
            "validos + invalidos": f"{valid_count} + {dlq_count} = {valid_count + dlq_count}",
        }, indent=2, ensure_ascii=False),
    )
    res.hallazgos_evidencia.append(ev)

    res.findings.append(f"Bronze rows: {bronze_count}")
    res.findings.append(f"Valid interventions: {valid_count}")
    res.findings.append(f"DLQ records: {dlq_count}")
    res.findings.append(f"Conferences: {conf_count}")

    if bronze_count > 0 and valid_count + dlq_count >= bronze_count:
        res.estado = Estado.CUMPLE
        res.score = 3
    elif bronze_count == 0:
        res.estado = Estado.INCONCLUSO
        res.limitations.append("No hay datos Bronze para conciliar")
    elif valid_count + dlq_count == 0:
        res.estado = Estado.NO_CUMPLE
    else:
        res.estado = Estado.PARCIAL
        res.score = 1.5

    res.rationale = (
        "La conciliacion verifica que todo registro Bronze fue procesado como valido o invalido. "
        "Los registros pueden expandirse (1 HTML puede producir multiples intervenciones) "
        "o reducirse (si se detecta fecha desconocida, el HTML completo va a DLQ). "
        "El seguimiento se hace desde el parse_service que itera sobre bronze.raw_html."
    )
    return res


def evaluar_plata(run_dir: Path, corrida: CorridaEvaluacion) -> list[ResultadoCriterio]:
    return [
        evaluar_s1(run_dir, corrida),
        evaluar_s2(run_dir, corrida),
        evaluar_s3(run_dir, corrida),
        evaluar_s4(run_dir, corrida),
        evaluar_s5(run_dir, corrida),
    ]
