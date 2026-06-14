#!/usr/bin/env python3
"""self_improve.py — Ciclo de autoaprendizaje gobernado (§10 del AGENTS.md).

Fases 1 capturar (journal.md) · 2 destilar · 3 proponer (auto) · 4 aplicar (Gate humano + git;
§3/§4/§7 inmutables, R13).  Uso: distill | list | apply <id> | apply --all
Req: pip install anthropic ; env ANTHROPIC_API_KEY [, SELF_IMPROVE_MODEL]
"""
from __future__ import annotations
import argparse, json, os, re, subprocess, sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent              # tools/ -> raíz

# Carga el .env local (fuera de iCloud) antes de leer cualquier variable.
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from env_loader import load_env
    load_env()
except Exception:
    pass

MODEL = os.environ.get("SELF_IMPROVE_MODEL", "claude-sonnet-4-6")
MIN_OCC = 3
AGENTS_MD = LEARNING = JOURNAL = PROPOSALS = CHANGELOG = None  # fijados por resolve()


def resolve(agent: str | None) -> None:
    """Apunta el motor al orquestador (agent=None) o a un subagente (agents/<id>/),
    cada uno con su propio AGENTS.md y journal separado."""
    global AGENTS_MD, LEARNING, JOURNAL, PROPOSALS, CHANGELOG
    base = (ROOT / "agents" / agent) if agent else ROOT
    AGENTS_MD = base / "AGENTS.md"
    LEARNING = (base / "learning") if agent else (ROOT / "shared" / "learning")
    JOURNAL, PROPOSALS, CHANGELOG = LEARNING / "journal.md", LEARNING / "proposals", LEARNING / "CHANGELOG.md"

PROMPT = """Módulo de destilación de un orquestador. Del journal, agrupa señales RECURRENTES \
(>= {n} ocurrencias o 1 corrección explícita) en "aprendizajes". Devuelve SOLO un array JSON; \
cada item: titulo, seccion_objetivo (entero), accion (añadir|modificar|ajustar_umbral), \
cambio_propuesto, evidencia (citas literales del journal), riesgo (bajo|medio|alto). Conservador: \
ante la duda no propongas; nunca sin evidencia.

JOURNAL:\n---\n{journal}\n---"""

def _find(raw: str, pat: str, default: str) -> str:
    m = re.search(pat, raw)
    return m.group(1) if m else default

def meta() -> dict:
    blk = re.search(r"```yaml\n(.*?self_modification.*?)\n```",
                    AGENTS_MD.read_text(encoding="utf-8"), re.DOTALL)
    if not blk:
        sys.exit("No se encontró el bloque meta en AGENTS.md.")
    raw = blk.group(1)
    prot = re.search(r"protected_sections:\s*\[([^\]]*)\]", raw)
    return {"version": _find(raw, r"version:\s*([\d.]+)", "0.0.0"),
            "mode": _find(raw, r"self_modification:\s*(\w+)", "gated"),
            "protected": [int(x) for x in re.findall(r"\d+", prot.group(1))] if prot else []}

def ensure_dirs() -> None:
    PROPOSALS.mkdir(parents=True, exist_ok=True)
    if not JOURNAL.exists():
        JOURNAL.write_text("# Journal de aprendizaje (Fase 1)\n\n## YYYY-MM-DD | "
            "<correccion|error|friccion|exito>\n- contexto: ...\n- señal: ...\n- evidencia: ...\n\n",
            encoding="utf-8")
    if not CHANGELOG.exists():
        CHANGELOG.write_text("# CHANGELOG de auto-modificaciones\n\n", encoding="utf-8")

def write_proposal(pid: str, lr: dict, status: str, nota: str = "") -> None:
    ev = "\n".join(f"  - {e}" for e in lr.get("evidencia", [])) or "  - (sin evidencia)"
    (PROPOSALS / f"{pid}.md").write_text(
        f"# Propuesta {pid} — {status}\n\n"
        f"**Título:** {lr.get('titulo','')}\n"
        f"**Sección objetivo:** §{lr.get('seccion_objetivo','?')}\n"
        f"**Acción:** {lr.get('accion','')}\n"
        f"**Riesgo:** {lr.get('riesgo','?')}\n"
        + (f"**Nota:** {nota}\n" if nota else "")
        + f"\n## Cambio propuesto\n\n{lr.get('cambio_propuesto','')}\n\n## Evidencia\n{ev}\n",
        encoding="utf-8")

def distill() -> None:
    ensure_dirs()
    m = meta()
    if m["mode"] == "off":
        sys.exit("self_modification: off — solo captura, sin propuestas.")
    journal = JOURNAL.read_text(encoding="utf-8").strip()
    if len(journal) < 50:
        sys.exit("Journal casi vacío; nada que destilar todavía.")
    try:
        from anthropic import Anthropic
    except ImportError:
        sys.exit("Falta el SDK para destilar: pip install anthropic")
    resp = Anthropic().messages.create(model=MODEL, max_tokens=2000,
        messages=[{"role": "user", "content": PROMPT.format(n=MIN_OCC, journal=journal)}])
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    try:
        learnings = json.loads(text)
    except json.JSONDecodeError as e:
        sys.exit(f"La destilación no devolvió JSON válido: {e}\n{text[:300]}")
    if not learnings:
        print("Sin aprendizajes promovibles por ahora.")
        return
    ok = rej = 0
    for i, lr in enumerate(learnings, 1):
        pid = f"{date.today().isoformat()}_{i:02d}"
        sec = int(lr.get("seccion_objetivo", 0))
        if sec in m["protected"]:
            write_proposal(pid, lr, "RECHAZADA_AUTOMATICA",
                           f"Toca §{sec} (protegida); requiere edición manual humana.")
            rej += 1
        else:
            write_proposal(pid, lr, "PENDIENTE")
            ok += 1
    print(f"Propuestas: {ok} pendientes, {rej} rechazadas por sección protegida. Ver {PROPOSALS}")

