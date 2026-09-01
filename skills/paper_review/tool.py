"""Skill paper_review — análisis científico multi-paper con modelo por etapa.

Envuelve `tools/paper_review.py` para exponerlo al ToolRegistry. Import perezoso: el
registro no falla si faltan pypdf / python-docx / biopython.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


def paper_review(args: dict) -> str:
    folder = args.get("dir", "").strip()
    if not folder:
        return "ERROR: falta 'dir' (carpeta con los PDF/DOCX)."
    sys.path.insert(0, str(ROOT / "tools"))
    try:
        import paper_review as pipeline  # import perezoso
    except ImportError as e:
        return f"ERROR: no pude cargar el pipeline (tools/paper_review.py): {e}"
    try:
        payload = pipeline.run(
            Path(folder).expanduser(),
            Path(args.get("out", "revision")).expanduser(),
            args.get("tema", "Revisión de literatura"),
            max_papers=int(args.get("max_papers", 0) or 0),
            use_pubmed=bool(args.get("use_pubmed", True)),
            dry_run=bool(args.get("dry_run", False)),
        )
    except (FileNotFoundError, RuntimeError, ValueError) as e:
        return f"ERROR: {e}"
    n_err = sum(1 for p in payload["papers"] if p["errores"])
    return (f"OK: {len(payload['papers'])} papers analizados ({n_err} con incidencias). "
            f"Modelos: ficha={payload['modelos']['ficha']}, "
            f"síntesis={payload['modelos']['sintesis']}. "
            f"Costo estimado ${payload['costo_usd_estimado']:.4f}. "
            f"Salidas en {args.get('out', 'revision')}/revision.md y revision.json.")


def register_skill(reg) -> None:
    reg.register(
        "paper_review",
        "Analiza varios papers (PDF/DOCX) de una carpeta, los contrasta con PubMed y "
        "produce revision.md + revision.json. Usa Sonnet por paper y Opus para la síntesis.",
        {"type": "object",
         "properties": {"dir": {"type": "string", "description": "Carpeta con los documentos."},
                        "tema": {"type": "string", "description": "Pregunta de la revisión."},
                        "out": {"type": "string", "description": "Carpeta de salida."},
                        "max_papers": {"type": "integer"},
                        "use_pubmed": {"type": "boolean"},
                        "dry_run": {"type": "boolean"}},
         "required": ["dir"]},
        paper_review,
    )
