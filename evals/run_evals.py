#!/usr/bin/env python3
"""run_evals.py — Red de seguridad del harness (offline, sin API).

Verifica que el comportamiento crítico no se rompa: routing correcto, guardas que disparan,
y secciones protegidas intactas. Corre esto ANTES y DESPUÉS de cada auto-modificación (§10):
si un cambio del ciclo de aprendizaje baja el score, se revierte.

Uso:  python evals/run_evals.py
Exit: 0 si todo pasa, 1 si hay fallos (apto para CI / pre-commit).
"""
from __future__ import annotations
import importlib.util, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CASES = json.loads((ROOT / "evals" / "cases.json").read_text(encoding="utf-8"))


def _load(mod: str):
    spec = importlib.util.spec_from_file_location(mod, ROOT / "tools" / f"{mod}.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


def main() -> int:
    L, SI = _load("loop"), _load("self_improve")
    passed = failed = 0
    fails: list[str] = []

    for c in CASES["routing"]:
        got = L.route(c["msg"], backend=None)
        ok = got == c["expect"]
        passed += ok; failed += not ok
        if not ok:
            fails.append(f"[routing] '{c['msg'][:40]}...' -> {got} (esperado {c['expect']})")

    for c in CASES["guards"]:
        verdict = L.guard_tool(c["tool"], c["args"])
        got = "OK" if verdict is None else verdict.split(":")[0]
        ok = got == c["expect"]
        passed += ok; failed += not ok
        if not ok:
            fails.append(f"[guard] {c['tool']} -> {got} (esperado {c['expect']})")

    for agent, expected in CASES["protected"].items():
        SI.resolve(agent or None)
        got = SI.meta()["protected"]
        ok = got == expected
        passed += ok; failed += not ok
        if not ok:
            fails.append(f"[protected] {agent or 'root'} -> {got} (esperado {expected})")

    print(f"evals: {passed} OK, {failed} fallos")
    for f in fails:
        print("  ✗", f)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
