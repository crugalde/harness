#!/usr/bin/env python3
"""pubmed_qa.py — Responde preguntas científicas con evidencia de abstracts de acceso libre.

Pipeline de la skill `pubmed_qa`:

    pregunta -> query (PubMed + Europe PMC) -> abstracts -> ranking (BM25 x nivel de evidencia)
    -> paquete de evidencia -> síntesis con citas [PMID:x] -> verificación anti-alucinación (R2)

Buscar, rankear y verificar usan solo la biblioteca estándar. La síntesis la redacta el agente
que ejecuta la skill (modo por defecto, siguiendo references/formato_respuesta.md) o la API de
Anthropic con --llm (requiere `pip install anthropic`).

Uso:
    # 1) Paquete de evidencia (luego el agente redacta respuesta.md en --out)
    python3 skills/pubmed_qa/scripts/pubmed_qa.py buscar \\
        "¿Efgartigimod mejora la MG-ADL en miastenia gravis generalizada?" \\
        --query "efgartigimod generalized myasthenia gravis" --out /ruta/salida

    # 2) Verificar la respuesta: citas existentes en el paquete + cifras presentes en los
    #    abstracts citados. Si pasa, escribe respuesta_final.md con referencias Vancouver.
    python3 skills/pubmed_qa/scripts/pubmed_qa.py verificar --dir /ruta/salida

    # Todo en uno con la API de Anthropic (redacta + verifica + 1 ronda de corrección)
    python3 skills/pubmed_qa/scripts/pubmed_qa.py buscar "pregunta" --llm --out /ruta/salida

Variables de entorno (opcionales; se cargan también desde ~/.config/harness/.env):
    ENTREZ_EMAIL       correo de contacto para NCBI (recomendado por sus términos de uso)
    NCBI_API_KEY       sube el rate limit de NCBI de 3 a 10 req/s
    PUBMED_QA_MODEL    modelo para --llm (si falta: HARNESS_MODEL, y si no claude-opus-5-5)
    ANTHROPIC_API_KEY  credencial para --llm (o un perfil de `ant auth login`)

Exit codes: 0 OK · 1 sin resultados o verificación fallida · 2 error de uso, red o API.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import importlib.util
import json
import logging
import math
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

log = logging.getLogger("pubmed_qa")

SKILL_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = SKILL_DIR.parent.parent
FORMATO_RESPUESTA = SKILL_DIR / "references" / "formato_respuesta.md"
DEFAULT_OUT_BASE = Path.home() / ".cache" / "harness" / "pubmed_qa"

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
EPMC_SEARCH = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
USER_AGENT = "harness-pubmed_qa/1.0 (skill de preguntas científicas; Python urllib)"
TOOL_NAME = "harness_pubmed_qa"

MODELO_DEFAULT = "claude-opus-5-5"
# Modelos que aceptan output_config.effort / el fallback server-side por defecto.
_CON_EFFORT = (
    "claude-opus-4-6",
    "claude-opus-4-7",
    "claude-opus-4-8",
    "claude-opus-5",
    "claude-fable-5",
    "claude-mythos-5",
    "claude-sonnet-4-6",
    "claude-sonnet-5",
    "claude-haiku-5-5",
)
_CON_FALLBACK = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}

LLMFn = Callable[[str, str], str]  # (sistema, usuario) -> texto


class ErrorRed(RuntimeError):
    """Fallo de red o de un servicio remoto (NCBI, Europe PMC)."""


class ErrorLLM(RuntimeError):
    """Fallo al llamar al modelo (credenciales, rate limit, rechazo)."""


class ErrorPrivacidad(ValueError):
    """La pregunta parece contener datos identificables de un paciente (R8)."""


# =============================================================================== modelo de datos


@dataclass
class Seccion:
    label: str
    texto: str


@dataclass
class Registro:
    id: str  # "PMID:123" o "EPMC:PPR123" — es la cita que se usa en la respuesta
    titulo: str
    abstract: str
    pmid: str = ""
    pmcid: str = ""
    doi: str = ""
    revista: str = ""
    anio: int | None = None
    volumen: str = ""
    numero: str = ""
    paginas: str = ""
    autores: list[str] = field(default_factory=list)
    tipos: list[str] = field(default_factory=list)
    idioma: str = ""
    secciones: list[Seccion] = field(default_factory=list)
    fuentes: list[str] = field(default_factory=list)
    texto_completo_libre: bool = False
    preprint: bool = False
    retractada: bool = False
    # --- calculados por analizar() / rankear()
    diseno: str = ""
    nivel: float = 0.0
    relevancia: float = 0.0
    puntaje: float = 0.0
    n_muestra: int | None = None
    n_estudios: int | None = None
    estimadores: bool = False
    conclusion: str = ""
    resultados_clave: list[str] = field(default_factory=list)

    @property
    def url(self) -> str:
        if self.pmid:
            return f"https://pubmed.ncbi.nlm.nih.gov/{self.pmid}/"
        if self.doi:
            return f"https://doi.org/{self.doi}"
        return f"https://europepmc.org/search?query={urllib.parse.quote(self.id.split(':', 1)[-1])}"

    @property
    def url_texto_completo(self) -> str:
        return f"https://www.ncbi.nlm.nih.gov/pmc/articles/{self.pmcid}/" if self.pmcid else ""

    @classmethod
    def desde_dict(cls, d: dict) -> Registro:
        d = dict(d)
        d["secciones"] = [Seccion(**s) for s in d.get("secciones", [])]
        conocidos = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in conocidos})


@dataclass
class Config:
    n: int = 10  # fuentes que entran al paquete de evidencia
    candidatos: int = 60  # registros PubMed a evaluar (Europe PMC aporta ~la mitad)
    desde: int = 2000
    hasta: int | None = None
    europepmc: bool = True
    preprints: bool = False
    email: str = ""
    api_key: str = ""

    @classmethod
    def desde_entorno(cls, **kw) -> Config:
        cfg = cls(**kw)
        cfg.email = cfg.email or os.environ.get("ENTREZ_EMAIL", "")
        cfg.api_key = cfg.api_key or os.environ.get("NCBI_API_KEY", "")
        return cfg


@dataclass
class Paquete:
    pregunta: str
    query: str
    registros: list[Registro]
    metricas: dict

    def ids(self) -> set[str]:
        return {r.id for r in self.registros}

    def por_id(self) -> dict[str, Registro]:
        return {r.id: r for r in self.registros}

    def a_dict(self) -> dict:
        return {
            "version": 1,
            "pregunta": self.pregunta,
            "query": self.query,
            "metricas": self.metricas,
            "registros": [asdict(r) for r in self.registros],
        }

    @classmethod
    def desde_dict(cls, d: dict) -> Paquete:
        return cls(
            pregunta=d["pregunta"],
            query=d.get("query", ""),
            registros=[Registro.desde_dict(r) for r in d.get("registros", [])],
            metricas=d.get("metricas", {}),
        )


# =============================================================================== privacidad (R8)

_PHI = [
    (re.compile(r"\b\d{1,2}\.?\d{3}\.?\d{3}-[\dkK]\b"), "RUT"),
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"), "correo electrónico"),
    (re.compile(r"(?:\+?56\s?)?\b9\s?\d{4}\s?\d{4}\b"), "teléfono"),
    (re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-](?:19|20)\d{2}\b"), "fecha completa"),
    (
        re.compile(
            r"\b(?:ficha|rut|nhc|historia cl[ií]nica)\s*(?:n[°º.]?|#|:)?\s*\d{4,}", re.IGNORECASE
        ),
        "número de ficha",
    ),
]


def chequear_privacidad(texto: str) -> None:
    """Bloquea preguntas con identificadores directos de pacientes antes de enviarlas a
    servicios externos (R8). No sustituye la de-identificación: es una red de seguridad."""
    hallados = sorted({nombre for rx, nombre in _PHI if rx.search(texto)})
    if hallados:
        raise ErrorPrivacidad(
            "La pregunta parece contener datos identificables (" + ", ".join(hallados) + "). "
            "De-identifica el caso y formula la pregunta en términos generales (R8)."
        )


# =============================================================================== texto


def _sin_tildes(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def _ahora() -> dt.datetime:
    """Hora local con zona horaria explícita."""
    return dt.datetime.now(dt.timezone.utc).astimezone()


def _limpio(s: str | None) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _texto_xml(el: ET.Element | None) -> str:
    return _limpio("".join(el.itertext())) if el is not None else ""


def _palabras(texto: str) -> set[str]:
    return set(texto.split())


STOP = _palabras(
    # inglés
    """a an and are as at be been being but by can could did do does for from had has have how
    if in into is it its may might more most no not of on or over should than that the their them
    then there these this those to was were what when where which while who whom why will with
    within without would vs versus among between after before during about compared patients
    patient people study studies evidence"""
    # español
    """ el la los las un una unos unas y o u de del al en con sin por para que qué cual cuál
    cuales cuáles como cómo cuando cuándo donde dónde quien quién es son ser fue fueron está están
    hay se su sus lo le les mas más menos muy entre sobre según tiene tienen puede pueden existe
    existen algun algún alguna mejor peor respecto frente versus pacientes paciente estudio
    estudios evidencia"""
)
STOP |= {_sin_tildes(w) for w in STOP}
# Términos que restringen demasiado una query AND en PubMed; se quitan al relajar.
GENERICOS = _palabras(
    """effect effects effective effectiveness efficacy efficacious improve improves improved
    outcome outcomes use used useful usefulness role treatment therapy benefit benefits associated
    association risk value utility accuracy reliable reliability safe safety better best efecto
    efectos eficaz eficacia efectivo efectividad mejora mejoran utilidad útil util rol papel
    tratamiento terapia beneficio asociación riesgo valor seguro seguridad"""
)
_ES_MARCAS = re.compile(
    r"[ñ¿¡áéíóú]|\b(?:el|los|las|del|que|qué|cuál|cómo|para|con|es|son|una|existe|sirve)\b",
    re.IGNORECASE,
)
_TOKEN = re.compile(r"[a-z0-9][a-z0-9\-]*")


def parece_espanol(texto: str) -> bool:
    return len(_ES_MARCAS.findall(texto)) >= 2


def _stem(tok: str) -> str:
    if len(tok) > 4 and tok.endswith("ies"):
        return tok[:-3] + "y"
    if len(tok) > 3 and tok.endswith("s") and not tok.endswith(("ss", "us", "is")):
        return tok[:-1]
    return tok


def tokens(texto: str) -> list[str]:
    """Tokens normalizados (minúsculas, sin tildes, sin stopwords, plural simple)."""
    out: list[str] = []
    for tok in _TOKEN.findall(_sin_tildes(texto.lower())):
        tok = tok.strip("-")
        partes = [tok] + (tok.split("-") if "-" in tok else [])
        for p in partes:
            if len(p) >= 2 and p not in STOP:
                out.append(_stem(p))
    return out


_ORACION = re.compile(r"(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÑ¿¡(\[0-9])")


_ABREVIATURA_FINAL = re.compile(
    r"(?:\bvs|\be\.g|\bi\.e|\bet al|\bapprox|\baprox|\bfigs?|\bref|\bp\.\s?ej|\bcf|\bca)\.$",
    re.IGNORECASE,
)


def oraciones(texto: str) -> list[str]:
    """Divide en oraciones sin cortar tras abreviaturas ("35% vs. 10%", "et al. 2020")."""
    out: list[str] = []
    for parte in (o.strip() for o in _ORACION.split(texto)):
        if not parte:
            continue
        if out and _ABREVIATURA_FINAL.search(out[-1]):
            out[-1] += " " + parte
        else:
            out.append(parte)
    return out


# =============================================================================== red


_ultimo_ncbi = 0.0


def _esperar_ncbi(api_key: str) -> None:
    """Respeta el rate limit de NCBI (3 req/s sin clave, 10 con clave), con margen."""
    global _ultimo_ncbi
    pausa = 0.11 if api_key else 0.35
    transcurrido = time.monotonic() - _ultimo_ncbi
    if transcurrido < pausa:
        time.sleep(pausa - transcurrido)
    _ultimo_ncbi = time.monotonic()


def _http_get(url: str, params: dict, *, intentos: int = 3, timeout: int = 40) -> bytes:
    qs = urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")})
    req = urllib.request.Request(f"{url}?{qs}", headers={"User-Agent": USER_AGENT})
    ultimo: Exception | None = None
    for intento in range(intentos):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            ultimo = exc
            if exc.code in (400, 404):
                break  # error de la petición, no transitorio
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            ultimo = exc
            if "403" in str(exc) or "Tunnel" in str(exc):
                break  # bloqueo de red/proxy: reintentar no ayuda
        if intento < intentos - 1:
            time.sleep(1.5 * 2**intento)
    host = urllib.parse.urlparse(url).netloc
    pista = (
        f" — ¿{host} está permitido en la red de este entorno?"
        if ultimo and ("403" in str(ultimo) or "Tunnel" in str(ultimo))
        else ""
    )
    raise ErrorRed(f"GET {host} falló: {ultimo}{pista}")


# =============================================================================== PubMed


def _ncbi_params(cfg: Config) -> dict:
    return {"tool": TOOL_NAME, "email": cfg.email, "api_key": cfg.api_key}


def pubmed_esearch(term: str, retmax: int, cfg: Config) -> tuple[int, list[str]]:
    _esperar_ncbi(cfg.api_key)
    raw = _http_get(
        f"{EUTILS}/esearch.fcgi",
        {
            "db": "pubmed",
            "term": term,
            "retmax": retmax,
            "sort": "relevance",
            "retmode": "json",
            **_ncbi_params(cfg),
        },
    )
    try:
        res = json.loads(raw).get("esearchresult", {})
    except json.JSONDecodeError as exc:
        raise ErrorRed(f"esearch devolvió JSON inválido: {exc}") from exc
    if "ERROR" in res:
        raise ErrorRed(f"esearch: {res['ERROR']}")
    return int(res.get("count", 0)), list(res.get("idlist", []))


def pubmed_efetch(pmids: list[str], cfg: Config) -> list[Registro]:
    regs: list[Registro] = []
    for i in range(0, len(pmids), 100):
        _esperar_ncbi(cfg.api_key)
        raw = _http_get(
            f"{EUTILS}/efetch.fcgi",
            {
                "db": "pubmed",
                "id": ",".join(pmids[i : i + 100]),
                "retmode": "xml",
                **_ncbi_params(cfg),
            },
        )
        regs.extend(parse_pubmed_xml(raw))
    return regs


def _anio(texto: str) -> int | None:
    m = re.search(r"(19|20)\d{2}", texto or "")
    return int(m.group(0)) if m else None


# El financiamiento se conserva (sirve para valorar sesgo); solo se descarta el copyright.
_SECCION_RUIDO = re.compile(r"^copyright", re.IGNORECASE)


def parse_pubmed_xml(raw: bytes | str) -> list[Registro]:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ErrorRed(f"efetch devolvió XML inválido: {exc}") from exc
    out: list[Registro] = []
    for art in root.iter("PubmedArticle"):
        cit = art.find("MedlineCitation")
        a = cit.find("Article") if cit is not None else None
        if a is None:
            continue
        pmid = _texto_xml(cit.find("PMID"))
        secciones = [
            Seccion(label=_limpio(at.get("Label", "")).capitalize(), texto=_texto_xml(at))
            for at in a.findall("Abstract/AbstractText")
        ]
        secciones = [s for s in secciones if s.texto and not _SECCION_RUIDO.match(s.label)]
        journal = a.find("Journal")
        ji = journal.find("JournalIssue") if journal is not None else None
        anio = None
        if ji is not None:
            anio = _anio(_texto_xml(ji.find("PubDate/Year"))) or _anio(
                _texto_xml(ji.find("PubDate/MedlineDate"))
            )
        anio = anio or _anio(_texto_xml(a.find("ArticleDate/Year")))
        autores = []
        for au in a.findall("AuthorList/Author"):
            colectivo = _texto_xml(au.find("CollectiveName"))
            apellido = _texto_xml(au.find("LastName"))
            if colectivo:
                autores.append(colectivo)
            elif apellido:
                autores.append(f"{apellido} {_texto_xml(au.find('Initials'))}".strip())
        tipos = [_texto_xml(pt) for pt in a.findall("PublicationTypeList/PublicationType")]
        ids = {
            aid.get("IdType"): _texto_xml(aid)
            for aid in art.findall("PubmedData/ArticleIdList/ArticleId")
        }
        doi = ids.get("doi", "")
        if not doi:
            for loc in a.findall("ELocationID"):
                if loc.get("EIdType") == "doi":
                    doi = _texto_xml(loc)
        retractada = "retracted publication" in {t.lower() for t in tipos} or any(
            c.get("RefType") == "RetractionIn"
            for c in cit.findall("CommentsCorrectionsList/CommentsCorrections")
        )
        pmcid = ids.get("pmc", "")
        out.append(
            Registro(
                id=f"PMID:{pmid}",
                pmid=pmid,
                pmcid=pmcid,
                doi=doi,
                titulo=_texto_xml(a.find("ArticleTitle")),
                abstract=_unir_secciones(secciones),
                secciones=secciones,
                revista=(
                    _texto_xml(journal.find("ISOAbbreviation")) or _texto_xml(journal.find("Title"))
                    if journal is not None
                    else ""
                ),
                anio=anio,
                volumen=_texto_xml(ji.find("Volume")) if ji is not None else "",
                numero=_texto_xml(ji.find("Issue")) if ji is not None else "",
                paginas=_texto_xml(a.find("Pagination/MedlinePgn")),
                autores=autores,
                tipos=tipos,
                idioma=_texto_xml(a.find("Language")),
                fuentes=["pubmed"],
                texto_completo_libre=bool(pmcid),
                preprint="preprint" in {t.lower() for t in tipos},
                retractada=retractada,
            )
        )
    return out


def _unir_secciones(secciones: list[Seccion]) -> str:
    return " ".join(f"{s.label}: {s.texto}" if s.label else s.texto for s in secciones)


# =============================================================================== Europe PMC


def query_europepmc(query: str, cfg: Config) -> str:
    """Adapta una query PubMed a la sintaxis de Europe PMC (sin etiquetas [campo])."""
    q = _limpio(re.sub(r"\[[^\]]*\]", " ", query))
    partes = [f"({q})", "HAS_ABSTRACT:y", f"PUB_YEAR:[{cfg.desde} TO {cfg.hasta or 3000}]"]
    if not cfg.preprints:
        partes.append("NOT SRC:PPR")
    return " AND ".join(partes)


def europepmc_search(query: str, n: int, cfg: Config) -> tuple[int, list[Registro], str]:
    q = query_europepmc(query, cfg)
    raw = _http_get(
        EPMC_SEARCH,
        {"query": q, "format": "json", "resultType": "core", "pageSize": max(1, min(n, 100))},
    )
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ErrorRed(f"Europe PMC devolvió JSON inválido: {exc}") from exc
    resultados = data.get("resultList", {}).get("result", [])
    return int(data.get("hitCount", 0)), [parse_europepmc(r) for r in resultados], q


def _secciones_html(texto_html: str) -> list[Seccion]:
    """Europe PMC marca las secciones del abstract con <h4>Label</h4>."""
    texto_html = texto_html or ""
    partes = re.split(r"<h4>(.*?)</h4>", texto_html, flags=re.IGNORECASE | re.DOTALL)
    secciones: list[Seccion] = []
    if partes and _limpio(re.sub(r"<[^>]+>", " ", partes[0])):
        secciones.append(Seccion(label="", texto=_html_a_texto(partes[0])))
    for i in range(1, len(partes) - 1, 2):
        label, cuerpo = _html_a_texto(partes[i]).rstrip(":"), _html_a_texto(partes[i + 1])
        if cuerpo and not _SECCION_RUIDO.match(label):
            secciones.append(Seccion(label=label.capitalize(), texto=cuerpo))
    return secciones


def _html_a_texto(s: str) -> str:
    return _limpio(html.unescape(re.sub(r"<[^>]+>", " ", s or "")))


def parse_europepmc(r: dict) -> Registro:
    fuente = r.get("source", "")
    rid = str(r.get("id", ""))
    pmid = str(r.get("pmid") or "")
    ident = f"PMID:{pmid}" if pmid else f"EPMC:{rid if rid.startswith(fuente) else fuente + rid}"
    ji = r.get("journalInfo") or {}
    revista = (ji.get("journal") or {}).get("isoabbreviation") or (ji.get("journal") or {}).get(
        "title", ""
    )
    autores = []
    for au in (r.get("authorList") or {}).get("author", []):
        if au.get("collectiveName"):
            autores.append(au["collectiveName"])
        elif au.get("lastName"):
            autores.append(f"{au['lastName']} {au.get('initials', '')}".strip())
        elif au.get("fullName"):
            autores.append(au["fullName"])
    tipos = list((r.get("pubTypeList") or {}).get("pubType", []))
    secciones = _secciones_html(r.get("abstractText", ""))
    preprint = fuente == "PPR" or "preprint" in {t.lower() for t in tipos}
    return Registro(
        id=ident,
        pmid=pmid,
        pmcid=r.get("pmcid") or "",
        doi=r.get("doi") or "",
        titulo=_html_a_texto(r.get("title", "")),
        abstract=_unir_secciones(secciones),
        secciones=secciones,
        revista=revista
        or (r.get("bookOrReportDetails") or {}).get("publisher", "")
        or ("Preprint" if preprint else ""),
        anio=_anio(str(r.get("pubYear", ""))),
        volumen=str(ji.get("volume") or ""),
        numero=str(ji.get("issue") or ""),
        paginas=r.get("pageInfo") or "",
        autores=autores,
        tipos=tipos,
        idioma=r.get("language", ""),
        fuentes=["europepmc"],
        texto_completo_libre=r.get("isOpenAccess") == "Y" or bool(r.get("pmcid")),
        preprint=preprint,
        retractada="retracted publication" in {t.lower() for t in tipos},
    )


# =============================================================================== fusión


def fusionar(*listas: list[Registro]) -> list[Registro]:
    """Une registros de varias fuentes sin duplicar (clave PMID, luego DOI)."""
    out: list[Registro] = []
    indice: dict[str, int] = {}
    for lista in listas:
        for r in lista:
            claves = [
                k
                for k in (
                    f"pmid:{r.pmid}" if r.pmid else "",
                    f"doi:{r.doi.lower()}" if r.doi else "",
                    f"id:{r.id}",
                )
                if k
            ]
            pos = next((indice[k] for k in claves if k in indice), None)
            if pos is None:
                pos = len(out)
                out.append(r)
            else:
                _completar(out[pos], r)
            for k in claves:
                indice.setdefault(k, pos)
    return out


def _completar(base: Registro, otro: Registro) -> None:
    for campo in ("pmid", "pmcid", "doi", "revista", "volumen", "numero", "paginas", "idioma"):
        if not getattr(base, campo) and getattr(otro, campo):
            setattr(base, campo, getattr(otro, campo))
    if base.pmid and base.id.startswith("EPMC:"):
        base.id = f"PMID:{base.pmid}"
    base.anio = base.anio or otro.anio
    base.autores = base.autores or otro.autores
    if len(otro.abstract) > len(base.abstract) * 1.2:
        base.abstract, base.secciones = otro.abstract, otro.secciones
    vistos = {t.lower() for t in base.tipos}
    base.tipos += [t for t in otro.tipos if t.lower() not in vistos]
    base.fuentes += [f for f in otro.fuentes if f not in base.fuentes]
    base.texto_completo_libre = base.texto_completo_libre or otro.texto_completo_libre
    base.retractada = base.retractada or otro.retractada


# =============================================================================== análisis

# (diseño, peso, tipos de publicación exactos, patrones en el título). El orden importa.
NIVELES: tuple[tuple[str, float, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "guía/consenso",
        1.00,
        (
            "guideline",
            "practice guideline",
            "consensus development conference",
            "consensus development conference, nih",
        ),
        (
            r"\bguidelines?\b",
            r"\bconsensus (?:statement|report|recommendations?)\b",
            r"\bposition statement\b",
        ),
    ),
    (
        "revisión sistemática/metaanálisis",
        0.90,
        ("systematic review", "systematic-review", "meta-analysis", "network meta-analysis"),
        (r"\bsystematic(?:al)? review\b", r"\bmeta-?analys[ie]s\b"),
    ),
    # PubMed suele etiquetar como "Randomized Controlled Trial" los análisis secundarios de un
    # ECA; el título los delata y pesan menos que el ensayo primario.
    (
        "análisis secundario de ensayo (post hoc/subgrupos/indirecto)",
        0.65,
        (),
        (
            r"\bpost[- ]?hoc\b",
            r"\bsubgroup analys[ie]s\b",
            r"\bsecondary analys[ie]s\b",
            r"\bexploratory analys[ie]s\b",
            r"\bpooled analys[ie]s\b",
            r"\bindirect (?:treatment )?comparison\b",
            r"\bmatching-adjusted\b",
        ),
    ),
    # Monografías y revisiones con etiqueta de ECA heredada de los ensayos que resumen.
    (
        "revisión narrativa",
        0.45,
        (),
        (r"\bprofile of its use\b", r"\bdrug profile\b", r"\breview\b", r"\boverview\b"),
    ),
    (
        "ensayo controlado aleatorizado",
        0.80,
        (
            "randomized controlled trial",
            "controlled clinical trial",
            "clinical trial, phase iii",
            "clinical trial, phase iv",
            "pragmatic clinical trial",
            "equivalence trial",
        ),
        (r"\brandomi[sz]ed\b", r"\bplacebo-controlled\b"),
    ),
    (
        "ensayo clínico no aleatorizado",
        0.60,
        ("clinical trial", "clinical trial, phase i", "clinical trial, phase ii"),
        (r"\bopen-label\b", r"\bphase (?:1|2|i|ii)[ab]?\b", r"\bsingle-arm\b"),
    ),
    (
        "estudio observacional/diagnóstico",
        0.50,
        (
            "observational study",
            "multicenter study",
            "comparative study",
            "validation study",
            "evaluation study",
            "twin study",
        ),
        (
            r"\bcohort\b",
            r"\bcase-control\b",
            r"\bcross-sectional\b",
            r"\bretrospective\b",
            r"\bprospective\b",
            r"\bdiagnostic accuracy\b",
            r"\bregistry\b",
        ),
    ),
    ("revisión narrativa", 0.45, ("review", "scoping review"), (r"\breview\b",)),
    ("reporte/serie de casos", 0.25, ("case reports",), (r"\bcase reports?\b", r"\bcase series\b")),
)
_BAJO_NIVEL = {
    "editorial": "editorial/carta/comentario",
    "comment": "editorial/carta/comentario",
    "letter": "editorial/carta/comentario",
    "news": "editorial/carta/comentario",
    "published erratum": "fe de erratas",
    "clinical trial protocol": "protocolo (sin resultados)",
}

_N_PAC = re.compile(
    r"(?<![\d.,])(\d{1,3}(?:,\d{3})+|\d+)\s+(?:[a-z\-]+\s+){0,2}?"
    r"(?:patients|participants|subjects|individuals|adults|children|cases|people|persons|"
    r"women|men|volunteers|infants|neonates|controls)\b",
    re.IGNORECASE,
)
_N_IGUAL = re.compile(r"\b[nN]\s*=\s*(\d{1,3}(?:,\d{3})+|\d+)")
_N_EST = re.compile(
    r"(?<![\d.,])(\d+)\s+(?:[a-z\-]+\s+){0,2}?(?:studies|trials|rcts|articles|cohorts)\b",
    re.IGNORECASE,
)
_ESTIMADOR = re.compile(
    r"\b(?:OR|RR|HR|IRR|MD|SMD|WMD|AUC|NNT|sensitivity|specificity|accuracy|"
    r"95\s?%\s?CI|CI\s?95)\b|\bp\s?[<=>≤]\s?0?\.\d",
    re.IGNORECASE,
)
_LABEL_RESULTADOS = re.compile(r"result|finding|main outcome|outcome", re.IGNORECASE)
_LABEL_CONCLUSION = re.compile(r"conclu|interpret|significance|implication", re.IGNORECASE)


_PRECLINICO = re.compile(
    r"\b(?:mice|mouse|murine|rats?|rodents?|zebrafish|drosophila|in vitro|cell lines?|"
    r"porcine|canine|primates?)\b"
)


def clasificar(r: Registro) -> tuple[str, float]:
    tipos = {t.lower() for t in r.tipos}
    titulo = r.titulo.lower()
    if r.preprint:
        return "preprint (sin revisión por pares)", 0.20
    if re.search(r"\b(?:study |trial |review )?protocol (?:for|of)\b|\bstudy protocol\b", titulo):
        return "protocolo (sin resultados)", 0.15
    if _PRECLINICO.search(titulo):
        return "estudio preclínico (animal/in vitro)", 0.20
    for tipo, nombre in _BAJO_NIVEL.items():
        sustantivo = tipos & {"journal article", "review", "systematic review"}
        if tipo in tipos and (tipo != "comment" or not sustantivo):
            return nombre, 0.15
    for nombre, peso, pts, patrones in NIVELES:
        if tipos & set(pts) or any(re.search(p, titulo) for p in patrones):
            return nombre, peso
    return "estudio original", 0.45


def _entero(s: str) -> int:
    return int(s.replace(",", ""))


def analizar(r: Registro, terminos: set[str]) -> None:
    """Completa diseño, nivel, tamaño muestral, estimadores y frases clave del registro."""
    r.diseno, r.nivel = clasificar(r)
    texto = r.abstract
    # Se ignoran conteos de cribado ("35 screened patients"): no son la muestra analizada.
    pacientes = [
        _entero(m.group(1))
        for m in _N_PAC.finditer(texto)
        if not re.search(r"screen|assessed for|potential", m.group(0), re.IGNORECASE)
    ] + [_entero(m) for m in _N_IGUAL.findall(texto)]
    pacientes = [n for n in pacientes if 0 < n < 10_000_000]
    r.n_muestra = max(pacientes) if pacientes else None
    if r.nivel >= 0.9 or "review" in r.diseno:
        estudios = [int(m) for m in _N_EST.findall(texto) if 0 < int(m) < 5000]
        r.n_estudios = max(estudios) if estudios else None
    r.estimadores = bool(_ESTIMADOR.search(texto))

    concl = [s.texto for s in r.secciones if _LABEL_CONCLUSION.search(s.label)]
    if concl:
        r.conclusion = _recortar(" ".join(concl), 500)
    else:
        ors = oraciones(texto)
        r.conclusion = _recortar(" ".join(ors[-2:]) if len(ors) > 2 else texto, 500)

    fuente_res = [s.texto for s in r.secciones if _LABEL_RESULTADOS.search(s.label)]
    candidatas = oraciones(" ".join(fuente_res) if fuente_res else texto)

    def _peso(o: str) -> float:
        solape = len(terminos & set(tokens(o)))
        return solape + 2 * bool(_ESTIMADOR.search(o)) + bool(re.search(r"\d", o))

    elegidas = sorted((o for o in candidatas if re.search(r"\d", o)), key=_peso, reverse=True)
    r.resultados_clave = [_recortar(o, 350) for o in elegidas[:3]]


def _recortar(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1].rsplit(" ", 1)[0] + "…"


def bm25(
    docs: list[list[str]], consulta: list[str], k1: float = 1.5, b: float = 0.75
) -> list[float]:
    if not docs:
        return []
    n_docs = len(docs)
    largo_medio = sum(map(len, docs)) / n_docs or 1.0
    df = Counter(t for d in docs for t in set(d))
    puntajes = []
    for d in docs:
        tf = Counter(d)
        s = 0.0
        for t in set(consulta):
            if t in tf:
                idf = math.log(1 + (n_docs - df[t] + 0.5) / (df[t] + 0.5))
                s += idf * tf[t] * (k1 + 1) / (tf[t] + k1 * (1 - b + b * len(d) / largo_medio))
        puntajes.append(s)
    return puntajes


def terminos_consulta(pregunta: str, query: str) -> list[str]:
    limpia = re.sub(r"\[[^\]]*\]", " ", query)
    return list(dict.fromkeys(tokens(limpia) + tokens(pregunta)))


def rankear(
    registros: list[Registro], pregunta: str, query: str, n: int, anio_actual: int | None = None
) -> tuple[list[Registro], dict]:
    """Excluye retractadas/sin abstract/irrelevantes y ordena por relevancia x evidencia."""
    anio_actual = anio_actual or _ahora().year
    excl = Counter()
    validos = []
    for r in registros:
        if r.retractada:
            excl["retractadas"] += 1
        elif len(r.abstract) < 150:
            excl["sin_abstract"] += 1
        else:
            validos.append(r)
    # Mismo título = versiones de la misma obra (p. ej. actualizaciones Cochrane): la más reciente.
    por_titulo: dict[str, Registro] = {}
    for r in validos:
        clave = re.sub(r"[^a-z0-9]+", " ", _sin_tildes(r.titulo.lower())).strip()
        previo = por_titulo.get(clave)
        if previo is None or (r.anio or 0) > (previo.anio or 0):
            por_titulo[clave] = r
    if len(por_titulo) < len(validos):
        excl["versiones_anteriores"] = len(validos) - len(por_titulo)
        vigentes = {id(r) for r in por_titulo.values()}
        validos = [r for r in validos if id(r) in vigentes]
    consulta = terminos_consulta(pregunta, query)
    docs = [tokens(r.titulo) * 2 + tokens(r.abstract) for r in validos]
    crudos = bm25(docs, consulta)
    maximo = max(crudos, default=0.0) or 1.0
    terminos = set(consulta)
    for r, s in zip(validos, crudos):
        r.relevancia = round(s / maximo, 4)
        analizar(r, terminos)
        edad = anio_actual - (r.anio or 1900)
        recencia = 1.0 if edad <= 5 else 0.5 if edad <= 10 else 0.0
        r.puntaje = round(0.65 * r.relevancia + 0.30 * r.nivel + 0.05 * recencia, 4)
    relevantes = [r for r in validos if r.relevancia >= 0.15]
    excl["baja_relevancia"] = len(validos) - len(relevantes)
    relevantes.sort(key=lambda r: (r.puntaje, r.relevancia), reverse=True)
    return relevantes[:n], dict(excl)


# =============================================================================== búsqueda


def construir_query(pregunta: str) -> tuple[str, list[str]]:
    """Query de palabras clave desde la pregunta (sirve bien para preguntas en inglés)."""
    avisos = []
    if parece_espanol(pregunta):
        avisos.append(
            "La pregunta parece estar en español y PubMed indexa en inglés: pasa --query en "
            "inglés (o usa --llm para traducirla). Se usan las palabras clave tal cual."
        )
    palabras = [
        w
        for w in re.findall(r"[\wáéíóúñü\-]+", pregunta)
        if _sin_tildes(w.lower()) not in STOP and len(w) > 1
    ]
    return " ".join(dict.fromkeys(palabras)), avisos


def _es_simple(query: str) -> bool:
    return not re.search(r"\[|\]|\"|\b(?:AND|OR|NOT)\b|\(", query)


def _filtros_pubmed(cfg: Config) -> str:
    f = f'hasabstract[text] AND ("{cfg.desde}"[dp] : "{cfg.hasta or 3000}"[dp])'
    return f if cfg.preprints else f + " NOT preprint[pt]"


ALTA_EVIDENCIA = (
    "(systematic review[pt] OR meta-analysis[pt] OR guideline[pt] OR practice guideline[pt] "
    "OR randomized controlled trial[pt])"
)


def buscar_pubmed(query: str, cfg: Config, metricas: dict) -> list[str]:
    """Búsqueda en dos estratos (Best Match general + alta evidencia) con relajación si hay
    pocos resultados y la query es de palabras clave."""
    filtros = _filtros_pubmed(cfg)
    variantes = [query]
    if _es_simple(query):
        palabras = query.split()
        sin_genericos = [w for w in palabras if _sin_tildes(w.lower()) not in GENERICOS]
        if 0 < len(sin_genericos) < len(palabras):
            variantes.append(" ".join(sin_genericos))
        if len(sin_genericos or palabras) > 2:
            variantes.append(" OR ".join(sin_genericos or palabras))
    ids: list[str] = []
    for q in variantes:
        term = f"({q}) AND {filtros}"
        total, encontrados = pubmed_esearch(term, cfg.candidatos, cfg)
        metricas["queries_pubmed"].append(
            {"estrato": "general", "term": term, "total": total, "recuperados": len(encontrados)}
        )
        if total >= max(5, cfg.n // 2) or q is variantes[-1]:
            ids = encontrados
            term_ae = f"({q}) AND {filtros} AND {ALTA_EVIDENCIA}"
            total_ae, ids_ae = pubmed_esearch(term_ae, max(10, cfg.candidatos // 3), cfg)
            metricas["queries_pubmed"].append(
                {
                    "estrato": "alta_evidencia",
                    "term": term_ae,
                    "total": total_ae,
                    "recuperados": len(ids_ae),
                }
            )
            metricas["query_efectiva"] = q
            ids = list(dict.fromkeys(ids + ids_ae))
            break
        metricas["avisos"].append(f"Query con pocos resultados ({total}), se relaja: {q!r}")
    return ids


def construir_paquete(
    pregunta: str, query: str | None = None, cfg: Config | None = None, llm: LLMFn | None = None
) -> Paquete:
    """Pregunta -> paquete de evidencia rankeado (sin redactar la respuesta)."""
    cfg = cfg or Config.desde_entorno()
    pregunta = _limpio(pregunta)
    if not pregunta:
        raise ValueError("Falta la pregunta.")
    chequear_privacidad(pregunta + " " + (query or ""))
    metricas: dict = {
        "fecha": _ahora().isoformat(timespec="seconds"),
        "fuentes_consultadas": ["PubMed (NCBI E-utilities)"]
        + (["Europe PMC"] if cfg.europepmc else []),
        "filtros": {
            "desde": cfg.desde,
            "hasta": cfg.hasta,
            "preprints": cfg.preprints,
            "requiere_abstract": True,
        },
        "queries_pubmed": [],
        "avisos": [],
    }
    if not query:
        if llm is not None:
            query = generar_query_llm(pregunta, llm)
            metricas["query_origen"] = "llm"
        else:
            if parece_espanol(pregunta):
                raise ValueError(
                    "La pregunta está en español y PubMed indexa en inglés: pasa --query con la "
                    "query en inglés (o usa --llm para que el modelo la traduzca)."
                )
            query, avisos = construir_query(pregunta)
            metricas["avisos"] += avisos
            metricas["query_origen"] = "palabras_clave"
    else:
        metricas["query_origen"] = "usuario/agente"
    query = _limpio(query)

    log.info("PubMed: %s", query)
    pmids = buscar_pubmed(query, cfg, metricas)
    q_pubmed = metricas.get("query_efectiva", query)
    registros = pubmed_efetch(pmids, cfg) if pmids else []
    metricas["recuperados_pubmed"] = len(registros)

    if cfg.europepmc:
        log.info("Europe PMC: %s", q_pubmed)
        try:
            total, regs_epmc, q_epmc = europepmc_search(q_pubmed, cfg.candidatos // 2, cfg)
            metricas["query_europepmc"] = {
                "query": q_epmc,
                "total": total,
                "recuperados": len(regs_epmc),
            }
            registros = fusionar(registros, regs_epmc)
        except ErrorRed as exc:  # Europe PMC es complementario: degradar, no abortar
            metricas["avisos"].append(f"Europe PMC no disponible: {exc}")
            log.warning("Europe PMC no disponible: %s", exc)

    seleccion, excluidos = rankear(registros, pregunta, q_pubmed, cfg.n)
    metricas.update(
        candidatos=len(registros),
        excluidos=excluidos,
        seleccionados=len(seleccion),
        por_diseno=dict(Counter(r.diseno for r in seleccion)),
        texto_completo_libre=sum(r.texto_completo_libre for r in seleccion),
    )
    if len(seleccion) < 3:
        metricas["avisos"].append(
            f"Solo {len(seleccion)} fuente(s) relevantes: la evidencia es escasa o la query "
            "es demasiado estrecha. Reformula (sinónimos, MeSH) antes de concluir."
        )
    return Paquete(pregunta=pregunta, query=q_pubmed, registros=seleccion, metricas=metricas)


# =============================================================================== salida


def _fmt_n(r: Registro) -> str:
    partes = []
    if r.n_estudios:
        partes.append(f"{r.n_estudios} estudios")
    if r.n_muestra:
        partes.append(f"n≈{r.n_muestra:,}".replace(",", "."))
    return " · ".join(partes) or "—"


def paquete_markdown(p: Paquete, *, max_chars_abstract: int | None = None) -> str:
    m = p.metricas
    lineas = [
        "# Paquete de evidencia",
        "",
        f"**Pregunta:** {p.pregunta}",
        f"**Query PubMed:** `{p.query}`",
        (
            f"**Generado:** {m.get('fecha', '')} · **Fuentes:** "
            f"{', '.join(m.get('fuentes_consultadas', []))}"
        ),
        (
            f"**Selección:** {len(p.registros)} de {m.get('candidatos', '?')} candidatos "
            f"(excluidos: {m.get('excluidos', {})})"
        ),
        "",
        (
            "Cita solo con los identificadores entre corchetes de esta lista, p. ej. "
            f"[{p.registros[0].id if p.registros else 'PMID:00000000'}]. "
            "Las cifras deben copiarse tal como aparecen en los abstracts."
        ),
        "",
    ]
    for aviso in m.get("avisos", []):
        lineas.append(f"> ⚠ {aviso}")
    lineas += [
        "",
        "## Resumen del paquete",
        "",
        "| # | Cita | Diseño | Año | n | Relevancia | Puntaje | Texto completo libre |",
        "|---|------|--------|-----|---|-----------|---------|----------------------|",
    ]
    for i, r in enumerate(p.registros, 1):
        lineas.append(
            f"| {i} | [{r.id}] | {r.diseno} | {r.anio or '—'} | {_fmt_n(r)} | "
            f"{r.relevancia:.2f} | {r.puntaje:.2f} | {'sí' if r.texto_completo_libre else 'no'} |"
        )
    for i, r in enumerate(p.registros, 1):
        acceso = (
            f"texto completo libre ({r.pmcid or 'Europe PMC OA'})"
            if r.texto_completo_libre
            else "solo abstract"
        )
        lineas += [
            "",
            f"## {i}. [{r.id}] {r.titulo}",
            "",
            (
                f"- **Diseño:** {r.diseno} · **Año:** {r.anio or '—'} · **Revista:** "
                f"{r.revista or '—'} · **n:** {_fmt_n(r)}"
            ),
            f"- **Acceso:** {acceso} · {r.url_texto_completo or r.url}",
            f"- **Tipos de publicación:** {', '.join(r.tipos) or '—'}",
            "",
        ]
        if r.secciones and any(s.label for s in r.secciones):
            for s in r.secciones:
                cuerpo = s.texto
                if max_chars_abstract:
                    cuerpo = _recortar(cuerpo, max_chars_abstract)
                lineas.append(f"**{s.label}:** {cuerpo}" if s.label else cuerpo)
                lineas.append("")
        else:
            cuerpo = r.abstract
            if max_chars_abstract:
                cuerpo = _recortar(cuerpo, max_chars_abstract)
            lineas += [cuerpo, ""]
    return "\n".join(lineas).rstrip() + "\n"


def _slug(texto: str, n: int = 50) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", _sin_tildes(texto.lower())).strip("-")
    return s[:n].rstrip("-") or "pregunta"


def guardar_paquete(p: Paquete, out: Path | None = None) -> Path:
    out = out or DEFAULT_OUT_BASE / f"{_ahora():%Y-%m-%d}_{_slug(p.pregunta)}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "evidencia.json").write_text(
        json.dumps(p.a_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out / "evidencia.md").write_text(paquete_markdown(p), encoding="utf-8")
    return out


def cargar_paquete(ruta: Path) -> Paquete:
    ruta = ruta / "evidencia.json" if ruta.is_dir() else ruta
    try:
        return Paquete.desde_dict(json.loads(ruta.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        raise ValueError(f"No se pudo leer el paquete {ruta}: {exc}") from exc


def vancouver(r: Registro) -> str:
    autores = ", ".join(r.autores[:6]) + (", et al" if len(r.autores) > 6 else "")
    titulo = r.titulo.rstrip(".")
    fecha = str(r.anio or "s.f.")
    if r.volumen:
        fecha += f";{r.volumen}"
    if r.numero:
        fecha += f"({r.numero})"
    if r.paginas:
        fecha += f":{r.paginas}"
    partes = [
        f"{autores}." if autores else "",
        f"{titulo}.",
        f"{r.revista}." if r.revista else "",
        f"{fecha}.",
    ]
    if r.doi:
        partes.append(f"doi:{r.doi}.")
    if r.pmid:
        partes.append(f"PMID: {r.pmid}.")
    if r.pmcid:
        partes.append(f"PMCID: {r.pmcid}.")
    if r.preprint:
        partes.append("[Preprint, sin revisión por pares].")
    return " ".join(p for p in partes if p)


# =============================================================================== verificación

_CITA = re.compile(r"\b(PMID)\s*:?\s*(\d{5,9})\b|\b(EPMC)\s*:\s*([A-Za-z]{2,5}\d+)", re.IGNORECASE)
_BLOQUE_CITA = re.compile(r"\[[^\]]*?(?:PMID|EPMC)[^\]]*\]", re.IGNORECASE)
_DOI = re.compile(r"\b10\.\d{4,9}/[^\s\]\)>,;]+", re.IGNORECASE)
_NUM = re.compile(r"(?<![\w.\-/])(\d+(?:[.,]\d+)*)(\s?%)?")
# En la fuente se aceptan todos los números (negativos, rangos "2.21-11.53", "IgG1").
_NUM_FUENTE = re.compile(r"\d+(?:[.,]\d+)*")
_SECCIONES_OBLIGATORIAS = ("respuesta breve", "sintesis de la evidencia")
# Secciones donde cada oración con contenido debe llevar cita (cobertura).
_SECCIONES_COBERTURA = ("respuesta breve", "sintesis")
# Secciones que no se verifican (meta-información o generadas por el script).
_SECCIONES_EXENTAS = (
    "certeza y limitaciones",
    "referencias",
    "metricas de busqueda",
    "verificacion",
)


@dataclass
class Verificacion:
    ok: bool
    citas_validas: list[str]
    citas_fuera_del_paquete: list[str]
    dois_desconocidos: list[str]
    cobertura: float
    oraciones_sin_cita: list[str]
    cifras_sin_respaldo: list[dict]
    secciones_faltantes: list[str]
    fuentes_no_usadas: list[str]
    avisos: list[str]


def _citas(texto: str) -> list[str]:
    out = []
    for m in _CITA.finditer(texto):
        out.append(f"PMID:{m.group(2)}" if m.group(1) else f"EPMC:{m.group(4).upper()}")
    return list(dict.fromkeys(out))


def _valores(tok: str) -> set[float]:
    """Interpretaciones numéricas posibles (decimal con punto o coma, miles en/es)."""
    vals: set[float] = set()
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+", tok):
        vals.add(float(tok.replace(",", "")))
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", tok):
        vals.add(float(tok.replace(".", "")))
    if re.fullmatch(r"\d+[.,]\d+", tok):
        vals.add(float(tok.replace(",", ".")))
    if re.fullmatch(r"\d+", tok):
        vals.add(float(tok))
    return {round(v, 6) for v in vals}


def _cifras_relevantes(oracion: str) -> list[tuple[str, set[float]]]:
    out = []
    for m in _NUM.finditer(oracion):
        tok, pct = m.group(1), bool(m.group(2))
        vals = _valores(tok)
        if not vals:
            continue
        if not pct and re.fullmatch(r"\d+", tok):
            v = int(tok)
            if v <= 10 or 1900 <= v <= 2100:
                continue  # conteos pequeños y años: demasiado ruido
        out.append((tok + ("%" if pct else ""), vals))
    return out


def _punto_medio_a_punto(texto: str) -> str:
    """The Lancet escribe decimales con punto medio (4·95): se normaliza a 4.95."""
    return re.sub(r"(?<=\d)[\u00b7\u2027\u2219](?=\d)", ".", texto)


def _cifras_sin_respaldo(texto: str, ids: list[str], por_id: dict[str, Registro]) -> list[dict]:
    """Cifras de `texto` que no aparecen (en ninguna notación) en los abstracts citados."""
    if "calculo propio" in _sin_tildes(texto.lower()):
        return []
    texto = _punto_medio_a_punto(texto)
    fuente = _punto_medio_a_punto(
        " ".join(f"{por_id[i].titulo} {por_id[i].abstract}" for i in ids if i in por_id)
    )
    vals_fuente: set[float] = set()
    for m in _NUM_FUENTE.finditer(fuente):
        vals_fuente |= _valores(m.group(0))
    return [
        {"cifra": cifra, "oracion": texto, "citas": ids}
        for cifra, vals in _cifras_relevantes(_BLOQUE_CITA.sub("", texto))
        if not vals & vals_fuente
    ]


def _secciones_md(texto: str) -> list[tuple[str, str]]:
    """[(titulo_normalizado, cuerpo)] según encabezados ## / ###."""
    bloques: list[tuple[str, str]] = []
    actual, cuerpo = "", []
    for linea in texto.splitlines():
        m = re.match(r"^#{2,3}\s+(.*)", linea)
        if m:
            bloques.append((actual, "\n".join(cuerpo)))
            actual, cuerpo = _sin_tildes(m.group(1).strip().lower()), []
        else:
            cuerpo.append(linea)
    bloques.append((actual, "\n".join(cuerpo)))
    return bloques


