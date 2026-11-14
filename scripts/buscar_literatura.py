#!/usr/bin/env python3
"""buscar_literatura.py — Búsqueda multi-fuente de literatura científica (agentes 1 y 2).

Fuentes:
  pubmed    E-utilities de NCBI, por estratos de evidencia (guías -> revisiones sistemáticas
            -> revisiones -> ensayos -> originales), heredado de buscar_fuentes.py.
  openalex  API de OpenAlex (índice abierto amplio; complementa a PubMed fuera de biomedicina).
  s2        Semantic Scholar Graph API.

Google Scholar NO se consulta: no tiene API oficial y automatizarlo exige scraping.

Deduplica por DOI -> PMID -> título normalizado + año, fusiona metadatos y registra en qué
fuentes apareció cada trabajo. Resuelve acceso a texto completo (PMC / Unpaywall).

Uso:
    python3 scripts/buscar_literatura.py "myasthenia gravis efgartigimod" \\
        --fuentes pubmed,openalex,s2 --n 30 --desde 2015 \\
        --out workspace/busquedas/mg-efgartigimod

    # Solo una revisión rápida en PubMed, sin estratos ni Unpaywall:
    python3 scripts/buscar_literatura.py "ALS riluzole survival" --fuentes pubmed \\
        --sin-estratos --sin-unpaywall --n 10 --out /tmp/als

Salidas en --out:
    fuentes.json          registros estructurados (entrada para los agentes 2, 3 y 4)
    bibliografia.md       lista numerada Vancouver con vía de acceso
    resumen_busqueda.md   queries, conteos por fuente/estrato/acceso y DOIs tras paywall

Variables de entorno (en ~/.config/harness/.env o exportadas):
    ENTREZ_EMAIL      correo para NCBI/Unpaywall/OpenAlex (recomendado)
    NCBI_API_KEY      sube el límite de NCBI de 3 a 10 req/s (opcional)
    OPENALEX_API_KEY  clave gratuita de OpenAlex (opcional; sube la cuota diaria)
    S2_API_KEY        clave de Semantic Scholar (opcional; sin ella hay más errores 429)
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _comun import (  # noqa: E402
    escribir_json,
    http_get,
    load_env,
    log,
    normalizar_doi,
    normalizar_titulo,
    vancouver,
)

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
UNPAYWALL = "https://api.unpaywall.org/v2"
OPENALEX = "https://api.openalex.org/works"
S2 = "https://api.semanticscholar.org/graph/v1/paper/search"
S2_CAMPOS = (
    "title,authors,year,venue,externalIds,abstract,citationCount,openAccessPdf,publicationTypes"
)

FUENTES_VALIDAS = ("pubmed", "openalex", "s2")

# Estratos PubMed en orden de prioridad de evidencia; el peso reparte el total pedido.
ESTRATOS = [
    (
        "guias",
        "guideline[pt] OR practice guideline[pt] OR consensus development conference[pt]",
        0.20,
    ),
    ("revisiones_sistematicas", "systematic review[pt] OR meta-analysis[pt]", 0.22),
    ("revisiones", "review[pt] AND hasabstract", 0.20),
    ("ensayos", "randomized controlled trial[pt] OR controlled clinical trial[pt]", 0.18),
    ("originales", "hasabstract", 0.20),
]

ETIQUETA_ACCESO = {
    "pmc": "PMC (libre)",
    "oa": "Open access",
    "paywall": "Paywall — probar proxy UC",
    "desconocido": "Acceso sin determinar",
}


def _cfg() -> dict[str, str]:
    return {
        "email": os.environ.get("ENTREZ_EMAIL") or os.environ.get("UNPAYWALL_EMAIL") or "",
        "ncbi_key": os.environ.get("NCBI_API_KEY", ""),
        "openalex_key": os.environ.get("OPENALEX_API_KEY", ""),
        "s2_key": os.environ.get("S2_API_KEY", ""),
    }


# =========================================================================== PubMed


def _ncbi(params: dict[str, Any], cfg: dict[str, str]) -> dict[str, Any]:
    base: dict[str, Any] = {"email": cfg["email"], "tool": "orquestador-cientifico"}
    if cfg["ncbi_key"]:
        base["api_key"] = cfg["ncbi_key"]
    base.update(params)
    return base


def pubmed_esearch(term: str, retmax: int, cfg: dict[str, str]) -> list[str]:
    time.sleep(0.11 if cfg["ncbi_key"] else 0.36)
    data = http_get(
        f"{EUTILS}/esearch.fcgi",
        _ncbi(
            {
                "db": "pubmed",
                "term": term,
                "retmax": retmax,
                "retmode": "json",
                "sort": "relevance",
            },
            cfg,
        ),
    )
    return (data or {}).get("esearchresult", {}).get("idlist", [])


def _texto(nodo: Any) -> str:
    return "".join(nodo.itertext()).strip() if nodo is not None else ""


def _anio_pubmed(art: Any) -> str:
    for ruta in (
        "MedlineCitation/Article/Journal/JournalIssue/PubDate/Year",
        "MedlineCitation/Article/ArticleDate/Year",
        "MedlineCitation/DateCompleted/Year",
    ):
        nodo = art.find(ruta)
        if nodo is not None and nodo.text:
            return nodo.text
    medline = art.find("MedlineCitation/Article/Journal/JournalIssue/PubDate/MedlineDate")
    return medline.text[:4] if medline is not None and medline.text else ""


def parse_pubmed_xml(root: Any) -> list[dict[str, Any]]:
    """Convierte la respuesta XML de efetch en registros normalizados."""
    registros: list[dict[str, Any]] = []
    for art in root.findall("PubmedArticle"):
        pmid = _texto(art.find("MedlineCitation/PMID"))
        ids = {
            e.get("IdType"): (e.text or "").strip()
            for e in art.findall("PubmedData/ArticleIdList/ArticleId")
        }
        abstract = " ".join(
            (f"{s.get('Label')}: " if s.get("Label") else "") + _texto(s)
            for s in art.findall("MedlineCitation/Article/Abstract/AbstractText")
        ).strip()
        autores = []
        for a in art.findall("MedlineCitation/Article/AuthorList/Author"):
            apellido, iniciales = _texto(a.find("LastName")), _texto(a.find("Initials"))
            colectivo = _texto(a.find("CollectiveName"))
            if apellido:
                autores.append(f"{apellido} {iniciales}".strip())
            elif colectivo:
                autores.append(colectivo)
        registros.append(
            {
                "fuentes": ["pubmed"],
                "pmid": pmid,
                "doi": normalizar_doi(ids.get("doi", "")),
                "pmcid": ids.get("pmc", ""),
                "titulo": _texto(art.find("MedlineCitation/Article/ArticleTitle")),
                "revista": _texto(art.find("MedlineCitation/Article/Journal/ISOAbbreviation"))
                or _texto(art.find("MedlineCitation/Article/Journal/Title")),
                "anio": _anio_pubmed(art),
                "autores": autores,
                "tipos": [
                    _texto(t)
                    for t in art.findall(
                        "MedlineCitation/Article/PublicationTypeList/PublicationType"
                    )
                ],
                "mesh": [
                    _texto(m)
                    for m in art.findall(
                        "MedlineCitation/MeshHeadingList/MeshHeading/DescriptorName"
                    )
                ][:12],
                "abstract": abstract,
                "citas": None,
                "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            }
        )
    return registros


def pubmed_efetch(pmids: list[str], cfg: dict[str, str]) -> list[dict[str, Any]]:
    registros: list[dict[str, Any]] = []
    for i in range(0, len(pmids), 150):
        time.sleep(0.11 if cfg["ncbi_key"] else 0.36)
        root = http_get(
            f"{EUTILS}/efetch.fcgi",
            _ncbi({"db": "pubmed", "id": ",".join(pmids[i : i + 150]), "retmode": "xml"}, cfg),
            parse="xml",
        )
        if root is not None:
            registros.extend(parse_pubmed_xml(root))
    return registros


def buscar_pubmed(
    query: str, n: int, desde: int, estratos: bool, enfoque: str, cfg: dict[str, str]
) -> tuple[list[dict[str, Any]], list[tuple[str, str, str, int]]]:
    rango = f'("{desde}"[dp] : "3000"[dp])'
    base = f"({query})"
    queries: list[tuple[str, str, str, int]] = []
    if not estratos:
        q = f"{base} AND {rango}"
        pmids = pubmed_esearch(q, n, cfg)
        queries.append(("pubmed", "todo", q, len(pmids)))
        regs = pubmed_efetch(pmids, cfg)
        for r in regs:
            r["estrato"] = "sin_estrato"
        return regs, queries

    plan = list(ESTRATOS)
    if enfoque:
        # El énfasis va como estrato propio y prioritario: meterlo como OR en la base sería
        # inerte y como AND global sesgaría toda la búsqueda hacia el subtema.
        plan = [("enfoque_dirigido", enfoque, 0.25)] + [(a, b, p * 0.75) for a, b, p in plan]

    vistos: set[str] = set()
    registros: list[dict[str, Any]] = []
    for nombre, filtro, peso in plan:
        cupo = max(3, round(n * peso))
        q = f"{base} AND ({filtro}) AND {rango}"
        pmids = pubmed_esearch(q, cupo * 3, cfg)  # se pide de más: los estratos se solapan
        nuevos = [p for p in pmids if p not in vistos][:cupo]
        queries.append(("pubmed", nombre, q, len(pmids)))
        log.info("pubmed %-24s %3d hits -> %d nuevos", nombre, len(pmids), len(nuevos))
        vistos.update(nuevos)
        for reg in pubmed_efetch(nuevos, cfg):
            reg["estrato"] = nombre
            registros.append(reg)
    return registros, queries


# ========================================================================= OpenAlex


def _abstract_invertido(indice: dict[str, list[int]] | None) -> str:
    """OpenAlex entrega el abstract como índice invertido {palabra: [posiciones]}."""
    if not indice:
        return ""
    posiciones = [(pos, palabra) for palabra, lista in indice.items() for pos in lista]
    return " ".join(palabra for _, palabra in sorted(posiciones))


def parse_openalex(data: dict[str, Any]) -> list[dict[str, Any]]:
    registros: list[dict[str, Any]] = []
    for w in (data or {}).get("results", []):
        ids = w.get("ids") or {}
        pmid = (ids.get("pmid") or "").rstrip("/").rsplit("/", 1)[-1]
        pmcid = (ids.get("pmcid") or "").rstrip("/").rsplit("/", 1)[-1]
        fuente = ((w.get("primary_location") or {}).get("source") or {}).get("display_name")
        oa = w.get("open_access") or {}
        registros.append(
            {
                "fuentes": ["openalex"],
                "openalex_id": (w.get("id") or "").rsplit("/", 1)[-1],
                "pmid": pmid if pmid.isdigit() else "",
                "doi": normalizar_doi(w.get("doi")),
                "pmcid": pmcid if pmcid.upper().startswith("PMC") else "",
                "titulo": w.get("display_name") or w.get("title") or "",
                "revista": fuente or "",
                "anio": str(w.get("publication_year") or ""),
                "autores": [
                    (a.get("author") or {}).get("display_name", "")
                    for a in w.get("authorships") or []
                    if (a.get("author") or {}).get("display_name")
                ],
                "tipos": [w["type"]] if w.get("type") else [],
                "abstract": _abstract_invertido(w.get("abstract_inverted_index")),
                "citas": w.get("cited_by_count"),
                "url": w.get("doi") or w.get("id") or "",
                "acceso": "oa" if oa.get("is_oa") and oa.get("oa_url") else "",
                "url_pdf": oa.get("oa_url") or "" if oa.get("is_oa") else "",
                "estrato": "openalex",
            }
        )
    return registros


def buscar_openalex(
    query: str, n: int, desde: int, cfg: dict[str, str]
) -> tuple[list[dict[str, Any]], list[tuple[str, str, str, int]]]:
    params = {
        "search": query,
        "per-page": min(n, 200),
        "filter": f"from_publication_date:{desde}-01-01",
        "mailto": cfg["email"],
        "api_key": cfg["openalex_key"],
    }
    data = http_get(OPENALEX, params)
    regs = parse_openalex(data or {})
    log.info("openalex %d resultados", len(regs))
    return regs, [("openalex", "busqueda", query, len(regs))]


# ================================================================== Semantic Scholar


def parse_s2(data: dict[str, Any]) -> list[dict[str, Any]]:
    registros: list[dict[str, Any]] = []
    for p in (data or {}).get("data", []):
        ext = p.get("externalIds") or {}
        pmc = str(ext.get("PubMedCentral") or "")
        pdf = (p.get("openAccessPdf") or {}).get("url") or ""
        registros.append(
            {
                "fuentes": ["s2"],
                "s2_id": p.get("paperId", ""),
                "pmid": str(ext.get("PubMed") or ""),
                "doi": normalizar_doi(ext.get("DOI")),
                "pmcid": f"PMC{pmc}" if pmc and not pmc.upper().startswith("PMC") else pmc,
                "titulo": p.get("title") or "",
                "revista": p.get("venue") or "",
                "anio": str(p.get("year") or ""),
                "autores": [a.get("name", "") for a in p.get("authors") or [] if a.get("name")],
                "tipos": p.get("publicationTypes") or [],
                "abstract": p.get("abstract") or "",
                "citas": p.get("citationCount"),
                "url": f"https://www.semanticscholar.org/paper/{p.get('paperId', '')}",
                "acceso": "oa" if pdf else "",
                "url_pdf": pdf,
                "estrato": "s2",
            }
        )
    return registros


def buscar_s2(
    query: str, n: int, desde: int, cfg: dict[str, str]
) -> tuple[list[dict[str, Any]], list[tuple[str, str, str, int]]]:
    headers = {"x-api-key": cfg["s2_key"]} if cfg["s2_key"] else None
    params = {"query": query, "limit": min(n, 100), "fields": S2_CAMPOS, "year": f"{desde}-"}
    data = http_get(S2, params, headers=headers, intentos=4)
    regs = parse_s2(data or {})
    log.info("s2 %d resultados", len(regs))
    return regs, [("s2", "busqueda", query, len(regs))]


# ===================================================================== fusión


def _clave(reg: dict[str, Any]) -> list[str]:
    claves = []
    if reg.get("doi"):
        claves.append(f"doi:{reg['doi']}")
    if reg.get("pmid"):
        claves.append(f"pmid:{reg['pmid']}")
    titulo = normalizar_titulo(reg.get("titulo"))
    if titulo:
        claves.append(f"t:{titulo}|{reg.get('anio', '')}")
    return claves


def deduplicar(registros: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fusiona registros del mismo trabajo. El primero en llegar define el orden y el estrato."""
    unicos: list[dict[str, Any]] = []
    indice: dict[str, dict[str, Any]] = {}
    for reg in registros:
        existente = next((indice[c] for c in _clave(reg) if c in indice), None)
        if existente is None:
            reg = dict(reg)
            reg["fuentes"] = list(reg.get("fuentes", []))
            unicos.append(reg)
            existente = reg
        else:
            for campo, valor in reg.items():
                if campo == "fuentes":
                    existente["fuentes"] = sorted(set(existente["fuentes"]) | set(valor))
                elif campo == "citas":
                    existente["citas"] = max(
                        (c for c in (existente.get("citas"), valor) if c is not None),
                        default=None,
                    )
                elif valor and not existente.get(campo):
                    existente[campo] = valor
        for c in _clave(existente):
            indice[c] = existente
    return unicos


