"""Motor del lote: clasifica cada archivo, abre un chat de Hermes por documento y registra
el resultado. Diseñado para carpetas de miles de archivos: estado persistente, reanudable,
y con parada limpia por Ctrl+C o por orden del flujo n8n.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from . import hermes as h
from .clasificador import clasificar
from .cliente_n8n import ClienteN8n, registro_anonimo
from .cola import Archivo, Cola
from .config import Config

SKILL_POR_CLASE = {"cientifico": "pdf", "clinico": "docx"}


@dataclass
class Progreso:
    procesados: int = 0
    hechos: int = 0
    omitidos: int = 0
    dudosos: int = 0
    errores: int = 0
    inicio: float = field(default_factory=time.time)

    @property
    def segundos(self) -> float:
        return time.time() - self.inicio

    def linea(self, total: int) -> str:
        tasa = self.procesados / max(self.segundos / 60, 1e-6)
        restante = (total - self.procesados) / tasa if tasa > 0 else 0
        return (f"[{self.procesados}/{total}] hechos={self.hechos} omitidos={self.omitidos} "
                f"dudosos={self.dudosos} errores={self.errores} "
                f"({tasa:.1f}/min, quedan ~{restante:.0f} min)")


class DetenerLote(Exception):
    """Parada ordenada: por el usuario (Ctrl+C) o por el flujo n8n."""


def _clasificar_archivo(cfg: Config, cola: Cola, archivo: Archivo):
    """Clasifica si hace falta y persiste el veredicto."""
    if archivo.clasificacion not in ("desconocido", ""):
        return archivo.clasificacion, archivo.score, archivo.motivo, archivo.evidencia
    clf = clasificar(archivo.ruta, cfg.clasificador)
    evidencia = dict(clf.evidencia)
    if clf.titulo:
        evidencia["titulo"] = clf.titulo
    cola.actualizar(archivo.id, clasificacion=clf.decision, score=clf.score,
                    evidencia=evidencia, motivo=clf.motivo, estado="clasificado")
    archivo.evidencia = evidencia
    return clf.decision, clf.score, clf.motivo, evidencia


def procesar_archivo(cfg: Config, cola: Cola, archivo: Archivo) -> dict:
    """Clasifica y, si corresponde, lo pasa por un chat de Hermes. Devuelve el registro anónimo."""
    inicio = time.time()
    decision, score, motivo, evidencia = _clasificar_archivo(cfg, cola, archivo)

    if decision in ("no_cientifico", "no_clinico", "no_soportado"):
        cola.actualizar(archivo.id, estado="omitido", motivo=motivo)
        return registro_anonimo(archivo, decision, "omitido", score, time.time() - inicio,
                                motivo=motivo, incluir_nombre=cfg.n8n.enviar_nombres)
    if decision == "dudoso":
        cola.actualizar(archivo.id, estado="dudoso", motivo=motivo)
        return registro_anonimo(archivo, decision, "dudoso", score, time.time() - inicio,
                                motivo=motivo, incluir_nombre=cfg.n8n.enviar_nombres)
    if decision == "error":
        cola.actualizar(archivo.id, estado="error", error=motivo)
        return registro_anonimo(archivo, decision, "error", score, time.time() - inicio,
                                error=motivo, incluir_nombre=cfg.n8n.enviar_nombres)

    if not cola.tomar(archivo.id):
        return registro_anonimo(archivo, decision, "omitido", score, 0.0, motivo="tomado por otro worker")

    evidencia = evidencia if isinstance(evidencia, dict) else {}
    titulo = str(evidencia.get("titulo", ""))
    if titulo:
        nombre_slug = h.slug(titulo)
    elif evidencia.get("phi_probable"):
        # El nombre del archivo también es PHI: que el .md lo tome del título del documento,
        # que la conversión ya de-identifica (R8).
        nombre_slug = ""
    else:
        nombre_slug = h.slug(archivo.ruta.stem)
    ruta_archivo = Path(evidencia["convertido_desde_doc"]) \
        if evidencia.get("convertido_desde_doc") else archivo.ruta

    if decision == "cientifico":
        skill, prompt = cfg.hermes.skill_pdf, h.prompt_pdf(cfg, ruta_archivo, titulo, nombre_slug)
    else:
        skill, prompt = cfg.hermes.skill_docx, h.prompt_docx(cfg, ruta_archivo, titulo, nombre_slug)

    cfg.destino_md.mkdir(parents=True, exist_ok=True)
    res = h.ejecutar_chat(cfg.hermes, archivo=ruta_archivo, skill=skill, prompt=prompt,
                          destino=cfg.destino_md, adjuntos=cfg.dir_adjuntos, nombre_slug=nombre_slug)
    if res.ok:
        cola.actualizar(archivo.id, estado="hecho", salida_md=res.md, notion_url=res.notion_url,
                        duracion_s=res.duracion_s, error="")
        return registro_anonimo(archivo, decision, "hecho", score, res.duracion_s,
                                md=True, notion=bool(res.notion_url), motivo=motivo,
                                incluir_nombre=cfg.n8n.enviar_nombres)
    cola.actualizar(archivo.id, estado="error", error=res.error[:500], duracion_s=res.duracion_s)
    return registro_anonimo(archivo, decision, "error", score, res.duracion_s, error=res.error,
                            motivo=motivo, incluir_nombre=cfg.n8n.enviar_nombres)


def procesar_lote(cfg: Config, cola: Cola, lote: str | None = None, limite: int | None = None,
                  cliente: ClienteN8n | None = None,
                  al_avanzar: Callable[[Progreso, int], None] | None = None) -> Progreso:
    """Procesa la cola pendiente. Reanudable: se puede cortar y volver a llamar."""
    cola.liberar_colgados()
    pendientes = cola.pendientes(lote=lote, limite=limite)
    total = len(pendientes)
    prog = Progreso()
    buffer: list[dict] = []
    cliente = cliente or ClienteN8n(cfg.n8n, cola)

    def _descargar(forzar: bool = False) -> None:
        if buffer and (forzar or len(buffer) >= cfg.n8n.lote_resultados):
            cliente.resultados(lote or "todos", list(buffer))
            buffer.clear()

    def _contabilizar(reg: dict) -> None:
        prog.procesados += 1
        estado = reg["estado"]
        if estado == "hecho":
            prog.hechos += 1
        elif estado == "omitido":
            prog.omitidos += 1
        elif estado == "dudoso":
            prog.dudosos += 1
        elif estado == "error":
            prog.errores += 1
        buffer.append(reg)

    try:
        if cfg.concurrencia == 1:
            for archivo in pendientes:
                _contabilizar(procesar_archivo(cfg, cola, archivo))
                _descargar()
                if al_avanzar:
                    al_avanzar(prog, total)
                if prog.procesados % 10 == 0:
                    ctrl = cliente.control(lote or "todos", {"procesados": prog.procesados, "total": total})
                    if ctrl.detener:
                        raise DetenerLote(ctrl.mensaje or "detenido desde n8n")
                    while ctrl.pausar:
                        time.sleep(30)
                        ctrl = cliente.control(lote or "todos", {"procesados": prog.procesados,
                                                                 "total": total, "pausado": True})
                        if ctrl.detener:
                            raise DetenerLote(ctrl.mensaje or "detenido desde n8n")
        else:
            with ThreadPoolExecutor(max_workers=cfg.concurrencia) as pool:
                futuros = {pool.submit(procesar_archivo, cfg, cola, a): a for a in pendientes}
                for fut in as_completed(futuros):
                    _contabilizar(fut.result())
                    _descargar()
                    if al_avanzar:
                        al_avanzar(prog, total)
    except KeyboardInterrupt:
        raise DetenerLote("interrumpido por el usuario (Ctrl+C)") from None
    finally:
        _descargar(forzar=True)
        cola.liberar_colgados(segundos=0)
        cliente.drenar_pendientes()
    return prog