def verificar(
    respuesta: str, paquete: Paquete, *, estricto: bool = False, cobertura_minima: float = 0.8
) -> Verificacion:
    """Anti-alucinación (R2): toda cita debe existir en el paquete; las cifras de oraciones
    citadas deben aparecer en los abstracts citados; las afirmaciones deben llevar cita."""
    cuerpo = re.split(r"^##\s+Referencias\b", respuesta, flags=re.MULTILINE | re.IGNORECASE)[0]
    validos = paquete.ids()
    por_id = paquete.por_id()
    citadas = _citas(cuerpo)
    fuera = [c for c in citadas if c not in validos]
    dois_paquete = {r.doi.lower() for r in paquete.registros if r.doi}
    dois = [d.rstrip(".") for d in _DOI.findall(cuerpo)]
    dois_desconocidos = [d for d in dois if d.lower() not in dois_paquete]

    total = con_cita = 0
    sin_cita: list[str] = []
    sin_respaldo: list[dict] = []
    titulos = set()
    for titulo, bloque in _secciones_md(cuerpo):
        titulos.add(titulo)
        if not titulo or any(titulo.startswith(s) for s in _SECCIONES_EXENTAS):
            continue
        mide_cobertura = any(titulo.startswith(s) for s in _SECCIONES_COBERTURA)
        for linea in bloque.splitlines():
            linea = re.sub(r"^(?:[-*+]\s+|\d+[.)]\s+)", "", linea.strip())
            if not linea or linea.startswith((">", "#")) or re.match(r"\|[\s:|-]*$", linea):
                continue
            if linea.startswith("|"):  # fila de tabla: solo control de cifras
                ids_fila = _citas(linea)
                if ids_fila:
                    sin_respaldo += _cifras_sin_respaldo(linea, ids_fila, por_id)
                continue
            if re.match(r"\*\*certeza", _sin_tildes(linea.lower())):
                continue  # la línea de certeza se justifica en "Certeza y limitaciones"
            for o in oraciones(linea):
                if len(o) < 25:
                    continue
                ids_o = _citas(o)
                if mide_cobertura:
                    total += 1
                    if ids_o:
                        con_cita += 1
                    else:
                        sin_cita.append(o)
                if ids_o:
                    sin_respaldo += _cifras_sin_respaldo(o, ids_o, por_id)
    cobertura = con_cita / total if total else 0.0
    faltantes = [s for s in _SECCIONES_OBLIGATORIAS if not any(t.startswith(s) for t in titulos)]
    avisos = []
    if cobertura < cobertura_minima:
        avisos.append(
            f"Cobertura de citas {cobertura:.0%} < {cobertura_minima:.0%}: hay afirmaciones "
            "sin fuente en las secciones de respuesta/síntesis."
        )
    if sin_respaldo:
        avisos.append(
            f"{len(sin_respaldo)} cifra(s) no aparecen en los abstracts citados: revisa que estén "
            "copiadas tal cual o márcalas como (cálculo propio)."
        )
    if dois_desconocidos:
        avisos.append("DOIs que no pertenecen al paquete: " + ", ".join(dois_desconocidos))
    ok = not fuera and not faltantes and bool(citadas)
    if estricto:
        ok = ok and not sin_respaldo and not dois_desconocidos and cobertura >= cobertura_minima
    if not citadas:
        avisos.append("La respuesta no cita ninguna fuente del paquete.")
    return Verificacion(
        ok=ok,
        citas_validas=[c for c in citadas if c in validos],
        citas_fuera_del_paquete=fuera,
        dois_desconocidos=dois_desconocidos,
        cobertura=round(cobertura, 3),
        oraciones_sin_cita=sin_cita,
        cifras_sin_respaldo=sin_respaldo,
        secciones_faltantes=faltantes,
        fuentes_no_usadas=[r.id for r in paquete.registros if r.id not in citadas],
        avisos=avisos,
    )


