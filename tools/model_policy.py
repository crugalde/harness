#!/usr/bin/env python3
"""model_policy.py — Política de modelos del harness (qué motor para qué tarea).

Resuelve la pregunta operativa "¿con qué modelo ejecuto esto?" ANTES de ejecutar, y lo
declara en una línea. Tres piezas:

1. `classify(mensaje)` — clasifica la tarea en una clase (format, extract, route,
   synthesis, deep_analysis, vision) con un léxico ponderado bilingüe. Determinista y
   offline: no gasta un token en decidir qué modelo usar.
2. `plan(clase, ...)` — elige el tier según capacidad/velocidad/costo, con degradación
   ordenada (local → cloud barato → cloud capaz) y forzado a local cuando hay PHI (R8).
3. `CostGuard` — techo de costo por turno y por sesión: el salto al tier caro es
   autónomo mientras el costo estimado no supere el techo; por encima exige Gate (R9).

Sin dependencias externas y sin red: es la capa de decisión, no la de ejecución
(esa vive en `tools/backends.py`).

Uso directo (diagnóstico):  python tools/model_policy.py "analiza estos 4 papers"
"""
from __future__ import annotations

import os
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Precios oficiales de la Claude API, USD por 1M de tokens (input, output).
# Fuente: tabla de modelos vigente de la API. Los modelos locales cuestan 0.
# ---------------------------------------------------------------------------
PRICES: dict[str, tuple[float, float]] = {
    "claude-opus-5": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-sonnet-4-6": (3.0, 15.0),  # legacy: HARNESS_MODEL previo del harness
    "claude-opus-4-8": (5.0, 25.0),
}

# Capacidades por modelo: modelan la forma de la petición, no su calidad.
#   thinking: "adaptive" | "budget" | None      effort: acepta output_config.effort
CAPS: dict[str, dict] = {
    "claude-opus-5": {"thinking": "adaptive", "effort": True, "ctx": 1_000_000},
    "claude-sonnet-5": {"thinking": "adaptive", "effort": True, "ctx": 1_000_000},
    "claude-sonnet-4-6": {"thinking": "adaptive", "effort": True, "ctx": 1_000_000},
    "claude-opus-4-8": {"thinking": "adaptive", "effort": True, "ctx": 1_000_000},
    # Haiku 4.5 es familia previa: `effort` da error y thinking usa budget_tokens.
    "claude-haiku-4-5": {"thinking": "budget", "effort": False, "ctx": 200_000},
}
DEFAULT_CAPS = {"thinking": None, "effort": False, "ctx": 128_000}


def caps(model: str) -> dict:
    """Capacidades de forma de petición de un modelo (defaults conservadores)."""
    return CAPS.get(model, DEFAULT_CAPS)


# ---------------------------------------------------------------------------
# Tiers
# ---------------------------------------------------------------------------
def _env(key: str, default: str) -> str:
    return os.environ.get(key, default).strip() or default


@dataclass(frozen=True)
class Tier:
    """Un escalón de la política: un modelo concreto en un proveedor concreto."""
    id: str
    model: str
    provider: str          # "local" | "anthropic"
    speed: str             # "muy rápido" | "rápido" | "medio" | "lento"
    why: str

    @property
    def is_local(self) -> bool:
        return self.provider == "local"


def tiers() -> dict[str, Tier]:
    """Tabla de tiers, resuelta contra el entorno en cada llamada.

    Los modelos locales son configurables porque dependen de qué tenga cargado
    LM Studio / Ollama en la máquina; los cloud son fijos por política.
    """
    cloud_work = _env("HARNESS_MODEL", "claude-sonnet-5")  # HARNESS_MODEL = tier de trabajo
    return {
        "T0-local": Tier(
            "T0-local", _env("HARNESS_LOCAL_FAST_MODEL", "qwen2.5-7b-instruct"), "local",
            "muy rápido", "transformación mecánica: el modelo pequeño local basta y cuesta 0"),
        "T1-local": Tier(
            "T1-local", _env("HARNESS_LOCAL_MODEL", "nemotron-3.5-lightning"), "local",
            "rápido", "razonamiento autocontenido sin salida de datos de la máquina"),
        "T0-cloud": Tier(
            "T0-cloud", "claude-haiku-4-5", "anthropic",
            "muy rápido",
            "tarea mecánica sin motor local: el modelo cloud más barato"),
        "T2-cloud": Tier(
            "T2-cloud", cloud_work, "anthropic",
            "medio",
            "síntesis y lectura por documento: mejor relación capacidad/velocidad"),
        "T3-cloud": Tier(
            "T3-cloud", "claude-opus-5", "anthropic",
            "lento", "análisis científico transversal: capacidad máxima, se paga una sola vez"),
        "TV-local": Tier(
            "TV-local", _env("HARNESS_LOCAL_VISION_MODEL", "qwen3vl"), "local",
            "medio", "visión local: la imagen no sale de la máquina"),
    }


