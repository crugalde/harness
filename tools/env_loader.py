"""env_loader.py — Carga el .env local (fuera de iCloud) a os.environ.

Sin dependencias externas: parsea líneas KEY=value y puebla os.environ sin
sobrescribir variables ya definidas (las del entorno tienen prioridad).

Ruta por defecto: ~/.config/harness/.env
Override con la variable de entorno HARNESS_ENV_FILE.
"""
from __future__ import annotations
import os
from pathlib import Path

DEFAULT_ENV = Path.home() / ".config" / "harness" / ".env"


def env_path() -> Path:
    """Ruta del .env: HARNESS_ENV_FILE si está definida, si no la default."""
    return Path(os.environ.get("HARNESS_ENV_FILE", DEFAULT_ENV)).expanduser()


def load_env(path: str | os.PathLike | None = None, *, override: bool = False) -> Path | None:
    """Carga el .env en os.environ. Devuelve la ruta usada, o None si no existe."""
    p = Path(path).expanduser() if path else env_path()
    if not p.is_file():
        return None
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and (override or key not in os.environ):
            os.environ[key] = val
    return p
