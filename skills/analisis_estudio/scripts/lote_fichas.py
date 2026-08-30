#!/usr/bin/env python3
"""lote_fichas.py — Fase A: inventaría una carpeta de PDFs y deja el trabajo listo.

El análisis crítico no se puede batchear sin perder lo que lo hace valioso: leer
cuarenta papers de corrido degrada el juicio y, peor, obliga a inferir patología y
aspecto en vez de preguntarlos. Lo que **sí** se batchea es todo lo determinista
que hay alrededor, que es justo la parte tediosa.

Esta fase recorre la carpeta y, por cada PDF, responde: qué estudio es, si ya está
en Notion, y qué le falta para poder analizarse. El resultado es una lista de
trabajo priorizada — y un `metadatos.json` por paper, verificado, listo para que
la fase B (un paper por invocación) no tenga que buscar nada.

Qué hace por cada PDF:

  1. **Saca el DOI del propio archivo**: metadatos XMP, diccionario Info y, si hace
     falta, los streams de texto inflados con zlib. Sin dependencias.
     Si no aparece, busca un sidecar `<pdf>.doi` y, como último recurso, calza el
     nombre del archivo contra «Actualización de estudio» — donde el DOI ya está.
  2. **Verifica** contra Crossref y PubMed, y escribe `<pdf>.metadatos.json`.
  3. **Deduplica** contra «Resumen de estudios»: si ya hay ficha, lo dice y no
     vuelve a proponerlo.
  4. **Marca los bloqueos**: sin DOI, sin verificar, o patología por asignar.

Salidas, junto a los PDFs:

  - `<pdf>.metadatos.json` — uno por paper, el insumo de la fase B.
  - `LOTE.md` — la lista de trabajo, legible, priorizada.
  - `manifiesto.json` — lo mismo en máquina, para reanudar.

Uso:
    python3 lote_fichas.py "C:/Users/Usuario/iCloudDrive/neuromuscular"
    python3 lote_fichas.py <carpeta> --rehacer        # reprocesa lo ya hecho
    python3 lote_fichas.py <carpeta> --sin-notion     # sin token: omite el dedup

Es reanudable: lo que ya tiene `metadatos.json` verificado se salta, salvo
`--rehacer`. Correrlo dos veces sobre la misma carpeta no repite trabajo ni red.

Solo biblioteca estándar.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import zlib
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
sys.path.insert(0, str(AQUI.parents[2] / "tools"))

import publicar_notion as PN          # noqa: E402
import verificar_metadatos as VM      # noqa: E402

# Un DOI empieza siempre por 10. y una barra. El final se recorta de los signos de
# puntuación que arrastra el PDF (paréntesis de cierre, punto final, comillas).
RE_DOI = re.compile(r"\b(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)")
RE_XMP = re.compile(rb"<x:xmpmeta.*?</x:xmpmeta>", re.S)
RE_DOI_XMP = re.compile(rb"<prism:doi>([^<]+)</prism:doi>|"
                        rb"<dc:identifier[^>]*>([^<]+)</dc:identifier>", re.I)
BASURA_FINAL = ").,;:'\"]}>"

# NCBI limita a 3 peticiones/s sin API key y a 10 con ella.
PAUSA = 0.34 if not os.environ.get("NCBI_API_KEY") else 0.11


def limpiar_doi(bruto: str) -> str:
    doi = bruto.strip().replace("doi:", "").replace("DOI:", "").strip()
    doi = doi.split()[0] if doi.split() else doi
    for prefijo in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/"):
        if doi.startswith(prefijo):
            doi = doi[len(prefijo):]
    while doi and doi[-1] in BASURA_FINAL:
        doi = doi[:-1]
    return doi


def doi_de_pdf(ruta: Path) -> tuple[str | None, str]:
    """Devuelve (doi, de_dónde_salió). Best-effort, sin dependencias.

    El orden va de más fiable a menos: XMP lo escribe el editor y es texto plano;
    los streams de contenido llevan el DOI partido por los operadores de posición
    del PDF, así que ahí acierta menos.
    """
    try:
        datos = ruta.read_bytes()
    except OSError as e:
        return None, f"ilegible ({e})"

    for bloque in RE_XMP.findall(datos):
        m = RE_DOI_XMP.search(bloque)
        if m:
            crudo = (m.group(1) or m.group(2) or b"").decode("utf-8", "replace")
            doi = limpiar_doi(crudo)
            if doi.startswith("10."):
                return doi, "XMP"
        m = RE_DOI.search(bloque.decode("latin-1", "replace"))
        if m:
            return limpiar_doi(m.group(1)), "XMP"

    # Diccionario Info: /Subject y /Keywords suelen traerlo en papers de editorial.
    cabeza = datos[:400_000].decode("latin-1", "replace")
    for campo in ("/Subject", "/Keywords", "/Title"):
        i = cabeza.find(campo)
        if i != -1:
            m = RE_DOI.search(cabeza[i:i + 2000])
            if m:
                return limpiar_doi(m.group(1)), "Info"

    # Streams de contenido: solo las primeras páginas, que es donde va el DOI.
    vistos = 0
    for m in re.finditer(rb"stream\r?\n", datos):
        if vistos >= 25:
            break
        fin = datos.find(b"endstream", m.end())
        if fin == -1:
            continue
        try:
            texto = zlib.decompress(datos[m.end():fin]).decode("latin-1", "replace")
        except zlib.error:
            continue
        vistos += 1
        hallazgo = RE_DOI.search(texto)
        if hallazgo:
            return limpiar_doi(hallazgo.group(1)), "stream"

    return None, "no encontrado"


def doi_de_sidecar(pdf: Path) -> str | None:
    """Un `<pdf>.doi` con el DOI dentro. La salida manual cuando el PDF no lo trae."""
    for cand in (pdf.with_suffix(".doi"), pdf.with_suffix(pdf.suffix + ".doi")):
        if cand.is_file():
            doi = limpiar_doi(cand.read_text(encoding="utf-8", errors="replace"))
            if doi.startswith("10."):
                return doi
    return None


def doi_de_actualizacion(token: str, nombre: str) -> str | None:
    """Calza el nombre del archivo contra «Actualización de estudio».

    Esa base ya guarda el DOI y el `Nombre esperado archivo` de cada paper marcado
    para descarga, así que para lo que salió de la vigilancia semanal el dato ya
    está y no hay que sacarlo del PDF.
    """
    tallo = Path(nombre).stem
    try:
        res = PN._peticion("POST", f"/databases/{PN.DB_ACTUALIZACION}/query", token, {
            "filter": {"property": "Nombre esperado archivo",
                       "rich_text": {"contains": tallo[:60]}},
            "page_size": 1})
    except PN.ErrorPublicacion:
        return None
    filas = res.get("results", [])
    if not filas:
        return None
    prop = filas[0].get("properties", {}).get("DOI", {})
    return limpiar_doi(prop.get("url") or "") or None


def ya_en_notion(token: str, doi: str, pmid: str | None) -> str | None:
    """URL de la ficha si este paper ya está publicado. None si no está."""
    meta = {"doi": doi} if doi else {"pmid": pmid}
    try:
        res = PN._peticion("POST", f"/databases/{PN.DB_RESUMEN}/query", token, {
            "filter": {"property": "Paper", "url": {"equals": PN.url_paper(meta)}},
            "page_size": 1})
    except PN.ErrorPublicacion:
        return None
    filas = res.get("results", [])
    return filas[0].get("url") if filas else None


def _desde_meta(meta: dict) -> dict:
    """Campos del informe que salen del metadatos.json, vengan de la red o del disco.

    `falta` importa más de lo que parece: si se omite al reanudar, la tabla dice
    «Falta: —» sobre un paper al que todavía le faltan patología y aspecto, y el
    publicador lo va a rechazar. Un informe que miente es peor que no tenerlo.
    """
    return {
        "titulo": meta.get("titulo", ""),
        "doi": meta.get("doi"),
        "anio": meta.get("anio"),
        "revista": meta.get("revista"),
        "tipo_estudio": meta.get("tipo_estudio"),
        "guia": meta.get("guia_reporte"),
        "discrepancias": meta.get("verificacion", {}).get("discrepancias", []),
        "falta": [c for c in ("patologia", "aspecto", "calidad", "aporte")
                  if not meta.get(c)],
    }


def procesar(pdf: Path, token: str | None, correo: str, *, rehacer: bool) -> dict:
    """Un PDF -> su entrada del manifiesto, con metadatos.json escrito si se pudo."""
    destino_meta = pdf.with_suffix(".metadatos.json")
    ficha_md = pdf.with_suffix(".md")
    entrada = {
        "pdf": pdf.name,
        "ruta": str(pdf),
        "archivo_local": pdf.resolve().as_uri(),
        "metadatos": destino_meta.name,
        "ficha_md": ficha_md.name,
    }

    if destino_meta.is_file() and not rehacer:
        meta = json.loads(destino_meta.read_text(encoding="utf-8"))
        if meta.get("verificacion", {}).get("verificado"):
            entrada.update(_desde_meta(meta), estado="ya_verificado", origen_doi="cache")
            if ficha_md.is_file():
                entrada["estado"] = "ficha_escrita"
            return entrada

    doi = doi_de_sidecar(pdf)
    origen = "sidecar" if doi else ""
    if not doi:
        doi, origen = doi_de_pdf(pdf)
    if not doi and token:
        doi = doi_de_actualizacion(token, pdf.name)
        origen = "actualizacion" if doi else origen
    entrada["origen_doi"] = origen

    if not doi:
        entrada.update(estado="sin_doi", titulo="",
                       nota=f"crea {pdf.stem}.doi con el DOI dentro, o añádelo a "
                            "«Actualización de estudio»")
        return entrada
    entrada["doi"] = doi

    if token:
        url = ya_en_notion(token, doi, None)
        if url:
            entrada.update(estado="ya_publicado", url_notion=url, titulo="")
            return entrada

    time.sleep(PAUSA)
    doi_r, pmid = VM.resolver_ids(doi, None, correo)
    time.sleep(PAUSA)
    cr = VM.de_crossref(doi_r or doi, correo)
    pm = VM.de_pubmed(pmid, correo) if pmid else {}
    if not cr and not pm:
        # El DOI va en el aviso: casi siempre está mal extraído del PDF (un sufijo
        # de más, una ligadura), y verlo es lo que permite corregirlo en el sidecar.
        entrada.update(estado="no_verificado", titulo="",
                       nota=f"`{doi}` (de {origen}) no resolvió en Crossref ni PubMed. "
                            f"Si el DOI está mal extraído, corrígelo en {pdf.stem}.doi; "
                            "si está bien, puede ser un corte de red.")
        return entrada

    prefiere, respaldo = (pm or cr), (cr if pm else {})
    meta: dict = {}
    for campo in ("titulo", "anio", "revista", "autor"):
        if prefiere.get(campo) or respaldo.get(campo):
            meta[campo] = prefiere.get(campo) or respaldo.get(campo)
    meta["doi"] = doi_r or doi
    if pmid:
        meta["pmid"] = str(pmid)
    meta["archivo_local"] = entrada["archivo_local"]

    tipo = VM.tipo_desde_pubmed(pm.get("pubtypes", []))
    if tipo:
        meta["tipo_estudio"] = tipo
        meta["guia_reporte"] = VM.GUIAS.get(tipo, "—")
    discrepancias = VM.comparar(cr, pm)
    meta["verificacion"] = {
        "verificado": True,
        "fuente": "+".join(f for f, d in (("crossref", cr), ("pubmed", pm)) if d),
        "fecha": __import__("datetime").date.today().isoformat(),
        "discrepancias": discrepancias,
        "pubtypes": pm.get("pubtypes", []),
        "tipo_crossref": cr.get("tipo_crossref", ""),
    }
    destino_meta.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")

    entrada.update(_desde_meta(meta), estado="listo")
    return entrada


# --------------------------------------------------------------------- informe

ORDEN = {"listo": 0, "ya_verificado": 1, "sin_doi": 2, "no_verificado": 3,
         "ficha_escrita": 4, "ya_publicado": 5}
ETIQUETA = {
    "listo": "Listo para analizar",
    "ya_verificado": "Verificado antes, sin ficha",
    "sin_doi": "Sin DOI — necesita tu mano",
    "no_verificado": "DOI no resuelto — revísalo",
    "ficha_escrita": "Ficha escrita, sin publicar",
    "ya_publicado": "Ya está en Notion",
}


def escribir_lote(carpeta: Path, entradas: list[dict]) -> Path:
    """La lista de trabajo legible. Es lo que de verdad se lee tras correr la fase A."""
    grupos: dict[str, list[dict]] = {}
    for e in entradas:
        grupos.setdefault(e["estado"], []).append(e)

    lineas = [f"# Lote — {carpeta.name}", "",
              f"{len(entradas)} PDF revisados · "
              + " · ".join(f"{len(v)} {ETIQUETA[k].lower()}"
                           for k, v in sorted(grupos.items(), key=lambda x: ORDEN[x[0]])),
              ""]

    for estado in sorted(grupos, key=lambda k: ORDEN[k]):
        items = grupos[estado]
        lineas += [f"## {ETIQUETA[estado]} ({len(items)})", ""]

        if estado in ("listo", "ya_verificado"):
            lineas += ["| # | Estudio | Año | Tipo | Guía | Falta |",
                       "|---|---|---|---|---|---|"]
            for i, e in enumerate(sorted(items, key=lambda x: -(x.get("anio") or 0)), 1):
                falta = ", ".join(e.get("falta") or []) or "—"
                titulo = (e.get("titulo") or e["pdf"])[:70]
                lineas.append(f"| {i} | {titulo} | {e.get('anio') or '?'} | "
                              f"{e.get('tipo_estudio') or '?'} | {e.get('guia') or '?'} | "
                              f"{falta} |")
            lineas.append("")
            for e in items:
                if e.get("discrepancias"):
                    lineas.append(f"- ⚠ **{e['pdf']}** — "
                                  + " · ".join(e["discrepancias"]))
            lineas.append("")
        elif estado == "ya_publicado":
            for e in items:
                lineas.append(f"- {e['pdf']} → [ficha]({e.get('url_notion', '')})")
            lineas.append("")
        else:
            for e in items:
                lineas.append(f"- **{e['pdf']}** — {e.get('nota', '')}")
            lineas.append("")

    listos = grupos.get("listo", []) + grupos.get("ya_verificado", [])
    if listos:
        lineas += ["---", "",
                   "## Cómo seguir (fase B, un paper por vez)", "",
                   "Cada uno tiene ya su `metadatos.json` verificado al lado del PDF. "
                   "Por cada estudio: lee el texto completo, escribe la ficha en el `.md` "
                   "que aparece abajo y publícala.", "",
                   "```bash"]
        for e in listos[:5]:
            lineas.append(f'python3 publicar_notion.py "{e["ficha_md"]}" '
                          f'--metadatos "{e["metadatos"]}"')
        if len(listos) > 5:
            lineas.append(f"# … y {len(listos) - 5} más (ver manifiesto.json)")
        lineas += ["```", "",
                   "**Antes de publicar hay que completar `patologia` y `aspecto`** en cada "
                   "`metadatos.json`: no salen de ninguna base y el publicador se detiene "
                   "sin ellos. Es deliberado — inferirlos fragmenta los filtros de la base."]

    destino = carpeta / "LOTE.md"
    destino.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    return destino


def main() -> int:
    ap = argparse.ArgumentParser(description="Fase A: inventaría una carpeta de PDFs.")
    ap.add_argument("carpeta")
    ap.add_argument("--rehacer", action="store_true",
                    help="reprocesa los PDF que ya tienen metadatos.json")
    ap.add_argument("--sin-notion", action="store_true",
                    help="no consulta Notion (omite el dedup y el rescate de DOI)")
    ap.add_argument("--limite", type=int, help="procesa solo los primeros N PDF")
    a = ap.parse_args()

    carpeta = Path(a.carpeta).expanduser()
    if not carpeta.is_dir():
        print(f"ERROR: no es una carpeta: {carpeta}", file=sys.stderr)
        return 1

    correo = os.environ.get("ENTREZ_EMAIL", "")
    if not correo:
        print("[aviso] sin ENTREZ_EMAIL: NCBI limitará las peticiones.", file=sys.stderr)
    token = None if a.sin_notion else PN.token_notion()
    if not token and not a.sin_notion:
        print("[aviso] sin NOTION_TOKEN: no puedo deduplicar contra la base. "
              "Puede que propongas analizar algo que ya está publicado.", file=sys.stderr)

    pdfs = sorted(p for p in carpeta.glob("*.pdf") if p.is_file())
    if a.limite:
        pdfs = pdfs[:a.limite]
    if not pdfs:
        print(f"No hay PDF en {carpeta}", file=sys.stderr)
        return 1

    entradas = []
    for i, pdf in enumerate(pdfs, 1):
        print(f"[{i}/{len(pdfs)}] {pdf.name}", file=sys.stderr)
        try:
            entradas.append(procesar(pdf, token, correo, rehacer=a.rehacer))
        except Exception as e:                      # un PDF roto no tumba el lote
            entradas.append({"pdf": pdf.name, "ruta": str(pdf), "estado": "no_verificado",
                             "titulo": "", "nota": f"error inesperado: {e}"})

    manifiesto = carpeta / "manifiesto.json"
    manifiesto.write_text(json.dumps(
        {"carpeta": str(carpeta), "generado": __import__("datetime").date.today().isoformat(),
         "entradas": entradas}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lote = escribir_lote(carpeta, entradas)

    resumen: dict[str, int] = {}
    for e in entradas:
        resumen[e["estado"]] = resumen.get(e["estado"], 0) + 1
    print(f"\n{lote}")
    for estado in sorted(resumen, key=lambda k: ORDEN[k]):
        print(f"  {ETIQUETA[estado]}: {resumen[estado]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
