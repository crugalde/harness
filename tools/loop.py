#!/usr/bin/env python3
"""loop.py — Runtime del harness (capa de ejecución).

Ciclo agnóstico al backend: ensambla contexto (jerarquía AGENTS.md + skills + _estado.md),
enruta al subagente y corre perceive -> plan -> act(tool) -> observe, con guardas y gates.

- Backend: interfaz pluggable (AnthropicBackend por defecto; reemplazable por OpenClaw, etc.).
- ToolRegistry: registras aquí tus herramientas / servidores MCP.
- Guards: bloquea comandos destructivos y exige confirmación humana en acciones con efecto.

Uso:  python tools/loop.py "investiga X" --agent research [--project 2026-06-11_tema]
Req:  pip install anthropic ; env ANTHROPIC_API_KEY [, HARNESS_MODEL]
"""
from __future__ import annotations
import argparse, json, os, re, subprocess, sys
from pathlib import Path
from typing import Callable, Protocol

ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = ROOT / "skills"

# Carga el .env local (fuera de iCloud) antes de leer cualquier variable.
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from env_loader import load_env
    load_env()
except Exception:
    pass

MODEL = os.environ.get("HARNESS_MODEL", "claude-sonnet-4-6")
MAX_ITERS = 8
AGENTS = ["med", "research", "biz", "signals", "coach", "docs", "home"]
DESTRUCTIVE = re.compile(r"(rm\s+-rf|mkfs|dd\s+if=|:\(\)\s*\{|shutdown|reboot|>\s*/dev/sd)")
GATED_TOOLS = {"send_email", "post", "publish", "write_file", "delete", "vps_write",
               "git_push", "ha_call_service", "ha_lights_off",
               "n8n_workflow_create", "n8n_workflow_update", "n8n_workflow_activate"}


class Backend(Protocol):
    def complete(self, system: str, messages: list[dict], tools: list[dict]) -> dict: ...


class AnthropicBackend:
    """Backend por defecto. Sustituible por cualquier otro que respete la interfaz Backend."""
    def __init__(self, model: str = MODEL):
        from anthropic import Anthropic
        self.client, self.model = Anthropic(), model

    def complete(self, system, messages, tools):
        r = self.client.messages.create(model=self.model, max_tokens=2000,
                                        system=system, messages=messages, tools=tools or [])
        text = "".join(b.text for b in r.content if b.type == "text")
        calls = [{"id": b.id, "name": b.name, "input": b.input}
                 for b in r.content if b.type == "tool_use"]
        return {"text": text, "tool_calls": calls, "stop_reason": r.stop_reason}


class ToolRegistry:
    def __init__(self):
        self._fns: dict[str, Callable[[dict], str]] = {}
        self._schemas: list[dict] = []

    def register(self, name, description, input_schema, fn):
        self._fns[name] = fn
        self._schemas.append({"name": name, "description": description, "input_schema": input_schema})

    def schemas(self):
        return self._schemas

    def call(self, name, args):
        return self._fns[name](args)


def load_skills() -> str:
    if not SKILLS_DIR.exists():
        return "(sin skills)"
    out = []
    for sk in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        head = sk.read_text(encoding="utf-8")
        name = re.search(r"name:\s*(.+)", head)
        desc = re.search(r"description:\s*(.+)", head)
        out.append(f"- {(name.group(1).strip() if name else sk.parent.name)}: "
                   f"{(desc.group(1).strip() if desc else '')}")
    return "\n".join(out) or "(sin skills)"


def load_context(agent: str | None, project: str | None) -> str:
    parts = [(ROOT / "AGENTS.md").read_text(encoding="utf-8")]
    if agent:
        sub = ROOT / "agents" / agent / "AGENTS.md"
        if sub.exists():
            parts.append(f"\n\n# --- Subagente activo: {agent} ---\n" + sub.read_text(encoding="utf-8"))
    parts.append("\n\n# --- Skills disponibles ---\n" + load_skills())
    if project:
        est = ROOT / "projects" / project / "_estado.md"
        if est.exists():
            parts.append("\n\n# --- Estado del proyecto ---\n" + est.read_text(encoding="utf-8"))
    return "\n".join(parts)


