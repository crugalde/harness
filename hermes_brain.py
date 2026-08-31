#!/usr/bin/env python3
"""Lanzador del worker documental (carpetas → Hermes agent → brain md).

    python hermes_brain.py correr --carpeta "C:\\Users\\Usuario\\OneDrive\\Papers"
    python hermes_brain.py revisar

Equivale a `python -m hermes_brain …` con `tools/` en el PYTHONPATH. El código vive en
`tools/hermes_brain/`; la puesta en marcha, en `n8n/README.md`.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "tools"))

from hermes_brain.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