def informe_verificacion(v: Verificacion) -> str:
    estado = "APROBADA" if v.ok else "RECHAZADA"
    lineas = [
        f"Verificación: {estado}",
        (
            f"- Citas válidas: {len(v.citas_validas)} · fuera del paquete: "
            f"{', '.join(v.citas_fuera_del_paquete) or 'ninguna'}"
        ),
        f"- Cobertura de citas: {v.cobertura:.0%}",
        f"- Cifras sin respaldo: {len(v.cifras_sin_respaldo)}",
    ]
    if v.secciones_faltantes:
        lineas.append(f"- Secciones faltantes: {', '.join(v.secciones_faltantes)}")
    for c in v.cifras_sin_respaldo[:10]:
        lineas.append(f"  · {c['cifra']} en: {_recortar(c['oracion'], 160)}")
    for o in v.oraciones_sin_cita[:10]:
        lineas.append(f"  · sin cita: {_recortar(o, 160)}")
    if v.fuentes_no_usadas:
        lineas.append(f"- Fuentes del paquete no citadas: {', '.join(v.fuentes_no_usadas)}")
    lineas += [f"⚠ {a}" for a in v.avisos]
    return "\n".join(lineas)


def anexar_referencias(respuesta: str, paquete: Paquete, v: Verificacion) -> str:
    """Respuesta final = cuerpo + Referencias (Vancouver, orden de aparición) + métricas."""
    cuerpo = re.split(r"^##\s+Referencias\b", respuesta, flags=re.MULTILINE | re.IGNORECASE)[
        0
    ].rstrip()
    por_id = paquete.por_id()
    m = paquete.metricas
    lineas = [cuerpo, "", "## Referencias", ""]
    for i, cid in enumerate(v.citas_validas, 1):
        lineas.append(f"{i}. [{cid}] {vancouver(por_id[cid])}")
    lineas += ["", "## Métricas de búsqueda", ""]
    lineas.append(
        f"- Fecha: {m.get('fecha', '')} · Fuentes: "
        f"{', '.join(m.get('fuentes_consultadas', []))}"
    )
    for q in m.get("queries_pubmed", []):
        lineas.append(
            f"- PubMed ({q['estrato']}): `{q['term']}` → {q['total']} resultados, "
            f"{q['recuperados']} recuperados"
        )
    if m.get("query_europepmc"):
        q = m["query_europepmc"]
        lineas.append(
            f"- Europe PMC: `{q['query']}` → {q['total']} resultados, "
            f"{q['recuperados']} recuperados"
        )
    lineas.append(
        f"- Candidatos: {m.get('candidatos', '?')} · excluidos: {m.get('excluidos', {})} · "
        f"en el paquete: {m.get('seleccionados', '?')} · citados: {len(v.citas_validas)}"
    )
    lineas.append(
        f"- Verificación automática: {len(v.citas_validas)} citas válidas, 0 fuera del "
        f"paquete, cobertura {v.cobertura:.0%}, {len(v.cifras_sin_respaldo)} cifra(s) sin "
        "respaldo literal en los abstracts."
    )
    return "\n".join(lineas) + "\n"


