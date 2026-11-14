"""_comun.py — Utilidades compartidas por los scripts del orquestador científico.

- Carga del .env local (fuera del repo y de carpetas sincronizadas como OneDrive o iCloud): ~/.config/harness/.env, o la ruta en
  HARNESS_ENV_FILE. Las variables ya exportadas en el shell tienen prioridad.
- GET HTTP con reintentos y backoff (solo biblioteca estándar).
- Normalización de DOI/títulos y formato de citas Vancouver.

No se ejecuta directamente: lo importan los demás scripts de esta carpeta.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parent.parent
DEFAULT_ENV = Path.home() / ".config" / "harness" / ".env"
USER_AGENT = "orquestador-cientifico/1.0 (uso academico; contacto via ENTREZ_EMAIL)"

log = logging.getLogger("orquestador")
if not log.handlers:
    _h = logging.StreamHandler(sys.stderr)
    _h.setFormatter(logging.Formatter("  [%(levelname)s] %(message)s"))
    log.addHandler(_h)
    log.setLevel(logging.INFO)


# --------------------------------------------------------------------------- .env


def env_path() -> Path:
    """Ruta del .env: HARNESS_ENV_FILE si está definida; si no, la ruta por defecto."""
    return Path(os.environ.get("HARNESS_ENV_FILE", DEFAULT_ENV)).expanduser()


def load_env(path: str | os.PathLike[str] | None = None, *, override: bool = False) -> Path | None:
    """Carga KEY=value del .env en os.environ. Devuelve la ruta usada o None si no existe."""
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


# --------------------------------------------------------------------------- red


def http_get(
    url: str,
    params: dict[str, Any] | None = None,
    *,
    parse: str = "json",
    headers: dict[str, str] | None = None,
    intentos: int = 3,
    timeout: int = 45,
) -> Any:
    """GET con reintentos. `parse`: 'json' | 'xml' | 'text'.

    Devuelve None ante 404 o tras agotar los reintentos (registra el motivo en stderr).
    Reintenta en errores de red, 429 y 5xx; un 4xx distinto de 429 no se reintenta.
    """
    params = {k: v for k, v in (params or {}).items() if v not in (None, "")}
    qs = urllib.parse.urlencode(params)
    full = f"{url}?{qs}" if qs else url
    req = urllib.request.Request(full, headers={"User-Agent": USER_AGENT, **(headers or {})})
    for intento in range(intentos):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
            if parse == "json":
                return json.loads(raw)
            if parse == "xml":
                return ET.fromstring(raw)
            return raw.decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            reintentable = exc.code == 429 or exc.code >= 500
            if not reintentable or intento == intentos - 1:
                log.warning("HTTP %s en %s", exc.code, _sin_claves(url))
                return None
            espera = _retry_after(exc) or 2.0 * (intento + 1)
            time.sleep(espera)
        except (urllib.error.URLError, TimeoutError, ET.ParseError, json.JSONDecodeError) as exc:
            if intento == intentos - 1:
                log.warning("fallo tras %d intentos en %s: %s", intentos, _sin_claves(url), exc)
                return None
            time.sleep(1.5 * (intento + 1))
    return None


def _retry_after(exc: urllib.error.HTTPError) -> float | None:
    valor = exc.headers.get("Retry-After") if exc.headers else None
    try:
        return min(float(valor), 30.0) if valor else None
    except ValueError:
        return None


def _sin_claves(url: str) -> str:
    """Nunca registrar query strings: pueden llevar claves de API."""
    return url.split("?", 1)[0]


# ------------------------------------------------------------------ normalización


def normalizar_doi(doi: str | None) -> str:
    """'https://doi.org/10.1/ABC' -> '10.1/abc'. Vacío si no parece un DOI."""
    if not doi:
        return ""
    d = doi.strip().lower()
    d = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", d)
    return d if d.startswith("10.") else ""


def normalizar_titulo(titulo: str | None) -> str:
    """Minúsculas, sin acentos ni puntuación: clave para deduplicar por título."""
    if not titulo:
        return ""
    t = unicodedata.normalize("NFKD", titulo)
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def slug(texto: str, largo: int = 60) -> str:
    """Nombre de archivo seguro y legible a partir de un texto."""
    s = normalizar_titulo(texto).replace(" ", "-")
    return s[:largo].strip("-") or "sin-titulo"


def vancouver(reg: dict[str, Any]) -> str:
    """Cita estilo Vancouver con DOI y PMID cuando existen."""
    autores = reg.get("autores") or []
    firma = ", ".join(autores[:6]) + (", et al" if len(autores) > 6 else "")
    partes = [
        p
        for p in (
            firma,
            (reg.get("titulo") or "").rstrip("."),
            reg.get("revista") or "",
            str(reg.get("anio") or ""),
        )
        if p
    ]
    cita = ". ".join(partes)
    if reg.get("doi"):
        cita += f". doi:{reg['doi']}"
    if reg.get("pmid"):
        cita += f". PMID: {reg['pmid']}"
    return cita + "."


def escribir_json(ruta: Path, datos: Any) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
