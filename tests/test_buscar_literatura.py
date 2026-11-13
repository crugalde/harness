"""Búsqueda multi-fuente: parsers, deduplicación y flujo completo con HTTP simulado."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET

import buscar_literatura as bl
import pytest

PUBMED_XML = """<PubmedArticleSet>
<PubmedArticle>
  <MedlineCitation>
    <PMID>111</PMID>
    <Article>
      <Journal><JournalIssue><PubDate><Year>2021</Year></PubDate></JournalIssue>
        <ISOAbbreviation>Lancet Neurol</ISOAbbreviation></Journal>
      <ArticleTitle>Efgartigimod in generalised myasthenia gravis (ADAPT)</ArticleTitle>
      <Abstract><AbstractText Label="BACKGROUND">FcRn blockade.</AbstractText>
        <AbstractText Label="FINDINGS">MG-ADL responders 68%.</AbstractText></Abstract>
      <AuthorList><Author><LastName>Howard</LastName><Initials>JF</Initials></Author>
        <Author><CollectiveName>ADAPT Investigator Study Group</CollectiveName></Author></AuthorList>
      <PublicationTypeList><PublicationType>Randomized Controlled Trial</PublicationType>
      </PublicationTypeList>
    </Article>
    <MeshHeadingList><MeshHeading><DescriptorName>Myasthenia Gravis</DescriptorName>
    </MeshHeading></MeshHeadingList>
  </MedlineCitation>
  <PubmedData><ArticleIdList>
    <ArticleId IdType="doi">10.1016/S1474-4422(21)00159-9</ArticleId>
  </ArticleIdList></PubmedData>
</PubmedArticle>
<PubmedArticle>
  <MedlineCitation><PMID>222</PMID><Article>
    <Journal><JournalIssue><PubDate><MedlineDate>2019 Jan-Feb</MedlineDate></PubDate>
    </JournalIssue><Title>Neurology</Title></Journal>
    <ArticleTitle>Older review of myasthenia</ArticleTitle>
  </Article></MedlineCitation>
  <PubmedData><ArticleIdList><ArticleId IdType="pmc">PMC999</ArticleId></ArticleIdList>
  </PubmedData>