def resolver_acceso(reg: dict[str, Any], email: str, consultar_unpaywall: bool) -> dict[str, Any]:
    """Mejor vía de texto completo. No descarga nada."""
    if reg.get("pmcid"):
        reg["acceso"] = "pmc"
        reg["url_pdf"] = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{reg['pmcid']}/pdf/"
        return reg
    if reg.get("acceso") == "oa" and reg.get("url_pdf"):
        return reg
    reg["acceso"] = "paywall" if reg.get("doi") else "desconocido"
    reg.setdefault("url_pdf", "")
    if not (consultar_unpaywall and reg.get("doi") and email):
        return reg
    time.sleep(0.11)
    data = http_get(f"{UNPAYWALL}/{urllib.parse.quote(reg['doi'])}", {"email": email})
    loc = (data or {}).get("best_oa_location") or {}
    if data and data.get("is_oa") and loc:
        reg["acceso"] = "oa"
        reg["url_pdf"] = loc.get("url_for_pdf") or ""
        reg["licencia"] = loc.get("license") or ""
    return reg


# ===================================================================== salidas


def escribir_salidas(
    dest: Path,
    query: str,
    enfoque: str,
    registros: list[dict[str, Any]],
    queries: list[tuple[str, str, str, int]],
) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    fecha = time.strftime("%Y-%m-%d %H:%M")
    escribir_json(
        dest / "fuentes.json",
        {
            "query": query,
            "enfoque": enfoque,
            "generado": fecha,
            "n_fuentes": len(registros),
            "fuentes": registros,
        },
    )

    biblio = [f"# Bibliografía — {query}", ""]
    for i, reg in enumerate(registros, 1):
        acceso = ETIQUETA_ACCESO.get(reg.get("acceso", ""), reg.get("acceso", ""))
        origen = "+".join(reg.get("fuentes", []))
        biblio.append(f"{i}. {vancouver(reg)} — *{reg.get('estrato', '')}* · {origen} · {acceso}")
        if reg.get("url_pdf"):
            biblio.append(f"   - PDF: {reg['url_pdf']}")
    (dest / "bibliografia.md").write_text("\n".join(biblio) + "\n", encoding="utf-8")

    def contar(campo: str) -> dict[str, int]:
        out: dict[str, int] = {}
        for r in registros:
            valores = r.get(campo) if isinstance(r.get(campo), list) else [r.get(campo, "?")]
            for v in valores or ["?"]:
                out[str(v)] = out.get(str(v), 0) + 1
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))

    anios = sorted(int(r["anio"]) for r in registros if str(r.get("anio", "")).isdigit())
    md = [
        f"# Resumen de búsqueda — {query}",
        "",
        f"- Fecha: {fecha}",
        f"- Énfasis: {enfoque or '(ninguno)'}",
        f"- Trabajos únicos tras deduplicar: **{len(registros)}**",
        f"- Rango de años: {anios[0] if anios else '?'}–{anios[-1] if anios else '?'}",
        "- Google Scholar: no consultado (sin API oficial).",
        "",
        "## Por fuente (un trabajo puede estar en varias)",
        "",
        "| Fuente | n |",
        "|---|---|",
    ]
    md += [f"| {k} | {v} |" for k, v in contar("fuentes").items()]
    md += ["", "## Por estrato", "", "| Estrato | n |", "|---|---|"]
    md += [f"| {k} | {v} |" for k, v in contar("estrato").items()]
    md += ["", "## Por vía de acceso", "", "| Acceso | n |", "|---|---|"]
    md += [f"| {ETIQUETA_ACCESO.get(k, k)} | {v} |" for k, v in contar("acceso").items()]
    md += [
        "",
        "## Queries ejecutadas",
        "",
        "| Fuente | Estrato | Query | Hits |",
        "|---|---|---|---|",
    ]
    md += [f"| {f} | {e} | `{q}` | {n} |" for f, e, q, n in queries]
    sin_abstract = sum(1 for r in registros if not r.get("abstract"))
    md += ["", "## Límites", "", f"- Trabajos sin abstract disponible: {sin_abstract}"]
    paywall = [r["doi"] for r in registros if r.get("acceso") == "paywall"]
    if paywall:
        md += ["", "## DOIs tras paywall (usar skill `acceso-uc`)", "", "```", *paywall, "```"]
    (dest / "resumen_busqueda.md").write_text("\n".join(md) + "\n", encoding="utf-8")


