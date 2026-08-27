"""Skill wiki_llm — acceso del harness al wiki LLM de `wiki/`.

Envuelve `tools/wiki.py` (misma lógica que el CLI, sin duplicarla) y la expone como tools del
ToolRegistry. Solo lectura salvo `wiki_index` (regenera el catálogo), `wiki_scan` (actualiza la cola de
ingesta) y `wiki_log` (append a la bitácora); ninguna crea, edita ni borra páginas — eso lo hace el agente siguiendo el flujo de
ingest de wiki/AGENTS.md §4.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


def _wiki():
    """Carga tools/wiki.py por ruta (el harness no es un paquete instalable)."""
    spec = importlib.util.spec_from_file_location("harness_wiki", ROOT / "tools" / "wiki.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _capture(fn, *args) -> str:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn(*args)
    return buf.getvalue().strip() or "(sin salida)"


def wiki_search(args: dict) -> str:
    query = (args.get("query") or "").strip()
    if not query:
        return "ERROR: falta 'query'."
    return _capture(_wiki().cmd_search, query, int(args.get("top", 5)))


def wiki_read(args: dict) -> str:
    """Lee una página por título, nombre de archivo o alias."""
    name = (args.get("pagina") or "").strip().lower()
    if not name:
        return "ERROR: falta 'pagina'."
    for p in _wiki().pages():
        candidates = {p.stem.lower(), p.get("titulo").lower(),
                      *(a.lower() for a in p.list("aliases"))}
        if name in candidates:
            return f"# {p.rel}\n\n{p.path.read_text(encoding='utf-8')}"
    return (f"No existe la página '{args['pagina']}'. Busca con wiki_search o revisa "
            "wiki/index.md antes de asumir que el wiki cubre el tema.")


def wiki_scan(args: dict) -> str:
    """Inventaría una carpeta de fuentes y actualiza la cola de ingesta."""
    carpeta = (args.get("carpeta") or "").strip()
    if not carpeta:
        return "ERROR: falta 'carpeta'."
    return _capture(_wiki().cmd_scan, carpeta, args.get("tema"))


def wiki_index(args: dict) -> str:
    return _capture(_wiki().cmd_index)


def wiki_lint(args: dict) -> str:
    return _capture(_wiki().cmd_lint, int(args.get("stale_days", 180)))


def wiki_log(args: dict) -> str:
    tipo = args.get("tipo", "ingest")
    if tipo not in ("ingest", "query", "lint", "refactor"):
        return "ERROR: 'tipo' debe ser ingest | query | lint | refactor."
    titulo = (args.get("titulo") or "").strip()
    if not titulo:
        return "ERROR: falta 'titulo'."
    detalles = args.get("detalles") or []
    if isinstance(detalles, str):
        detalles = [detalles]
    return _capture(_wiki().cmd_log, tipo, titulo, detalles)


def register_skill(reg) -> None:
    reg.register(
        "wiki_search",
        "Busca en el wiki LLM (BM25) y devuelve las páginas más relevantes con contexto.",
        {"type": "object",
         "properties": {"query": {"type": "string"}, "top": {"type": "integer"}},
         "required": ["query"]},
        wiki_search)
    reg.register(
        "wiki_read",
        "Lee una página completa del wiki por título, nombre de archivo o alias.",
        {"type": "object", "properties": {"pagina": {"type": "string"}},
         "required": ["pagina"]},
        wiki_read)
    reg.register(
        "wiki_scan",
        "Inventaría una carpeta de fuentes (PDF, md, docx): DOI, títulos, duplicados, "
        "archivos de iCloud sin descargar, y qué falta por ingerir.",
        {"type": "object",
         "properties": {"carpeta": {"type": "string"}, "tema": {"type": "string"}},
         "required": ["carpeta"]},
        wiki_scan)
    reg.register(
        "wiki_index",
        "Regenera wiki/index.md desde el front-matter de las páginas.",
        {"type": "object", "properties": {}},
        wiki_index)
    reg.register(
        "wiki_lint",
        "Verifica el wiki: enlaces rotos, páginas huérfanas, esbozos y front-matter incompleto.",
        {"type": "object", "properties": {"stale_days": {"type": "integer"}}},
        wiki_lint)
    reg.register(
        "wiki_log",
        "Añade una entrada a la bitácora del wiki (tipo: ingest|query|lint|refactor).",
        {"type": "object",
         "properties": {"tipo": {"type": "string"}, "titulo": {"type": "string"},
                        "detalles": {"type": "array", "items": {"type": "string"}}},
         "required": ["tipo", "titulo"]},
        wiki_log)