# =============================================================================== LLM (opcional)


def modelo_por_defecto() -> str:
    return os.environ.get("PUBMED_QA_MODEL") or os.environ.get("HARNESS_MODEL") or MODELO_DEFAULT


def llamar_claude(
    sistema: str, usuario: str, modelo: str | None = None, max_tokens: int = 16000
) -> str:
    """Una llamada a la Messages API con el SDK oficial (streaming + mensaje final)."""
    try:
        import anthropic
    except ImportError as exc:
        raise ErrorLLM("Falta el SDK de Anthropic: pip install anthropic") from exc
    modelo = modelo or modelo_por_defecto()
    kwargs: dict = {
        "model": modelo,
        "max_tokens": max_tokens,
        "system": sistema,
        "messages": [{"role": "user", "content": usuario}],
    }
    if modelo.startswith(_CON_EFFORT):
        kwargs["output_config"] = {"effort": "high"}
    try:
        client = anthropic.Anthropic()
        if modelo in _CON_FALLBACK:
            # Si el modelo declina por política, la API reintenta con un modelo de respaldo.
            with client.beta.messages.stream(
                betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs
            ) as stream:
                msg = stream.get_final_message()
        else:
            with client.messages.stream(**kwargs) as stream:
                msg = stream.get_final_message()
    except anthropic.AuthenticationError as exc:
        raise ErrorLLM(
            "Credencial de Anthropic inválida o ausente (ANTHROPIC_API_KEY o " "`ant auth login`)."
        ) from exc
    except anthropic.RateLimitError as exc:
        raise ErrorLLM("Rate limit de la API de Anthropic; reintenta más tarde.") from exc
    except anthropic.APIStatusError as exc:
        raise ErrorLLM(f"La API de Anthropic respondió {exc.status_code}: {exc.message}") from exc
    except anthropic.APIConnectionError as exc:
        raise ErrorLLM(f"Sin conexión con la API de Anthropic: {exc}") from exc
    except anthropic.AnthropicError as exc:
        raise ErrorLLM(f"Error del SDK de Anthropic: {exc}") from exc
    except TypeError as exc:  # el SDK lo usa cuando no hay ninguna credencial configurada
        if "authentication" not in str(exc).lower():
            raise
        raise ErrorLLM(
            "No hay credencial de Anthropic: define ANTHROPIC_API_KEY o usa `ant auth login`."
        ) from exc
    if msg.stop_reason == "refusal":
        raise ErrorLLM("El modelo declinó responder (stop_reason=refusal).")
    if msg.stop_reason == "max_tokens":
        log.warning("La respuesta del modelo se cortó por max_tokens.")
    return "".join(b.text for b in msg.content if b.type == "text").strip()


