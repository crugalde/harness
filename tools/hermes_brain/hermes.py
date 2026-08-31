"""Adaptador del CLI de Hermes agent: un proceso = un chat que se abre y se cierra.

El comando concreto se declara en la configuración, así que este módulo no asume la sintaxis
de Hermes. Marcadores admitidos en `hermes.comando` y `hermes.comando_cierre`:

    {archivo}      ruta absoluta del documento a analizar
    {skill}        nombre de la skill a usar (analisis-estudio / resumen-clinico-md)
    {prompt}       prompt renderizado (texto en línea)
    {prompt_file}  ruta a un archivo temporal con el prompt
    {destino}      carpeta OneDrive donde debe quedar el .md
    {adjuntos}     carpeta de figuras
    {slug}         nombre sugerido para el .md (sin extensión)
    {salida_json}  ruta donde Hermes puede dejar su resultado en JSON
    {sesion}       id de sesión devuelto por Hermes (solo en `comando_cierre`)
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

RE_JSON = re.compile(r"\{[^{}]*\"(?:md|md_path|archivo_md|notion_url|sesion|session_id)\"[^{}]*\}", re.S)
RE_RUTA_MD = re.compile(r"[A-Za-z]:\\[^\r\n\"']+\.md|/[^\r\n\"']+\.md")
RE_NOTION = re.compile(r"https://(?:www\.)?notion\.so/[^\s\"'<>)]+", re.I)


class ErrorHermes(RuntimeError):
    """Hermes falló de forma que amerita reintento o marcar el archivo como error."""


@dataclass
class ResultadoHermes:
    ok: bool
    md: str = ""
    notion_url: str = ""
    sesion: str = ""
    duracion_s: float = 0.0
    salida: str = ""
    error: str = ""
    extra: dict = field(default_factory=dict)


def slug(texto: str, largo: int = 80) -> str:
    """Nombre de archivo seguro y estable a partir de un título o nombre de documento."""
    normal = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    normal = re.sub(r"[^\w\s-]", "", normal).strip().lower()
    normal = re.sub(r"[\s_-]+", "-", normal)
    return (normal[:largo].strip("-") or "documento")


def _sustituir(plantilla: list[str], valores: dict[str, str]) -> list[str]:
    """Rellena los marcadores. Un marcador vacío se lleva consigo la bandera que lo precede.

    Sin esto, una skill sin nombre produce `-s ""`, que el CLI rechaza; con esto la bandera
    simplemente no se pasa, que es lo que corresponde cuando no hay skill que precargar.
    """
    salida: list[str] = []
    for original in plantilla:
        arg = original
        for clave, valor in valores.items():
            arg = arg.replace("{" + clave + "}", valor)
        if arg == "" and original != "":
            if salida and salida[-1].startswith("-"):
                salida.pop()
            continue
        salida.append(arg)
    return salida


def _matar(proc: subprocess.Popen) -> None:
    """Termina el proceso y sus hijos (el CLI puede lanzar un modelo local)."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, check=False)
        else:
            os.killpg(os.getpgid(proc.pid), 9)
    except (ProcessLookupError, PermissionError, OSError):
        # El proceso ya terminó (o el SO no deja señalarlo): el wait de abajo lo confirma.
        pass
    finally:
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass


def _ejecutar(cmd: list[str], timeout_s: int, cwd: str | None, env_extra: dict[str, str]) -> tuple[int, str]:
    env = {**os.environ, **env_extra}
    kwargs: dict = {}
    if os.name != "nt":
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace", cwd=cwd, env=env, **kwargs)
    try:
        salida, _ = proc.communicate(timeout=timeout_s)
        return proc.returncode, salida or ""
    except subprocess.TimeoutExpired:
        _matar(proc)
        raise ErrorHermes(f"timeout tras {timeout_s}s") from None


