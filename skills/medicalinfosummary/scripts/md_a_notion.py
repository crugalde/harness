#!/usr/bin/env python3
"""Convierte el informe .md a Notion-flavored Markdown para publicar por API.

El markdown que se **pega** en Notion y el que acepta la **API** no son el mismo
formato, y la diferencia es silenciosa: la API acepta el texto sin error pero lo
renderiza mal. Las tres divergencias que importan en estos informes:

  1. Tablas: la API no entiende tablas de pipes; usa XML <table>/<tr>/<td>.
  2. Mermaid: los saltos de línea en las etiquetas son <br>, no \\n.
  3. Citas [n]: los corchetes son sintaxis reservada y hay que escaparlos, o
     Notion intenta interpretarlos como enlace o referencia.

Uso:
    python3 md_a_notion.py <informe.md> [-o <salida.md>] [--titulo]

    --titulo   imprime solo el título (H1) y no convierte; sirve para pasarlo
               a properties.title, ya que el cuerpo NO debe repetirlo.

Salida por stdout si no se da -o. Solo biblioteca estándar.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Caracteres reservados en Notion-flavored Markdown que hay que escapar en prosa.
# Excluimos deliberadamente * ` ~ porque los usamos como formato intencional.
ESCAPAR = r"[\]{}|^<>"


def extraer_titulo(texto: str) -> str:
    m = re.search(r"^#\s+(.+)$", texto, re.M)
    return m.group(1).strip() if m else ""


def _celdas(fila: str) -> list[str]:
    """Divide una fila de tabla por | respetando el pipe escapado \\|."""
    fila = fila.strip()
    if fila.startswith("|"):
        fila = fila[1:]
    if fila.endswith("|"):
        fila = fila[:-1]
    return [c.strip() for c in re.split(r"(?<!\\)\|", fila)]


def _es_separador(linea: str) -> bool:
    return bool(re.match(r"^\s*\|[\s:|-]+\|\s*$", linea))


def convertir_tablas(texto: str) -> str:
    """Tabla de pipes -> XML <table>. Notion no renderiza pipes vía API."""
    salida: list[str] = []
    lineas = texto.split("\n")
    i = 0
    while i < len(lineas):
        ln = lineas[i]
        hay_tabla = (ln.strip().startswith("|") and i + 1 < len(lineas)
                     and _es_separador(lineas[i + 1]))
        if not hay_tabla:
            salida.append(ln)
            i += 1
            continue

        cabecera = _celdas(ln)
        i += 2  # saltamos cabecera y separador
        filas = []
        while i < len(lineas) and lineas[i].strip().startswith("|"):
            filas.append(_celdas(lineas[i]))
            i += 1

        salida.append('<table fit-page-width="true" header-row="true">')
        for fila in [cabecera] + filas:
            salida.append("\t<tr>")
            for c in fila:
                # Las celdas solo admiten rich text; los | internos ya vienen escapados.
                salida.append(f"\t\t<td>{c.replace(chr(92) + '|', '|')}</td>")
            salida.append("\t</tr>")
        salida.append("</table>")
    return "\n".join(salida)


def convertir_mermaid(texto: str) -> str:
    """En Mermaid, Notion quiere <br> dentro de las etiquetas, no \\n."""
    def _fix(m: re.Match) -> str:
        return "```mermaid\n" + m.group(1).replace("\\n", "<br>") + "```"
    return re.sub(r"```mermaid\n(.*?)```", _fix, texto, flags=re.S)


def escapar_prosa(texto: str) -> str:
    """Escapa corchetes de las citas [n] sin tocar enlaces ni bloques de código.

    Dentro de bloques de código el escapado está prohibido por el spec: el
    contenido es literal. Por eso los aislamos antes de tocar nada.
    """
    bloques: list[str] = []

    def _guardar(m: re.Match) -> str:
        bloques.append(m.group(0))
        return f"\x00BLOQUE{len(bloques) - 1}\x00"

    # Aislamos código, tablas XML e imágenes/enlaces antes de escapar.
    texto = re.sub(r"```.*?```", _guardar, texto, flags=re.S)
    texto = re.sub(r"<table.*?</table>", _guardar, texto, flags=re.S)
    texto = re.sub(r"!?\[[^\]]*\]\([^)]*\)", _guardar, texto)
    texto = re.sub(r"`[^`\n]+`", _guardar, texto)

    # Ahora sí: los [n] que quedan son citas, y hay que escaparlos.
    texto = re.sub(r"\[(\d+(?:\s*,\s*\d+)*)\]", r"\\[\1\\]", texto)

    for i, b in enumerate(bloques):
        texto = texto.replace(f"\x00BLOQUE{i}\x00", b)
    return texto


def unir_citas(texto: str) -> str:
    """Fusiona líneas `>` consecutivas en un solo bloque con <br>.

    En Notion, cada línea que empieza con `>` es un blockquote **independiente**.
    Un encabezado de cuatro líneas se rompe en cuatro cajas separadas, que es
    justo lo contrario del efecto buscado.
    """
    salida: list[str] = []
    buffer: list[str] = []

    def _volcar() -> None:
        if buffer:
            salida.append("> " + "<br>".join(buffer))
            buffer.clear()

    for ln in texto.split("\n"):
        if ln.startswith(">"):
            contenido = ln[1:].strip()
            if contenido:                     # un `>` solo produce una cita vacía
                buffer.append(contenido)
        else:
            _volcar()
            salida.append(ln)
    _volcar()
    return "\n".join(salida)


def quitar_titulo(texto: str) -> str:
    """El H1 va en properties.title; repetirlo en el cuerpo lo duplica."""
    return re.sub(r"^#\s+.+\n+", "", texto, count=1)


def convertir(texto: str) -> str:
    texto = quitar_titulo(texto)
    texto = convertir_mermaid(texto)
    texto = unir_citas(texto)
    # El escapado va ANTES de armar las tablas: si no, las citas [n] que están
    # dentro de celdas quedan sin escapar, porque el aislador salta los <table>.
    texto = escapar_prosa(texto)
    texto = convertir_tablas(texto)
    # Los encabezados 5-6 se degradan a 4 en Notion; los bajamos a 4 explícitamente.
    texto = re.sub(r"^#{5,}\s", "#### ", texto, flags=re.M)
    return texto.strip() + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="Markdown estándar -> Notion-flavored.")
    ap.add_argument("informe")
    ap.add_argument("-o", "--out", help="Archivo de salida (por defecto stdout)")
    ap.add_argument("--titulo", action="store_true",
                    help="Imprime solo el título H1 y termina")
    a = ap.parse_args()

    texto = Path(a.informe).expanduser().read_text(encoding="utf-8")

    if a.titulo:
        print(extraer_titulo(texto))
        return 0

    salida = convertir(texto)
    if a.out:
        Path(a.out).expanduser().write_text(salida, encoding="utf-8")
        n_tab = salida.count("<table")
        print(f"{a.out}: {len(salida)} chars · {n_tab} tablas XML · "
              f"{salida.count('```mermaid')} mermaid", file=sys.stderr)
    else:
        sys.stdout.write(salida)
    return 0


if __name__ == "__main__":
    sys.exit(main())
