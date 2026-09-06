#!/usr/bin/env python3
"""Exporta el reporte en Markdown a PDF con portada y diagramas mermaid.

Convierte ``docs/reporte.md`` a HTML con pandoc y lo renderiza con WeasyPrint,
anteponiendo ``docs/Portada-reporte.png`` como portada a página completa (A4).
Los bloques ``mermaid`` del Markdown se renderizan a PNG (mermaid-cli + Chrome
del sistema) y se incrustan en el PDF. El contenido arranca en la página 2, sin
numeración.

Uso:
    python3 scripts/export_report_pdf.py
    python3 scripts/export_report_pdf.py --markdown docs/reporte.md \
        --cover docs/Portada-reporte.png --output docs/reporte.pdf

Dependencias (instaladas en el host):
  - pandoc y weasyprint (Python)
  - Pillow (ajuste de tamaño de los diagramas)
  - mermaid-cli + Chrome del sistema (scripts/pdf-tools, ver README del repo)
"""

from __future__ import annotations

import argparse
import re
import subprocess
import tempfile
from pathlib import Path

from PIL import Image
from weasyprint import HTML

_MERMAID_RE = re.compile(r"```mermaid\s*\n(.*?)\n```", re.DOTALL)

# Caja de contenido A4 (márgenes de 2 cm) en píxeles a 96 dpi.
_CONTENT_W = 643
# Se deja un pequeño margen inferior para que un diagrama alto no roce el borde.
_CONTENT_H = 920
# Factor de súper-muestreo para diagramas anchos (mejor nitidez en impresión).
_SUPERSAMPLE = 3

_CHROME_CANDIDATES = (
    "/usr/bin/google-chrome-stable",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
)

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
.content img.diagram { border: none; margin: 1em auto; display: block; }
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


def _find_chrome() -> Path | None:
    for candidate in _CHROME_CANDIDATES:
        if Path(candidate).exists():
            return Path(candidate)
    return None


def _default_mmdc() -> Path:
    return Path(__file__).resolve().parent.parent / "scripts/pdf-tools/node_modules/.bin/mmdc"


def _fit_diagram(png_file: Path) -> None:
    """Ajusta un diagrama renderizado para que quepa en una página A4.

    Los diagramas anchos (relación alto/ancho ≤ 1.51) se mantienen con súper-muestreo:
    WeasyPrint los reduce con ``max-width``. Los diagramas altos se redimensionan a la
    altura de la caja de contenido para que no se desborden de la página.
    """
    with Image.open(png_file) as im:
        im = im.convert("RGB")
        width, height = im.size
        ratio = height / width
        if ratio <= _CONTENT_H / _CONTENT_W:
            target_w = min(_CONTENT_W * _SUPERSAMPLE, width)
            target_h = round(target_w * ratio)
        else:
            target_h = _CONTENT_H
            target_w = round(target_h / ratio)
        im = im.resize((target_w, target_h), Image.LANCZOS)
        im.save(png_file)


def _render_mermaid(
    markdown_text: str, tmpdir: Path, mmdc: Path, puppeteer_cfg: Path
) -> str:
    counter = 0

    def repl(match: re.Match[str]) -> str:
        nonlocal counter
        counter += 1
        source = match.group(1).strip()
        mmd_file = tmpdir / f"diagram_{counter}.mmd"
        png_file = tmpdir / f"diagram_{counter}.png"
        mmd_file.write_text(source, encoding="utf-8")
        subprocess.run(
            [
                str(mmdc),
                "-i",
                str(mmd_file),
                "-o",
                str(png_file),
                "-p",
                str(puppeteer_cfg),
                "-s",
                "3",
                "-b",
                "white",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        if not png_file.exists():
            raise RuntimeError(f"mermaid falló al renderizar el diagrama {counter}")
        _fit_diagram(png_file)
        return f'\n\n<img class="diagram" src="{png_file.as_uri()}" alt="Diagrama {counter}">\n\n'

    return _MERMAID_RE.sub(repl, markdown_text)


def _md_to_html(markdown_text: str) -> str:
    result = subprocess.run(
        ["pandoc", "-f", "markdown", "-t", "html5"],
        input=markdown_text,
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
    parser.add_argument("--mmdc", default=str(_default_mmdc()), help="Binario mermaid-cli")
    parser.add_argument("--chrome", default=None, help="Ejecutable de Chrome/Chromium")
    args = parser.parse_args()

    markdown = Path(args.markdown).resolve()
    cover = Path(args.cover).resolve()
    output = Path(args.output).resolve()
    mmdc = Path(args.mmdc)

    if not markdown.exists():
        raise SystemExit(f"Markdown no encontrado: {markdown}")
    if not cover.exists():
        raise SystemExit(f"Portada no encontrada: {cover}")

    chrome = Path(args.chrome) if args.chrome else _find_chrome()
    if chrome is None:
        raise SystemExit("No se encontró Chrome/Chromium; pásalo con --chrome")

    markdown_text = markdown.read_text(encoding="utf-8")

    with tempfile.TemporaryDirectory(prefix="reporte_") as tmp:
        tmpdir = Path(tmp)
        if _MERMAID_RE.search(markdown_text):
            if not mmdc.exists():
                raise SystemExit(
                    f"mermaid-cli no encontrado en {mmdc}; "
                    "instálalo con pnpm en scripts/pdf-tools"
                )
            puppeteer_cfg = tmpdir / "puppeteer-config.json"
            puppeteer_cfg.write_text(
                '{"executablePath": "%s", "args": ["--no-sandbox", "--disable-gpu", '
                '"--disable-dev-shm-usage"]}' % chrome.as_posix(),
                encoding="utf-8",
            )
            markdown_text = _render_mermaid(markdown_text, tmpdir, mmdc, puppeteer_cfg)

        body_html = _md_to_html(markdown_text)
        document = build_document(cover, body_html)
        base_url = markdown.parent.as_uri() + "/"
        HTML(string=document, base_url=base_url).write_pdf(str(output))

    print(f"PDF generado: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
