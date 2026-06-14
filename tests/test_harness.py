"""Tests del harness. Correr con: pytest -q  (desde la raíz del paquete)."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load(mod, sub="tools"):
    spec = importlib.util.spec_from_file_location(mod, ROOT / sub / f"{mod}.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


L = _load("loop")
SI = _load("self_improve")
TR = _load("tracing")


def test_router_scoring():
    cases = {"necesito una revisión en pubmed": "research",
             "interpreta este EMG de aguja": "med",
             "descompón la señal HD-sEMG con CKC": "signals",
             "propuesta de costo para el directorio": "biz",
             "plan de nutrición y recuperación": "coach",
             "redacta el informe final en un documento": "docs"}
    for msg, expect in cases.items():
        assert L.route(msg, backend=None) == expect, msg


def test_guards():
    assert L.guard_tool("read_shell", {"cmd": "rm -rf /"}).startswith("BLOQUEADO")
    assert L.guard_tool("send_email", {"to": "x"}).startswith("GATE")
    assert L.guard_tool("read_shell", {"cmd": "ls"}) is None


def test_protected_sections():
    SI.resolve(None)
    assert SI.meta()["protected"] == [1, 3, 4, 7]
    for a in ["med", "research", "biz", "signals", "coach", "docs"]:
        SI.resolve(a)
        assert SI.meta()["protected"] == [1, 3, 7], a


def test_skills_discovery():
    idx = L.load_skills()
    for name in ["pubmed_search", "build_docx", "build_pptx"]:
        assert name in idx


def test_trace_roundtrip():
    t = TR.Trace("med", "test")
    t.turn("assistant", "ok"); t.tool("read_shell", True); t.usage("claude-sonnet-4-6", 100, 50)
    f = t.close()
    assert f.exists()
    assert "sesiones" in TR.summarize()
