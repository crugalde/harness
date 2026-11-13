#!/usr/bin/env python3
"""exportar.py — Convierte un .md (resumen o análisis) a PDF/HTML y extrae sus esquemas.

- Markdown -> HTML con tablas y estilos de impresión A4.
- Bloques ```mermaid``` se dibujan con mermaid.js en Chromium (vía Playwright) y quedan como
  figuras vectoriales en el PDF. Con --esquemas DIR, cada diagrama se guarda además como SVG.
- Sin conexión, mermaid.js (CDN) no carga: el PDF se genera igual mostrando el código del
  diagrama y se avisa. Los .md siguen viéndose bien en Obsidian/GitHub, que renderizan Mermaid.

Uso:
    python3 scripts/exportar.py workspace/analisis_globales/x.md --pdf workspace/analisis_globales/x.pdf
    python3 scripts/exportar.py x.md --pdf x.pdf --esquemas workspace/analisis_globales/esquemas
    python3 scripts/exportar.py x.md --html x.html          # sin navegador

Dependencias: markdown; para PDF/SVG además playwright + Chromium:
    pip install markdown playwright && python3 -m playwright install chromium
Si ya tienes un Chromium, apúntalo con CHROMIUM_PATH=/ruta/al/binario.
"""

from __future__ import annotations

import argparse
import html
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _comun import log  # noqa: E402

MERMAID_CDN = "https://cdn.jsdelivr.net/npm/mermaid@11.4.1/dist/mermaid.min.js"

CSS = """
@page { size: A4; margin: 18mm 16mm; }
body { font-family: "Helvetica Neue", Arial, sans-serif; font-size: 10.5pt; line-height: 1.45;
       color: #1a1a1a; max-width: 180mm; margin: 0 auto; }
h1 { font-size: 17pt; border-bottom: 2px solid #1f4e79; padding-bottom: 4px; color: #1f4e79; }
h2 { font-size: 13pt; color: #1f4e79; margin-top: 18px; page-break-after: avoid; }
h3 { font-size: 11pt; }
table { border-collapse: collapse; width: 100%; font-size: 8.5pt; margin: 8px 0;
        page-break-inside: auto; }
th, td { border: 1px solid #b7c4d1; padding: 4px 5px; vertical-align: top; text-align: left; }
th { background: #e8eef5; }
tr { page-break-inside: avoid; }
code { background: #f3f3f3; padding: 1px 3px; border-radius: 3px; font-size: 9pt; }
pre { background: #f6f8fa; padding: 8px; overflow-x: auto; font-size: 8.5pt; }
pre.mermaid { background: none; text-align: center; page-break-inside: avoid; }
blockquote { border-left: 3px solid #b7c4d1; margin: 8px 0; padding: 2px 10px; color: #444; }
.meta { font-size: 9pt; color: #444; border: 1px solid #dde3ea; padding: 6px 8px;
        margin-bottom: 10px; }
.meta td { border: none; padding: 1px 6px 1px 0; }
"""


def _frontmatter(texto: str) -> tuple[list[tuple[str, str]], str]:
    m = re.match(r"^---\n(.*?)\n---\n?", texto, re.S)
    if not m:
        return [], texto
    pares = []
    for linea in m.group(1).splitlines():
        if ":" in linea and not linea.startswith((" ", "-")):
            k, _, v = linea.partition(":")
            pares.append((k.strip(), v.strip().strip('"')))
    return pares, texto[m.end() :]


