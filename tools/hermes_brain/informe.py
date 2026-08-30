"""Informe local del lote: qué se procesó, qué quedó dudoso y qué falló.

Este informe **sí** lleva rutas y nombres: se queda en el PC. Lo que viaja al VPS son
contadores (ver `cliente_n8n.registro_anonimo`).
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .cola import Cola

ETIQUETAS = {
    "cientifico": "PDF de revista científica",
    "no_cientifico": "PDF no científico",
    "clinico": "Word de resumen clínico",
    "no_clinico": "Word no clínico",
    "dudoso": "dudoso (requiere revisión)",
    "no_soportado": "formato no soportado",
    "error": "error de lectura",
    "desconocido": "sin clasificar",
}


def _tabla(pares: dict[str, int], titulo_col: str) -> list[str]:
    filas = [f"| {titulo_col} | n |", "| --- | ---: |"]
    for clave, valor in sorted(pares.items(), key=lambda kv: -kv[1]):
        filas.append(f"| {ETIQUETAS.get(clave, clave)} | {valor} |")
    return filas


def generar(cola: Cola, lote: str | None = None, destino: Path | None = None) -> str:
    """Construye el informe en Markdown y, si se indica `destino`, lo escribe."""
    resumen = cola.resumen(lote)
    clases = cola.resumen_clasificacion(lote)
    dudosos = cola.por_estado("dudoso", lote)
    errores = cola.por_estado("error", lote)
    hechos = cola.por_estado("hecho", lote)

    lineas = [
        f"# Informe del lote `{lote or 'todos'}`",
        "",
        f"Generado: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "## Estado",
        "",
        *_tabla({k: v for k, v in resumen.items() if k != "total" and v}, "Estado"),
        f"| **total** | **{resumen['total']}** |",
        "",
        "## Clasificación",
        "",
        *_tabla(clases, "Clasificación"),
        "",
    ]

    if dudosos:
        lineas += [
            f"## Dudosos ({len(dudosos)}) — resolver con `python hermes_brain.py revisar`",
            "",
            "Cada uno quedó en la zona gris del clasificador. La columna *motivo* dice por qué.",
            "",
            "| # | archivo | motivo |",
            "| ---: | --- | --- |",
        ]
        for i, a in enumerate(dudosos, 1):
            lineas.append(f"| {i} | `{a.ruta}` | {a.motivo} |")
        lineas.append("")

    if errores:
        lineas += [f"## Errores ({len(errores)})", "", "| archivo | intentos | error |",
                   "| --- | ---: | --- |"]
        for a in errores:
            lineas.append(f"| `{a.ruta}` | {a.intentos} | {a.error[:160]} |")
        lineas += ["", "Reintentar con: `python hermes_brain.py reintentar`", ""]

    if hechos:
        con_notion = sum(1 for a in hechos if a.notion_url)
        lineas += [
            f"## Procesados ({len(hechos)})", "",
            f"- `.md` generados: {sum(1 for a in hechos if a.salida_md)}",
            f"- publicados en Notion: {con_notion}",
            "",
        ]
    texto = "\n".join(lineas)
    if destino:
        destino = Path(destino)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(texto, encoding="utf-8")
    return texto
