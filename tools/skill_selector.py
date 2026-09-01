#!/usr/bin/env python3
"""skill_selector.py — Elección autónoma de skill desde el pool.

Antes, `load_skills()` volcaba el índice entero de skills al contexto y el modelo elegía
de memoria. Eso escala mal (cada skill nueva es ruido para todas las tareas) y no deja
rastro de por qué se usó una. Aquí la elección es explícita, ordenada y auditable:

1. `index()`   — auto-descubre `skills/*/SKILL.md` en cada llamada (más las rutas extra de
   `HARNESS_SKILL_PATHS`), así una skill instalada después queda disponible sin tocar código.
2. `search()`  — ranking léxico bilingüe (TF ponderado × IDF sobre el pool). El front-matter
   `description` y la sección "Cuándo usar" pesan más que el cuerpo: son las que dicen
   *cuándo* usarla.
3. `select()`  — devuelve las mejores por sobre un umbral, con tope duro de skills por plan.
4. `declare()` — la línea que deja constancia de qué se buscó, qué ganó y con qué puntaje.

Regla dura heredada del contrato: **una skill imaginada es peor que ninguna**. Si nada
supera el umbral, `select()` devuelve lista vacía y el agente resuelve con su criterio,
diciéndolo.

Uso directo:  python tools/skill_selector.py "compara estos papers con la literatura"
"""
from __future__ import annotations

import math
import os
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAX_SKILLS_PER_PLAN = 4          # tope del contrato: más de 4 es dividir la tarea
MIN_SCORE = 0.12                 # bajo esto, no hay skill adecuada (se dice, no se inventa)
SKILL_BUDGET_CHARS = 12_000      # tope de texto de skill inyectado al contexto

STOPWORDS = {
    # español
    "para", "con", "los", "las", "del", "una", "unos", "unas", "que", "por", "como", "este",
    "esta", "estos", "estas", "sobre", "desde", "hasta", "entre", "cuando", "donde", "porque",
    "sus", "más", "mas", "muy", "todo", "toda", "todos", "todas", "hacer", "haz", "dame",
    "necesito", "quiero", "puedes", "debe", "debes", "seg", "según", "segun", "ser", "hay",
    # inglés
    "the", "and", "for", "with", "from", "this", "that", "these", "those", "into", "your",
    "you", "are", "was", "were", "have", "has", "had", "not", "but", "its", "can", "will",
}


def _norm(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _tokens(text: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9_]+", _norm(text))
            if len(t) >= 3 and t not in STOPWORDS]


# ---------------------------------------------------------------------------
# Descubrimiento
# ---------------------------------------------------------------------------
def skill_dirs() -> list[Path]:
    """Directorios donde buscar skills: `skills/` + los de HARNESS_SKILL_PATHS."""
    dirs = [ROOT / "skills"]
    extra = os.environ.get("HARNESS_SKILL_PATHS", "")
    dirs += [Path(p).expanduser() for p in extra.split(os.pathsep) if p.strip()]
    return [d for d in dirs if d.is_dir()]


def _front_matter(raw: str) -> dict[str, str]:
    """Parser tolerante del front-matter: `k: v`, `k: "v"` y bloques plegados `k: >-`."""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", raw, re.DOTALL)
    if not m:
        return {}
    out, key, buf = {}, None, []
    for line in m.group(1).splitlines():
        head = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if head and not line.startswith((" ", "\t")):
            if key:
                out[key] = " ".join(buf).strip()
            key, val = head.group(1), head.group(2).strip()
            buf = [] if val in (">", ">-", "|", "|-") else [val]
        elif key:
            buf.append(line.strip())
    if key:
        out[key] = " ".join(buf).strip()
    return {k: v.strip().strip('"').strip("'") for k, v in out.items()}


def _when_to_use(raw: str) -> str:
    """Extrae la sección de disparadores ('Cuándo usar' / 'When to use')."""
    m = re.search(r"^#+\s*(cu[aá]ndo\s+usar|when\s+to\s+use)[^\n]*\n(.*?)(?=\n#+\s|\Z)",
                  raw, re.IGNORECASE | re.DOTALL | re.MULTILINE)
    return m.group(2) if m else ""


@dataclass
class Skill:
    id: str
    name: str
    description: str
    path: Path
    body: str
    when: str

    @property
    def bag(self) -> dict[str, float]:
        """Bolsa de términos ponderada: el 'cuándo' pesa más que el cuerpo."""
        weights: dict[str, float] = {}
        for text, w in ((self.name.replace("_", " "), 4.0), (self.id.replace("_", " "), 4.0),
                        (self.description, 2.5), (self.when, 2.0), (self.body, 0.5)):
            for tok in _tokens(text):
                weights[tok] = weights.get(tok, 0.0) + w
        return weights

    def text(self, budget: int = SKILL_BUDGET_CHARS) -> str:
        """Contenido completo del SKILL.md, recortado al presupuesto de contexto."""
        raw = self.path.read_text(encoding="utf-8")
        if len(raw) <= budget:
            return raw
        return raw[:budget] + f"\n\n[... recortado: {len(raw) - budget} caracteres. " \
                              f"Archivo completo en {self.path} ...]"


