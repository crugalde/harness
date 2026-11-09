"""Tests offline de la skill pubmed_qa (sin red ni API). Correr con: pytest -q tests/test_pubmed_qa.py

Los PMIDs, DOIs y autores de los fixtures son sintéticos.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import types
import urllib.parse
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TOOL_PATH = ROOT / "skills" / "pubmed_qa" / "tool.py"


def _cargar_tool():
    spec = importlib.util.spec_from_file_location("skill_pubmed_qa_test", TOOL_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


TOOL = _cargar_tool()
CORE = TOOL._core()


# ----------------------------------------------------------------------------------- fixtures

_ART_RCT = """
<PubmedArticle><MedlineCitation><PMID>11111111</PMID><Article>
<Journal><JournalIssue><Volume>20</Volume><Issue>7</Issue><PubDate><Year>2021</Year></PubDate>
</JournalIssue><Title>The Lancet. Neurology</Title><ISOAbbreviation>Lancet Neurol</ISOAbbreviation>
</Journal>
<ArticleTitle>Efgartigimod in generalised myasthenia gravis: a randomised, placebo-controlled,
phase 3 trial.</ArticleTitle>
<Pagination><MedlinePgn>526-536</MedlinePgn></Pagination>
<Abstract>
<AbstractText Label="BACKGROUND">There is an unmet need for targeted treatments for generalised
myasthenia gravis. We assessed efgartigimod, a neonatal Fc receptor (FcRn) antagonist.</AbstractText>
<AbstractText Label="METHODS">In this randomised, double-blind, placebo-controlled, phase 3 trial,
167 patients with generalised myasthenia gravis were randomly assigned to efgartigimod or
placebo.</AbstractText>
<AbstractText Label="FINDINGS">More patients in the efgartigimod group were MG-ADL responders than
in the placebo group (68% vs 30%; odds ratio 4·95, 95% CI 2·21-11·53; p&lt;0·0001). Adverse events
were similar between groups.</AbstractText>
<AbstractText Label="INTERPRETATION">Efgartigimod was well tolerated and efficacious in patients
with generalised myasthenia gravis.</AbstractText>
<AbstractText Label="FUNDING">argenx, grant 777777.</AbstractText>
</Abstract>
<AuthorList><Author><LastName>Alfa</LastName><Initials>AB</Initials></Author>
<Author><LastName>Beta</LastName><Initials>C</Initials></Author>
<Author><LastName>Gamma</LastName><Initials>D</Initials></Author>
<Author><LastName>Delta</LastName><Initials>E</Initials></Author>
<Author><LastName>Epsilon</LastName><Initials>F</Initials></Author>
<Author><LastName>Zeta</LastName><Initials>G</Initials></Author>
<Author><LastName>Eta</LastName><Initials>H</Initials></Author></AuthorList>
<Language>eng</Language>
<PublicationTypeList><PublicationType>Clinical Trial, Phase III</PublicationType>
<PublicationType>Journal Article</PublicationType>
<PublicationType>Randomized Controlled Trial</PublicationType></PublicationTypeList>
</Article></MedlineCitation>
<PubmedData><ArticleIdList><ArticleId IdType="pubmed">11111111</ArticleId>
<ArticleId IdType="doi">10.1000/adapt</ArticleId><ArticleId IdType="pmc">PMC9999999</ArticleId>
</ArticleIdList></PubmedData></PubmedArticle>
"""

_ART_RETRACTADA = """
<PubmedArticle><MedlineCitation><PMID>22222222</PMID><Article>
<Journal><JournalIssue><PubDate><Year>2019</Year></PubDate></JournalIssue>
<ISOAbbreviation>Fake J</ISOAbbreviation></Journal>
<ArticleTitle>Efgartigimod cures myasthenia gravis in all patients.</ArticleTitle>
<Abstract><AbstractText>Efgartigimod cured myasthenia gravis in 100% of 20 patients treated with
efgartigimod in an uncontrolled series of myasthenia gravis patients followed for one year.
</AbstractText></Abstract>
<PublicationTypeList><PublicationType>Journal Article</PublicationType>
<PublicationType>Retracted Publication</PublicationType></PublicationTypeList>
</Article></MedlineCitation></PubmedArticle>
"""

_ART_IRRELEVANTE = """
<PubmedArticle><MedlineCitation><PMID>33333333</PMID><Article>
<Journal><JournalIssue><PubDate><Year>2020</Year></PubDate></JournalIssue>
<ISOAbbreviation>Hypertension</ISOAbbreviation></Journal>
<ArticleTitle>Dietary sodium reduction and blood pressure in adults.</ArticleTitle>
<Abstract><AbstractText>We evaluated dietary sodium reduction in 400 adults with hypertension.
Systolic blood pressure decreased by 5.4 mmHg after sodium reduction compared with usual diet over
six months of follow-up in a community setting.</AbstractText></Abstract>
<PublicationTypeList><PublicationType>Journal Article</PublicationType></PublicationTypeList>
</Article></MedlineCitation></PubmedArticle>
"""

_ART_RS = """
<PubmedArticle><MedlineCitation><PMID>44444444</PMID><Article>
<Journal><JournalIssue><Volume>12</Volume><PubDate><Year>2023</Year></PubDate></JournalIssue>
<ISOAbbreviation>Neurol Ther</ISOAbbreviation></Journal>
<ArticleTitle>FcRn antagonists in myasthenia gravis: a systematic review and
meta-analysis.</ArticleTitle>
<Abstract><AbstractText>Neonatal Fc receptor (FcRn) antagonists such as efgartigimod are a new
therapeutic class for myasthenia gravis. We performed a systematic review and meta-analysis of
randomized controlled trials. We included 12 trials with 1,234 patients. FcRn antagonists improved
MG-ADL scores compared with placebo (mean difference -2.1, 95% CI -2.8 to -1.4). FcRn antagonists
are effective in generalized myasthenia gravis.</AbstractText></Abstract>
<AuthorList><Author><LastName>Theta</LastName><Initials>I</Initials></Author></AuthorList>
<PublicationTypeList><PublicationType>Journal Article</PublicationType>
<PublicationType>Review</PublicationType></PublicationTypeList>
</Article></MedlineCitation>
<PubmedData><ArticleIdList><ArticleId IdType="doi">10.1000/sr</ArticleId></ArticleIdList>
</PubmedData></PubmedArticle>
"""

ARTICULOS = {
    "11111111": _ART_RCT,
    "22222222": _ART_RETRACTADA,
    "33333333": _ART_IRRELEVANTE,
    "44444444": _ART_RS,
}


def _xml(ids) -> bytes:
    cuerpo = "".join(ARTICULOS[i] for i in ids if i in ARTICULOS)
    return f"<PubmedArticleSet>{cuerpo}</PubmedArticleSet>".encode()


EPMC = {
    "hitCount": 4,
    "resultList": {
        "result": [
            {
                "id": "11111111",
                "source": "MED",
                "pmid": "11111111",
                "doi": "10.1000/adapt",
                "title": "Efgartigimod in generalised myasthenia gravis",
                "pubYear": "2021",
                "isOpenAccess": "Y",
                "abstractText": "<h4>Background</h4>Short.",
                "pubTypeList": {"pubType": ["Randomized Controlled Trial", "Journal Article"]},
            },
            {
                "id": "PPR123456",
                "source": "PPR",
                "doi": "10.1101/2024.01.01.000001",
                "title": "Real-world efgartigimod in myasthenia gravis (preprint)",
                "pubYear": "2024",
                "abstractText": "<h4>Objective</h4>We describe real-world efgartigimod use in 45 "
                "patients with myasthenia gravis.<h4>Results</h4>MG-ADL improved by 4.5 points in "
                "myasthenia gravis patients treated with efgartigimod over 12 weeks.",
                "pubTypeList": {"pubType": ["Preprint"]},
                "authorList": {
                    "author": [{"fullName": "Iota J", "lastName": "Iota", "initials": "J"}]
                },
            },
            {
                "id": "PMC7777777",
                "source": "PMC",
                "pmcid": "PMC7777777",
                "doi": "10.1000/SR",
                "title": "FcRn antagonists in myasthenia gravis: a systematic review",
                "pubYear": "2023",
                "isOpenAccess": "Y",
                "abstractText": "Short duplicate.",
            },
            {
                "id": "PMC8888888",
                "source": "PMC",
                "pmcid": "PMC8888888",
                "doi": "10.1000/cohort",
                "title": "Long-term efgartigimod in myasthenia gravis: a retrospective cohort",
                "pubYear": "2025",
                "isOpenAccess": "Y",
                "journalInfo": {"volume": "3", "journal": {"isoabbreviation": "Neuromuscul Rep"}},
                "abstractText": "<h4>Objective</h4>To assess long-term efgartigimod treatment in "
                "myasthenia gravis.<h4>Results</h4>Among 89 patients with generalized myasthenia "
                "gravis treated with efgartigimod, 61% achieved minimal symptom expression at 52 "
                "weeks.<h4>Conclusion</h4>Efgartigimod sustained benefit in routine myasthenia "
                "gravis care.",
            },
        ]
    },
}


@pytest.fixture
def red_falsa(monkeypatch):
    """Sustituye la red: esearch/efetch/Europe PMC responden con los fixtures."""
    estado = {"terms": [], "epmc_query": None, "epmc_falla": False, "count_por_term": None}

    def _get(url, params, **_kw):
        if "esearch" in url:
            term = params["term"]
            estado["terms"].append(term)
            if estado["count_por_term"]:
                total = estado["count_por_term"](term)
            else:
                total = 4
            ids = ["44444444"] if "systematic review[pt]" in term else list(ARTICULOS)
            ids = ids if total else []
            return json.dumps({"esearchresult": {"count": str(total), "idlist": ids}}).encode()
        if "efetch" in url:
            return _xml(params["id"].split(","))
        if "europepmc" in url:
            estado["epmc_query"] = params["query"]
            if estado["epmc_falla"]:
                raise CORE.ErrorRed("GET www.ebi.ac.uk falló: simulado")
            return json.dumps(EPMC).encode()
        raise AssertionError(f"URL inesperada: {url} {urllib.parse.urlencode(params)}")

    monkeypatch.setattr(CORE, "_http_get", _get)
    monkeypatch.setattr(CORE, "_esperar_ncbi", lambda _k: None)
    return estado


def _paquete_base():
    regs = CORE.fusionar(
        CORE.parse_pubmed_xml(_xml(ARTICULOS)),
        [CORE.parse_europepmc(r) for r in EPMC["resultList"]["result"]],
    )
    sel, _ = CORE.rankear(
        regs, "efgartigimod in myasthenia gravis", "efgartigimod myasthenia gravis", 10, 2026
    )
    metricas = {
        "fecha": "2026-11-09T10:00:00-03:00",
        "fuentes_consultadas": ["PubMed (NCBI E-utilities)", "Europe PMC"],
        "queries_pubmed": [
            {"estrato": "general", "term": "efgartigimod", "total": 4, "recuperados": 4}
        ],
        "candidatos": len(regs),
        "excluidos": {},
        "seleccionados": len(sel),
    }
    return CORE.Paquete("¿Efgartigimod es eficaz?", "efgartigimod", sel, metricas)


RESPUESTA_OK = """# ¿Efgartigimod es eficaz en MG generalizada?

