"""Skill pubmed_search — búsqueda en PubMed vía Entrez (Biopython).

Import perezoso de Bio para que el registro no falle si la dependencia no está instalada.
Expón register_skill(reg) para que tools/registry.py la descubra automáticamente.
"""
from __future__ import annotations
import os


def pubmed_search(args: dict) -> str:
    query = args.get("query", "").strip()
    retmax = int(args.get("retmax", 10))
    if not query:
        return "ERROR: falta 'query'."
    try:
        from Bio import Entrez  # import perezoso
    except ImportError:
        return "ERROR: instala biopython (pip install biopython)."
    Entrez.email = os.environ.get("ENTREZ_EMAIL", "anon@example.com")
    ids = Entrez.read(Entrez.esearch(db="pubmed", term=query, retmax=retmax))["IdList"]
    if not ids:
        return f"Sin resultados para: {query}"
    handle = Entrez.efetch(db="pubmed", id=",".join(ids), rettype="abstract", retmode="xml")
    out = []
    for art in Entrez.read(handle)["PubmedArticle"]:
        cit = art["MedlineCitation"]
        pmid = str(cit["PMID"])
        art_d = cit["Article"]
        title = art_d.get("ArticleTitle", "")
        abst = art_d.get("Abstract", {}).get("AbstractText", [""])
        abst = " ".join(str(x) for x in abst)
        out.append(f"PMID {pmid}: {title}\n{abst[:600]}")
    return "\n\n".join(out)


def register_skill(reg) -> None:
    reg.register(
        "pubmed_search",
        "Busca en PubMed y devuelve PMIDs, título y abstract. Sin datos de pacientes en la query.",
        {"type": "object",
         "properties": {"query": {"type": "string"}, "retmax": {"type": "integer"}},
         "required": ["query"]},
        pubmed_search,
    )