# Clase de tarea -> tiers candidatos, en orden de preferencia.
CANDIDATES: dict[str, list[str]] = {
    "format":        ["T0-local", "T0-cloud"],
    "extract":       ["T0-local", "T0-cloud"],
    "route":         ["T0-local", "T0-cloud"],
    "synthesis":     ["T2-cloud", "T1-local"],
    "deep_analysis": ["T3-cloud", "T2-cloud"],
    "vision":        ["TV-local", "T2-cloud"],
}
CLASSES = list(CANDIDATES)

# Con PHI a bordo, la política se estrecha a lo que corre en la máquina (R8).
PHI_CANDIDATES: dict[str, list[str]] = {
    "format": ["T0-local"], "extract": ["T0-local"], "route": ["T0-local"],
    "synthesis": ["T1-local"], "deep_analysis": ["T1-local"], "vision": ["TV-local"],
}

# Esfuerzo (output_config.effort) por clase, para los modelos que lo aceptan.
EFFORT: dict[str, str] = {
    "format": "low", "extract": "low", "route": "low",
    "synthesis": "high", "deep_analysis": "xhigh", "vision": "medium",
}

# ---------------------------------------------------------------------------
# Clasificador léxico (determinista, bilingüe es/en)
# ---------------------------------------------------------------------------
LEXICON: dict[str, list[tuple[str, int]]] = {
    "format": [
        ("convierte", 3), ("conviertelo", 3), ("transforma", 3), ("pasa a formato", 3),
        ("formato", 2), ("exporta", 3), ("materializa", 2), ("arma el docx", 3),
        ("docx", 2), ("pptx", 2), ("xlsx", 2), ("csv", 2), ("plantilla", 2),
        ("maqueta", 2), ("renombra", 2), ("convert", 3), ("export", 3), ("reformat", 3),
    ],
    "extract": [
        ("extrae", 3), ("extraccion", 3), ("metadatos", 3), ("ocr", 3), ("parsea", 3),
        ("saca el texto", 3), ("texto del pdf", 3), ("campos", 2), ("indexa", 2),
        ("extract", 3), ("parse", 3), ("scrape", 2),
    ],
    "route": [
        ("clasifica", 3), ("clasificar", 3), ("etiqueta", 3), ("taggea", 3), ("enruta", 3),
        ("que skill", 3), ("que subagente", 3), ("ordena por", 2),
        ("classify", 3), ("route", 3), ("triage", 2),
    ],
    "synthesis": [
        ("resume", 3), ("resumen", 3), ("redacta", 3), ("escribe", 2), ("explica", 3),
        ("interpreta", 3), ("diferencial", 3), ("informe", 2), ("borrador", 2),
        ("summarize", 3), ("draft", 2), ("explain", 3),
    ],
    "deep_analysis": [
        ("analisis critico", 6), ("critica metodologica", 6), ("appraisal", 5),
        ("compara con la literatura", 6), ("contrasta con la literatura", 6),
        ("frente a la literatura", 5), ("que aporta", 5), ("aporte", 4), ("aportes", 4),
        ("estado del arte", 4), ("revision sistematica", 4), ("metaanalisis", 4),
        ("meta-analisis", 4), ("nivel academico", 4), ("multi-paper", 4),
        ("varios papers", 4), ("multiples papers", 4), ("varios articulos", 4),
        ("corpus", 3), ("sesgo", 3), ("riesgo de sesgo", 4), ("grade", 3), ("prisma", 3),
        ("literatura", 3), ("evidencia", 2), ("papers", 2), ("paper", 1), ("discusion", 2),
        ("systematic review", 4), ("meta-analysis", 4), ("critical appraisal", 6),
        ("state of the art", 4),
    ],
    "vision": [
        ("imagen", 4), ("imagenes", 4), ("foto", 4), ("captura de pantalla", 4),
        ("escaneo", 3), ("figura de la", 3), ("screenshot", 4), ("png", 2), ("jpg", 2),
    ],
}
DEFAULT_CLASS = "synthesis"


def _norm(text: str) -> str:
    """Minúsculas sin tildes, para que 'análisis' y 'analisis' cuenten igual."""
    nfkd = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def classify(message: str) -> tuple[str, dict[str, int]]:
    """Clasifica la tarea. Devuelve (clase, puntajes) — puntajes para poder auditarlo."""
    low = _norm(message)
    scores = {cls: 0 for cls in CLASSES}
    for cls, terms in LEXICON.items():
        for term, weight in terms:
            if _norm(term) in low:
                scores[cls] += weight
    best = max(scores, key=lambda c: (scores[c], -CLASSES.index(c)))
    return (best if scores[best] > 0 else DEFAULT_CLASS), scores


