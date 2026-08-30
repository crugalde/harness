"""Recorrido recursivo de carpetas y alta en la cola.

Recorre con `os.scandir` (no carga la lista completa en memoria), salta archivos temporales
de Word (`~$...`), respeta patrones de exclusión y evita ciclos por enlaces simbólicos o
junctions de Windows.
"""
from __future__ import annotations

import fnmatch
import hashlib
import os
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from .cola import Cola
from .config import Config

TROZO = 1024 * 1024


@dataclass
class ResultadoInventario:
    vistos: int = 0
    nuevos: int = 0
    repetidos: int = 0
    excluidos: int = 0
    demasiado_grandes: int = 0
    ilegibles: int = 0

    def como_dict(self) -> dict[str, int]:
        return self.__dict__.copy()


def _excluido(nombre: str, patrones: list[str]) -> bool:
    return any(fnmatch.fnmatch(nombre, p) for p in patrones)


def recorrer(raiz: Path, extensiones: list[str], excluir: list[str]) -> Iterator[Path]:
    """Genera rutas de archivo bajo `raiz` con las extensiones pedidas, en profundidad."""
    vistos_dir: set[tuple[int, int]] = set()
    pila = [raiz]
    while pila:
        actual = pila.pop()
        try:
            with os.scandir(actual) as it:
                for entrada in it:
                    nombre = entrada.name
                    if _excluido(nombre, excluir):
                        continue
                    try:
                        if entrada.is_dir(follow_symlinks=False):
                            st = entrada.stat(follow_symlinks=False)
                            clave = (st.st_dev, st.st_ino)
                            if clave in vistos_dir:
                                continue
                            vistos_dir.add(clave)
                            pila.append(Path(entrada.path))
                        elif entrada.is_file(follow_symlinks=False):
                            if Path(nombre).suffix.lower() in extensiones:
                                yield Path(entrada.path)
                    except OSError:
                        continue
        except (PermissionError, FileNotFoundError, OSError):
            continue


def sha256_archivo(ruta: Path, limite_bytes: int | None = None) -> str:
    """SHA-256 en streaming. `limite_bytes` acota la lectura en archivos enormes."""
    h = hashlib.sha256()
    leidos = 0
    with open(ruta, "rb") as fh:
        while True:
            trozo = fh.read(TROZO)
            if not trozo:
                break
            h.update(trozo)
            leidos += len(trozo)
            if limite_bytes and leidos >= limite_bytes:
                break
    return h.hexdigest()


def escanear(cfg: Config, cola: Cola, lote: str, carpetas: list[Path] | None = None,
             progreso: Callable[[int], None] | None = None) -> ResultadoInventario:
    """Recorre las carpetas configuradas y da de alta lo nuevo en la cola."""
    res = ResultadoInventario()
    tope = cfg.tamano_max_mb * 1024 * 1024
    destino = cfg.destino_md.resolve() if cfg.destino_md.exists() else cfg.destino_md
    for raiz in (carpetas or cfg.carpetas):
        raiz = Path(raiz).expanduser()
        if not raiz.exists():
            raise FileNotFoundError(f"La carpeta no existe: {raiz}")
        for ruta in recorrer(raiz, cfg.extensiones, cfg.excluir):
            res.vistos += 1
            if progreso and res.vistos % 200 == 0:
                progreso(res.vistos)
            try:
                if destino in ruta.resolve().parents:  # no reprocesar lo que ya generamos
                    res.excluidos += 1
                    continue
                st = ruta.stat()
            except OSError:
                res.ilegibles += 1
                continue
            if st.st_size == 0:
                res.ilegibles += 1
                continue
            if st.st_size > tope:
                res.demasiado_grandes += 1
                continue
            try:
                sha = sha256_archivo(ruta)
            except OSError:
                res.ilegibles += 1
                continue
            if cola.registrar(lote, ruta, ruta.suffix.lower(), st.st_size, st.st_mtime, sha):
                res.nuevos += 1
            else:
                res.repetidos += 1
    cola.marcar_duplicados()
    return res