def _llm_por_defecto(modelo: str | None) -> LLMFn:
    return lambda sistema, usuario: llamar_claude(sistema, usuario, modelo)


def generar_query_llm(pregunta: str, llm: LLMFn) -> str:
    sistema = (
        "Eres bibliotecario biomédico. Convierte la pregunta en una query de PubMed en inglés: "
        "conceptos PICO esenciales unidos con AND, sinónimos con OR entre paréntesis, términos "
        "MeSH cuando existan. Sin filtros de fecha ni de tipo de publicación. Responde solo con "
        'JSON: {"pubmed": "<query>"}'
    )
    texto = llm(sistema, pregunta)
    m = re.search(r"\{.*\}", texto, re.DOTALL)
    try:
        query = json.loads(m.group(0))["pubmed"] if m else ""
    except (json.JSONDecodeError, KeyError, TypeError):
        query = ""
    if not query.strip():
        raise ErrorLLM(f"El modelo no devolvió una query válida: {texto[:200]!r}")
    return query.strip()


def cargar_formato() -> str:
    try:
        return FORMATO_RESPUESTA.read_text(encoding="utf-8")
    except OSError:
        log.warning("No se encontró %s; uso instrucciones mínimas.", FORMATO_RESPUESTA)
        return (
            "Responde en español solo con la evidencia del paquete. Cita cada afirmación con "
            "[PMID:x]. Secciones: ## Respuesta breve, ## Síntesis de la evidencia, "
            "## Estudios clave, ## Consistencia, controversias y vacíos, "
            "## Certeza y limitaciones."
        )


