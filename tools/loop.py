#!/usr/bin/env python3
"""loop.py — Runtime del harness (capa de ejecución).

Ciclo agnóstico al backend: ensambla contexto (jerarquía AGENTS.md + skills seleccionadas +
_estado.md), enruta al subagente y corre perceive -> plan -> act(tool) -> observe, con
guardas y gates.

Tres decisiones se toman y se DECLARAN antes de ejecutar nada:
  1. subagente   — `route()` (léxico, con desempate por modelo barato).
  2. skills      — `skill_selector` busca en el pool y carga las instrucciones completas
                   de las que ganan. Ninguna skill se usa "de memoria".
  3. modelo      — `model_policy` clasifica la tarea y elige el tier: local rápido para
                   transformación de formato, Sonnet 5 para síntesis, Opus 5 para análisis
                   científico. Autónomo mientras el costo estimado no supere el techo.

- Backend: interfaz pluggable (`RoutedBackend` por defecto; reemplazable por OpenClaw, etc.).
- ToolRegistry: registras aquí tus herramientas / servidores MCP.
- Guards: bloquea comandos destructivos y exige confirmación humana en acciones con efecto.

Uso:  python tools/loop.py "investiga X" --agent research [--project 2026-06-11_tema]
      python tools/loop.py "convierte esto a docx" --class format   # forzar tier
      python tools/loop.py "interpreta este EMG" --phi              # solo motores locales
Req:  pip install anthropic ; env ANTHROPIC_API_KEY [, HARNESS_MODEL, HARNESS_LOCAL_BASE_URL]
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

import model_policy as mp        # noqa: E402
import skill_selector            # noqa: E402

MODEL = os.environ.get("HARNESS_MODEL", "claude-sonnet-5")   # tier de trabajo (T2)
MAX_ITERS = 8
AGENTS = ["med", "research", "biz", "signals", "coach", "docs", "home"]
DESTRUCTIVE = re.compile(r"(rm\s+-rf|mkfs|dd\s+if=|:\(\)\s*\{|shutdown|reboot|>\s*/dev/sd)")
GATED_TOOLS = {"send_email", "post", "publish", "write_file", "delete", "vps_write",
               "git_push", "ha_call_service", "ha_lights_off"}


class Backend(Protocol):
    def complete(self, system: str, messages: list[dict], tools: list[dict]) -> dict: ...


def _complete(backend, system, messages, tools, task_class=None) -> dict:
    """Llama al backend pasándole la clase de tarea si la soporta (backends externos no)."""
    try:
        return backend.complete(system, messages, tools, task_class=task_class)
    except TypeError:
        return backend.complete(system, messages, tools)


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
    """Índice plano del pool (nombre: descripción). Es el catálogo, no la selección."""
    pool = skill_selector.index()
    if not pool:
        return "(sin skills)"
    return "\n".join(f"- {s.name}: {s.description}" for s in pool)


def load_context(agent: str | None, project: str | None, task: str | None = None,
                 select_skills: bool = True) -> tuple[str, str]:
    """Ensambla el system prompt. Devuelve (contexto, línea de declaración de skills).

    Con `task`, en vez de volcar el índice entero se cargan las **instrucciones completas**
    de las skills que ganan la búsqueda en el pool, y se deja constancia de cuáles fueron.
    """
    parts = [(ROOT / "AGENTS.md").read_text(encoding="utf-8")]
    if agent:
        sub = ROOT / "agents" / agent / "AGENTS.md"
        if sub.exists():
            parts.append(f"\n\n# --- Subagente activo: {agent} ---\n" + sub.read_text(encoding="utf-8"))

    declaration = ""
    if task and select_skills:
        declaration, block = skill_selector.context_block(task)
        parts.append("\n\n" + block)
    else:
        parts.append("\n\n# --- Skills disponibles ---\n" + load_skills())

    parts.append("\n\n# --- Política de modelos activa ---\n" + mp.table_markdown() +
                 "\n\nEl tier se declara antes de ejecutar. No cambies de modelo por tu "
                 "cuenta: la política lo resuelve el runtime.\n")

    if project:
        est = ROOT / "projects" / project / "_estado.md"
        if est.exists():
            parts.append("\n\n# --- Estado del proyecto ---\n" + est.read_text(encoding="utf-8"))
    return "\n".join(parts), declaration


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
    # Desempate con modelo: es clasificación, va al tier más barato disponible.
    r = _complete(backend,
                  f"Clasifica el mensaje en uno de: {', '.join(AGENTS)}. Responde solo el id.",
                  [{"role": "user", "content": user_msg}], [], task_class="route")
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


def run(user_msg, agent=None, project=None, registry=None, backend=None, max_iters=MAX_ITERS,
        task_class=None, phi=False, select_skills=True):
    """Un turno completo: declara subagente, skills y tier; luego ejecuta el ciclo de tools."""
    try:
        from tracing import Trace
        tr = Trace(agent, project)
    except Exception:
        tr = None

    backend = backend or _make_backend(phi=phi, trace=tr)
    registry = registry or ToolRegistry()
    if agent is None:
        agent = route(user_msg, backend)
        print(f"[router] -> {agent}")

    system, skill_line = load_context(agent, project, task=user_msg, select_skills=select_skills)
    if skill_line:
        print(skill_line)

    messages = [{"role": "user", "content": user_msg}]
    for _ in range(max_iters):
        resp = _complete(backend, system, messages, registry.schemas(), task_class=task_class)
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
    if isinstance(backend, object) and hasattr(backend, "guard"):
        print(f"[costo] corrida ~${backend.guard.spent:.4f} USD")
    if tr: tr.close()
    return messages


def _make_backend(phi: bool = False, trace=None):
    """Backend por defecto: enruta el modelo por clase de tarea y registra el uso."""
    import backends
    on_usage = (lambda model, i, o: trace.usage(model, i, o)) if trace else None
    return backends.make_backend(phi=phi, on_usage=on_usage)


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
    ap.add_argument("--class", dest="task_class", choices=mp.CLASSES,
                    help="Forzar la clase de tarea (y con ella el tier de modelo).")
    ap.add_argument("--phi", action="store_true",
                    help="Hay datos de paciente: restringe la ejecución a motores locales (R8).")
    ap.add_argument("--no-skills", action="store_true",
                    help="No seleccionar skills; inyecta solo el índice del pool.")
    args = ap.parse_args()
    try:
        from registry import build_registry
        reg = build_registry()
    except Exception as e:
        print(f"[loop] registry por defecto (demo): {e}")
        reg = _demo_registry()
    run(args.mensaje, agent=args.agent, project=args.project, registry=reg,
        task_class=args.task_class, phi=args.phi, select_skills=not args.no_skills)


if __name__ == "__main__":
    main()
