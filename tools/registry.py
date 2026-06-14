"""registry.py — Ensambla el ToolRegistry del harness.

Auto-descubre cada skills/<nombre>/tool.py que exponga register_skill(reg) y la registra.
Si una skill falla al importar (dependencia ausente), se omite con aviso y el harness sigue.
Aquí también conectas tus servidores MCP reales (PubMed, archivos, VPS).
"""
from __future__ import annotations
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = ROOT / "skills"


def _import(path: Path):
    spec = importlib.util.spec_from_file_location(f"skill_{path.parent.name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def build_registry():
    from loop import ToolRegistry  # loop ya está cargado cuando se llama esto
    reg = ToolRegistry()
    for tool_py in sorted(SKILLS_DIR.glob("*/tool.py")):
        try:
            mod = _import(tool_py)
            if hasattr(mod, "register_skill"):
                mod.register_skill(reg)
        except Exception as e:
            print(f"[registry] omito skill '{tool_py.parent.name}': {e}")
    register_mcp(reg)
    return reg


def register_mcp(reg) -> None:
    """Punto de anclaje para servidores MCP reales. Ejemplo de patrón:

        def vps_read(args):
            # cliente MCP/SSH de solo lectura
            ...
        reg.register("vps_read", "Lee del VPS (solo lectura).", {...}, vps_read)

    Las herramientas con efecto externo deben ir además en GATED_TOOLS de loop.py.
    """
    return None