# ======================================================================== main


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Búsqueda multi-fuente de literatura científica.")
    ap.add_argument("query", help="Términos de búsqueda (en inglés rinde más en PubMed)")
    ap.add_argument(
        "--fuentes",
        default="pubmed,openalex,s2",
        help="Lista separada por comas: pubmed,openalex,s2 (default: las tres)",
    )
    ap.add_argument("--n", type=int, default=30, help="Resultados aproximados por fuente")
    ap.add_argument("--desde", type=int, default=2000, help="Año mínimo de publicación")
    ap.add_argument("--enfoque", default="", help="Subtema prioritario (estrato PubMed propio)")
    ap.add_argument("--sin-estratos", action="store_true", help="PubMed sin estratos")
    ap.add_argument("--sin-unpaywall", action="store_true", help="No consulta Unpaywall")
    ap.add_argument("--out", required=True, help="Directorio de salida")
    args = ap.parse_args(argv)

    load_env()
    cfg = _cfg()
    fuentes = [f.strip() for f in args.fuentes.split(",") if f.strip()]
    invalidas = sorted(set(fuentes) - set(FUENTES_VALIDAS))
    if invalidas:
        ap.error(f"fuentes no válidas: {invalidas}. Opciones: {', '.join(FUENTES_VALIDAS)}")
    if not cfg["email"]:
        log.warning("ENTREZ_EMAIL no definido: NCBI puede limitar y Unpaywall queda desactivado.")

    registros: list[dict[str, Any]] = []
    queries: list[tuple[str, str, str, int]] = []
    if "pubmed" in fuentes:
        r, q = buscar_pubmed(
            args.query, args.n, args.desde, not args.sin_estratos, args.enfoque, cfg
        )
        registros += r
        queries += q
    if "openalex" in fuentes:
        r, q = buscar_openalex(args.query, args.n, args.desde, cfg)
        registros += r
        queries += q
    if "s2" in fuentes:
        r, q = buscar_s2(args.query, args.n, args.desde, cfg)
        registros += r
        queries += q

    brutos = len(registros)
    registros = deduplicar(registros)
    registros = [
        r for r in registros if not str(r.get("anio", "")).isdigit() or int(r["anio"]) >= args.desde
    ]
    if not registros:
        log.error("Sin resultados (o todas las fuentes fallaron). Revisa términos y conexión.")
        return 1

    for reg in registros:
        resolver_acceso(reg, cfg["email"], consultar_unpaywall=not args.sin_unpaywall)

    dest = Path(args.out).expanduser()
    escribir_salidas(dest, args.query, args.enfoque, registros, queries)
    libres = sum(1 for r in registros if r.get("acceso") in ("pmc", "oa"))
    print(f"{brutos} resultados brutos -> {len(registros)} únicos -> {dest}")
    print(f"  {libres} con texto completo libre · {len(registros) - libres} sin acceso libre")
    return 0


if __name__ == "__main__":
    sys.exit(main())