def redactar_con_llm(p: Paquete, llm: LLMFn, *, intentos: int = 2) -> tuple[str, Verificacion]:
    """Redacta con el modelo y verifica; si falla, una ronda de corrección con el informe."""
    sistema = cargar_formato()
    usuario = (
        paquete_markdown(p)
        + "\n\n---\nRedacta ahora la respuesta a la pregunta siguiendo exactamente el formato "
        "indicado, usando solo este paquete."
    )
    texto = llm(sistema, usuario)
    v = verificar(texto, p)
    for _ in range(intentos - 1):
        if v.ok and not v.cifras_sin_respaldo:
            break
        usuario_corr = (
            usuario + "\n\n---\nTu borrador:\n\n" + texto + "\n\n---\nEl verificador automático "
            "informó:\n" + informe_verificacion(v) + "\n\nCorrige el borrador: elimina o "
            "reemplaza citas fuera del paquete, copia las cifras tal como aparecen en los "
            "abstracts y añade cita a toda afirmación. Devuelve la respuesta completa corregida."
        )
        texto = llm(sistema, usuario_corr)
        v = verificar(texto, p)
    return texto, v


# =============================================================================== CLI


def _cargar_env() -> None:
    ruta = REPO_ROOT / "tools" / "env_loader.py"
    if not ruta.is_file():
        return
    try:
        spec = importlib.util.spec_from_file_location("harness_env_loader", ruta)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.load_env()
    except (OSError, ImportError, AttributeError, ValueError) as exc:  # .env opcional
        log.warning("No se pudo cargar el .env del harness: %s", exc)


