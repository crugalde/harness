#!/usr/bin/env python3
"""loop.py (raíz) — alias de `tools/loop.py`.

Este archivo era una copia del runtime y se había quedado atrás (le faltaba el subagente
`home` y todo el enrutado de modelo). Ahora carga el runtime canónico y reexporta su
superficie, para que `python loop.py ...` y `python tools/loop.py ...` ejecuten lo mismo.

El runtime vive en `tools/loop.py`. No edites este archivo: edita aquel.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_TOOLS = Path(__file__).resolve().parent / "tools"
sys.path.insert(0, str(_TOOLS))

# Carga por ruta explícita: `import loop` aquí se resolvería a este mismo archivo.
_spec = importlib.util.spec_from_file_location("harness_loop", _TOOLS / "loop.py")
_runtime = importlib.util.module_from_spec(_spec)
sys.modules["harness_loop"] = _runtime
_spec.loader.exec_module(_runtime)

AGENTS = _runtime.AGENTS
DESTRUCTIVE = _runtime.DESTRUCTIVE
GATED_TOOLS = _runtime.GATED_TOOLS
MAX_ITERS = _runtime.MAX_ITERS
MODEL = _runtime.MODEL
ROOT = _runtime.ROOT
SKILLS_DIR = _runtime.SKILLS_DIR
Backend = _runtime.Backend
ToolRegistry = _runtime.ToolRegistry
guard_tool = _runtime.guard_tool
load_context = _runtime.load_context
load_skills = _runtime.load_skills
main = _runtime.main
route = _runtime.route
run = _runtime.run

if __name__ == "__main__":
    main()
