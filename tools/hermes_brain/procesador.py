"""Motor del lote: clasifica cada archivo, abre un chat de Hermes por documento y registra
el resultado. Diseñado para carpetas de miles de archivos: estado persistente, reanudable,
y con parada limpia por Ctrl+C o por orden del flujo n8n.
"""
from __future__ import annotations

import json
import subprocess
import sys
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
TIMEOUT_CONVERSOR_S = 600


@dataclass
class ResultadoConversion:
    """Salida del conversor determinista .docx → .md de la skill."""

    ok: bool
    md: str = ""
    figuras: int = 0
    enmascarados: int = 0
    error: str = ""


def convertir_docx(cfg: Config, archivo: Path, nombre_slug: str) -> ResultadoConversion:
    """Corre el conversor de la skill. Es determinista: no necesita a Hermes para nada."""
    cmd = [cfg.python or sys.executable, str(cfg.script_docx_md), str(archivo),
           "--salida", str(cfg.destino_md), "--adjuntos", cfg.adjuntos, "--json"]
    if nombre_slug:
        cmd += ["--slug", nombre_slug]
    if not cfg.deidentificar:
        cmd.append("--sin-deidentificar")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=TIMEOUT_CONVERSOR_S, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return ResultadoConversion(False, error=f"conversor: {type(exc).__name__}: {exc}"[:300])
    if proc.returncode != 0:
        return ResultadoConversion(False, error=((proc.stderr or proc.stdout) or "").strip()[-300:])
    lineas = [l for l in (proc.stdout or "").splitlines() if l.strip()]
    try:
        datos = json.loads(lineas[-1])
    except (json.JSONDecodeError, IndexError):
        return ResultadoConversion(False, error="el conversor no devolvió JSON")
    return ResultadoConversion(True, md=str(datos.get("md", "")),
                               figuras=int(datos.get("figuras", 0)),
                               enmascarados=int(datos.get("enmascarados", 0)))


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

    cfg.destino_md.mkdir(parents=True, exist_ok=True)
    if decision == "clinico" and cfg.hermes.convertir_docx_en_worker:
        return _procesar_clinico(cfg, cola, archivo, ruta_archivo, nombre_slug, score, motivo,
                                 inicio)

    if decision == "cientifico":
        skill, prompt = cfg.hermes.skill_pdf, h.prompt_pdf(cfg, ruta_archivo, titulo, nombre_slug)
    else:
        skill, prompt = cfg.hermes.skill_docx, h.prompt_docx(cfg, ruta_archivo, titulo, nombre_slug)

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


def _procesar_clinico(cfg: Config, cola: Cola, archivo: Archivo, ruta: Path, nombre_slug: str,
                      score: float, motivo: str, inicio: float) -> dict:
    """Word clínico: convierte el worker, revisa Hermes.

    El orden importa. Si Hermes falla —no responde, no sabe editar archivos, no tiene shell—
    el `.md` con sus figuras ya está escrito en la bóveda y el archivo cuenta como hecho, con
    la nota de que quedó sin revisar. Al revés, un fallo del agente costaría la conversión.
    """
    conv = convertir_docx(cfg, ruta, nombre_slug)
    if not conv.ok:
        cola.actualizar(archivo.id, estado="error", error=conv.error[:500])
        return registro_anonimo(archivo, "clinico", "error", score, time.time() - inicio,
                                error=conv.error, motivo=motivo,
                                incluir_nombre=cfg.n8n.enviar_nombres)

    nota = ""
    if cfg.hermes.revisar_docx_con_hermes and cfg.hermes.comando:
        md = Path(conv.md)
        res = h.ejecutar_chat(
            cfg.hermes, archivo=md, skill=cfg.hermes.skill_docx,
            prompt=h.prompt_revision_docx(cfg, md, ruta, conv.figuras, conv.enmascarados),
            destino=cfg.destino_md, adjuntos=cfg.dir_adjuntos,
            nombre_slug=nombre_slug or md.stem, exige_md=False)
        if not res.ok:
            nota = f"convertido; la revisión de Hermes falló: {res.error}"[:300]

    cola.actualizar(archivo.id, estado="hecho", salida_md=conv.md,
                    duracion_s=time.time() - inicio, error=nota)
    return registro_anonimo(archivo, "clinico", "hecho", score, time.time() - inicio, md=True,
                            motivo=motivo, error=nota, incluir_nombre=cfg.n8n.enviar_nombres)


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
