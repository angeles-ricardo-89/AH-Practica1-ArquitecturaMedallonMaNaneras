from __future__ import annotations

import json
from pathlib import Path

from .models import CorridaEvaluacion, Estado


CSS = """
*,:after,:before{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
background:#f5f7fa;color:#1a1a2e;line-height:1.6;padding:20px}
.container{max-width:1200px;margin:0 auto}
h1{font-size:1.8em;margin-bottom:.3em}
h2{font-size:1.4em;margin:1.5em 0 .8em;border-bottom:2px solid #e0e0e0;padding-bottom:.3em}
h3{font-size:1.1em;margin:1em 0 .5em}
.header{background:#16213e;color:#fff;padding:30px;border-radius:12px;margin-bottom:24px}
.header h1{margin:0}.header .meta{opacity:.8;font-size:.9em;margin-top:8px}
.score-big{font-size:3em;font-weight:700}
.score-label{font-size:1em;opacity:.7}
.sg{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px;margin:20px 0}
.sc{background:#fff;padding:20px;border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,.1);text-align:center}
.sn{font-size:2em;font-weight:700}
.sl{font-size:.85em;color:#666;margin-top:4px}
table{width:100%;border-collapse:collapse;background:#fff;border-radius:8px;overflow:hidden;
box-shadow:0 1px 3px rgba(0,0,0,.1);margin:16px 0}
th{background:#16213e;color:#fff;padding:12px 16px;text-align:left;font-weight:600}
td{padding:10px 16px;border-bottom:1px solid #eee}
tr:last-child td{border-bottom:none}
.s-CUMPLE{background:#d4edda;color:#155724;padding:3px 10px;border-radius:12px;font-weight:600;font-size:.85em}
.s-PARCIAL{background:#fff3cd;color:#856404;padding:3px 10px;border-radius:12px;font-weight:600;font-size:.85em}
.s-NO_CUMPLE{background:#f8d7da;color:#721c24;padding:3px 10px;border-radius:12px;font-weight:600;font-size:.85em}
.s-INCONCLUSO{background:#e2e3e5;color:#383d41;padding:3px 10px;border-radius:12px;font-weight:600;font-size:.85em}
pre{background:#f0f0f0;padding:12px;border-radius:6px;overflow-x:auto;font-size:.85em}
a.el{color:#06c;text-decoration:none}
a.el:hover{text-decoration:underline}
.sec{background:#fff;padding:20px;border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,.1);margin:16px 0}
ul{margin-left:20px}li{margin-bottom:4px}
"""


def _h(r: Path) -> str:
    return f'<a class="el" href="{r}" target="_blank">ver</a>'