def _cmd_buscar(args: argparse.Namespace) -> int:
    cfg = Config.desde_entorno(
        n=args.n,
        candidatos=args.candidatos,
        desde=args.desde,
        hasta=args.hasta,
        europepmc=not args.sin_europepmc,
        preprints=args.incluir_preprints,
    )
    llm = _llm_por_defecto(args.modelo) if args.llm else None
    p = construir_paquete(args.pregunta, args.query, cfg, llm=llm if not args.query else None)
    out = guardar_paquete(p, args.out)
    m = p.metricas
    print(f"Paquete: {len(p.registros)} fuentes de {m.get('candidatos', 0)} candidatos -> {out}")
    for r in p.registros:
        print(
            f"  [{r.id}] {r.anio or '—'} · {r.diseno} · puntaje {r.puntaje:.2f} · "
            f"{_recortar(r.titulo, 90)}"
        )
    for aviso in m.get("avisos", []):
        print(f"⚠ {aviso}")
    if not p.registros:
        return 1
    if not args.llm:
        print(
            f"\nSiguiente: redactar {out / 'respuesta.md'} según "
            f"{FORMATO_RESPUESTA.relative_to(REPO_ROOT)} y correr `verificar --dir {out}`."
        )
        return 0
    texto, v = redactar_con_llm(p, llm)
    (out / "respuesta.md").write_text(texto + "\n", encoding="utf-8")
    return _cerrar_verificacion(texto, p, v, out)


