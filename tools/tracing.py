#!/usr/bin/env python3
"""trace.py — Observabilidad del harness.

Registra cada sesión en JSONL (shared/traces/AAAA-MM-DD.jsonl): turnos, tool calls, uso de
tokens, costo estimado y latencia. Es el insumo tanto de los evals como del journal de
autoaprendizaje (§10), que de otro modo aprende a ciegas.
"""
from __future__ import annotations
import json, sys, time
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "shared" / "traces"

# La tabla de precios vive en model_policy (fuente única: la usa también el techo de costo).
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from model_policy import PRICES, cost_usd
except ImportError:  # tracing debe funcionar aunque falte la política
    PRICES = {"claude-sonnet-5": (2.0, 10.0), "claude-opus-5": (5.0, 25.0),
              "claude-haiku-4-5": (1.0, 5.0), "claude-sonnet-4-6": (3.0, 15.0)}

    def cost_usd(model, inp, out):
        pi, po = PRICES.get(model, (0.0, 0.0))
        return round(inp / 1e6 * pi + out / 1e6 * po, 6)


class Trace:
    def __init__(self, agent: str | None, project: str | None = None):
        self.rec = {"ts": datetime.now(timezone.utc).isoformat(), "agent": agent,
                    "project": project, "turns": [], "tools": [], "usage": {}}
        self.t0 = time.time()

    def turn(self, role: str, summary: str):
        self.rec["turns"].append({"role": role, "summary": (summary or "")[:300]})

    def tool(self, name: str, ok: bool):
        self.rec["tools"].append({"name": name, "ok": ok})

    def usage(self, model: str, inp: int, out: int):
        """Acumula el uso del turno. Un turno puede tocar varios modelos (router de tiers)."""
        u = self.rec["usage"]
        u["model"] = model if not u.get("model") else (
            u["model"] if model in u["model"].split("+") else f"{u['model']}+{model}")
        u["input"] = u.get("input", 0) + inp
        u["output"] = u.get("output", 0) + out
        u["cost_usd"] = round(u.get("cost_usd", 0.0) + cost_usd(model, inp, out), 6)

    def close(self) -> Path:
        self.rec["latency_s"] = round(time.time() - self.t0, 2)
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        f = LOG_DIR / f"{date.today().isoformat()}.jsonl"
        with f.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(self.rec, ensure_ascii=False) + "\n")
        return f


def summarize(day: str | None = None) -> str:
    f = LOG_DIR / f"{day or date.today().isoformat()}.jsonl"
    if not f.exists():
        return "(sin trazas)"
    recs = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
    cost = sum(r.get("usage", {}).get("cost_usd", 0) for r in recs)
    tools = sum(len(r.get("tools", [])) for r in recs)
    return f"{len(recs)} sesiones · {tools} tool calls · ~${cost:.4f} · {f.name}"


if __name__ == "__main__":
    print(summarize())