def md_a_html(texto: str, titulo: str = "Documento") -> tuple[str, int]:
    """Devuelve (html_completo, n_diagramas_mermaid)."""
    try:
        import markdown
    except ImportError as exc:
        raise RuntimeError("Falta 'markdown': pip install markdown") from exc

    meta, cuerpo = _frontmatter(texto)
    diagramas: list[str] = []

    def _guardar(m: re.Match[str]) -> str:
        diagramas.append(m.group(1))
        return f"\n\nMERMAIDBLOQUE{len(diagramas) - 1}\n\n"

    cuerpo = re.sub(r"```mermaid\n(.*?)```", _guardar, cuerpo, flags=re.S)
    contenido = markdown.markdown(cuerpo, extensions=["tables", "fenced_code", "sane_lists"])
    for i, codigo in enumerate(diagramas):
        bloque = f'<pre class="mermaid">{html.escape(codigo)}</pre>'
        contenido = contenido.replace(f"<p>MERMAIDBLOQUE{i}</p>", bloque)

    filas_meta = "".join(
        f"<tr><td><b>{html.escape(k)}</b></td><td>{html.escape(v)}</td></tr>"
        for k, v in meta
        if k not in ("tags",)
    )
    bloque_meta = f'<table class="meta">{filas_meta}</table>' if filas_meta else ""
    script = ""
    if diagramas:
        script = f"""
<script src="{MERMAID_CDN}"></script>
<script>
  window.__listo = false;
  try {{
    mermaid.initialize({{ startOnLoad: false, theme: "neutral", securityLevel: "strict" }});
    mermaid.run().then(() => {{ window.__listo = true; }})
      .catch(e => {{ window.__error = String(e); window.__listo = true; }});
  }} catch (e) {{ window.__error = String(e); window.__listo = true; }}
</script>"""
    documento = f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><title>{html.escape(titulo)}</title>
<style>{CSS}</style></head>
<body>{bloque_meta}{contenido}{script}</body></html>"""
    return documento, len(diagramas)


def renderizar(
    documento: str, n_diagramas: int, pdf: Path | None, esquemas: Path | None
) -> list[Path]:
    """Abre Chromium, espera a Mermaid y escribe PDF y/o SVGs. Devuelve los archivos creados."""
    try:
        from playwright.sync_api import Error as PWError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Falta playwright: pip install playwright && python3 -m playwright install chromium"
        ) from exc

    creados: list[Path] = []
    with sync_playwright() as p:
        try:
            navegador = p.chromium.launch(executable_path=os.environ.get("CHROMIUM_PATH") or None)
        except PWError as exc:
            raise RuntimeError(
                f"No se pudo abrir Chromium ({exc}). Ejecuta: python3 -m playwright install "
                "chromium, o define CHROMIUM_PATH."
            ) from exc
        pagina = navegador.new_page()
        pagina.set_content(documento, wait_until="load")
        if n_diagramas:
            try:
                pagina.wait_for_function("window.__listo === true", timeout=30_000)
                error = pagina.evaluate("window.__error || ''")
            except PWError:
                error = "mermaid.js no cargó (¿sin conexión?)"
            if error:
                log.warning("Diagramas no renderizados: %s. Se muestra su código.", error)
        if pdf:
            pdf.parent.mkdir(parents=True, exist_ok=True)
            pagina.pdf(
                path=str(pdf),
                format="A4",
                print_background=True,
                margin={"top": "18mm", "bottom": "18mm", "left": "16mm", "right": "16mm"},
            )
            creados.append(pdf)
        if esquemas and n_diagramas:
            svgs = pagina.eval_on_selector_all(
                "pre.mermaid svg", "els => els.map(e => e.outerHTML)"
            )
            esquemas.mkdir(parents=True, exist_ok=True)
            for i, svg in enumerate(svgs, 1):
                destino = esquemas / f"esquema_{i}.svg"
                destino.write_text(svg, encoding="utf-8")
                creados.append(destino)
        navegador.close()
    return creados


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Exporta un .md a PDF/HTML y sus esquemas a SVG.")
    ap.add_argument("archivo")
    ap.add_argument("--pdf", help="Ruta del PDF de salida")
    ap.add_argument("--html", help="Ruta del HTML de salida (no requiere navegador)")
    ap.add_argument("--esquemas", help="Carpeta donde guardar cada diagrama Mermaid como SVG")
    args = ap.parse_args(argv)
    if not (args.pdf or args.html or args.esquemas):
        ap.error("indica al menos --pdf, --html o --esquemas")

    origen = Path(args.archivo).expanduser()
    if not origen.is_file():
        log.error("No existe: %s", origen)
        return 1
    try:
        documento, n = md_a_html(origen.read_text(encoding="utf-8"), origen.stem)
        creados: list[Path] = []
        if args.html:
            destino = Path(args.html).expanduser()
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_text(documento, encoding="utf-8")
            creados.append(destino)
        if args.pdf or args.esquemas:
            creados += renderizar(
                documento,
                n,
                Path(args.pdf).expanduser() if args.pdf else None,
                Path(args.esquemas).expanduser() if args.esquemas else None,
            )
    except RuntimeError as exc:
        log.error("%s", exc)
        return 1
    for c in creados:
        print(f"-> {c}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
