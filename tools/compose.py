#!/usr/bin/env python3
"""compose.py — Motor del subagente `docs`: integra subagentes y materializa el entregable.

Toma un `spec` (esquema del documento), pide cada sección al subagente que corresponda, y
construye un .docx o .pptx con las skills build_docx / build_pptx. El `spec` se guarda junto a
la salida para trazabilidad (D5 de docs).

spec.json (ejemplo):
{
  "title": "Transmisión neuromuscular: revisión",
  "format": "docx",
  "sections": [
    {"heading": "Evidencia",   "agent": "research", "prompt": "Resume la evidencia 2023-2025"},
    {"heading": "Interpretación clínica", "agent": "med", "prompt": "Implicancias clínicas"}
  ]
}

Uso:  python tools/compose.py --spec spec.json --out salida.docx
"""
from __future__ import annotations
import argparse, importlib.util, json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _skill(name: str):
    spec = importlib.util.spec_from_file_location(f"skill_{name}", ROOT / "skills" / name / "tool.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


def compose(spec: dict, ask, out: str) -> str:
    """`ask(agent, prompt) -> texto` reúne el contenido; las skills lo materializan."""
    fmt = spec.get("format", "docx")
    title = spec.get("title", "Documento")
    gathered = []
    for sec in spec.get("sections", []):
        content = ask(sec.get("agent", "research"), sec.get("prompt", ""))
        gathered.append({**sec, "content": content})
    # Guardar el spec resuelto junto a la salida (trazabilidad)
    Path(out).with_suffix(".spec.json").write_text(
        json.dumps({"title": title, "sections": gathered}, ensure_ascii=False, indent=2), encoding="utf-8")
    if fmt == "pptx":
        slides = [{"title": s.get("heading", ""), "bullets": s["content"].split("\n")} for s in gathered]
        return _skill("build_pptx").build_pptx({"title": title, "slides": slides, "out": out})
    sections = [{"heading": s.get("heading", ""), "body": s["content"]} for s in gathered]
    return _skill("build_docx").build_docx({"title": title, "sections": sections, "out": out})


def _ask_via_loop(agent: str, prompt: str) -> str:
    """Pide contenido al subagente real a través del loop (requiere API)."""
    import loop
    msgs = loop.run(prompt, agent=agent, registry=loop._demo_registry())
    last = [m for m in msgs if m["role"] == "assistant"]
    return last[-1]["content"][0]["text"] if last else ""


def _ask_demo(agent: str, prompt: str) -> str:
    return f"[{agent}] (contenido pendiente para: {prompt})"


def main():
    ap = argparse.ArgumentParser(description="Compositor: integra subagentes en un entregable.")
    ap.add_argument("--spec", required=True, help="Ruta a spec.json")
    ap.add_argument("--out", required=True, help="Ruta de salida (.docx o .pptx)")
    ap.add_argument("--demo", action="store_true", help="Sin API: usa contenido marcador.")
    args = ap.parse_args()
    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    if args.out.endswith(".pptx"):
        spec["format"] = "pptx"
    ask = _ask_demo if args.demo else _ask_via_loop
    print(compose(spec, ask, args.out))


if __name__ == "__main__":
    main()
