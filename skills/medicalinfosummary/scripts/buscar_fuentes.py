#!/usr/bin/env python3
"""Cosechador de fuentes para la skill `medicalinfosummary`.

Ejecuta una búsqueda PubMed por estratos (guías -> revisiones sistemáticas ->
revisiones -> ECAs -> originales), filtra a >= 2000, enriquece cada registro con
metadatos de Entrez y resuelve acceso abierto vía Unpaywall/PMC.

Solo biblioteca estándar: urllib + json + xml.etree. No requiere pip install.

Uso:
    python3 buscar_fuentes.py "myasthenia gravis" \\
        --enfoque "tratamiento en crisis miasténica" \\
        --n 35 --out ./fuentes

Salidas en --out:
    fuentes.json          registros estructurados
    bibliografia.md       lista numerada estilo Vancouver
    resumen_busqueda.md   queries ejecutadas, conteos y cobertura

Variables de entorno opcionales:
    ENTREZ_EMAIL     correo para NCBI (obligatorio por sus TOS; hay fallback)
    NCBI_API_KEY     sube el rate limit de 3 a 10 req/s
    UNPAYWALL_EMAIL  correo para Unpaywall (usa ENTREZ_EMAIL si falta)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
UNPAYWALL = "https://api.unpaywall.org/v2"
USER_AGENT = "medicalinfosummary/1.0 (harness; contacto vía ENTREZ_EMAIL)"

EMAIL = os.environ.get("ENTREZ_EMAIL") or os.environ.get("UNPAYWALL_EMAIL") or ""
API_KEY = os.environ.get("NCBI_API_KEY", "")
# NCBI permite 3 req/s sin clave y 10 con clave. Dejamos margen.
DELAY = 0.11 if API_KEY else 0.36

# Estratos de búsqueda, en orden de prioridad de evidencia. El peso guía cuántos
# resultados pedir de cada uno cuando el usuario fija un total.
ESTRATOS = [
    ("guias", 'guideline[pt] OR practice guideline[pt] OR consensus development conference[pt]', 0.20),
    ("revisiones_sistematicas", 'systematic review[pt] OR meta-analysis[pt]', 0.22),
    ("revisiones", 'review[pt] AND (jsubsetaim[text] OR hasabstract)', 0.20),
    ("ensayos", 'randomized controlled trial[pt] OR controlled clinical trial[pt]', 0.18),
    ("originales", 'hasabstract', 0.20),
]

RANGO_FECHA = '("2000"[dp] : "3000"[dp])'


# --------------------------------------------------------------------------- red


def _get(url: str, params: dict, *, parse: str, intentos: int = 3):
    """GET con reintentos y backoff. `parse` es 'json' o 'xml'."""
    qs = urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")})
    full = f"{url}?{qs}" if qs else url
    req = urllib.request.Request(full, headers={"User-Agent": USER_AGENT})
    for intento in range(intentos):
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                raw = resp.read()
            return json.loads(raw) if parse == "json" else ET.fromstring(raw)
        except (urllib.error.HTTPError, urllib.error.URLError, ET.ParseError,
                json.JSONDecodeError, TimeoutError) as exc:
            if isinstance(exc, urllib.error.HTTPError) and exc.code == 404:
                return None  # recurso ausente: no es un fallo transitorio
            if intento == intentos - 1:
                print(f"  ! fallo tras {intentos} intentos: {exc}", file=sys.stderr)
                return None
            time.sleep(1.5 * (intento + 1))
    return None


def _ncbi(params: dict) -> dict:
    base = {"email": EMAIL, "tool": "medicalinfosummary"}
    if API_KEY:
        base["api_key"] = API_KEY
    base.update(params)
    return base


def esearch(term: str, retmax: int) -> list[str]:
    time.sleep(DELAY)
    data = _get(f"{EUTILS}/esearch.fcgi", _ncbi({
        "db": "pubmed", "term": term, "retmax": retmax,
        "retmode": "json", "sort": "relevance",
    }), parse="json")
    if not data:
        return []
    return data.get("esearchresult", {}).get("idlist", [])


# ----------------------------------------------------------------- parseo Entrez


def _texto(nodo) -> str:
    """innerText de un nodo, aplanando <i>, <sup>, etc. de los títulos MEDLINE."""
    return "".join(nodo.itertext()).strip() if nodo is not None else ""


def _fecha(art) -> str:
    for ruta in ("MedlineCitation/Article/Journal/JournalIssue/PubDate/Year",
                 "MedlineCitation/Article/ArticleDate/Year",
                 "MedlineCitation/DateCompleted/Year"):
        nodo = art.find(ruta)
        if nodo is not None and nodo.text:
            return nodo.text
    medline = art.find("MedlineCitation/Article/Journal/JournalIssue/PubDate/MedlineDate")
    if medline is not None and medline.text:
        return medline.text[:4]
    return ""


def _autores(art) -> list[str]:
    out = []
    for a in art.findall("MedlineCitation/Article/AuthorList/Author"):
        apellido = _texto(a.find("LastName"))
        iniciales = _texto(a.find("Initials"))
        colectivo = _texto(a.find("CollectiveName"))
        if apellido:
            out.append(f"{apellido} {iniciales}".strip())
        elif colectivo:
            out.append(colectivo)
    return out


def efetch(pmids: list[str]) -> list[dict]:
    """Trae metadatos completos en lotes de 150."""
    registros: list[dict] = []
    for i in range(0, len(pmids), 150):
        lote = pmids[i:i + 150]
        time.sleep(DELAY)
        root = _get(f"{EUTILS}/efetch.fcgi", _ncbi({
            "db": "pubmed", "id": ",".join(lote), "retmode": "xml",
        }), parse="xml")
        if root is None:
            continue
        for art in root.findall("PubmedArticle"):
            pmid = _texto(art.find("MedlineCitation/PMID"))
            ids = {e.get("IdType"): (e.text or "").strip()
                   for e in art.findall("PubmedData/ArticleIdList/ArticleId")}
            abstract = " ".join(
                (f"{s.get('Label')}: " if s.get("Label") else "") + _texto(s)
                for s in art.findall("MedlineCitation/Article/Abstract/AbstractText")
            ).strip()
            registros.append({
                "pmid": pmid,
                "doi": ids.get("doi", ""),
                "pmcid": ids.get("pmc", ""),
                "titulo": _texto(art.find("MedlineCitation/Article/ArticleTitle")),
                "revista": _texto(art.find("MedlineCitation/Article/Journal/ISOAbbreviation"))
                           or _texto(art.find("MedlineCitation/Article/Journal/Title")),
                "anio": _fecha(art),
                "autores": _autores(art),
                "tipos": [_texto(t) for t in
                          art.findall("MedlineCitation/Article/PublicationTypeList/PublicationType")],
                "mesh": [_texto(m) for m in
                         art.findall("MedlineCitation/MeshHeadingList/MeshHeading/DescriptorName")][:12],
                "abstract": abstract,
                "url_pubmed": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            })
    return registros


# ------------------------------------------------------------------- acceso libre


def resolver_acceso(reg: dict, consultar_unpaywall: bool = True) -> dict:
    """Determina la mejor vía de texto completo. No descarga nada."""
    if reg.get("pmcid"):
        reg["acceso"] = "pmc"
        reg["url_pdf"] = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{reg['pmcid']}/pdf/"
        reg["url_texto"] = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{reg['pmcid']}/"
        return reg

    reg.setdefault("acceso", "paywall")
    reg.setdefault("url_pdf", "")
    reg.setdefault("url_texto", f"https://doi.org/{reg['doi']}" if reg.get("doi") else "")

    if not consultar_unpaywall or not reg.get("doi") or not EMAIL:
        return reg

    time.sleep(0.11)
    data = _get(f"{UNPAYWALL}/{urllib.parse.quote(reg['doi'])}", {"email": EMAIL}, parse="json")
    if not data:
        return reg
    loc = data.get("best_oa_location") or {}
    if data.get("is_oa") and loc:
        reg["acceso"] = "oa"
        reg["url_pdf"] = loc.get("url_for_pdf") or ""
        reg["url_texto"] = loc.get("url_for_landing_page") or loc.get("url") or reg["url_texto"]
        reg["licencia"] = loc.get("license") or ""
    return reg


# --------------------------------------------------------------------- salidas


def vancouver(reg: dict) -> str:
    autores = reg.get("autores") or []
    firma = ", ".join(autores[:6]) + (", et al" if len(autores) > 6 else "")
    partes = [p for p in (firma, reg.get("titulo", "").rstrip("."),
                          reg.get("revista", ""), reg.get("anio", "")) if p]
    cita = ". ".join(partes)
    if reg.get("doi"):
        cita += f". doi:{reg['doi']}"
    if reg.get("pmid"):
        cita += f". PMID: {reg['pmid']}"
    return cita + "."


ETIQUETA_ACCESO = {
    "pmc": "PMC (libre)",
    "oa": "Open access",
    "paywall": "Paywall — requiere proxy UC",
}


def escribir_salidas(dest: Path, tema: str, enfoque: str, registros: list[dict],
                     queries: list[tuple[str, str, int]]) -> None:
    dest.mkdir(parents=True, exist_ok=True)

    (dest / "fuentes.json").write_text(json.dumps({
        "tema": tema,
        "enfoque": enfoque,
        "generado": time.strftime("%Y-%m-%d %H:%M"),
        "n_fuentes": len(registros),
        "fuentes": registros,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    biblio = [f"# Bibliografía — {tema}", ""]
    if enfoque:
        biblio.append(f"*Énfasis solicitado: {enfoque}*\n")
    for i, reg in enumerate(registros, 1):
        etiqueta = ETIQUETA_ACCESO.get(reg.get("acceso"), reg.get("acceso", ""))
        biblio.append(f"{i}. {vancouver(reg)} — *{reg.get('estrato', '')}* · {etiqueta}")
        if reg.get("url_texto"):
            biblio.append(f"   - Texto completo: {reg['url_texto']}")
    (dest / "bibliografia.md").write_text("\n".join(biblio) + "\n", encoding="utf-8")

    por_estrato: dict[str, int] = {}
    por_acceso: dict[str, int] = {}
    for reg in registros:
        por_estrato[reg.get("estrato", "?")] = por_estrato.get(reg.get("estrato", "?"), 0) + 1
        por_acceso[reg.get("acceso", "?")] = por_acceso.get(reg.get("acceso", "?"), 0) + 1

    anios = sorted(r["anio"] for r in registros if r.get("anio", "").isdigit())
    resumen = [
        f"# Resumen de búsqueda — {tema}", "",
        f"- Fecha: {time.strftime('%Y-%m-%d %H:%M')}",
        f"- Énfasis: {enfoque or '(ninguno)'}",
        f"- Total de fuentes únicas: **{len(registros)}**",
        f"- Rango de años: {anios[0] if anios else '?'}–{anios[-1] if anios else '?'}",
        "", "## Por estrato de evidencia", "",
        "| Estrato | n |", "|---|---|",
    ]
    resumen += [f"| {k} | {v} |" for k, v in sorted(por_estrato.items(), key=lambda x: -x[1])]
    resumen += ["", "## Por vía de acceso", "", "| Acceso | n |", "|---|---|"]
    resumen += [f"| {ETIQUETA_ACCESO.get(k, k)} | {v} |"
                for k, v in sorted(por_acceso.items(), key=lambda x: -x[1])]
    resumen += ["", "## Queries ejecutadas", "", "| Estrato | Query | Resultados |", "|---|---|---|"]
    resumen += [f"| {e} | `{q}` | {n} |" for e, q, n in queries]

    paywalled = [r for r in registros if r.get("acceso") == "paywall" and r.get("doi")]
    if paywalled:
        resumen += ["", "## DOIs que requieren el proxy UC", "",
                    "Pásalos a `uc_library_fetcher` para conseguir el PDF:", "", "```"]
        resumen += [r["doi"] for r in paywalled]
        resumen += ["```"]
    (dest / "resumen_busqueda.md").write_text("\n".join(resumen) + "\n", encoding="utf-8")


# ------------------------------------------------------------------------ main


def main() -> int:
    ap = argparse.ArgumentParser(description="Cosecha fuentes PubMed para un tema médico.")
    ap.add_argument("tema", help='Enfermedad o tema, p.ej. "myasthenia gravis"')
    ap.add_argument("--enfoque", default="", help="Énfasis específico pedido por el usuario")
    ap.add_argument("--n", type=int, default=35, help="Total aproximado de fuentes (default 35)")
    ap.add_argument("--out", default="./fuentes", help="Directorio de salida")
    ap.add_argument("--desde", type=int, default=2000, help="Año mínimo (default 2000)")
    ap.add_argument("--sin-unpaywall", action="store_true",
                    help="Omite la resolución de acceso abierto (más rápido)")
    args = ap.parse_args()

    if not EMAIL:
        print("AVISO: ENTREZ_EMAIL no está definido. NCBI puede limitar o bloquear las "
              "peticiones, y Unpaywall quedará deshabilitado.\n"
              "  export ENTREZ_EMAIL='tu@correo.cl'\n", file=sys.stderr)

    rango = f'("{args.desde}"[dp] : "3000"[dp])' if args.desde != 2000 else RANGO_FECHA
    base = f"({args.tema})"

    estratos = list(ESTRATOS)
    if args.enfoque:
        # El énfasis merece su propio estrato dirigido y prioritario. Meterlo como
        # OR dentro de la base sería inerte —(A) AND (A OR B) equivale a (A)— y
        # como AND global sesgaría todo el informe hacia ese subtema.
        estratos.insert(0, ("enfoque_dirigido", f"{args.enfoque}", 0.25))
        # Reescalamos el resto para que el total siga cerca de --n.
        estratos = [(n, f, p * 0.75 if n != "enfoque_dirigido" else p)
                    for n, f, p in estratos]

    vistos: set[str] = set()
    registros: list[dict] = []
    queries: list[tuple[str, str, int]] = []

    print(f"Buscando «{args.tema}» (objetivo ~{args.n} fuentes, desde {args.desde})\n")

    for nombre, filtro, peso in estratos:
        cupo = max(3, round(args.n * peso))
        query = f"{base} AND ({filtro}) AND {rango}"
        # Pedimos de más porque los estratos se solapan y porque el sort por
        # relevancia de PubMed cuela resultados tangenciales que habrá que podar.
        pmids = esearch(query, cupo * 3)
        nuevos = [p for p in pmids if p not in vistos][:cupo]
        queries.append((nombre, query, len(pmids)))
        print(f"  {nombre:<24} {len(pmids):>3} hits -> {len(nuevos)} nuevos")
        if not nuevos:
            continue
        vistos.update(nuevos)
        for reg in efetch(nuevos):
            reg["estrato"] = nombre
            registros.append(reg)

    if not registros:
        print("\nSin resultados. Revisa el término o prueba sinónimos MeSH.", file=sys.stderr)
        return 1

    # Descarta lo anterior al corte que pudiera colarse por MedlineDate irregular.
    registros = [r for r in registros
                 if not r["anio"].isdigit() or int(r["anio"]) >= args.desde]

    # La detección de PMC es local (viene del efetch) y siempre corre; --sin-unpaywall
    # solo evita la ronda extra de peticiones HTTP a la API de Unpaywall.
    if not args.sin_unpaywall:
        print(f"\nResolviendo acceso a texto completo de {len(registros)} registros...")
    for reg in registros:
        resolver_acceso(reg, consultar_unpaywall=not args.sin_unpaywall)

    orden = {n: i for i, (n, _, _) in enumerate(estratos)}
    registros.sort(key=lambda r: (orden.get(r.get("estrato"), 9),
                                  -int(r["anio"]) if r["anio"].isdigit() else 0))

    dest = Path(args.out).expanduser()
    escribir_salidas(dest, args.tema, args.enfoque, registros, queries)

    libres = sum(1 for r in registros if r.get("acceso") in ("pmc", "oa"))
    print(f"\n{len(registros)} fuentes -> {dest}")
    print(f"  {libres} con texto completo libre · {len(registros) - libres} tras paywall")
    print(f"  Revisa {dest / 'resumen_busqueda.md'} para los DOIs que necesitan el proxy UC.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
