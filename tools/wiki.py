#!/usr/bin/env python3
"""wiki.py — Herramientas del wiki LLM (`wiki/`).

El agente escribe las páginas; este script hace el bookkeeping mecánico que el agente no
debería gastar tokens en hacer a mano: catálogo, verificación de enlaces, búsqueda y bitácora.

    python tools/wiki.py index                    # regenera wiki/index.md desde el front-matter
    python tools/wiki.py lint                     # enlaces rotos, huérfanas, esbozos, sin fuente
    python tools/wiki.py search "seno cavernoso"  # BM25 sobre las páginas
    python tools/wiki.py log ingest "Titulo" --detalle "..." --detalle "..."
    python tools/wiki.py stats                    # salud del wiki de un vistazo
    python tools/wiki.py pack --out /tmp/wiki.md  # empaqueta el wiki para pegarlo en un LLM
    python tools/wiki.py init --dest ~/ruta       # crea la estructura en otra carpeta

Sin dependencias externas (stdlib). El contrato del wiki está en wiki/AGENTS.md.
"""
from __future__ import annotations

import argparse
import math
import re
import shutil
import sys
import unicodedata
from collections import Counter
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WIKI = ROOT / "wiki"
SECTIONS = ["fuentes", "entidades", "conceptos", "sintesis"]
META = {"AGENTS.md", "CLAUDE.md", "index.md", "log.md", "README.md"}
REQUIRED_FM = ["tipo", "titulo", "estado", "actualizado"]
STALE_DAYS = 180


# --------------------------------------------------------------------------- #
# Modelo de página
# --------------------------------------------------------------------------- #
class Page:
    """Una página del wiki: front-matter parseado + cuerpo."""

    def __init__(self, path: Path):
        self.path = path
        self.rel = path.relative_to(WIKI).as_posix()
        self.stem = path.stem
        raw = path.read_text(encoding="utf-8")
        self.fm, self.body = _split_frontmatter(raw)

    def get(self, key: str, default: str = "") -> str:
        v = self.fm.get(key, default)
        return v if isinstance(v, str) else ", ".join(v)

    def list(self, key: str) -> list[str]:
        v = self.fm.get(key, [])
        return v if isinstance(v, list) else [v]

    @property
    def section(self) -> str:
        return self.rel.split("/")[0] if "/" in self.rel else "(raíz)"

    @property
    def summary(self) -> str:
        """Primer párrafo de prosa tras el H1, recortado — el resumen que va al índice."""
        buf: list[str] = []
        for line in self.body.splitlines():
            s = line.strip()
            if s and not re.match(r"([-*+]\s|#|>|\||`)", s):
                buf.append(s)
            elif buf:
                break
        if not buf:
            return ""
        clean = re.sub(r"\s+", " ", re.sub(r"[\[\]]|\(\[\[.*?\]\].*?\)", "", " ".join(buf)))
        clean = clean.strip()
        return clean if len(clean) <= 150 else clean[:150].rsplit(" ", 1)[0] + "…"

    @property
    def links(self) -> list[str]:
        clean = re.sub(r"```.*?```", "", self.body, flags=re.DOTALL)
        clean = re.sub(r"`[^`\n]*`", "", clean)
        return [re.split(r"[|#]", m)[0].strip() for m in re.findall(r"\[\[(.+?)\]\]", clean)]

    @property
    def stale_days(self) -> int | None:
        try:
            d = datetime.strptime(self.get("actualizado"), "%Y-%m-%d").date()
        except ValueError:
            return None
        return (date.today() - d).days


def _split_frontmatter(raw: str) -> tuple[dict, str]:
    """Parser YAML mínimo: escalares y listas inline `[a, b]`. Sin dependencias."""
    m = re.match(r"---\n(.*?)\n---\n?(.*)", raw, re.DOTALL)
    if not m:
        return {}, raw
    fm: dict[str, str | list[str]] = {}
    for line in m.group(1).splitlines():
        kv = re.match(r"([\w-]+):\s*(.*)", line)
        if not kv:
            continue
        key, val = kv.group(1), kv.group(2).strip()
        if val.startswith("[") and val.endswith("]"):
            items = [x.strip().strip("\"'") for x in val[1:-1].split(",") if x.strip()]
            fm[key] = items
        else:
            fm[key] = val.strip("\"'")
    return fm, m.group(2)


def pages() -> list[Page]:
    if not WIKI.is_dir():
        sys.exit(f"No existe {WIKI}. Crea el wiki o usa `init --dest`.")
    out = []
    for p in sorted(WIKI.rglob("*.md")):
        if p.name in META or "raw" in p.relative_to(WIKI).parts:
            continue
        out.append(Page(p))
    return out