def generar_reporte(corrida: CorridaEvaluacion, directorio: Path):
    cumplen = sum(1 for r in corrida.resultados if r.estado == Estado.CUMPLE)
    parciales = sum(1 for r in corrida.resultados if r.estado == Estado.PARCIAL)
    no_cumplen = sum(1 for r in corrida.resultados if r.estado == Estado.NO_CUMPLE)
    inconclusos = sum(1 for r in corrida.resultados if r.estado == Estado.INCONCLUSO)
    score_pct = (corrida.score_total / corrida.max_score * 100) if corrida.max_score > 0 else 0

    rows = ""
    for r in corrida.resultados:
        rows += f"""<tr>
<td><strong>{r.id}</strong></td>
<td>{r.nombre}</td>
<td><span class="s-{r.estado.value}">{r.estado.value}</span></td>
<td style="text-align:center">{r.score:.1f} / {r.max_score:.1f}</td>
</tr>"""

    detalles = ""
    for r in corrida.resultados:
        ev = "".join(
            f'<p><a class="el" href="{e.path}" target="_blank">Evidencia: {e.descripcion}</a></p>'
            for e in r.hallazgos_evidencia
        )
        hallazgos = ("<ul>" + "".join(f"<li>{f}</li>" for f in r.findings) + "</ul>") if r.findings else ""
        limitaciones = ("<ul>" + "".join(f"<li>{l}</li>" for l in r.limitations) + "</ul>") if r.limitations else ""
        detalles += f"""<div class="sec">
<h3>{r.id}: {r.nombre} <span class="s-{r.estado.value}">{r.estado.value}</span> ({r.score:.1f}/{r.max_score:.1f})</h3>
<p><strong>Estrategia:</strong> {r.strategy}</p>
<p><strong>Justificacion:</strong> {r.rationale}</p>
{ev}{hallazgos}{limitaciones}</div>"""

    sup = "".join(f"<li>{s}</li>" for s in corrida.supuestos) or "<p>Ninguno</p>"
    lim = "".join(f"<li>{l}</li>" for l in corrida.limitaciones) or "<p>Ninguna</p>"

    cmd_rows = "".join(
        f'<tr><td><code>{e.comando[:100]}</code></td><td>{e.codigo_salida}</td><td>{e.duracion_ms}ms</td></tr>'
        for e in corrida.ejecuciones
    )

    commit = f"<p>Commit: <code>{corrida.commit}</code></p>" if corrida.commit else ""
    duracion = f"{(corrida.finished_at - corrida.started_at).total_seconds():.1f}s" if corrida.finished_at else ""

    html = f"""<!DOCTYPE html>
<html lang="es">
<head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Evaluacion - {corrida.run_id}</title>
<style>{CSS}</style></head>
<body>
<div class="container">

<div class="header">
<h1>Evaluacion de Practica: Arquitectura Medallon</h1>
<div class="meta">
<p>Run ID: {corrida.run_id}</p>
<p>Inicio: {corrida.started_at.strftime('%Y-%m-%d %H:%M:%S')} UTC</p>
{"<p>Fin: " + corrida.finished_at.strftime('%Y-%m-%d %H:%M:%S') + " UTC</p>" if corrida.finished_at else ""}
{commit}
<p>Duracion: {duracion}</p>
</div></div>

<div class="sec" style="text-align:center;padding:30px">
<div class="score-big">{corrida.score_total:.1f}</div>
<div class="score-label">Puntuacion sobre {corrida.max_score:.0f} ({score_pct:.1f}%)</div>
</div>

<div class="sg">
<div class="sc"><div class="sn" style="color:#28a745">{cumplen}</div><div class="sl">CUMPLE</div></div>
<div class="sc"><div class="sn" style="color:#ffc107">{parciales}</div><div class="sl">PARCIAL</div></div>
<div class="sc"><div class="sn" style="color:#dc3545">{no_cumplen}</div><div class="sl">NO CUMPLE</div></div>
<div class="sc"><div class="sn" style="color:#6c757d">{inconclusos}</div><div class="sl">INCONCLUSO</div></div>
</div>

<h2>Resultados</h2>
<table><thead><tr><th>ID</th><th>Criterio</th><th>Estado</th><th>Puntos</th></tr></thead>
<tbody>{rows}</tbody></table>

<h2>Detalle</h2>
{detalles}

<h2>Supuestos</h2>
<div class="sec"><ul>{sup}</ul></div>

<h2>Limitaciones</h2>
<div class="sec"><ul>{lim}</ul></div>

<h2>Comandos</h2>
<div class="sec"><table><thead><tr><th>Comando</th><th>Codigo</th><th>Duracion</th></tr></thead>
<tbody>{cmd_rows}</tbody></table></div>

</div></body></html>"""

    (directorio / "reporte.html").write_text(html, encoding="utf-8")

    json_output = corrida.to_json()
    (directorio / "resultado.json").write_text(
        json.dumps(json_output, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    lines = [
        f"Evaluacion: {corrida.run_id}",
        f"Puntuacion: {corrida.score_total:.1f} / {corrida.max_score:.0f}",
        "",
        "Resultados:",
    ]
    for r in corrida.resultados:
        lines.append(f"  {r.id}: {r.estado.value} ({r.score:.1f}/{r.max_score:.1f}) - {r.nombre}")
    lines.append("")
    lines.append(f"CUMPLE: {cumplen} | PARCIAL: {parciales} | NO_CUMPLE: {no_cumplen} | INCONCLUSO: {inconclusos}")

    (directorio / "resumen.txt").write_text("\n".join(lines), encoding="utf-8")
