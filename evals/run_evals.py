#!/usr/bin/env python3
"""run_evals.py — Red de seguridad del harness (offline, sin API).

Verifica que el comportamiento crítico no se rompa: routing al subagente, guardas que
disparan, secciones protegidas intactas, **clasificación de la tarea**, **tier de modelo
elegido** y **selección autónoma de skill**. Corre esto ANTES y DESPUÉS de cada
auto-modificación (§10): si un cambio del ciclo de aprendizaje baja el score, se revierte.

Uso:  python evals/run_evals.py
Exit: 0 si todo pasa, 1 si hay fallos (apto para CI / pre-commit).
"""
from __future__ import annotations
import importlib.util, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CASES = json.loads((ROOT / "evals" / "cases.json").read_text(encoding="utf-8"))


def _load(mod: str):
    """Carga por ruta, registrando en sys.modules (lo necesitan las dataclasses)."""
    spec = importlib.util.spec_from_file_location(mod, ROOT / "tools" / f"{mod}.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules[mod] = m
    spec.loader.exec_module(m)
    return m


def main() -> int:
    L, SI = _load("loop"), _load("self_improve")
    MP, SS = _load("model_policy"), _load("skill_selector")
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

    for c in CASES["task_class"]:
        got = MP.classify(c["msg"])[0]
        ok = got == c["expect"]
        passed += ok; failed += not ok
        if not ok:
            fails.append(f"[clase] '{c['msg'][:40]}...' -> {got} (esperado {c['expect']})")

    for c in CASES["model_tier"]:
        d = MP.plan(c["class"], allow_local=c["local"])
        ok = d.model == c["expect_model"] and d.provider == c["expect_provider"]
        passed += ok; failed += not ok
        if not ok:
            fails.append(f"[tier] {c['class']} (local={c['local']}) -> {d.model}/{d.provider} "
                         f"(esperado {c['expect_model']}/{c['expect_provider']})")

    pool = SS.index()
    for c in CASES["skills"]:
        hits = SS.select(c["task"], k=2, pool=pool)
        got = hits[0].skill.id if hits else None
        ok = got == c["expect"]
        passed += ok; failed += not ok
        if not ok:
            fails.append(f"[skill] '{c['task'][:40]}...' -> {got} (esperado {c['expect']})")

    print(f"evals: {passed} OK, {failed} fallos")
    for f in fails:
        print("  ✗", f)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