# --------------------------------------------------------------------------- #
# index
# --------------------------------------------------------------------------- #
def cmd_index() -> int:
    ps = pages()
    by_section: dict[str, list[Page]] = {}
    for p in ps:
        by_section.setdefault(p.section, []).append(p)

    lines = ["---", "tipo: indice", "titulo: Índice del wiki",
             "tags: [wiki/indice]", "generado: true", f"actualizado: {date.today().isoformat()}",
             "---", "",
             "# Índice del wiki", "",
             "Catálogo de todas las páginas. Lo regenera `python tools/wiki.py index` desde el",
             "front-matter — no lo edites a mano. Para el orden cronológico de lo que fue pasando,",
             "ver `log.md`; para las convenciones, `AGENTS.md`.", ""]

    total_fuentes = len(by_section.get("fuentes", []))
    lines += [f"**{len(ps)} páginas** · {total_fuentes} fuentes ingeridas · "
              f"{sum(1 for p in ps if p.get('estado') == 'esbozo')} esbozos pendientes", ""]

    titles = {"fuentes": "Fuentes ingeridas", "entidades": "Entidades",
              "conceptos": "Conceptos", "sintesis": "Síntesis"}
    for sec in SECTIONS + [s for s in by_section if s not in SECTIONS]:
        group = by_section.get(sec)
        if not group:
            continue
        lines += [f"## {titles.get(sec, sec)}", "",
                  "| Página | Qué contiene | Estado | Actualizado |", "|---|---|---|---|"]
        for p in sorted(group, key=lambda x: x.stem):
            lines.append(f"| [[{p.stem}]] | {p.summary or '—'} | {p.get('estado','?')} "
                         f"| {p.get('actualizado','?')} |")
        lines.append("")
    (WIKI / "index.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(f"[wiki] index.md: {len(ps)} páginas en {len(by_section)} secciones")
    return 0


# --------------------------------------------------------------------------- #
# lint
# --------------------------------------------------------------------------- #
def cmd_lint(stale_days: int) -> int:
    ps = pages()
    known = {p.stem for p in ps} | {"index", "log", "AGENTS", "CLAUDE"}
    known |= {a for p in ps for a in p.list("aliases")}
    incoming = Counter()
    errors: list[str] = []
    warnings: list[str] = []

    for p in ps:
        missing = [k for k in REQUIRED_FM if not p.fm.get(k)]
        if not p.fm:
            errors.append(f"{p.rel}: sin front-matter")
        elif missing:
            errors.append(f"{p.rel}: front-matter incompleto ({', '.join(missing)})")
        for target in p.links:
            if target in known:
                incoming[target] += 1
            else:
                errors.append(f"{p.rel}: enlace roto -> [[{target}]]")
        if p.section != "fuentes" and not p.list("fuentes"):
            warnings.append(f"{p.rel}: sin `fuentes:` — ¿de dónde sale lo que afirma?")
        if p.get("estado") == "esbozo":
            warnings.append(f"{p.rel}: esbozo pendiente de desarrollar")
        d = p.stale_days
        if d is None:
            errors.append(f"{p.rel}: `actualizado` no es una fecha AAAA-MM-DD")
        elif d > stale_days:
            warnings.append(f"{p.rel}: sin tocar hace {d} días — ¿sigue vigente? (R1)")

    orphans = [p.rel for p in ps if incoming[p.stem] == 0
               and not any(incoming[a] for a in p.list("aliases"))]

    print(f"lint: {len(ps)} páginas · {len(errors)} errores · {len(warnings)} avisos · "
          f"{len(orphans)} huérfanas")
    for e in errors:
        print("  ✗", e)
    for w in warnings:
        print("  ·", w)
    for o in orphans:
        print("  ○ sin enlaces entrantes:", o)
    if errors or warnings or orphans:
        print("\nLo mecánico termina aquí. Falta el juicio (ver wiki/AGENTS.md §6):")
        print("  contradicciones sin resolver · afirmaciones que una fuente nueva superó ·")
        print("  conceptos repetidos que merecen página · huecos que piden una fuente nueva.")
    return 1 if errors else 0


# --------------------------------------------------------------------------- #
# search (BM25 sobre las páginas)
# --------------------------------------------------------------------------- #
def _norm(text: str) -> list[str]:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.findall(r"[a-z0-9]{2,}", text)


def cmd_search(query: str, top: int) -> int:
    ps = pages()
    if not ps:
        print("(wiki vacío)")
        return 0
    docs = [_norm(p.get("titulo") + " " + " ".join(p.list("aliases")) + " " + p.body) for p in ps]
    avgdl = sum(len(d) for d in docs) / len(docs)
    df = Counter(t for d in docs for t in set(d))
    q, k1, b = _norm(query), 1.5, 0.75
    scored = []
    for p, d in zip(ps, docs):
        tf, dl, score = Counter(d), len(d), 0.0
        for term in q:
            if not tf[term]:
                continue
            idf = math.log(1 + (len(docs) - df[term] + 0.5) / (df[term] + 0.5))
            score += idf * tf[term] * (k1 + 1) / (tf[term] + k1 * (1 - b + b * dl / avgdl))
        if score:
            scored.append((score, p))
    if not scored:
        print(f"Sin resultados para «{query}». Prueba con sinónimos o revisa `index.md`.")
        return 0
    for score, p in sorted(scored, key=lambda x: -x[0])[:top]:
        line = next((l.strip() for l in p.body.splitlines()
                     if any(t in _norm(l) for t in q) and len(l.strip()) > 30), p.summary)
        print(f"\n{score:5.1f}  [[{p.stem}]]  ({p.rel} · {p.get('estado','?')})")
        print(f"       {line[:170]}")
    return 0


# --------------------------------------------------------------------------- #
# log / stats / pack / init
# --------------------------------------------------------------------------- #
def cmd_log(tipo: str, titulo: str, detalles: list[str]) -> int:
    f = WIKI / "log.md"
    if not f.exists():
        f.write_text("# Bitácora del wiki\n\nRegistro append-only. Formato: "
                     "`## [AAAA-MM-DD] tipo | título` (ver AGENTS.md §6).\n", encoding="utf-8")
    entry = f"\n## [{date.today().isoformat()}] {tipo} | {titulo}\n"
    entry += "".join(f"- {d}\n" for d in detalles) or "- (sin detalle)\n"
    with f.open("a", encoding="utf-8") as fh:
        fh.write(entry)
    print(f"[wiki] log.md += {tipo} | {titulo}")
    return 0


def cmd_stats() -> int:
    ps = pages()
    by_section = Counter(p.section for p in ps)
    estados = Counter(p.get("estado", "?") for p in ps)
    links = sum(len(p.links) for p in ps)
    log = (WIKI / "log.md")
    last = ""
    if log.exists():
        entries = [l for l in log.read_text(encoding="utf-8").splitlines() if l.startswith("## [")]
        last = entries[-1] if entries else ""
    print(f"páginas: {len(ps)}  ({', '.join(f'{k} {v}' for k, v in sorted(by_section.items()))})")
    print(f"estado:  {', '.join(f'{k} {v}' for k, v in sorted(estados.items()))}")
    print(f"enlaces: {links} ({links / max(len(ps), 1):.1f} por página)")
    print(f"última entrada de la bitácora: {last or '(vacía)'}")
    return 0


def cmd_pack(out: str) -> int:
    parts = [f"# Wiki — volcado completo ({date.today().isoformat()})\n"]
    for p in sorted(pages(), key=lambda x: (SECTIONS.index(x.section)
                                            if x.section in SECTIONS else 9, x.stem)):
        parts.append(f"\n\n<!-- {p.rel} -->\n{p.body.strip()}")
    dest = Path(out).expanduser()
    dest.write_text("".join(parts) + "\n", encoding="utf-8")
    print(f"[wiki] {len(pages())} páginas -> {dest} ({dest.stat().st_size // 1024} KB)")
    return 0


def cmd_init(dest: str) -> int:
    target = Path(dest).expanduser()
    for sub in SECTIONS + ["raw/assets"]:
        (target / sub).mkdir(parents=True, exist_ok=True)
    for name in ("AGENTS.md", "CLAUDE.md"):
        src = WIKI / name
        if src.exists() and not (target / name).exists():
            shutil.copy2(src, target / name)
    if not (target / "raw" / "README.md").exists() and (WIKI / "raw" / "README.md").exists():
        shutil.copy2(WIKI / "raw" / "README.md", target / "raw" / "README.md")
    (target / "log.md").touch()
    print(f"[wiki] estructura creada en {target}")
    print("      Ábrela desde Obsidian y empieza dejando fuentes en raw/.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Herramientas del wiki LLM.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("index", help="Regenera wiki/index.md desde el front-matter.")
    lt = sub.add_parser("lint", help="Enlaces rotos, huérfanas, esbozos, front-matter.")
    lt.add_argument("--stale-days", type=int, default=STALE_DAYS)
    se = sub.add_parser("search", help="Búsqueda BM25 sobre las páginas.")
    se.add_argument("query")
    se.add_argument("--top", type=int, default=5)
    lg = sub.add_parser("log", help="Añade una entrada a wiki/log.md.")
    lg.add_argument("tipo", choices=["ingest", "query", "lint", "refactor"])
    lg.add_argument("titulo")
    lg.add_argument("--detalle", action="append", default=[])
    sub.add_parser("stats", help="Salud del wiki de un vistazo.")
    pk = sub.add_parser("pack", help="Empaqueta el wiki en un archivo de contexto.")
    pk.add_argument("--out", default="wiki-volcado.md")
    it = sub.add_parser("init", help="Crea la estructura del wiki en otra carpeta.")
    it.add_argument("--dest", required=True)
    a = ap.parse_args()
    if a.cmd == "index":
        return cmd_index()
    if a.cmd == "lint":
        return cmd_lint(a.stale_days)
    if a.cmd == "search":
        return cmd_search(a.query, a.top)
    if a.cmd == "log":
        return cmd_log(a.tipo, a.titulo, a.detalle)
    if a.cmd == "stats":
        return cmd_stats()
    if a.cmd == "pack":
        return cmd_pack(a.out)
    return cmd_init(a.dest)


if __name__ == "__main__":
    sys.exit(main())
