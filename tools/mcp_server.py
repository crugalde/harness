#!/usr/bin/env python3
"""mcp_server.py — Puente MCP: expone el harness a Hermes (o a cualquier cliente MCP).

Hasta ahora Hermes podía **leer** los `SKILL.md` del repo pero no **ejecutar** nada: las
tools viven en el `ToolRegistry` del harness, que solo conoce `tools/loop.py`. Este
servidor las publica por MCP para que Hermes las invoque, y además le da acceso a las
carpetas locales del usuario.

## La parte que importa: contención de rutas

Un servidor MCP con acceso a archivos es, si no se acota, acceso al disco entero desde el
modelo. Aquí toda ruta que entre por una tool se resuelve (`resolve()`, que colapsa `..` y
sigue los enlaces simbólicos) y se comprueba que caiga **dentro** de alguna raíz permitida
antes de tocarla. Sin `HARNESS_FILE_ROOTS` configurado no hay raíces y las tools de
archivos se niegan a operar: el fallo cerrado es el correcto cuando la alternativa es
exponer `C:/`.

Resolver antes de comparar es lo que atrapa los tres escapes: `..` en la ruta, una ruta
absoluta fuera de la raíz, y un enlace simbólico que apunte afuera.

Uso:
  HARNESS_FILE_ROOTS="C:/Users/Usuario/Documentos:C:/Users/Usuario/Zotero" \\
  python tools/mcp_server.py
Req: pip install mcp
"""
from __future__ import annotations

import functools
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

try:
    from env_loader import load_env
    load_env()
except Exception:                                   # el harness corre sin .env local
    pass

MAX_LECTURA = 200_000            # caracteres por lectura de archivo
MAX_RESULTADOS = 200             # entradas por listado o búsqueda
SUFIJOS_TEXTO = {".md", ".txt", ".json", ".csv", ".yaml", ".yml", ".py", ".log", ".bib"}


# ---------------------------------------------------------------------------
# Contención de rutas
# ---------------------------------------------------------------------------
def raices() -> list[Path]:
    """Carpetas que este servidor puede tocar. Vacío = no puede tocar ninguna."""
    crudo = os.environ.get("HARNESS_FILE_ROOTS", "")
    out: list[Path] = []
    for parte in crudo.split(os.pathsep):
        parte = parte.strip()
        if not parte:
            continue
        try:
            p = Path(parte).expanduser().resolve()
        except OSError:
            continue
        if p.is_dir():
            out.append(p)
    return out


def dentro_de_raices(candidata: Path, permitidas: list[Path]) -> Path:
    """Devuelve la ruta resuelta si cae dentro de alguna raíz; si no, levanta.

    `resolve()` va antes que la comparación a propósito: colapsa `..` y sigue los enlaces
    simbólicos, que son las dos formas de salirse de una raíz aparentando estar dentro.
    """
    if not permitidas:
        raise PermissionError(
            "No hay carpetas permitidas. Define HARNESS_FILE_ROOTS con las rutas a las "
            "que este servidor puede acceder, separadas por el separador del sistema.")
    try:
        real = Path(candidata).expanduser().resolve()
    except OSError as e:
        raise PermissionError(f"Ruta ilegible: {candidata} ({e})") from e
    for raiz in permitidas:
        if real == raiz or raiz in real.parents:
            return real
    raise PermissionError(
        f"Fuera de las carpetas permitidas: {real}\n"
        f"Permitidas: {', '.join(str(r) for r in permitidas)}")


def _resolver(ruta: str) -> Path:
    return dentro_de_raices(Path(ruta), raices())


# ---------------------------------------------------------------------------
# Implementación de las tools (separada del decorador, para poder probarla)
# ---------------------------------------------------------------------------
def listar_carpeta(ruta: str, patron: str = "*") -> str:
    p = _resolver(ruta)
    if not p.is_dir():
        return f"ERROR: no es una carpeta: {p}"
    filas = []
    for hijo in sorted(p.glob(patron))[:MAX_RESULTADOS]:
        tipo = "dir " if hijo.is_dir() else "file"
        tam = "" if hijo.is_dir() else f"  {hijo.stat().st_size:,} B"
        filas.append(f"  {tipo}  {hijo.name}{tam}")
    if not filas:
        return f"{p}: sin entradas que coincidan con '{patron}'."
    return f"{p} ({len(filas)} entradas)\n" + "\n".join(filas)


def buscar_archivos(patron: str, subcarpeta: str = "") -> str:
    permitidas = raices()
    bases = [_resolver(subcarpeta)] if subcarpeta else permitidas
    if not bases:
        raise PermissionError("No hay carpetas permitidas (define HARNESS_FILE_ROOTS).")
    encontrados: list[str] = []
    for base in bases:
        for hit in base.rglob(patron):
            encontrados.append(str(hit))
            if len(encontrados) >= MAX_RESULTADOS:
                break
        if len(encontrados) >= MAX_RESULTADOS:
            break
    if not encontrados:
        return f"Sin coincidencias para '{patron}' en {', '.join(str(b) for b in bases)}."
    cola = ("\n(tope de resultados alcanzado; afina el patrón)"
            if len(encontrados) >= MAX_RESULTADOS else "")
    return "\n".join(encontrados) + cola


