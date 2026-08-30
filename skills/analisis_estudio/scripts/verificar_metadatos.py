#!/usr/bin/env python3
"""verificar_metadatos.py — Contrasta la identificación del paper contra Crossref y PubMed.

Es la condición de entrada de la publicación automática. `publicar_notion.py` se
niega a escribir en Notion sin un `metadatos.json` con `verificado: true`, y este
script es lo único que lo produce.

El motivo es concreto: una ficha crítica que se equivoca en el **diseño** del
estudio evalúa con la guía de reporte equivocada, y entonces todo el juicio de
calidad que sigue es inválido. Lo mismo con el año y la revista, que es por donde
el lector vuelve a la fuente. Contrastarlo cuesta dos peticiones HTTP.

Qué hace:

  1. Baja los metadatos de **Crossref** (por DOI) y de **PubMed** (por PMID).
     Con solo uno de los dos identificadores también funciona: resuelve el otro.
  2. **Compara** título, año y revista entre ambas fuentes y anota las
     discrepancias en vez de elegir en silencio. Crossref y PubMed discrepan más
     de lo que parece, sobre todo en el año (electrónico vs impreso).
  3. **Deriva el tipo de estudio** desde los PublicationType de PubMed. Es una
     propuesta, no un veredicto: la etiqueta del editor miente a menudo — una
     "comprehensive review" sin método declarado es una revisión narrativa, y una
     guía que se autodenomina revisión sistemática se evalúa con AGREE-II. Revisa
     `tipo_estudio` a mano antes de publicar y corrige si el texto lo desmiente.
  4. **Fusiona** con un metadatos.json parcial: lo que no se puede derivar de
     ninguna base —patología, aspecto, calidad, aporte— se conserva tal cual.

Uso:
    python3 verificar_metadatos.py --doi 10.1186/s12967-023-03905-1 -o metadatos.json
    python3 verificar_metadatos.py --pmid 36765380 --base parcial.json -o metadatos.json

Exporta ENTREZ_EMAIL antes de correrlo; sin él NCBI limita las peticiones.
Solo biblioteca estándar.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CROSSREF = "https://api.crossref.org/works/"
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
IDCONV = "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/"
UA = "harness-analisis-estudio/1.0 (mailto:{correo})"

# PublicationType de PubMed -> opción de «Tipo de estudio» en la base.
# El orden importa: se toma la primera que calce, de la más específica a la más
# genérica, porque un ECA viene etiquetado además como "Clinical Trial".
TIPOS = [
    ("Meta-Analysis", "Metaanálisis"),
    ("Systematic Review", "Revisión sistemática"),
    ("Practice Guideline", "Guía de práctica clínica"),
    ("Guideline", "Guía de práctica clínica"),
    ("Randomized Controlled Trial", "Ensayo clínico aleatorizado"),
    ("Controlled Clinical Trial", "Ensayo clínico no aleatorizado"),
    ("Clinical Trial", "Ensayo clínico no aleatorizado"),
    ("Case Reports", "Reporte de caso"),
    ("Observational Study", "Cohorte"),
    ("Review", "Revisión narrativa"),
]

# Guía de reporte que corresponde a cada diseño. La ficha la nombra explícitamente.
GUIAS = {
    "Metaanálisis": "PRISMA + AMSTAR-2",
    "Revisión sistemática": "PRISMA + AMSTAR-2",
    "Guía de práctica clínica": "AGREE-II",
    "Ensayo clínico aleatorizado": "CONSORT + RoB 2",
    "Ensayo clínico no aleatorizado": "TREND + ROBINS-I",
    "Cohorte": "STROBE + Newcastle-Ottawa",
    "Casos y controles": "STROBE + Newcastle-Ottawa",
    "Transversal": "STROBE",
    "Precisión diagnóstica": "STARD + QUADAS-2",
    "Reporte de caso": "CARE",
    "Serie de casos": "CARE",
    "Evaluación económica": "CHEERS",
    "Investigación cualitativa": "COREQ",
    "Revisión narrativa": "SANRA",
    "Estudio preclínico o básico": "ARRIVE",
}


def _get(url: str, correo: str) -> dict | None:
    req = urllib.request.Request(url, headers={"User-Agent": UA.format(correo=correo)})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError) as e:
        print(f"[aviso] {url.split('?')[0]} -> {e}", file=sys.stderr)
        return None


def de_crossref(doi: str, correo: str) -> dict:
    d = (_get(CROSSREF + urllib.parse.quote(doi), correo) or {}).get("message")
    if not d:
        return {}
    fecha = (d.get("published-print") or d.get("published-online")
             or d.get("issued") or {}).get("date-parts", [[None]])[0]
    autores = d.get("author") or []
    primero = ""
    if autores:
        a = autores[0]
        iniciales = "".join(p[0] for p in (a.get("given") or "").split() if p)
        primero = f"{a.get('family', '')} {iniciales}".strip()
        if len(autores) > 1:
            primero += " et al."
    return {
        "titulo": (d.get("title") or [""])[0].strip(),
        "anio": fecha[0] if fecha else None,
        "revista": (d.get("short-container-title") or d.get("container-title") or [""])[0],
        "autor": primero,
        "tipo_crossref": d.get("type", ""),
    }


def de_pubmed(pmid: str, correo: str) -> dict:
    url = (f"{EUTILS}/esummary.fcgi?db=pubmed&id={pmid}&retmode=json"
           f"&email={urllib.parse.quote(correo)}")
    d = (_get(url, correo) or {}).get("result", {}).get(str(pmid))
    if not d:
        return {}
    autores = d.get("authors") or []
    primero = autores[0].get("name", "") if autores else ""
    if len(autores) > 1:
        primero += " et al."
    anio = (d.get("pubdate") or "")[:4]
    return {
        "titulo": (d.get("title") or "").rstrip(". ").strip(),
        "anio": int(anio) if anio.isdigit() else None,
        "revista": d.get("source", ""),
        "autor": primero,
        "pubtypes": d.get("pubtype") or [],
    }


def resolver_ids(doi: str | None, pmid: str | None, correo: str) -> tuple[str | None, str | None]:
    """Con uno de los dos identificadores, consigue el otro."""
    if doi and pmid:
        return doi, pmid
    clave = doi or pmid
    d = _get(f"{IDCONV}?ids={urllib.parse.quote(clave)}&format=json&tool=harness"
             f"&email={urllib.parse.quote(correo)}", correo) or {}
    registros = d.get("records") or [{}]
    return doi or registros[0].get("doi"), pmid or registros[0].get("pmid")


def tipo_desde_pubmed(pubtypes: list[str]) -> str | None:
    for etiqueta, opcion in TIPOS:
        if etiqueta in pubtypes:
            return opcion
    return None


def comparar(cr: dict, pm: dict) -> list[str]:
    """Discrepancias entre fuentes. No se resuelven en silencio: se reportan."""
    fuera = []
    if cr.get("titulo") and pm.get("titulo"):
        a = cr["titulo"].lower().rstrip(".")
        b = pm["titulo"].lower().rstrip(".")
        if a != b:
            fuera.append(f"título: Crossref «{cr['titulo']}» vs PubMed «{pm['titulo']}»")
    if cr.get("anio") and pm.get("anio") and cr["anio"] != pm["anio"]:
        fuera.append(f"año: Crossref {cr['anio']} vs PubMed {pm['anio']} "
                     "(suele ser electrónico vs impreso; usa el de PubMed)")
    if cr.get("revista") and pm.get("revista") and cr["revista"].lower() != pm["revista"].lower():
        fuera.append(f"revista: Crossref «{cr['revista']}» vs PubMed «{pm['revista']}» "
                     "(la base quiere la abreviatura NLM, que es la de PubMed)")
    return fuera


def main() -> int:
    ap = argparse.ArgumentParser(description="Verifica metadatos contra Crossref y PubMed.")
    ap.add_argument("--doi")
    ap.add_argument("--pmid")
    ap.add_argument("--base", help="metadatos.json parcial a fusionar (patología, aspecto…)")
    ap.add_argument("-o", "--out", default="metadatos.json")
    a = ap.parse_args()

    if not a.doi and not a.pmid:
        ap.error("hace falta --doi o --pmid")
    correo = os.environ.get("ENTREZ_EMAIL", "")
    if not correo:
        print("[aviso] sin ENTREZ_EMAIL: NCBI limitará las peticiones.", file=sys.stderr)

    doi, pmid = resolver_ids(a.doi, a.pmid, correo)
    cr = de_crossref(doi, correo) if doi else {}
    pm = de_pubmed(pmid, correo) if pmid else {}
    if not cr and not pm:
        print("ERROR: ni Crossref ni PubMed devolvieron nada. Sin verificación no se "
              "publica automáticamente; revisa el DOI/PMID.", file=sys.stderr)
        return 1

    meta = json.loads(Path(a.base).expanduser().read_text(encoding="utf-8")) if a.base else {}
    discrepancias = comparar(cr, pm)

    # PubMed manda en título, año y revista: es la forma que la base espera
    # (abreviatura NLM) y la que el lector reencuentra al buscar.
    prefiere = pm if pm else cr
    respaldo = cr if pm else {}
    for campo in ("titulo", "anio", "revista", "autor"):
        valor = prefiere.get(campo) or respaldo.get(campo)
        if valor:
            meta[campo] = valor
    if doi:
        meta["doi"] = doi
    if pmid:
        meta["pmid"] = str(pmid)

    tipo = tipo_desde_pubmed(pm.get("pubtypes", []))
    if tipo and not meta.get("tipo_estudio"):
        meta["tipo_estudio"] = tipo
    if meta.get("tipo_estudio"):
        meta["guia_reporte"] = GUIAS.get(meta["tipo_estudio"], "—")

    meta["verificacion"] = {
        "verificado": True,
        "fuente": "+".join(f for f, d in (("crossref", cr), ("pubmed", pm)) if d),
        "fecha": __import__("datetime").date.today().isoformat(),
        "discrepancias": discrepancias,
        "pubtypes": pm.get("pubtypes", []),
        "tipo_crossref": cr.get("tipo_crossref", ""),
    }

    Path(a.out).expanduser().write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"{a.out}: {meta.get('titulo', '?')}")
    print(f"  {meta.get('autor', '?')} · {meta.get('anio', '?')} · {meta.get('revista', '?')}")
    print(f"  tipo: {meta.get('tipo_estudio', 'NO DERIVADO — asígnalo a mano')} "
          f"-> guía {meta.get('guia_reporte', '—')}")
    if discrepancias:
        print("  DISCREPANCIAS entre fuentes (resuélvelas antes de publicar):")
        for d in discrepancias:
            print(f"    · {d}")
    faltan = [c for c in ("patologia", "aspecto", "calidad", "aporte") if not meta.get(c)]
    if faltan:
        print(f"  falta por completar (no se deriva de ninguna base): {', '.join(faltan)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