</PubmedArticle>
</PubmedArticleSet>"""

OPENALEX = {
    "results": [
        {
            "id": "https://openalex.org/W1",
            "doi": "https://doi.org/10.1016/S1474-4422(21)00159-9",
            "display_name": "Efgartigimod in generalised myasthenia gravis (ADAPT)",
            "publication_year": 2021,
            "ids": {"pmid": "https://pubmed.ncbi.nlm.nih.gov/111"},
            "authorships": [{"author": {"display_name": "James F. Howard"}}],
            "primary_location": {"source": {"display_name": "The Lancet Neurology"}},
            "abstract_inverted_index": {"FcRn": [0], "blockade": [1]},
            "cited_by_count": 500,
            "open_access": {"is_oa": False, "oa_url": None},
            "type": "article",
        },
        {
            "id": "https://openalex.org/W2",
            "doi": None,
            "display_name": "Rozanolixizumab in MG",
            "publication_year": 2023,
            "ids": {},
            "authorships": [],
            "abstract_inverted_index": {"world": [1], "Hello": [0]},
            "cited_by_count": 40,
            "open_access": {"is_oa": True, "oa_url": "https://x.org/r.pdf"},
        },
    ]
}

S2 = {
    "data": [
        {
            "paperId": "abc",
            "title": "Efgartigimod in Generalised Myasthenia Gravis: ADAPT",
            "year": 2021,
            "externalIds": {},
            "authors": [{"name": "J. Howard"}],
            "citationCount": 610,
        },
        {
            "paperId": "def",
            "title": "Zilucoplan in MG",
            "year": 2023,
            "externalIds": {"DOI": "10.1/ZIL", "PubMed": "333", "PubMedCentral": "12345"},
            "authors": [{"name": "R. Howard"}],
            "openAccessPdf": None,
        },
    ]
}


def test_parse_pubmed_xml():
    regs = bl.parse_pubmed_xml(ET.fromstring(PUBMED_XML))
    assert [r["pmid"] for r in regs] == ["111", "222"]
    a = regs[0]
    assert a["doi"] == "10.1016/s1474-4422(21)00159-9"
    assert a["autores"] == ["Howard JF", "ADAPT Investigator Study Group"]
    assert a["abstract"].startswith("BACKGROUND: FcRn blockade.")
    assert a["anio"] == "2021" and a["revista"] == "Lancet Neurol"
    assert regs[1]["anio"] == "2019" and regs[1]["pmcid"] == "PMC999"


def test_parse_openalex_reconstruye_abstract_invertido():
    regs = bl.parse_openalex(OPENALEX)
    assert regs[0]["pmid"] == "111" and regs[0]["citas"] == 500
    assert regs[1]["abstract"] == "Hello world"
    assert regs[1]["acceso"] == "oa" and regs[1]["url_pdf"] == "https://x.org/r.pdf"


def test_parse_s2_normaliza_pmcid_y_doi():
    regs = bl.parse_s2(S2)
    assert regs[1]["pmcid"] == "PMC12345" and regs[1]["doi"] == "10.1/zil"
    assert regs[1]["pmid"] == "333"


def test_deduplicar_por_doi_pmid_y_titulo():
    pubmed = bl.parse_pubmed_xml(ET.fromstring(PUBMED_XML))
    for r in pubmed:
        r["estrato"] = "ensayos"  # buscar_pubmed lo asigna en el flujo real
    regs = bl.deduplicar(pubmed + bl.parse_openalex(OPENALEX) + bl.parse_s2(S2))
    assert len(regs) == 4  # 111 (x3 fuentes), 222, W2, Zilucoplan
    adapt = regs[0]
    assert adapt["fuentes"] == ["openalex", "pubmed", "s2"]
    assert adapt["citas"] == 610  # máximo entre fuentes
    assert adapt["estrato"] == "ensayos"  # conserva el estrato del primero (PubMed)
    assert adapt["abstract"].startswith("BACKGROUND")  # no se pisa con el de OpenAlex


def test_resolver_acceso_sin_red():
    assert bl.resolver_acceso({"pmcid": "PMC1"}, "", False)["acceso"] == "pmc"
    assert bl.resolver_acceso({"doi": "10.1/x"}, "", False)["acceso"] == "paywall"
    assert bl.resolver_acceso({}, "", False)["acceso"] == "desconocido"
    oa = {"acceso": "oa", "url_pdf": "https://x/y.pdf"}
    assert bl.resolver_acceso(oa, "", False)["acceso"] == "oa"


def _http_falso(url, params=None, **_):
    if "esearch" in url:
        return {"esearchresult": {"idlist": ["111", "222"]}}
    if "efetch" in url:
        return ET.fromstring(PUBMED_XML)
    if "openalex" in url:
        return OPENALEX
    if "semanticscholar" in url:
        return S2
    if "unpaywall" in url:
        return {"is_oa": False}
    raise AssertionError(f"URL inesperada: {url}")


def test_main_flujo_completo_sin_red(tmp_path, monkeypatch):
    monkeypatch.setattr(bl, "http_get", _http_falso)
    monkeypatch.setattr(bl.time, "sleep", lambda *_: None)
    monkeypatch.setenv("ENTREZ_EMAIL", "test@example.org")
    out = tmp_path / "busqueda"
    assert bl.main(["myasthenia efgartigimod", "--n", "10", "--out", str(out)]) == 0

    datos = json.loads((out / "fuentes.json").read_text(encoding="utf-8"))
    assert datos["n_fuentes"] == 4
    por_pmid = {f.get("pmid"): f for f in datos["fuentes"]}
    assert por_pmid["222"]["acceso"] == "pmc"
    assert por_pmid["111"]["acceso"] == "paywall"
    resumen = (out / "resumen_busqueda.md").read_text(encoding="utf-8")
    assert "Google Scholar: no consultado" in resumen
    assert "10.1016/s1474-4422(21)00159-9" in resumen  # DOI tras paywall listado
    biblio = (out / "bibliografia.md").read_text(encoding="utf-8")
    assert "PMID: 111" in biblio and "openalex+pubmed+s2" in biblio


def test_main_rechaza_fuente_invalida(tmp_path):
    with pytest.raises(SystemExit):
        bl.main(["x", "--fuentes", "scholar", "--out", str(tmp_path)])


def test_main_sin_resultados_devuelve_1(tmp_path, monkeypatch):
    monkeypatch.setattr(bl, "http_get", lambda *a, **k: None)
    monkeypatch.setattr(bl.time, "sleep", lambda *_: None)
    assert bl.main(["nada", "--out", str(tmp_path / "o")]) == 1