def leer_archivo(ruta: str) -> str:
    p = _resolver(ruta)
    if not p.is_file():
        return f"ERROR: no es un archivo: {p}"
    if p.suffix.lower() not in SUFIJOS_TEXTO:
        return (f"ERROR: {p.suffix} no es texto. Un PDF o un .docx son contenedores "
                f"binarios: usa harness_pdf_a_markdown o harness_analizar_papers.")
    texto = p.read_text(encoding="utf-8", errors="replace")
    if len(texto) > MAX_LECTURA:
        return texto[:MAX_LECTURA] + f"\n\n[... recortado: {len(texto) - MAX_LECTURA} caracteres]"
    return texto


def pdf_a_markdown(pdf: str, salida: str, dpi: int = 200) -> str:
    origen, destino = _resolver(pdf), _resolver(salida)
    import pdf_a_markdown as motor
    r = motor.convertir(origen, destino, dpi=dpi)
    return (f"OK: {r['md']} · {r['paginas']} páginas ({r['dos_columnas']} a dos columnas) "
            f"· {r['tablas']} tablas · {r['rasters']} rasters + {r['figuras']} figuras")


def analizar_papers(carpeta: str, tema: str, salida: str, dry_run: bool = False) -> str:
    origen, destino = _resolver(carpeta), _resolver(salida)
    import paper_review as motor
    payload = motor.run(origen, destino, tema, dry_run=dry_run)
    n_err = sum(1 for p in payload["papers"] if p["errores"])
    return (f"OK: {len(payload['papers'])} papers ({n_err} con incidencias) · "
            f"costo est. ${payload['costo_usd_estimado']:.4f} · salidas en {destino}")


def publicar_obsidian(origen: str, vault: str = "", tema: str = "") -> str:
    o = _resolver(origen)
    vault = vault or os.environ.get("OBSIDIAN_VAULT", "")
    if not vault:
        return "ERROR: falta 'vault' (o la variable OBSIDIAN_VAULT)."
    v = _resolver(vault)
    import publicar as motor
    markdown, datos, carpeta = motor.leer_revision(o)
    r = motor.publicar_obsidian(markdown, datos, carpeta, vault=v, tema=tema)
    return (f"OK: nota en {r['nota']} · {len(r['adjuntos'])} adjuntos"
            f"{' · índice actualizado' if r['indice_actualizado'] else ''}")


def publicar_notion(origen: str, database: str = "", tema: str = "") -> str:
    o = _resolver(origen)
    database = database or os.environ.get("NOTION_DATABASE_ID", "")
    token = os.environ.get("NOTION_TOKEN", "")
    if not database:
        return "ERROR: falta 'database' (o la variable NOTION_DATABASE_ID)."
    if not token:
        return "ERROR: falta NOTION_TOKEN en el entorno."
    import publicar as motor
    markdown, datos, _ = motor.leer_revision(o)
    r = motor.publicar_notion(markdown, datos, database=database, token=token, tema=tema)
    return f"OK: {r['url']} · {r['bloques']} bloques · propiedades: {r['propiedades']}"


