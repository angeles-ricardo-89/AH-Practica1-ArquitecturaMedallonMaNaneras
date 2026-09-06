#!/usr/bin/env python3
"""Exporta el reporte en Markdown a PDF con portada.

Convierte ``docs/reporte.md`` a HTML con pandoc y lo renderiza con WeasyPrint,
anteponiendo ``docs/Portada-reporte.png`` como portada a página completa (A4).
El contenido arranca en la página 2, sin numeración.

Uso:
    python3 scripts/export_report_pdf.py
    python3 scripts/export_report_pdf.py --markdown docs/reporte.md \
        --cover docs/Portada-reporte.png --output docs/reporte.pdf

Dependencias (instaladas en el host): pandoc y weasyprint.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from weasyprint import HTML

_CSS = """
@page { size: A4; margin: 0; }
@page cover { margin: 0; }
@page content { margin: 2cm 2cm 2cm 2cm; }

body { font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
       color: #1c1917; line-height: 1.55; }

.cover { page: cover; }
.cover img { width: 210mm; height: 297mm; object-fit: cover; display: block; }

.content { page: content; }
.content h1 { color: #7f1d1d; border-bottom: 3px solid #7f1d1d; padding-bottom: .3rem; }
.content h2 { color: #991b1b; margin-top: 1.6em; }
.content h3 { color: #292524; }
.content code, .content pre {
  font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
  background: #f5f5f4; border-radius: 3px;
}
.content code { padding: 0 .25rem; font-size: .9em; }
.content pre { padding: .75em; overflow-x: auto; }
.content pre code { background: transparent; padding: 0; }
.content img { max-width: 100%; border: 1px solid #d6d3d1; border-radius: 4px; }
.content table { border-collapse: collapse; width: 100%; margin: 1em 0; }
.content th, .content td { border: 1px solid #d6d3d1; padding: .4em .6em; text-align: left; vertical-align: top; }
.content th { background: #f5f5f4; }
.content blockquote {
  border-left: 3px solid #d6d3d1; margin-left: 0; padding-left: .75em;
  color: #57534e; font-style: italic;
}
.content em { color: #57534e; }
.content hr { border: none; border-top: 1px solid #d6d3d1; margin: 2em 0; }
"""


def _md_to_html(markdown: Path) -> str:
    result = subprocess.run(
        ["pandoc", "-f", "markdown", "-t", "html5", str(markdown)],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def build_document(cover: Path, body_html: str) -> str:
    cover_src = cover.name
    return (
        "<!DOCTYPE html>\n"
        "<html><head><meta charset='utf-8'>"
        f"<style>{_CSS}</style></head><body>"
        f"<section class='cover'><img src='{cover_src}' alt='Portada'></section>"
        f"<div class='content'>{body_html}</div>"
        "</body></html>"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--markdown", default="docs/reporte.md", help="Markdown fuente")
    parser.add_argument("--cover", default="docs/Portada-reporte.png", help="Imagen de portada")
    parser.add_argument("--output", default="docs/reporte.pdf", help="PDF de salida")
    args = parser.parse_args()

    markdown = Path(args.markdown).resolve()
    cover = Path(args.cover).resolve()
    output = Path(args.output).resolve()

    if not markdown.exists():
        raise SystemExit(f"Markdown no encontrado: {markdown}")
    if not cover.exists():
        raise SystemExit(f"Portada no encontrada: {cover}")

    body_html = _md_to_html(markdown)
    document = build_document(cover, body_html)
    base_url = markdown.parent.as_uri() + "/"
    HTML(string=document, base_url=base_url).write_pdf(str(output))
    print(f"PDF generado: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
