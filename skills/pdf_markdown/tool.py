"""Skill pdf_markdown — convierte un PDF a Markdown y extrae sus imágenes.

Envuelve `tools/pdf_a_markdown.py` para exponerlo al ToolRegistry. Import perezoso: el
registro no falla si faltan pdfplumber / pypdf / pypdfium2.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


def pdf_a_markdown(args: dict) -> str:
    ruta = args.get("pdf", "").strip()
    if not ruta:
        return "ERROR: falta 'pdf' (ruta del archivo a convertir)."
    pdf_path = Path(ruta).expanduser()
    if not pdf_path.is_file():
        return f"ERROR: no existe el archivo {pdf_path}"

    sys.path.insert(0, str(ROOT / "tools"))
    try:
        import pdf_a_markdown as motor  # import perezoso
    except ImportError as e:
        return f"ERROR: no pude cargar el motor (tools/pdf_a_markdown.py): {e}"

    try:
        r = motor.convertir(pdf_path, Path(args.get("out", "salida_md")).expanduser(),
                            columnas=str(args.get("columnas", "auto")),
                            figuras=bool(args.get("figuras", True)),
                            dpi=int(args.get("dpi", 200) or 200))
    except (RuntimeError, ValueError, OSError) as e:
        return f"ERROR: {e}"

    aviso = ("" if r["rasters"] + r["figuras"] else
             " El PDF no trae rasters ni dibujo vectorial que parezca figura; si esperabas "
             "figuras y no hay texto extraído, probablemente sea un escaneo y necesite OCR.")
    return (f"OK: {r['md']} · {r['paginas']} páginas ({r['dos_columnas']} a dos columnas) · "
            f"{r['caracteres']:,} caracteres · {r['tablas']} tablas · "
            f"{r['rasters']} rasters + {r['figuras']} figuras rasterizadas.{aviso}")


def register_skill(reg) -> None:
    reg.register(
        "pdf_a_markdown",
        "Convierte un PDF a Markdown y extrae sus imágenes (rasters incrustados y figuras "
        "vectoriales rasterizadas), respetando el orden de lectura a dos columnas.",
        {"type": "object",
         "properties": {"pdf": {"type": "string", "description": "Ruta del PDF."},
                        "out": {"type": "string", "description": "Carpeta de salida."},
                        "columnas": {"type": "string", "enum": ["auto", "1", "2"]},
                        "dpi": {"type": "integer", "description": "Resolución de figuras."},
                        "figuras": {"type": "boolean",
                                    "description": "Rasterizar figuras vectoriales."}},
         "required": ["pdf"]},
        pdf_a_markdown,
    )