def index() -> list[Skill]:
    """Escanea el pool en cada llamada: las skills nuevas entran sin reiniciar nada."""
    skills: list[Skill] = []
    seen: set[str] = set()
    for d in skill_dirs():
        for md in sorted(d.glob("*/SKILL.md")):
            sid = md.parent.name
            if sid in seen:
                continue
            seen.add(sid)
            raw = md.read_text(encoding="utf-8", errors="replace")
            fm = _front_matter(raw)
            skills.append(Skill(id=sid, name=fm.get("name", sid),
                                description=fm.get("description", ""), path=md,
                                body=raw, when=_when_to_use(raw)))
    return skills


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------
@dataclass
class Hit:
    skill: Skill
    score: float


def search(task: str, pool: list[Skill] | None = None) -> list[Hit]:
    """Ordena TODO el pool por relevancia a la tarea (puntaje 0..~1)."""
    pool = pool if pool is not None else index()
    if not pool:
        return []
    bags = [s.bag for s in pool]
    n = len(pool)
    df: dict[str, int] = {}
    for bag in bags:
        for tok in bag:
            df[tok] = df.get(tok, 0) + 1
    q = _tokens(task)
    if not q:
        return []
    hits = []
    for skill, bag in zip(pool, bags):
        norm = math.sqrt(sum(w * w for w in bag.values())) or 1.0
        score = sum(bag.get(tok, 0.0) * math.log((n + 1) / (df.get(tok, 0) + 1) + 1)
                    for tok in set(q)) / norm
        hits.append(Hit(skill, round(score, 4)))
    return sorted(hits, key=lambda h: (-h.score, h.skill.id))


def select(task: str, k: int = 2, min_score: float = MIN_SCORE,
           pool: list[Skill] | None = None) -> list[Hit]:
    """Las mejores k skills por sobre el umbral. Lista vacía = ninguna aplica."""
    k = max(1, min(k, MAX_SKILLS_PER_PLAN))
    return [h for h in search(task, pool)[:k] if h.score >= min_score]


def declare(task: str, hits: list[Hit], pool_size: int | None = None) -> str:
    """Línea de constancia: qué pool se buscó, qué ganó y con qué puntaje."""
    total = pool_size if pool_size is not None else len(index())
    if not hits:
        return (f"[skills] busqué en el pool ({total} skills) y ninguna supera el umbral "
                f"{MIN_SCORE}: resuelvo con criterio propio y lo explico.")
    picked = ", ".join(f"{h.skill.id} ({h.score:.2f})" for h in hits)
    return f"[skills] pool de {total} · seleccionadas automáticamente: {picked}"


def context_block(task: str, k: int = 2) -> tuple[str, str]:
    """(línea de declaración, texto a inyectar) — instrucciones completas de lo elegido."""
    pool = index()
    hits = select(task, k=k, pool=pool)
    line = declare(task, hits, pool_size=len(pool))
    catalogo = "\n".join(f"- {s.id}: {s.description[:180]}" for s in pool)
    if not hits:
        return line, f"# --- Pool de skills (ninguna seleccionada) ---\n{catalogo}\n"
    budget = max(2000, SKILL_BUDGET_CHARS // len(hits))
    cuerpos = "\n\n".join(f"## SKILL activa: {h.skill.id} (score {h.score:.2f})\n"
                          f"{h.skill.text(budget)}" for h in hits)
    return line, (f"# --- Skills seleccionadas automáticamente ---\n{line}\n\n"
                  f"Sigue estas instrucciones al pie de la letra: reemplazan tu enfoque por "
                  f"defecto para esta tarea.\n\n{cuerpos}\n\n"
                  f"# --- Resto del pool (no cargado) ---\n{catalogo}\n")


def main() -> int:
    if len(sys.argv) < 2:
        pool = index()
        print(f"Pool: {len(pool)} skills en {[str(d) for d in skill_dirs()]}")
        for s in pool:
            print(f"  - {s.id}: {s.description[:100]}")
        return 0
    task = " ".join(sys.argv[1:])
    pool = index()
    print(declare(task, select(task, pool=pool), pool_size=len(pool)))
    for h in search(task, pool)[:6]:
        print(f"  {h.score:>7.4f}  {h.skill.id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
