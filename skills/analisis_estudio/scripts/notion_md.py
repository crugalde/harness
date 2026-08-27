#!/usr/bin/env python3
"""notion_md.py — Markdown de la ficha -> bloques de la API REST de Notion.

La API REST **no acepta markdown**: quiere objetos `block`. Esta es la pieza que
permite que `publicar_notion.py` publique solo, sin que un modelo intermedie.

Cubre exactamente lo que emite una ficha de `analisis_estudio`, ni más ni menos:
encabezados 2-3, listas, párrafos, `<callout>`, citas, separadores, tablas de
pipes, bloques de código (mermaid incluido) y el formato inline
(**negrita**, *cursiva*, `código`, [enlace](url), ~~tachado~~).

Lo que la API impone y aquí se respeta:

  - Máximo **100 bloques** por petición: `trocear()` parte la lista.
  - Máximo **2000 caracteres** por objeto de texto: `_partir()` divide sin cortar
    palabras a la mitad.
  - Notion solo tiene **tres niveles** de encabezado; `####` y más profundos se
    degradan a `heading_3` en vez de perderse.

Solo biblioteca estándar. Importable (`a_bloques`) y ejecutable para inspección:

    python3 notion_md.py ficha.md | head -40
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

LIMITE_TEXTO = 2000      # máximo de caracteres por objeto rich_text
LIMITE_BLOQUES = 100     # máximo de bloques por petición

# Notion-flavored markdown escribe `orange_bg`; la API REST quiere
# `orange_background`. Traducir es obligatorio: un color inválido devuelve 400.
COLORES = {
    "default": "default", "gray": "gray", "brown": "brown", "orange": "orange",
    "yellow": "yellow", "green": "green", "blue": "blue", "purple": "purple",
    "pink": "pink", "red": "red",
}
COLORES.update({f"{c}_bg": f"{c}_background" for c in list(COLORES)})
COLORES.update({f"{c}_background": f"{c}_background" for c in list(COLORES) if not c.endswith("_bg")})

# Lenguajes que Notion reconoce y que aparecen en las fichas. Uno desconocido
# también devuelve 400, así que lo desconocido cae a "plain text".
LENGUAJES = {"mermaid", "python", "bash", "shell", "json", "yaml", "sql", "r",
             "javascript", "typescript", "markdown", "xml", "html", "plain text"}

_RE_CALLOUT = re.compile(r'<callout([^>]*)>', re.I)
_RE_ATRIB = re.compile(r'(\w[\w-]*)\s*=\s*"([^"]*)"')
_RE_SEPARADOR = re.compile(r'^\s*\|[\s:|-]+\|\s*$')


# --------------------------------------------------------------------------- inline

def _partir(texto: str, limite: int = LIMITE_TEXTO) -> list[str]:
    """Trocea en fragmentos <= limite sin cortar palabras cuando se puede."""
    if len(texto) <= limite:
        return [texto]
    trozos, resto = [], texto
    while len(resto) > limite:
        corte = resto.rfind(" ", 0, limite)
        if corte <= 0:
            corte = limite          # una "palabra" más larga que el límite: corte duro
        trozos.append(resto[:corte])
        resto = resto[corte:].lstrip()
    if resto:
        trozos.append(resto)
    return trozos


# Notion-flavored markdown escapa los caracteres reservados con `\\`. Al pasar a
# bloques hay que devolverlos a su forma literal, o el lector ve `\\~62%` y `\\[3\\]`.
_RE_ESCAPE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!|~>])")


def _fragmento(texto: str, anot: dict, enlace: str | None = None) -> list[dict]:
    """Un tramo de texto con sus anotaciones, troceado al límite de la API."""
    if not anot.get("code"):        # dentro de código el contenido es literal
        texto = _RE_ESCAPE.sub(r"\1", texto)
    salida = []
    for trozo in _partir(texto):
        if not trozo:
            continue
        item: dict = {"type": "text", "text": {"content": trozo}}
        if enlace:
            item["text"]["link"] = {"url": enlace}
        if anot:
            item["annotations"] = dict(anot)
        salida.append(item)
    return salida


# El orden importa: `código` primero, porque dentro de él no hay formato que
# interpretar; enlaces antes que negrita, porque el texto del enlace puede
# llevarla y queremos el enlace como unidad.
_INLINE = [
    ("code",   re.compile(r"`([^`\n]+)`")),
    ("link",   re.compile(r"\[([^\]]*)\]\(([^)\s]+)\)")),
    ("bold",   re.compile(r"\*\*([^*]+)\*\*")),
    ("strike", re.compile(r"~~([^~]+)~~")),
    ("italic", re.compile(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])")),
    ("italic_", re.compile(r"(?<![\w_])_([^_\n]+)_(?![\w_])")),
]


def _rich(texto: str, anot: dict | None = None) -> list[dict]:
    """Markdown inline -> array rich_text de Notion, recursivo por tipo de marca."""
    anot = anot or {}
    if not texto:
        return []

    # Gana la marca que **empieza antes**, y a igual inicio la primera de _INLINE.
    # Buscar por orden de lista en vez de por posición parte mal los tramos que se
    # anidan: en `*texto con `código` dentro*` la cursiva abre antes y debe envolver.
    candidatos = [(m.start(), idx, tipo, m)
                  for idx, (tipo, patron) in enumerate(_INLINE)
                  if (m := patron.search(texto))]
    if candidatos:
        _, _, tipo, m = min(candidatos, key=lambda c: (c[0], c[1]))
        antes, despues = texto[:m.start()], texto[m.end():]
        if tipo == "code":
            medio = _fragmento(m.group(1), {**anot, "code": True})
        elif tipo == "link":
            medio = _fragmento(m.group(1) or m.group(2), anot, enlace=m.group(2))
        else:
            clave = "italic" if tipo == "italic_" else tipo
            clave = {"bold": "bold", "strike": "strikethrough", "italic": "italic"}[clave]
            medio = _rich(m.group(1), {**anot, clave: True})
        return _rich(antes, anot) + medio + _rich(despues, anot)

    return _fragmento(texto, anot)


# --------------------------------------------------------------------------- bloques

def _bloque(tipo: str, texto: str, **extra) -> dict:
    cuerpo = {"rich_text": _rich(texto)}
    cuerpo.update(extra)
    return {"object": "block", "type": tipo, tipo: cuerpo}


def _celdas(fila: str) -> list[str]:
    fila = fila.strip()
    if fila.startswith("|"):
        fila = fila[1:]
    if fila.endswith("|"):
        fila = fila[:-1]
    return [c.strip() for c in re.split(r"(?<!\\)\|", fila)]


def _tabla(lineas: list[str], i: int) -> tuple[dict, int]:
    """Construye un bloque `table` desde una tabla de pipes. Devuelve (bloque, i)."""
    cabecera = _celdas(lineas[i])
    i += 2                                    # cabecera + separador
    filas = [cabecera]
    while i < len(lineas) and lineas[i].strip().startswith("|"):
        filas.append(_celdas(lineas[i]))
        i += 1

    ancho = max(len(f) for f in filas)
    hijos = []
    for fila in filas:
        fila = fila + [""] * (ancho - len(fila))          # Notion exige filas parejas
        hijos.append({"object": "block", "type": "table_row",
                      "table_row": {"cells": [_rich(c.replace("\\|", "|")) for c in fila]}})
    bloque = {"object": "block", "type": "table",
              "table": {"table_width": ancho, "has_column_header": True,
                        "has_row_header": False, "children": hijos}}
    return bloque, i


def _callout(lineas: list[str], i: int) -> tuple[dict, int]:
    """Construye un bloque `callout` desde <callout icon="⚠️" color="orange_bg">."""
    atrib = dict(_RE_ATRIB.findall(_RE_CALLOUT.match(lineas[i].strip()).group(1)))
    i += 1
    cuerpo: list[str] = []
    while i < len(lineas) and "</callout>" not in lineas[i]:
        cuerpo.append(lineas[i].strip().lstrip("\t"))
        i += 1
    i += 1                                               # cierre </callout>
    bloque = {"object": "block", "type": "callout", "callout": {
        "rich_text": _rich(" ".join(l for l in cuerpo if l)),
        "icon": {"type": "emoji", "emoji": atrib.get("icon", "💡")},
        "color": COLORES.get(atrib.get("color", "default"), "default")}}
    return bloque, i


def a_bloques(md: str) -> list[dict]:
    """Markdown de la ficha -> lista de bloques listos para la API REST."""
    lineas = md.replace("\r\n", "\n").split("\n")
    bloques: list[dict] = []
    i = 0
    while i < len(lineas):
        ln = lineas[i]
        crudo = ln.strip()

        if not crudo:
            i += 1
            continue

        # Bloque de código: se copia literal, sin interpretar formato.
        if crudo.startswith("```"):
            lang = crudo[3:].strip().lower() or "plain text"
            i += 1
            cuerpo = []
            while i < len(lineas) and not lineas[i].strip().startswith("```"):
                cuerpo.append(lineas[i])
                i += 1
            i += 1
            bloques.append({"object": "block", "type": "code", "code": {
                "rich_text": [{"type": "text", "text": {"content": t}}
                              for t in _partir("\n".join(cuerpo))],
                "language": lang if lang in LENGUAJES else "plain text"}})
            continue

        if _RE_CALLOUT.match(crudo):
            bloque, i = _callout(lineas, i)
            bloques.append(bloque)
            continue

        if crudo.startswith("|") and i + 1 < len(lineas) and _RE_SEPARADOR.match(lineas[i + 1]):
            bloque, i = _tabla(lineas, i)
            bloques.append(bloque)
            continue

        if re.match(r"^(---+|\*\*\*+|___+)$", crudo):
            bloques.append({"object": "block", "type": "divider", "divider": {}})
            i += 1
            continue

        m = re.match(r"^(#{1,6})\s+(.*)$", crudo)
        if m:
            # Notion solo tiene tres niveles; 4+ se degrada a heading_3.
            nivel = min(len(m.group(1)), 3)
            bloques.append(_bloque(f"heading_{nivel}", m.group(2)))
            i += 1
            continue

        m = re.match(r"^[-*+]\s+(.*)$", crudo)
        if m:
            bloques.append(_bloque("bulleted_list_item", m.group(1)))
            i += 1
            continue

        m = re.match(r"^\d+[.)]\s+(.*)$", crudo)
        if m:
            bloques.append(_bloque("numbered_list_item", m.group(1)))
            i += 1
            continue

        if crudo.startswith(">"):
            # Líneas `>` consecutivas son UNA cita, no una por línea.
            cuerpo = []
            while i < len(lineas) and lineas[i].strip().startswith(">"):
                cuerpo.append(lineas[i].strip()[1:].strip())
                i += 1
            bloques.append(_bloque("quote", " ".join(c for c in cuerpo if c)))
            continue

        bloques.append(_bloque("paragraph", crudo))
        i += 1

    return bloques


def trocear(bloques: list[dict], tam: int = LIMITE_BLOQUES) -> list[list[dict]]:
    """Parte en lotes de <= 100: el máximo que la API acepta por petición."""
    return [bloques[i:i + tam] for i in range(0, len(bloques), tam)] or [[]]


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    md = Path(sys.argv[1]).expanduser().read_text(encoding="utf-8")
    bloques = a_bloques(md)
    print(json.dumps(bloques, ensure_ascii=False, indent=2))
    print(f"{len(bloques)} bloques · {len(trocear(bloques))} peticiones", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
