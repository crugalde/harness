#!/usr/bin/env python3
"""backends.py — Capa de ejecución multi-modelo del harness.

`model_policy.py` decide QUÉ modelo; este módulo sabe CÓMO hablarle a cada uno:

- `AnthropicBackend`  — Claude API. Da forma a la petición según las capacidades reales
  del modelo (Opus 5 / Sonnet 5 aceptan `thinking: adaptive` + `output_config.effort`;
  Haiku 4.5 es familia previa y ambos parámetros le dan error).
- `LocalOpenAIBackend` — motor local con API compatible OpenAI (LM Studio, Ollama,
  vLLM). Traduce el formato de bloques de Anthropic a `chat/completions` y de vuelta.
  Solo stdlib: no añade dependencias al harness.
- `RoutedBackend`     — el orquestador de modelos. Por cada turno clasifica la tarea,
  declara el tier ANTES de ejecutar, aplica el techo de costo y degrada a cloud si el
  motor local no responde.

Todos respetan la interfaz `Backend` de `loop.py`:
    complete(system, messages, tools) -> {"text", "tool_calls", "stop_reason"}
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import model_policy as mp  # noqa: E402

DEFAULT_MAX_TOKENS = 8000
LOCAL_TIMEOUT_S = float(os.environ.get("HARNESS_LOCAL_TIMEOUT", "180"))


class BackendError(RuntimeError):
    """Fallo de un backend concreto. Nunca se silencia: o degrada o sube (R4)."""


# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------
class AnthropicBackend:
    """Claude API, con la forma de petición correcta para cada familia de modelo."""

    def __init__(self, model: str = "claude-sonnet-5", max_tokens: int = DEFAULT_MAX_TOKENS):
        from anthropic import Anthropic  # import perezoso: el harness corre sin la lib
        self.client = Anthropic()
        self.model = model
        self.max_tokens = max_tokens
        self.last_usage: tuple[int, int] = (0, 0)

    def complete(self, system, messages, tools, effort: str | None = None) -> dict:
        cap = mp.caps(self.model)
        kwargs: dict = {"model": self.model, "max_tokens": self.max_tokens,
                        "system": system, "messages": messages, "tools": tools or []}
        if cap["thinking"] == "adaptive":
            kwargs["thinking"] = {"type": "adaptive"}
        if cap["effort"] and effort:
            kwargs["output_config"] = {"effort": effort}

        r = self.client.messages.create(**kwargs)
        text = "".join(b.text for b in r.content if b.type == "text")
        calls = [{"id": b.id, "name": b.name, "input": b.input}
                 for b in r.content if b.type == "tool_use"]
        usage = getattr(r, "usage", None)
        self.last_usage = (getattr(usage, "input_tokens", 0) or 0,
                           getattr(usage, "output_tokens", 0) or 0)
        return {"text": text, "tool_calls": calls, "stop_reason": r.stop_reason}


# ---------------------------------------------------------------------------
# Local (API compatible OpenAI)
# ---------------------------------------------------------------------------
def _to_openai(system: str, messages: list[dict]) -> list[dict]:
    """Traduce el historial en bloques de Anthropic al formato chat/completions."""
    out: list[dict] = [{"role": "system", "content": system}] if system else []
    for m in messages:
        content = m.get("content")
        if isinstance(content, str):
            out.append({"role": m["role"], "content": content})
            continue
        text_parts, tool_calls, tool_results = [], [], []
        for b in content or []:
            btype = b.get("type")
            if btype == "text":
                text_parts.append(b.get("text", ""))
            elif btype == "tool_use":
                tool_calls.append({"id": b["id"], "type": "function",
                                   "function": {"name": b["name"],
                                                "arguments": json.dumps(b.get("input", {}),
                                                                        ensure_ascii=False)}})
            elif btype == "tool_result":
                tool_results.append({"role": "tool", "tool_call_id": b.get("tool_use_id", ""),
                                     "content": str(b.get("content", ""))})
        if text_parts or tool_calls:
            msg: dict = {"role": m["role"], "content": "\n".join(text_parts) or None}
            if tool_calls:
                msg["tool_calls"] = tool_calls
            out.append(msg)
        out.extend(tool_results)
    return out


def _to_openai_tools(tools: list[dict]) -> list[dict]:
    return [{"type": "function",
             "function": {"name": t["name"], "description": t.get("description", ""),
                          "parameters": t.get("input_schema", {"type": "object",
                                                               "properties": {}})}}
            for t in tools or []]


class LocalOpenAIBackend:
    """Motor local vía endpoint compatible OpenAI (LM Studio, Ollama, vLLM)."""

    def __init__(self, model: str, base_url: str | None = None,
                 max_tokens: int = DEFAULT_MAX_TOKENS):
        self.model = model
        self.base_url = (base_url or os.environ.get(
            "HARNESS_LOCAL_BASE_URL", "http://127.0.0.1:1234/v1")).rstrip("/")
        self.max_tokens = max_tokens
        self.last_usage: tuple[int, int] = (0, 0)

    def complete(self, system, messages, tools, effort: str | None = None) -> dict:
        payload = {"model": self.model, "messages": _to_openai(system, messages),
                   "max_tokens": self.max_tokens, "stream": False}
        if tools:
            payload["tools"] = _to_openai_tools(tools)
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {os.environ.get('HARNESS_LOCAL_API_KEY', 'local')}"},
            method="POST")
        try:
            with urllib.request.urlopen(req, timeout=LOCAL_TIMEOUT_S) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise BackendError(f"motor local {self.base_url} respondió {e.code}: "
                               f"{e.read()[:300].decode('utf-8', 'replace')}") from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise BackendError(f"motor local {self.base_url} inalcanzable: {e}") from e

        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message", {}) or {}
        calls = []
        for i, tc in enumerate(msg.get("tool_calls") or []):
            fn = tc.get("function", {})
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError as e:
                nombre = fn.get("name")
                raise BackendError(
                    f"el motor local devolvió argumentos no-JSON para '{nombre}': {e}") from e
            calls.append({"id": tc.get("id") or f"local_{i}", "name": fn.get("name", ""),
                          "input": args})
        usage = data.get("usage") or {}
        self.last_usage = (usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))
        return {"text": msg.get("content") or "", "tool_calls": calls,
                "stop_reason": "tool_use" if calls else (choice.get("finish_reason") or "end_turn")}


# ---------------------------------------------------------------------------
# Router de modelos
# ---------------------------------------------------------------------------
def _last_user_text(messages: list[dict]) -> str:
    for m in reversed(messages or []):
        if m.get("role") != "user":
            continue
        c = m.get("content")
        if isinstance(c, str):
            return c
        parts = [b.get("text", "") for b in (c or []) if b.get("type") == "text"]
        if parts:
            return "\n".join(parts)
    return ""


def _confirm_tty(decision: mp.Decision) -> bool:
    print(f"\nGATE de costo · {decision.declare()}")
    respuesta = input("¿Autorizas este modelo para este turno? [si para confirmar] ")
    return respuesta.strip().lower() == "si"


class RoutedBackend:
    """Elige modelo por turno, lo declara, cobra el techo y degrada si el local falla.

    - `task_class`: si el llamador ya sabe la clase (p. ej. el pipeline de papers), la
      impone; si no, se clasifica el último mensaje del usuario.
    - `phi=True`: fuerza tiers locales (R8). Si no hay local, aborta en vez de filtrar.
    - `confirm_fn`: Gate humano cuando el costo estimado supera el techo. Inyectable
      para poder correr headless (devuelve False = se cancela el turno).
    """

    def __init__(self, guard: mp.CostGuard | None = None,
                 confirm_fn: Callable[[mp.Decision], bool] | None = None,
                 on_decision: Callable[[mp.Decision], None] | None = None,
                 on_usage: Callable[[str, int, int], None] | None = None,
                 max_tokens: int = DEFAULT_MAX_TOKENS, phi: bool = False):
        self.guard = guard or mp.CostGuard()
        self.confirm_fn = confirm_fn or _confirm_tty
        self.on_decision = on_decision or (lambda d: print(d.declare()))
        self.on_usage = on_usage
        self.max_tokens = max_tokens
        self.phi = phi
        self._cache: dict[tuple[str, str], object] = {}
        self.decisions: list[mp.Decision] = []

    # -- construcción de backends concretos (cacheada por proveedor+modelo) --
    def _backend(self, provider: str, model: str):
        key = (provider, model)
        if key not in self._cache:
            self._cache[key] = (LocalOpenAIBackend(model, max_tokens=self.max_tokens)
                                if provider == "local"
                                else AnthropicBackend(model, max_tokens=self.max_tokens))
        return self._cache[key]

    def _decide(self, system: str, messages: list[dict], task_class: str | None) -> mp.Decision:
        cls = task_class or mp.classify(_last_user_text(messages))[0]
        est_in = mp.estimate_tokens(system) + mp.estimate_tokens(json.dumps(messages)[:200_000])
        return mp.plan(cls, est_in_tokens=est_in, est_out_tokens=self.max_tokens // 2,
                       phi=self.phi, guard=self.guard)

    def complete(self, system, messages, tools, task_class: str | None = None) -> dict:
        decision = self._decide(system, messages, task_class)
        self.decisions.append(decision)
        self.on_decision(decision)

        if decision.needs_confirmation and not self.confirm_fn(decision):
            return {"text": "Turno cancelado: el costo superaba el techo y no hubo confirmación.",
                    "tool_calls": [], "stop_reason": "end_turn"}

        try:
            backend = self._backend(decision.provider, decision.model)
            resp = backend.complete(system, messages, tools, effort=decision.effort)
        except BackendError as e:
            fallback = self._fallback(decision)
            if fallback is None:
                raise
            print(f"[modelo] {e} → degrado a {fallback.model} ({fallback.provider})")
            decision = fallback
            self.decisions.append(decision)
            self.on_decision(decision)
            backend = self._backend(decision.provider, decision.model)
            resp = backend.complete(system, messages, tools, effort=decision.effort)

        inp, out = getattr(backend, "last_usage", (0, 0))
        self.guard.record(decision.model, inp, out)
        if self.on_usage:
            self.on_usage(decision.model, inp, out)
        return resp

    def _fallback(self, decision: mp.Decision) -> mp.Decision | None:
        """Siguiente candidato de la clase, saltándose el tier que acaba de fallar."""
        if self.phi:
            return None  # con PHI no hay degradación a cloud: es la regla, no una preferencia
        table = mp.tiers()
        for cand in mp.CANDIDATES[decision.task_class]:
            tier = table[cand]
            if tier.id == decision.tier.id or tier.is_local:
                continue
            return mp.Decision(task_class=decision.task_class, tier=tier,
                               effort=decision.effort,
                               est_cost_usd=mp.cost_usd(tier.model, 4000, self.max_tokens // 2),
                               needs_confirmation=False,
                               reason=f"{tier.why} (fallback tras fallo de {decision.tier.id})",
                               degraded_from=decision.tier.id)
        return None


def make_backend(**kw) -> RoutedBackend:
    """Backend por defecto del harness: enrutado por clase de tarea."""
    return RoutedBackend(**kw)


def one_shot(prompt: str, *, task_class: str, system: str = "", phi: bool = False,
             guard: mp.CostGuard | None = None, max_tokens: int = DEFAULT_MAX_TOKENS,
             quiet: bool = False) -> str:
    """Una llamada suelta con la política aplicada. Lo usa el pipeline de papers."""
    rb = RoutedBackend(guard=guard, max_tokens=max_tokens, phi=phi,
                       on_decision=(lambda d: None) if quiet else (lambda d: print(d.declare())),
                       confirm_fn=_confirm_tty)
    resp = rb.complete(system, [{"role": "user", "content": prompt}], [], task_class=task_class)
    return resp["text"]