def route(user_msg: str, backend: Backend) -> str:
    kw = {"med": ["emg", "ncs", "ultrasonido", "nmus", "clínico", "diagnóstico", "paciente"],
          "research": ["revisión", "pubmed", "paper", "investiga", "bibliografía", "evidencia"],
          "biz": ["negocio", "directorio", "costo", "proyecto", "presupuesto", "plan"],
          "signals": ["señal", "hd-semg", "semg", "descomposición", "descompón", "cadwell", ".sd", "unidad motora"],
          "coach": ["entrenamiento", "nutrición", "dieta", "bmr", "recuperación"],
          "docs": ["documento", "presentación", "informe", "reporte", "deck", "slides", "redacta", "compón"],
          "home": ["domótica", "home assistant", "hogar", "luz", "luces", "enciende", "apaga",
                   "switch", "sensor", "termostato", "clima", "automatización", "entidad", "escena"]}
    low = user_msg.lower()
    scores = {a: sum(w in low for w in words) for a, words in kw.items()}
    best = max(scores, key=scores.get)
    top = scores[best]
    if top > 0 and list(scores.values()).count(top) == 1:
        return best                                   # ganador claro por palabras clave
    if backend is None:                               # empate o cero, sin backend
        return "research"
    r = backend.complete(f"Clasifica el mensaje en uno de: {', '.join(AGENTS)}. Responde solo el id.",
                         [{"role": "user", "content": user_msg}], [])
    pick = r["text"].strip().lower()
    return pick if pick in AGENTS else "research"


def guard_tool(name: str, args: dict) -> str | None:
    """None = OK. Devuelve motivo si se bloquea o requiere confirmación."""
    if DESTRUCTIVE.search(json.dumps(args, ensure_ascii=False)):
        return "BLOQUEADO: patrón destructivo"
    if name in GATED_TOOLS:
        return f"GATE: '{name}' tiene efecto externo; requiere confirmación humana"
    return None


def _assistant_blocks(resp):
    blocks = [{"type": "text", "text": resp["text"]}] if resp["text"] else []
    for c in resp["tool_calls"]:
        blocks.append({"type": "tool_use", "id": c["id"], "name": c["name"], "input": c["input"]})
    return blocks


def run(user_msg, agent=None, project=None, registry=None, backend=None, max_iters=MAX_ITERS):
    backend = backend or AnthropicBackend()
    registry = registry or ToolRegistry()
    if agent is None:
        agent = route(user_msg, backend)
        print(f"[router] -> {agent}")
    try:
        from tracing import Trace
        tr = Trace(agent, project)
    except Exception:
        tr = None
    system = load_context(agent, project)
    messages = [{"role": "user", "content": user_msg}]
    for _ in range(max_iters):
        resp = backend.complete(system, messages, registry.schemas())
        if resp["text"]:
            print(resp["text"])
            if tr: tr.turn("assistant", resp["text"])
        if not resp["tool_calls"]:
            break
        messages.append({"role": "assistant", "content": _assistant_blocks(resp)})
        results = []
        for call in resp["tool_calls"]:
            verdict = guard_tool(call["name"], call["input"])
            if verdict and verdict.startswith("BLOQUEADO"):
                out, ok = verdict, False
            elif verdict and verdict.startswith("GATE"):
                print(f"\n{verdict}\n  args: {call['input']}")
                ok = input("¿Autorizas esta acción? [si para confirmar] ").strip().lower() == "si"
                out = registry.call(call["name"], call["input"]) if ok else "Acción cancelada por el humano."
            else:
                out, ok = registry.call(call["name"], call["input"]), True
            if tr: tr.tool(call["name"], ok)
            results.append({"type": "tool_result", "tool_use_id": call["id"], "content": str(out)})
        messages.append({"role": "user", "content": results})
    else:
        print(f"[loop] alcanzó el máximo de {max_iters} iteraciones.")
    if tr: tr.close()
    return messages


def _demo_registry() -> ToolRegistry:
    """Registry de ejemplo con una herramienta de shell de SOLO lectura, guardada.
    Aquí registras tus servidores MCP reales (PubMed, archivos, VPS, etc.)."""
    reg = ToolRegistry()

    def read_shell(args):
        cmd = args.get("cmd", "")
        if DESTRUCTIVE.search(cmd):
            return "BLOQUEADO"
        return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=20).stdout[:4000]

    reg.register("read_shell", "Ejecuta un comando de SOLO lectura y devuelve stdout.",
                 {"type": "object", "properties": {"cmd": {"type": "string"}}, "required": ["cmd"]},
                 read_shell)
    return reg


def main():
    ap = argparse.ArgumentParser(description="Runtime del harness (capa de ejecución).")
    ap.add_argument("mensaje")
    ap.add_argument("--agent", choices=AGENTS, help="Forzar subagente (si se omite, enruta solo).")
    ap.add_argument("--project", help="Proyecto para cargar/guardar _estado.md.")
    args = ap.parse_args()
    try:
        from registry import build_registry
        reg = build_registry()
    except Exception as e:
        print(f"[loop] registry por defecto (demo): {e}")
        reg = _demo_registry()
    run(args.mensaje, agent=args.agent, project=args.project, registry=reg)


if __name__ == "__main__":
    main()