def list_proposals() -> None:
    ensure_dirs()
    items = sorted(PROPOSALS.glob("*.md"))
    if not items:
        print("No hay propuestas.")
        return
    for p in items:
        print(f"  {p.stem:<16} {p.read_text(encoding='utf-8').splitlines()[0]}")

def apply_proposal(pid: str) -> None:
    ensure_dirs()
    m = meta()
    path = PROPOSALS / f"{pid}.md"
    if not path.exists():
        sys.exit(f"No existe la propuesta {pid}.")
    content = path.read_text(encoding="utf-8")
    if "RECHAZADA_AUTOMATICA" in content:
        sys.exit("Propuesta rechazada (sección protegida): no aplicable por el ciclo.")
    sec = int(re.search(r"Sección objetivo:\*\*\s*§(\d+)", content).group(1))
    if sec in m["protected"]:
        sys.exit(f"§{sec} es protegida (R13): el ciclo no puede aplicarla.")
    print("\n" + content + "\n" + "=" * 60)
    if input(f"¿Aplicar {pid} a AGENTS.md? [escribe 'si' para confirmar] ").strip().lower() != "si":
        print("Cancelado. Nada se modificó.")
        return
    cambio = content.split("## Cambio propuesto\n\n", 1)[1].split("\n\n## Evidencia", 1)[0].strip()
    _insert_into_section(sec, cambio)
    ver = _bump_version(m["version"])
    _changelog(pid, sec, cambio, ver)
    path.unlink()
    _git_commit(f"self-improve: aplica {pid} (§{sec}) -> v{ver}")
    print(f"Aplicado. AGENTS.md -> v{ver}. Commit creado (reversible con git revert).")

def _insert_into_section(sec: int, texto: str) -> None:
    lines = AGENTS_MD.read_text(encoding="utf-8").splitlines()
    start = next((i for i, l in enumerate(lines) if l.startswith(f"## {sec}.")), None)
    if start is None:
        sys.exit(f"No se encontró §{sec} en AGENTS.md.")
    end = start + 1
    while end < len(lines) and not lines[end].startswith("## "):
        end += 1
    while end - 1 > start and lines[end - 1].strip() in ("", "---"):
        end -= 1
    lines[end:end] = [texto, ""]
    AGENTS_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")

def _bump_version(ver: str, part: str = "patch") -> str:
    a, b, c = (int(x) for x in ver.split("."))
    b, c = (b + 1, 0) if part == "minor" else (b, c + 1)
    new = f"{a}.{b}.{c}"
    txt = AGENTS_MD.read_text(encoding="utf-8")
    txt = re.sub(r"version:\s*[\d.]+", f"version: {new}", txt, count=1)
    txt = re.sub(r"updated:\s*[\d-]+", f"updated: {date.today().isoformat()}", txt, count=1)
    AGENTS_MD.write_text(txt, encoding="utf-8")
    return new

def _changelog(pid: str, sec: int, cambio: str, ver: str) -> None:
    entry = f"## v{ver} — {date.today().isoformat()} — {pid}\n- §{sec}: {cambio.splitlines()[0][:120]}\n\n"
    CHANGELOG.write_text(entry + CHANGELOG.read_text(encoding="utf-8"), encoding="utf-8")

def _git_commit(msg: str) -> None:
    try:
        subprocess.run(["git", "-C", str(ROOT), "add", "-A"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(ROOT), "commit", "-m", msg], check=True, capture_output=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("Aviso: sin commit git (¿repo no inicializado?). Cambio aplicado igual.")

def main() -> None:
    ap = argparse.ArgumentParser(description="Ciclo de autoaprendizaje gobernado (§10).")
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument("--agent", help="ID del subagente (med|research|biz|signals|coach). Omitir = orquestador.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("distill", parents=[parent], help="Fases 2-3: destila el journal y genera propuestas.")
    sub.add_parser("list", parents=[parent], help="Lista propuestas pendientes.")
    a = sub.add_parser("apply", parents=[parent], help="Fase 4: aplica una propuesta (Gate humano).")
    a.add_argument("proposal_id", nargs="?")
    a.add_argument("--all", action="store_true", help="Revisar y aplicar todas, una por una.")
    args = ap.parse_args()
    resolve(args.agent)
    if args.cmd == "distill":
        distill()
    elif args.cmd == "list":
        list_proposals()
    elif args.cmd == "apply":
        if args.all:
            for p in sorted(PROPOSALS.glob("*.md")):
                if "RECHAZADA" not in p.read_text(encoding="utf-8"):
                    apply_proposal(p.stem)
        elif args.proposal_id:
            apply_proposal(args.proposal_id)
        else:
            sys.exit("Indica un proposal_id o usa --all.")

if __name__ == "__main__":
    main()