def _parsear(salida: str, salida_json: Path, destino: Path, desde: float) -> dict:
    """Extrae {md, notion_url, sesion} del JSON de Hermes; si no lo hay, deduce del texto."""
    datos: dict = {}
    if salida_json.exists():
        try:
            datos = json.loads(salida_json.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            datos = {}
    if not datos:
        for trozo in reversed(RE_JSON.findall(salida)):
            try:
                datos = json.loads(trozo)
                break
            except json.JSONDecodeError:
                continue
    md = str(datos.get("md") or datos.get("md_path") or datos.get("archivo_md") or "")
    notion = str(datos.get("notion_url") or datos.get("notion") or "")
    sesion = str(datos.get("sesion") or datos.get("session_id") or datos.get("chat_id") or "")
    if not md:
        rutas = [r for r in RE_RUTA_MD.findall(salida) if Path(r).exists()]
        if rutas:
            md = rutas[-1]
    if not md and destino.exists():
        recientes = [p for p in destino.glob("*.md") if p.stat().st_mtime >= desde - 1]
        if len(recientes) == 1:
            md = str(recientes[0])
    if not notion:
        enlaces = RE_NOTION.findall(salida)
        notion = enlaces[-1] if enlaces else ""
    return {"md": md, "notion_url": notion, "sesion": sesion, "extra": datos}


def ejecutar_chat(cfg_hermes, *, archivo: Path, skill: str, prompt: str, destino: Path,
                  adjuntos: Path, nombre_slug: str, exige_md: bool = True) -> ResultadoHermes:
    """Abre un chat de Hermes para un archivo, espera a que termine y lo cierra.

    Reintenta según `hermes.reintentos`. Nunca deja procesos huérfanos: al vencer el timeout
    mata el árbol de procesos antes de reintentar.
    """
    tmp = Path(tempfile.mkdtemp(prefix="hermes_chat_"))
    salida_json = tmp / "resultado.json"
    archivo_prompt = tmp / "prompt.txt"
    archivo_prompt.write_text(prompt, encoding="utf-8")
    valores = {
        "archivo": str(archivo), "skill": skill, "prompt": prompt,
        "prompt_file": str(archivo_prompt), "destino": str(destino), "adjuntos": str(adjuntos),
        "slug": nombre_slug, "salida_json": str(salida_json),
    }
    cmd = _sustituir(cfg_hermes.comando, valores)
    intentos = max(1, cfg_hermes.reintentos + 1)
    ultimo_error = ""
    for intento in range(1, intentos + 1):
        inicio = time.time()
        try:
            codigo, salida = _ejecutar(cmd, cfg_hermes.timeout_s, cfg_hermes.cwd, cfg_hermes.env)
        except ErrorHermes as exc:
            ultimo_error = str(exc)
        except FileNotFoundError:
            return ResultadoHermes(False, error=f"no se encuentra el ejecutable: {cmd[0]}",
                                   duracion_s=time.time() - inicio)
        else:
            datos = _parsear(salida, salida_json, destino, inicio)
            if cfg_hermes.comando_cierre:
                cierre = _sustituir(cfg_hermes.comando_cierre, {**valores, "sesion": datos["sesion"]})
                try:
                    _ejecutar(cierre, 120, cfg_hermes.cwd, cfg_hermes.env)
                except ErrorHermes:
                    pass  # el chat se cierra igual al terminar el proceso principal
            if codigo == 0 and (datos["md"] or not exige_md):
                return ResultadoHermes(True, md=datos["md"], notion_url=datos["notion_url"],
                                       sesion=datos["sesion"], duracion_s=time.time() - inicio,
                                       salida=salida[-4000:], extra=datos["extra"])
            ultimo_error = (f"código {codigo}" if codigo != 0 else "Hermes terminó sin producir .md")
            if codigo == 0:
                # No es un fallo transitorio: reintentar produciría lo mismo.
                return ResultadoHermes(False, error=ultimo_error, salida=salida[-4000:],
                                       duracion_s=time.time() - inicio, sesion=datos["sesion"])
        if intento < intentos:
            time.sleep(cfg_hermes.espera_reintento_s * intento)
    return ResultadoHermes(False, error=ultimo_error or "fallo desconocido")


def prompt_pdf(cfg, archivo: Path, titulo: str, nombre_slug: str) -> str:
    """Prompt para un PDF de revista científica.

    Pensado para un CLI de un solo disparo que imprime solo la respuesta final: la ruta del
    documento va dentro del texto (no hay bandera de adjunto) y el resultado se recupera de
    la última línea de stdout (no hay bandera de salida JSON).
    """
    if cfg.hermes.prompt_pdf:
        return cfg.hermes.prompt_pdf.format(archivo=archivo, titulo=titulo, slug=nombre_slug,
                                            destino=cfg.destino_md, skill=cfg.hermes.skill_pdf)
    return (
        f"Analiza este artículo con la skill `{cfg.hermes.skill_pdf}`.\n\n"
        f"Archivo: {archivo}\n"
        f"Título detectado: {titulo or '(no detectado)'}\n\n"
        "Entrega los dos productos que define la skill:\n"
        "1. La publicación en Notion.\n"
        f"2. El .md guardado en «{cfg.destino_md}» con nombre `{nombre_slug}.md`.\n\n"
        "La ÚLTIMA línea de tu respuesta debe ser exactamente una línea JSON, sin texto "
        "después de ella:\n"
        '{"md": "<ruta absoluta del .md>", "notion_url": "<url o cadena vacía>"}'
    )


def prompt_revision_docx(cfg, md: Path, origen: Path, figuras: int, enmascarados: int) -> str:
    """Prompt de la pasada de revisión sobre un `.md` que el worker ya generó.

    La conversión es determinista y ya ocurrió; lo que se le pide a Hermes es exactamente lo
    que un script no puede hacer: decidir qué párrafo en negrita era un título, qué muestra
    una figura, y con qué nota de la bóveda enlazar.
    """
    if cfg.hermes.prompt_docx:
        return cfg.hermes.prompt_docx.format(archivo=md, origen=origen, titulo=md.stem,
                                             slug=md.stem, destino=cfg.destino_md,
                                             skill=cfg.hermes.skill_docx)
    return (
        f"El resumen clínico ya fue convertido a Markdown por el conversor determinista de la "
        f"skill `{cfg.hermes.skill_docx}`. Tu trabajo es la revisión que describe la skill, "
        "no la conversión.\n\n"
        f"Archivo .md: {md}\n"
        f"Figuras extraídas: {figuras} · datos enmascarados: {enmascarados}\n\n"
        "Corrige en ese mismo archivo, sin inventar contenido clínico que no esté en él:\n"
        "1. Párrafos en negrita que en realidad son títulos → conviértelos en ## o ###.\n"
        "2. Figuras con pie genérico → describe qué muestra la figura.\n"
        "3. Tablas descuadradas por celdas combinadas de Word.\n"
        "4. Front-matter: añade a `tags` la patología y su dominio.\n"
        "5. Si la bóveda ya tiene una nota del mismo tema, enlázala con [[nota]].\n\n"
        'La ÚLTIMA línea de tu respuesta debe ser exactamente: {"md": "' + str(md) + '"}'
    )


def prompt_docx(cfg, archivo: Path, titulo: str, nombre_slug: str) -> str:
    """Prompt del modo alternativo: es Hermes quien ejecuta el conversor.

    Solo se usa con `convertir_docx_en_worker: false`, y exige que el CLI de Hermes pueda
    ejecutar comandos. El modo por defecto convierte en el worker y no depende de eso.
    """
    if cfg.hermes.prompt_docx:
        return cfg.hermes.prompt_docx.format(archivo=archivo, titulo=titulo, slug=nombre_slug,
                                             destino=cfg.destino_md, skill=cfg.hermes.skill_docx)
    python = cfg.python or sys.executable
    # Sin slug, el conversor toma el nombre del título del documento (ya de-identificado): es
    # lo que corresponde cuando el nombre del Word trae datos de paciente (R8).
    arg_slug = f' --slug "{nombre_slug}"' if nombre_slug else ""
    return (
        f"Usa la skill `{cfg.hermes.skill_docx}` para convertir este resumen clínico a Markdown "
        "conservando las figuras.\n"
        f"Archivo: {archivo}\n\n"
        "El paso determinista es este comando; ejecútalo tal cual:\n"
        f'  "{python}" "{cfg.script_docx_md}" "{archivo}" --salida "{cfg.destino_md}" '
        f'--adjuntos "{cfg.adjuntos}"{arg_slug} --json\n\n'
        "Después revisa el .md generado según la skill (títulos, tablas, pies de figura, "
        "front-matter) y corrige lo que haga falta.\n"
        'La ÚLTIMA línea de tu respuesta debe ser exactamente: {"md": "<ruta del .md>"}'
    )