## Respuesta breve

Sí: en un ECA fase 3 con 167 pacientes, el 68% de los tratados con efgartigimod fue respondedor \
en MG-ADL frente al 30% con placebo [PMID:11111111]. Un metaanálisis de 12 ensayos confirma el \
beneficio de los antagonistas de FcRn sobre la MG-ADL [PMID:44444444].

**Certeza de la evidencia:** moderada — un ECA grande y un metaanálisis consistentes.

## Síntesis de la evidencia

- La diferencia de respondedores fue significativa, con odds ratio 4,95 [PMID:11111111].
- En práctica clínica, el 61% alcanzó expresión mínima de síntomas a 52 semanas \
[EPMC:PMC8888888].

## Estudios clave

| Cita | Diseño | Población / n | Hallazgo principal |
|------|--------|---------------|--------------------|
| [PMID:11111111] | ECA fase 3 | MG generalizada, n=167 | 68% vs 30% respondedores |

## Consistencia, controversias y vacíos

- No hay comparaciones directas entre antagonistas de FcRn.

## Certeza y limitaciones

- Basado solo en abstracts de acceso libre.
"""


# ----------------------------------------------------------------------------------- parsers


def test_parse_pubmed_xml():
    regs = {r.pmid: r for r in CORE.parse_pubmed_xml(_xml(ARTICULOS))}
    rct = regs["11111111"]
    assert rct.id == "PMID:11111111"
    assert (rct.pmcid, rct.doi, rct.anio, rct.revista) == (
        "PMC9999999",
        "10.1000/adapt",
        2021,
        "Lancet Neurol",
    )
    assert rct.texto_completo_libre and not rct.retractada
    assert [s.label for s in rct.secciones] == [
        "Background",
        "Methods",
        "Findings",
        "Interpretation",
        "Funding",  # se conserva: sirve para valorar sesgo por financiamiento
    ]
    assert regs["22222222"].retractada


def test_parse_europepmc_secciones_y_preprint():
    regs = [CORE.parse_europepmc(r) for r in EPMC["resultList"]["result"]]
    pre = next(r for r in regs if r.preprint)
    assert pre.id == "EPMC:PPR123456"
    cohorte = next(r for r in regs if r.id == "EPMC:PMC8888888")
    assert [s.label for s in cohorte.secciones] == ["Objective", "Results", "Conclusion"]
    assert cohorte.texto_completo_libre and cohorte.revista == "Neuromuscul Rep"


def test_fusion_por_pmid_y_doi():
    fus = CORE.fusionar(
        CORE.parse_pubmed_xml(_xml(ARTICULOS)),
        [CORE.parse_europepmc(r) for r in EPMC["resultList"]["result"]],
    )
    ids = [r.id for r in fus]
    assert ids.count("PMID:11111111") == 1
    rct = next(r for r in fus if r.pmid == "11111111")
    assert rct.fuentes == ["pubmed", "europepmc"]
    rs = next(r for r in fus if r.pmid == "44444444")  # fusionado por DOI (sin distinguir caso)
    assert rs.pmcid == "PMC7777777" and rs.texto_completo_libre
    assert "EPMC:PMC7777777" not in ids
    assert len(fus) == 6


# ----------------------------------------------------------------------------------- análisis


@pytest.mark.parametrize(
    ("titulo", "tipos", "preprint", "esperado"),
    [
        ("A randomised, placebo-controlled trial", ["Journal Article"], False, 0.80),
        ("FcRn antagonists: a systematic review and meta-analysis", ["Review"], False, 0.90),
        ("Practice update", ["Practice Guideline"], False, 1.00),
        ("A retrospective cohort of MG", ["Journal Article"], False, 0.50),
        ("Post-hoc analyses from the ADAPT study", ["Randomized Controlled Trial"], False, 0.65),
        ("Drug X in MG: A Profile of Its Use", ["Randomized Controlled Trial"], False, 0.45),
        ("sEMG in ALS: A protocol for a systematic review", ["Journal Article"], False, 0.15),
        ("Riluzole prolongs survival in mice with ALS", ["Journal Article"], False, 0.20),
        (
            "Drug A vs B: indirect treatment comparison",
            ["Randomized Controlled Trial"],
            False,
            0.65,
        ),
        ("Opinion", ["Editorial"], False, 0.15),
        ("Anything", ["Preprint"], True, 0.20),
        ("Plain study", ["Journal Article"], False, 0.45),
    ],
)
def test_clasificar(titulo, tipos, preprint, esperado):
    r = CORE.Registro(id="x", titulo=titulo, abstract="", tipos=tipos, preprint=preprint)
    assert CORE.clasificar(r)[1] == esperado


def test_tokens_y_bm25():
    assert CORE.tokens("Myasthenia gravis patients") == ["myasthenia", "gravis"]
    assert "mg" in CORE.tokens("MG-ADL") and "adl" in CORE.tokens("MG-ADL")
    docs = [CORE.tokens("efgartigimod myasthenia trial"), CORE.tokens("sodium blood pressure")]
    s = CORE.bm25(docs, CORE.tokens("efgartigimod myasthenia"))
    assert s[0] > 0 and s[1] == 0


def test_rankear_excluye_y_extrae():
    p = _paquete_base()
    ids = [r.id for r in p.registros]
    assert "PMID:22222222" not in ids  # retractada
    assert "PMID:33333333" not in ids  # irrelevante
    assert ids[0] in {"PMID:11111111", "PMID:44444444"}  # alta evidencia y relevante primero
    rct = p.por_id()["PMID:11111111"]
    assert rct.n_muestra == 167 and rct.estimadores
    assert any("68%" in o for o in rct.resultados_clave)
    assert "well tolerated" in rct.conclusion
    rs = p.por_id()["PMID:44444444"]
    assert (rs.n_estudios, rs.n_muestra, rs.nivel) == (12, 1234, 0.90)
    pre = p.por_id()["EPMC:PPR123456"]
    assert pre.nivel == 0.20 and ids.index(pre.id) > ids.index("PMID:11111111")


def test_n_muestra_ignora_cribado():
    r = CORE.Registro(
        id="x",
        titulo="t",
        abstract="Of the 35 screened patients, 24 were enrolled and randomized to drug or placebo.",
    )
    CORE.analizar(r, set())
    assert r.n_muestra is None
    r.abstract = "Of 35 screened patients, 24 patients were randomized; n = 12 per arm."
    CORE.analizar(r, set())
    assert r.n_muestra == 24


def test_oraciones_respeta_abreviaturas():
    texto = "Fue 35% vs. 10% en ELA [PMID:1]. Smith et al. 2020 lo replicó. Luego cayó."
    assert CORE.oraciones(texto) == [
        "Fue 35% vs. 10% en ELA [PMID:1].",
        "Smith et al. 2020 lo replicó.",
        "Luego cayó.",
    ]


def test_verificar_controla_cifras_tras_vs():
    p = _paquete_base()
    texto = RESPUESTA_OK.replace(
        "con odds ratio 4,95 [PMID:11111111].",
        "con respondedores 68% vs. 31% [PMID:11111111].",
    )
    v = CORE.verificar(texto, p)
    assert v.cobertura == 1.0
    assert [c["cifra"] for c in v.cifras_sin_respaldo] == ["31%"]


def test_rankear_descarta_versiones_anteriores():
    base = "Riluzole for amyotrophic lateral sclerosis (ALS)/motor neuron disease (MND)."
    abstract = "Riluzole in amyotrophic lateral sclerosis prolonged survival in trials. " * 4
    regs = [
        CORE.Registro(id=f"PMID:{i}", pmid=str(i), titulo=base, abstract=abstract, anio=anio)
        for i, anio in [(17253460, 2007), (22419278, 2012), (11687111, 2001)]
    ]
    sel, excl = CORE.rankear(regs, "riluzole survival", "riluzole amyotrophic", 5, 2026)
    assert [r.id for r in sel] == ["PMID:22419278"] and excl["versiones_anteriores"] == 2


def test_espanol_sin_query_falla_antes_de_buscar():
    with pytest.raises(ValueError, match="--query"):
        CORE.construir_paquete("¿El riluzol prolonga la supervivencia en la ELA?", None)


def test_construir_query_y_aviso_espanol():
    q, avisos = CORE.construir_query(
        "Does efgartigimod improve MG-ADL in generalized myasthenia gravis?"
    )
    assert q == "efgartigimod improve MG-ADL generalized myasthenia gravis" and not avisos
    _, avisos_es = CORE.construir_query("¿Es efectivo el efgartigimod en la miastenia gravis?")
    assert avisos_es and "inglés" in avisos_es[0]


@pytest.mark.parametrize(
    "texto",
    [
        "paciente RUT 12.345.678-9 con MG",
        "escribir a juan.perez@hospital.cl",
        "nacido el 03/05/1960 con debilidad",
        "ficha 1234567 con miastenia",
        "llamar al +56 9 8765 4321",
    ],
)
def test_privacidad_bloquea(texto):
    with pytest.raises(CORE.ErrorPrivacidad):
        CORE.chequear_privacidad(texto)


def test_privacidad_permite_pregunta_general():
    CORE.chequear_privacidad("¿Efgartigimod en MG generalizada AChR+ entre 2015 y 2024? n=167")


# ----------------------------------------------------------------------------------- búsqueda


def test_construir_paquete_e2e(red_falsa, tmp_path):
    cfg = CORE.Config(n=5, candidatos=20)
    query = '"myasthenia gravis"[MeSH Terms] AND efgartigimod'
    p = CORE.construir_paquete("Does efgartigimod work in myasthenia gravis?", query, cfg)
    assert p.registros and all(not r.retractada for r in p.registros)
    m = p.metricas
    assert [q["estrato"] for q in m["queries_pubmed"]] == ["general", "alta_evidencia"]
    assert (
        "hasabstract[text]" in red_falsa["terms"][0] and "NOT preprint[pt]" in red_falsa["terms"][0]
    )
    assert "NOT SRC:PPR" in red_falsa["epmc_query"] and "[MeSH" not in red_falsa["epmc_query"]
    assert m["excluidos"]["retractadas"] == 1 and m["seleccionados"] == len(p.registros)

    out = CORE.guardar_paquete(p, tmp_path / "pq")
    assert CORE.cargar_paquete(out).ids() == p.ids()
    md = (out / "evidencia.md").read_text(encoding="utf-8")
    assert "## Resumen del paquete" in md and "[PMID:11111111]" in md
    assert "**Findings:**" in md


def test_relaja_query_sin_resultados(red_falsa):
    red_falsa["count_por_term"] = lambda term: 0 if "improve" in term else 4
    p = CORE.construir_paquete(
        "q", "efgartigimod improve myasthenia", CORE.Config(n=5, candidatos=20)
    )
    assert p.metricas["query_efectiva"] == "efgartigimod myasthenia"
    assert any("se relaja" in a for a in p.metricas["avisos"])
    assert p.registros


def test_europepmc_caido_degrada(red_falsa):
    red_falsa["epmc_falla"] = True
    p = CORE.construir_paquete("q", "efgartigimod myasthenia", CORE.Config(n=5, candidatos=20))
    assert p.registros and all("pubmed" in r.fuentes for r in p.registros)
    assert any("Europe PMC no disponible" in a for a in p.metricas["avisos"])


# ----------------------------------------------------------------------------------- verificación


def test_verificar_respuesta_correcta():
    p = _paquete_base()
    v = CORE.verificar(RESPUESTA_OK, p)
    assert v.ok, CORE.informe_verificacion(v)
    assert v.citas_fuera_del_paquete == [] and v.cobertura == 1.0
    assert v.cifras_sin_respaldo == []  # 4,95 (coma decimal) coincide con 4.95
    assert v.citas_validas == ["PMID:11111111", "PMID:44444444", "EPMC:PMC8888888"]


def test_verificar_rechaza_cita_inventada():
    p = _paquete_base()
    v = CORE.verificar(RESPUESTA_OK.replace("PMID:44444444", "PMID:99999999"), p)
    assert not v.ok and v.citas_fuera_del_paquete == ["PMID:99999999"]


def test_verificar_cifras_sin_respaldo_y_estricto():
    p = _paquete_base()
    texto = RESPUESTA_OK.replace("el 68% de los tratados", "el 75% de los tratados").replace(
        "68% vs 30% respondedores", "80% vs 30% respondedores"
    )
    v = CORE.verificar(texto, p)
    assert v.ok  # no estricto: avisa pero no rechaza
    assert {c["cifra"] for c in v.cifras_sin_respaldo} == {"75%", "80%"}
    assert not CORE.verificar(texto, p, estricto=True).ok


def test_verificar_calculo_propio_y_cobertura():
    p = _paquete_base()
    extra = (
        "\n- La diferencia absoluta fue de 38 puntos porcentuales (cálculo propio) [PMID:11111111].\n"
        "- Esto cambiará la práctica clínica en todos los centros del país.\n"
    )
    texto = RESPUESTA_OK.replace("## Estudios clave", extra + "\n## Estudios clave")
    v = CORE.verificar(texto, p)
    assert v.cifras_sin_respaldo == []
    assert any("práctica clínica" in o for o in v.oraciones_sin_cita)
    assert v.cobertura < 1.0


def test_verificar_secciones_obligatorias():
    p = _paquete_base()
    v = CORE.verificar(RESPUESTA_OK.replace("## Síntesis de la evidencia", "## Otra cosa"), p)
    assert not v.ok and v.secciones_faltantes == ["sintesis de la evidencia"]


def test_vancouver_y_referencias():
    p = _paquete_base()
    rct = p.por_id()["PMID:11111111"]
    assert CORE.vancouver(rct) == (
        "Alfa AB, Beta C, Gamma D, Delta E, Epsilon F, Zeta G, et al. Efgartigimod in "
        "generalised myasthenia gravis: a randomised, placebo-controlled, phase 3 trial. "
        "Lancet Neurol. 2021;20(7):526-536. doi:10.1000/adapt. PMID: 11111111. "
        "PMCID: PMC9999999."
    )
    v = CORE.verificar(RESPUESTA_OK, p)
    final = CORE.anexar_referencias(RESPUESTA_OK, p, v)
    assert "## Referencias" in final and "## Métricas de búsqueda" in final
    assert "1. [PMID:11111111] Alfa AB" in final and "3. [EPMC:PMC8888888]" in final
    assert CORE.verificar(final, p).ok  # re-verificar la final ignora la sección Referencias


# ----------------------------------------------------------------------------------- modo LLM


def test_redactar_con_llm_ronda_de_correccion():
    p = _paquete_base()
    sistemas, usuarios = [], []

    def llm(sistema, usuario):
        sistemas.append(sistema)
        usuarios.append(usuario)
        if len(usuarios) == 1:
            return RESPUESTA_OK.replace("PMID:44444444", "PMID:99999999")
        return RESPUESTA_OK

    texto, v = CORE.redactar_con_llm(p, llm)
    assert v.ok and texto == RESPUESTA_OK and len(usuarios) == 2
    assert "## Reglas" in sistemas[0]  # formato_respuesta.md como prompt de sistema
    assert "PMID:99999999" in usuarios[1] and "verificador" in usuarios[1]


def test_generar_query_llm():
    q = CORE.generar_query_llm(
        "¿sirve?", lambda s, u: 'Claro: {"pubmed": "efgartigimod AND myasthenia gravis"}'
    )
    assert q == "efgartigimod AND myasthenia gravis"
    with pytest.raises(CORE.ErrorLLM):
        CORE.generar_query_llm("¿sirve?", lambda s, u: "no sé")


def _anthropic_falso(stop_reason="end_turn"):
    """Módulo `anthropic` mínimo para comprobar la forma de la llamada sin red."""
    mod = types.ModuleType("anthropic")
    llamadas = []

    class AnthropicError(Exception):
        pass

    class APIConnectionError(AnthropicError):
        pass

    class APIStatusError(AnthropicError):
        status_code, message = 500, "x"

    class AuthenticationError(APIStatusError):
        pass

    class RateLimitError(APIStatusError):
        pass

    for cls in (
        AnthropicError,
        APIConnectionError,
        APIStatusError,
        AuthenticationError,
        RateLimitError,
    ):
        setattr(mod, cls.__name__, cls)

    class _Stream:
        def __init__(self, kwargs):
            llamadas.append(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get_final_message(self):
            bloque = types.SimpleNamespace(type="text", text="respuesta del modelo")
            return types.SimpleNamespace(stop_reason=stop_reason, content=[bloque])

    class Anthropic:
        def __init__(self):
            ns = types.SimpleNamespace
            self.messages = ns(stream=lambda **kw: _Stream({"ruta": "messages", **kw}))
            self.beta = ns(messages=ns(stream=lambda **kw: _Stream({"ruta": "beta", **kw})))

    mod.Anthropic = Anthropic
    return mod, llamadas


def test_llamar_claude_forma_de_la_llamada(monkeypatch):
    mod, llamadas = _anthropic_falso()
    monkeypatch.setitem(sys.modules, "anthropic", mod)
    assert CORE.llamar_claude("sis", "usr", "claude-opus-5-5") == "respuesta del modelo"
    k = llamadas[-1]
    assert k["ruta"] == "beta" and k["fallbacks"] == "default"
    assert k["betas"] == ["server-side-fallback-2026-07-01"]
    assert k["output_config"] == {"effort": "high"} and k["system"] == "sis"
    assert k["messages"] == [{"role": "user", "content": "usr"}]

    CORE.llamar_claude("sis", "usr", "claude-haiku-4-5")
    k = llamadas[-1]
    assert k["ruta"] == "messages" and "output_config" not in k and "fallbacks" not in k


def test_llamar_claude_sin_credenciales(monkeypatch):
    mod, _ = _anthropic_falso()

    class SinCredencial:
        def __init__(self):
            def _falla(**_kw):
                raise TypeError('"Could not resolve authentication method. Expected api_key"')

            ns = types.SimpleNamespace
            self.messages = ns(stream=_falla)
            self.beta = ns(messages=ns(stream=_falla))

    mod.Anthropic = SinCredencial
    monkeypatch.setitem(sys.modules, "anthropic", mod)
    with pytest.raises(CORE.ErrorLLM, match="credencial"):
        CORE.llamar_claude("sis", "usr", "claude-opus-5-5")


def test_llamar_claude_rechazo(monkeypatch):
    mod, _ = _anthropic_falso(stop_reason="refusal")
    monkeypatch.setitem(sys.modules, "anthropic", mod)
    with pytest.raises(CORE.ErrorLLM):
        CORE.llamar_claude("sis", "usr", "claude-opus-5-5")


# ----------------------------------------------------------------------------------- CLI y harness


def test_cli_buscar_y_verificar(red_falsa, tmp_path, capsys):
    out = tmp_path / "salida"
    rc = CORE.main(
        [
            "buscar",
            "¿Efgartigimod es eficaz en MG?",
            "--query",
            "efgartigimod myasthenia gravis",
            "--out",
            str(out),
            "--candidatos",
            "20",
        ]
    )
    assert rc == 0 and (out / "evidencia.json").exists()
    (out / "respuesta.md").write_text(
        RESPUESTA_OK.replace("PMID:44444444", "PMID:99999999"), encoding="utf-8"
    )
    assert CORE.main(["verificar", "--dir", str(out)]) == 1
    assert not (out / "respuesta_final.md").exists()
    (out / "respuesta.md").write_text(RESPUESTA_OK, encoding="utf-8")
    assert CORE.main(["verificar", "--dir", str(out)]) == 0
    assert "## Referencias" in (out / "respuesta_final.md").read_text(encoding="utf-8")
    assert "APROBADA" in capsys.readouterr().out


def test_cli_bloquea_phi(capsys):
    assert CORE.main(["buscar", "MG en paciente RUT 12.345.678-9"]) == 2
    assert "R8" in capsys.readouterr().err


def test_registro_en_harness():
    nombres = []

    class Reg:
        def register(self, name, description, schema, fn):
            nombres.append(name)
            assert schema["type"] == "object" and callable(fn) and description

    TOOL.register_skill(Reg())
    assert nombres == ["pubmed_qa", "pubmed_qa_verificar"]


def test_tool_flujo_completo(red_falsa, tmp_path, monkeypatch):
    monkeypatch.setattr(CORE, "DEFAULT_OUT_BASE", tmp_path / "cache")
    salida = TOOL.pubmed_qa(
        {"pregunta": "¿Efgartigimod es eficaz?", "query": "efgartigimod myasthenia gravis"}
    )
    assert "[PMID:11111111]" in salida and "## Reglas" in salida
    ruta = salida.rsplit("Paquete guardado en: ", 1)[1].splitlines()[0]
    final = TOOL.pubmed_qa_verificar({"respuesta": RESPUESTA_OK, "paquete": ruta})
    assert "APROBADA" in final and "## Referencias" in final
    assert TOOL.pubmed_qa_verificar({"respuesta": "x", "paquete": "/etc"}).startswith(
        "ERROR: el paquete debe"
    )
    assert TOOL.pubmed_qa({"pregunta": "RUT 12.345.678-9"}).startswith("ERROR")
