#!/usr/bin/env python3
"""schedule_distill.py — Disparador del autoaprendizaje.

Corre `distill` (fases 2-3) para el orquestador y cada subagente. NO aplica nada: solo genera
propuestas que esperan tu Gate humano. Pensado para correr periódicamente.

Uso:  python tools/schedule_distill.py

Cron (ej. diario 03:00), en `crontab -e`:
  0 3 * * * cd /ruta/al/harness && /ruta/.venv/bin/python tools/schedule_distill.py >> shared/traces/distill.log 2>&1
"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SELF_IMPROVE = ROOT / "tools" / "self_improve.py"
AGENTS = [None, "med", "research", "biz", "signals", "coach", "docs"]


def main():
    py = sys.executable
    for agent in AGENTS:
        cmd = [py, str(SELF_IMPROVE), "distill"] + (["--agent", agent] if agent else [])
        label = agent or "orquestador"
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            print(f"[{label}] {r.stdout.strip() or r.stderr.strip()}")
        except Exception as e:
            print(f"[{label}] error: {e}")


if __name__ == "__main__":
    main()