def estado() -> str:
    """Qué ve este servidor: carpetas permitidas y credenciales presentes."""
    permitidas = raices()
    return json.dumps({
        "carpetas_permitidas": [str(r) for r in permitidas] or
                               "(ninguna: define HARNESS_FILE_ROOTS)",
        "obsidian_vault": os.environ.get("OBSIDIAN_VAULT") or "(sin definir)",
        "notion_database": os.environ.get("NOTION_DATABASE_ID") or "(sin definir)",
        "notion_token": "presente" if os.environ.get("NOTION_TOKEN") else "(sin definir)",
        "anthropic_key": "presente" if os.environ.get("ANTHROPIC_API_KEY") else "(sin definir)",
    }, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Servidor
# ---------------------------------------------------------------------------
def blindado(fn):
    """Convierte la excepción en un mensaje que el modelo pueda leer y corregir.

    El SDK envuelve cualquier excepción de una tool en un `UnexpectedToolError` genérico
    ("Error executing tool X") y descarta el texto: el modelo recibe "falló" sin saber que
    la ruta estaba fuera de las carpetas permitidas ni cuáles son. Devolviendo el texto
    conserva la única parte útil del fallo.
    """
    @functools.wraps(fn)
    def envuelta(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except PermissionError as e:
            return f"ERROR de permisos: {e}"
        except FileNotFoundError as e:
            return f"ERROR: no existe: {e}"
        except ImportError as e:
            return (f"ERROR: falta una dependencia ({e}). Instálala en el entorno desde "
                    f"el que corre este servidor: pip install -r requirements.txt")
        except Exception as e:                      # noqa: BLE001 - el modelo necesita el texto
            return f"ERROR {type(e).__name__}: {e}"
    return envuelta


def construir_servidor():
    """Registra las tools. El import de `mcp` es perezoso: el resto del módulo —incluida
    la contención de rutas, que es lo que se prueba— funciona sin el SDK instalado."""
    from mcp.server.mcpserver import MCPServer
    from mcp.types import ToolAnnotations

    mcp = MCPServer(
        name="harness_mcp",
        instructions="Herramientas del harness de Cristian: análisis de papers, "
                     "conversión de PDF a Markdown, publicación en Obsidian y Notion, y "
                     "acceso de solo lectura a las carpetas locales autorizadas.")

    solo_lectura = ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                                   idempotentHint=True, openWorldHint=False)
    escribe = ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                              idempotentHint=False, openWorldHint=False)
    externo = ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                              idempotentHint=False, openWorldHint=True)

    @mcp.tool(name="harness_estado", annotations=solo_lectura)
    @blindado
    def _estado() -> str:
        """Qué carpetas puede tocar este servidor y qué credenciales tiene a mano.

        Úsala primero si una tool falla por permisos o por falta de configuración."""
        return estado()

    @mcp.tool(name="harness_listar_carpeta", annotations=solo_lectura)
    @blindado
    def _listar(ruta: str, patron: str = "*") -> str:
        """Lista una carpeta local. `ruta` debe caer dentro de HARNESS_FILE_ROOTS.

        Args:
            ruta: carpeta a listar, p. ej. "C:/Users/Usuario/Documentos/papers".
            patron: glob opcional, p. ej. "*.pdf".
        """
        return listar_carpeta(ruta, patron)

    @mcp.tool(name="harness_buscar_archivos", annotations=solo_lectura)
    @blindado
    def _buscar(patron: str, subcarpeta: str = "") -> str:
        """Busca archivos por nombre bajo las carpetas permitidas, recursivamente.

        Args:
            patron: glob, p. ej. "*miastenia*.pdf".
            subcarpeta: acota la búsqueda a una carpeta concreta (opcional).
        """
        return buscar_archivos(patron, subcarpeta)

    @mcp.tool(name="harness_leer_archivo", annotations=solo_lectura)
    @blindado
    def _leer(ruta: str) -> str:
        """Lee un archivo de texto. Para PDF o .docx usa las tools de conversión."""
        return leer_archivo(ruta)

    @mcp.tool(name="harness_pdf_a_markdown", annotations=escribe)
    @blindado
    def _pdf(pdf: str, salida: str, dpi: int = 200) -> str:
        """Convierte un PDF a Markdown con sus figuras, respetando el orden de lectura
        a dos columnas.

        Args:
            pdf: ruta del PDF.
            salida: carpeta destino (se crea si no existe).
            dpi: resolución de las figuras rasterizadas.
        """
        return pdf_a_markdown(pdf, salida, dpi)

    @mcp.tool(name="harness_analizar_papers", annotations=externo)
    @blindado
    def _analizar(carpeta: str, tema: str, salida: str, dry_run: bool = False) -> str:
        """Analiza los papers de una carpeta: ficha cada uno, los contrasta con PubMed y
        escribe la lectura transversal en revision.md y revision.json.

        Llama a modelos y cuesta dinero. Con `dry_run` extrae y de-identifica sin llamar
        a ninguno, que es la forma de comprobar qué se redactó antes de mandar material
        clínico.
        """
        return analizar_papers(carpeta, tema, salida, dry_run)

    @mcp.tool(name="harness_publicar_obsidian", annotations=escribe)
    @blindado
    def _obsidian(origen: str, vault: str = "", tema: str = "") -> str:
        """Publica una revisión como nota en una bóveda de Obsidian."""
        return publicar_obsidian(origen, vault, tema)

    @mcp.tool(name="harness_publicar_notion", annotations=externo)
    @blindado
    def _notion(origen: str, database: str = "", tema: str = "") -> str:
        """Crea una página en una database de Notion desde una revisión.

        Deja una página en el workspace: confirma el destino antes de llamarla.
        """
        return publicar_notion(origen, database, tema)

    return mcp


def main() -> int:
    try:
        servidor = construir_servidor()
    except ImportError as e:
        print(f"ERROR: falta el SDK de MCP ({e}). Instálalo con: pip install mcp",
              file=sys.stderr)
        return 1
    if not raices():
        print("aviso: HARNESS_FILE_ROOTS sin definir; las tools de archivos se negarán "
              "a operar hasta que configures las carpetas permitidas.", file=sys.stderr)
    servidor.run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
