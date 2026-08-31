"""Cliente HTTP hacia los webhooks del flujo n8n del VPS.

Reglas de la frontera (R8): al VPS solo viajan identificadores opacos (sha256 truncado),
extensión, clasificación, score, estado, código de error y duraciones. Nunca rutas, nombres
de archivo, títulos ni contenido. Si el VPS no responde, los envíos se encolan en SQLite y
el trabajo local continúa.
"""
from __future__ import annotations

import platform
import time
from dataclasses import dataclass
from typing import Any

try:
    import requests
except ImportError:          # solo se necesita si hay un n8n configurado
    requests = None

# Rutas de los webhooks del flujo n8n. Se concatenan a `n8n.base_url`, que ya incluye
# el prefijo del servidor (…/webhook para producción, …/webhook-test para pruebas).
RUTAS = {
    "inventario": "/hermes-inventario",
    "resultado": "/hermes-resultado",
    "fin": "/hermes-fin",
    "control": "/hermes-control",
}


@dataclass
class Control:
    """Órdenes que el flujo n8n devuelve al worker entre archivo y archivo."""

    accion: str = "seguir"          # seguir | pausa | detener
    mensaje: str = ""

    @property
    def detener(self) -> bool:
        return self.accion == "detener"

    @property
    def pausar(self) -> bool:
        return self.accion == "pausa"


class ClienteN8n:
    def __init__(self, cfg_n8n, cola=None):
        self.cfg = cfg_n8n
        self.cola = cola
        self.activo = bool(cfg_n8n.base_url)
        self.ultimo_error = ""
        self.sesion = None
        if not self.activo:
            return                      # sin VPS el worker trabaja igual, solo sin panel
        if requests is None:
            raise RuntimeError("Configuraste 'n8n.base_url' pero falta la librería requests. "
                               "Instala con: pip install requests (o deja base_url vacío).")
        self.sesion = requests.Session()
        self.sesion.headers.update({
            "X-Hermes-Token": cfg_n8n.token,
            "Content-Type": "application/json",
            "User-Agent": "hermes-brain-worker/1.0",
        })

    # ------------------------------------------------------------------ interno
    def _post(self, ruta: str, payload: dict, reintentos: int = 2) -> dict | None:
        if not self.activo:
            return None
        url = f"{self.cfg.base_url}{ruta}"
        for intento in range(reintentos + 1):
            try:
                r = self.sesion.post(url, json=payload, timeout=self.cfg.timeout_s,
                                     verify=self.cfg.verificar_tls)
                if r.status_code >= 500 and intento < reintentos:
                    time.sleep(2 ** intento)
                    continue
                r.raise_for_status()
                self.ultimo_error = ""
                try:
                    return r.json()
                except ValueError:
                    return {"ok": True}
            except requests.RequestException as exc:
                self.ultimo_error = f"{type(exc).__name__}: {exc}"
                if intento < reintentos:
                    time.sleep(2 ** intento)
        if self.cola is not None:
            self.cola.encolar_envio({"ruta": ruta, "payload": payload})
        return None

    # ------------------------------------------------------------------ API
    def inventario(self, lote: str, resumen: dict[str, int], carpetas: int) -> dict | None:
        return self._post(RUTAS["inventario"], {
            "lote": lote, "host": platform.node(), "carpetas": carpetas,
            "inventario": resumen, "ts": time.time(),
        })

    def resultados(self, lote: str, registros: list[dict]) -> dict | None:
        return self._post(RUTAS["resultado"], {"lote": lote, "host": platform.node(),
                                               "n": len(registros), "registros": registros,
                                               "ts": time.time()})

    def fin(self, lote: str, resumen: dict, clasificaciones: dict, dudosos: int,
            errores: list[dict]) -> dict | None:
        return self._post(RUTAS["fin"], {
            "lote": lote, "host": platform.node(), "resumen": resumen,
            "clasificaciones": clasificaciones, "dudosos": dudosos,
            "errores": errores[:50], "ts": time.time(),
        })

    def control(self, lote: str, avance: dict[str, Any] | None = None) -> Control:
        """Heartbeat + consulta de órdenes. Ante fallo de red devuelve 'seguir'."""
        if not self.activo:
            return Control()
        try:
            r = self.sesion.post(f"{self.cfg.base_url}{RUTAS['control']}",
                                 json={"lote": lote, "host": platform.node(),
                                       "avance": avance or {}, "ts": time.time()},
                                 timeout=self.cfg.timeout_s, verify=self.cfg.verificar_tls)
            r.raise_for_status()
            datos = r.json()
        except (requests.RequestException, ValueError) as exc:
            self.ultimo_error = f"{type(exc).__name__}: {exc}"
            return Control()
        if isinstance(datos, list) and datos:
            datos = datos[0]
        if not isinstance(datos, dict):
            return Control()
        return Control(accion=str(datos.get("accion", "seguir")), mensaje=str(datos.get("mensaje", "")))

    def drenar_pendientes(self) -> int:
        """Reintenta los envíos que quedaron encolados por caída del VPS."""
        if not (self.activo and self.cola):
            return 0
        enviados: list[int] = []
        for id_envio, sobre in self.cola.envios_pendientes():
            url = f"{self.cfg.base_url}{sobre['ruta']}"
            try:
                r = self.sesion.post(url, json=sobre["payload"], timeout=self.cfg.timeout_s,
                                     verify=self.cfg.verificar_tls)
                r.raise_for_status()
                enviados.append(id_envio)
            except requests.RequestException:
                break
        self.cola.borrar_envios(enviados)
        return len(enviados)


def registro_anonimo(archivo, clasificacion: str, estado: str, score: float,
                     duracion_s: float, error: str = "", motivo: str = "",
                     notion: bool = False, md: bool = False,
                     incluir_nombre: bool = False) -> dict:
    """Construye el registro que viaja al VPS. Sin PHI salvo que se habilite explícitamente."""
    registro = {
        "id": archivo.id_opaco,
        "ext": archivo.ext,
        "kb": round(archivo.tamano / 1024),
        "clasificacion": clasificacion,
        "estado": estado,
        "score": score,
        "motivo": motivo[:180],
        "duracion_s": round(duracion_s, 1),
        "md": md,
        "notion": notion,
        "error": error[:180],
    }
    if incluir_nombre:
        registro["nombre"] = archivo.ruta.name
    return registro