# ---------------------------------------------------------------------------
# Costo
# ---------------------------------------------------------------------------
def estimate_tokens(text: str) -> int:
    """Estimación grosera (~4 caracteres por token). Sirve para el techo, no para facturar."""
    return max(1, len(text or "") // 4)


def cost_usd(model: str, in_tokens: int, out_tokens: int) -> float:
    p_in, p_out = PRICES.get(model, (0.0, 0.0))
    return round(in_tokens / 1e6 * p_in + out_tokens / 1e6 * p_out, 6)


@dataclass
class CostGuard:
    """Techo de costo: por turno y acumulado de sesión.

    Por debajo del techo el orquestador sube de tier solo (sin fricción). Por encima,
    devuelve `needs_confirmation` y el loop pide Gate humano (R9).
    """
    per_call: float = field(default_factory=lambda: float(_env("HARNESS_COST_CEILING", "0.50")))
    per_session: float = field(
        default_factory=lambda: float(_env("HARNESS_SESSION_COST_CEILING", "5.00")))
    spent: float = 0.0

    def would_exceed(self, est: float) -> str | None:
        if est > self.per_call:
            return f"costo estimado ${est:.4f} > techo por turno ${self.per_call:.2f}"
        if self.spent + est > self.per_session:
            return (f"acumulado ${self.spent + est:.4f} > techo de sesión "
                    f"${self.per_session:.2f}")
        return None

    def record(self, model: str, in_tokens: int, out_tokens: int) -> float:
        real = cost_usd(model, in_tokens, out_tokens)
        self.spent = round(self.spent + real, 6)
        return real


# ---------------------------------------------------------------------------
# Decisión
# ---------------------------------------------------------------------------
@dataclass
class Decision:
    task_class: str
    tier: Tier
    effort: str
    est_cost_usd: float
    needs_confirmation: bool
    reason: str
    degraded_from: str | None = None

    @property
    def model(self) -> str:
        return self.tier.model

    @property
    def provider(self) -> str:
        return self.tier.provider

    def declare(self) -> str:
        """La línea que se imprime ANTES de ejecutar. Si no la declaraste, no ejecutaste."""
        costo = ("costo 0 (local)" if self.tier.is_local
                 else f"costo est. ${self.est_cost_usd:.4f}")
        extra = f" · DEGRADADO desde {self.degraded_from}" if self.degraded_from else ""
        gate = " · GATE: sobre el techo, requiere confirmación" if self.needs_confirmation else ""
        return (f"[{self.tier.id}] {self.task_class} → {self.model} ({self.provider}, "
                f"{self.tier.speed}) porque {self.reason}; {costo}{extra}{gate}")


def local_available() -> bool:
    """¿Hay motor local declarado? Sin sondear la red: el harness debe decidir rápido.

    `HARNESS_LOCAL_DISABLED=1` lo apaga; `backends.py` degrada solo si el endpoint falla.
    """
    if _env("HARNESS_LOCAL_DISABLED", "0") not in ("0", "", "false", "no"):
        return False
    return bool(_env("HARNESS_LOCAL_BASE_URL", "http://127.0.0.1:1234/v1"))


def plan(task_class: str, *, est_in_tokens: int = 2000, est_out_tokens: int = 1500,
         phi: bool = False, guard: CostGuard | None = None,
         allow_local: bool | None = None) -> Decision:
    """Elige el tier para una clase de tarea y devuelve la decisión declarable."""
    if task_class not in CANDIDATES:
        task_class = DEFAULT_CLASS
    guard = guard or CostGuard()
    allow_local = local_available() if allow_local is None else allow_local
    table = tiers()

    candidates = (PHI_CANDIDATES if phi else CANDIDATES)[task_class]
    viable = [table[c] for c in candidates if allow_local or not table[c].is_local]
    if not viable:
        if phi:
            raise RuntimeError(
                "PHI sin motor local disponible: la política prohíbe enviar datos de paciente "
                "a un modelo cloud (R8). Levanta el motor local o de-identifica antes.")
        viable = [table[c] for c in candidates]

    chosen, degraded_from = viable[0], None
    if len(viable) < len(candidates):
        degraded_from = table[candidates[0]].id

    est = cost_usd(chosen.model, est_in_tokens, est_out_tokens)
    over = guard.would_exceed(est)
    return Decision(task_class=task_class, tier=chosen, effort=EFFORT.get(task_class, "high"),
                    est_cost_usd=est, needs_confirmation=bool(over),
                    reason=(chosen.why if not over else f"{chosen.why} — pero {over}"),
                    degraded_from=degraded_from)


def plan_for(message: str, **kw) -> Decision:
    """Atajo: clasifica el mensaje y planifica en un paso."""
    cls, _ = classify(message)
    kw.setdefault("est_in_tokens", estimate_tokens(message) + 4000)  # + contexto del sistema
    return plan(cls, **kw)


def table_markdown() -> str:
    """Tabla de la política, para inyectarla en el contexto del agente."""
    t = tiers()
    rows = ["| Clase de tarea | Tier | Modelo | Velocidad |",
            "|---|---|---|---|"]
    for cls, cands in CANDIDATES.items():
        tier = t[cands[0]]
        rows.append(f"| {cls} | {tier.id} | {tier.model} | {tier.speed} |")
    return "\n".join(rows)


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        print(table_markdown())
        return 0
    msg = " ".join(sys.argv[1:])
    cls, scores = classify(msg)
    d = plan_for(msg)
    print(d.declare())
    print(f"  clase={cls}  puntajes={ {k: v for k, v in scores.items() if v} }")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