def _cerrar_verificacion(texto: str, p: Paquete, v: Verificacion, out: Path) -> int:
    (out / "verificacion.json").write_text(
        json.dumps(asdict(v), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(informe_verificacion(v))
    if not v.ok:
        print("No se genera respuesta_final.md: corrige respuesta.md y vuelve a verificar.")
        return 1
    final = anexar_referencias(texto, p, v)
    (out / "respuesta_final.md").write_text(final, encoding="utf-8")
    print(f"Respuesta final: {out / 'respuesta_final.md'}")
    return 0


def _cmd_verificar(args: argparse.Namespace) -> int:
    p = cargar_paquete(args.dir)
    ruta = args.respuesta or args.dir / "respuesta.md"
    try:
        texto = ruta.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"No se pudo leer la respuesta {ruta}: {exc}") from exc
    v = verificar(texto, p, estricto=args.estricto)
    return _cerrar_verificacion(texto, p, v, args.dir)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
    _cargar_env()
    ap = argparse.ArgumentParser(
        description="Responde preguntas científicas con abstracts libres de PubMed/Europe PMC."
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("buscar", help="Pregunta -> paquete de evidencia (y respuesta con --llm).")
    b.add_argument("pregunta")
    b.add_argument(
        "--query",
        help="Query PubMed en inglés (recomendado si la pregunta está en "
        "español; admite MeSH y operadores).",
    )
    b.add_argument("--n", type=int, default=10, help="Fuentes en el paquete (default 10).")
    b.add_argument("--candidatos", type=int, default=60, help="Registros PubMed a evaluar.")
    b.add_argument("--desde", type=int, default=2000, help="Año mínimo (default 2000).")
    b.add_argument("--hasta", type=int, help="Año máximo.")
    b.add_argument("--sin-europepmc", action="store_true", help="Solo PubMed.")
    b.add_argument(
        "--incluir-preprints",
        action="store_true",
        help="Incluye preprints (excluidos por defecto).",
    )
    b.add_argument("--out", type=Path, help=f"Directorio de salida (default {DEFAULT_OUT_BASE}/…)")
    b.add_argument(
        "--llm",
        action="store_true",
        help="Redacta y verifica la respuesta con la API de Anthropic.",
    )
    b.add_argument(
        "--modelo",
        help="Modelo para --llm (default PUBMED_QA_MODEL/HARNESS_MODEL/" f"{MODELO_DEFAULT}).",
    )
    b.set_defaults(fn=_cmd_buscar)
    v = sub.add_parser("verificar", help="Verifica respuesta.md contra el paquete.")
    v.add_argument("--dir", type=Path, required=True, help="Directorio con evidencia.json.")
    v.add_argument(
        "--respuesta", type=Path, help="Archivo de respuesta (default DIR/respuesta.md)."
    )
    v.add_argument(
        "--estricto",
        action="store_true",
        help="Falla también por cifras sin respaldo, DOIs ajenos o baja cobertura.",
    )
    v.set_defaults(fn=_cmd_verificar)
    args = ap.parse_args(argv)
    try:
        return args.fn(args)
    except (ValueError, OSError, ErrorRed, ErrorLLM) as exc:  # ErrorPrivacidad es ValueError
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
