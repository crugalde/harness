#!/usr/bin/env python3
"""Convierte un resumen clínico en Word (.docx) a Markdown conservando las figuras.

Uso:
    python docx_a_md.py "C:\\ruta\\resumen.docx" \
        --salida "C:\\Users\\Usuario\\OneDrive\\brain md" \
        --adjuntos _adjuntos --json

Qué hace:
  * respeta el orden real del documento (párrafos, tablas e imágenes intercaladas);
  * mapea estilos de título (Heading/Título, en inglés o español) a `#`…`######`;
  * extrae cada imagen a `<salida>/<adjuntos>/<slug>/fig-NN.<ext>` y la enlaza con su pie;
  * convierte tablas a Markdown, listas (viñeta/numerada) y negrita/cursiva/enlaces;
  * recupera las notas al pie como sección final;
  * de-identifica por defecto (RUT, nombres de campo, teléfonos, correos, N° de ficha).

Requiere: python-docx (`pip install python-docx`).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from urllib.parse import quote

try:
    import docx
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph
except ImportError:  # pragma: no cover
    sys.exit("Falta python-docx. Instala con: pip install python-docx")

from lxml import etree

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "v": "urn:schemas-microsoft-com:vml",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
}

RE_NIVEL = re.compile(r"(?:heading|t[ií]tulo|titulo|encabezado)\s*(\d)", re.I)
RE_PIE = re.compile(r"^\s*(figura|fig\.?|imagen|tabla|cuadro|gr[áa]fico)\s*\d*\s*[.:—-]?", re.I)

# ------------------------------------------------------------------ de-identificación
RE_RUT = re.compile(r"\b\d{1,2}\.?\d{3}\.?\d{3}\s*[-‐]\s*[\dkK]\b")
RE_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]{2,}")
RE_TEL = re.compile(r"(?:\+?56\s?)?(?:9\s?\d{4}\s?\d{4}|\(?\d{2}\)?\s?\d{3}\s?\d{4})\b")
RE_CAMPO = re.compile(
    r"(?im)^(\s*(?:paciente|nombre(?:\s+del\s+paciente)?|apellidos?|rut|r\.u\.t|ficha|n[°º]\s*ficha|"
    r"tel[eé]fono|fono|correo|e-?mail|direcci[óo]n|previsi[óo]n|fecha\s+de\s+nacimiento)\s*:\s*)(.{1,80})$")
RE_FICHA = re.compile(r"(?i)\b(ficha|episodio|hc)\s*(n[°º]?\s*)?[:#]?\s*\d{3,}\b")


@dataclass
class Conversion:
    md: Path
    titulo: str = ""
    figuras: int = 0
    tablas: int = 0
    enmascarados: int = 0
    notas: int = 0
    advertencias: list[str] = field(default_factory=list)

    def como_dict(self) -> dict:
        return {"md": str(self.md), "titulo": self.titulo, "figuras": self.figuras,
                "tablas": self.tablas, "enmascarados": self.enmascarados, "notas": self.notas,
                "advertencias": self.advertencias}


# ------------------------------------------------------------------ utilidades
def slugificar(texto: str, largo: int = 80) -> str:
    normal = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    normal = re.sub(r"[^\w\s-]", "", normal).strip().lower()
    normal = re.sub(r"[\s_-]+", "-", normal)
    return normal[:largo].strip("-") or "resumen"


def deidentificar(texto: str) -> tuple[str, int]:
    """Enmascara identificadores directos. Devuelve (texto, n_reemplazos)."""
    n = 0

    def _sub(patron, reemplazo, s):
        nonlocal n
        s, k = patron.subn(reemplazo, s)
        n += k
        return s

    texto = _sub(RE_CAMPO, lambda m: m.group(1) + "[DATO PERSONAL OMITIDO]", texto)
    texto = _sub(RE_RUT, "[RUT]", texto)
    texto = _sub(RE_EMAIL, "[CORREO]", texto)
    texto = _sub(RE_TEL, "[TELÉFONO]", texto)
    texto = _sub(RE_FICHA, "[FICHA]", texto)
    return texto, n


def escapar(texto: str) -> str:
    """Escapa lo que Markdown interpretaría por accidente, sin arruinar el texto clínico."""
    return re.sub(r"(?<!\\)([*_`])", r"\\\1", texto)


# ------------------------------------------------------------------ lectura del .docx
def bloques(documento):
    """Genera Paragraph/Table en el orden real del cuerpo del documento."""
    for hijo in documento.element.body.iterchildren():
        if hijo.tag == qn("w:p"):
            yield Paragraph(hijo, documento)
        elif hijo.tag == qn("w:tbl"):
            yield Table(hijo, documento)


def nivel_titulo(parrafo: Paragraph) -> int:
    """Nivel de encabezado (1–6) o 0 si es texto normal."""
    nombre = (parrafo.style.name or "") if parrafo.style is not None else ""
    estilo_id = (parrafo.style.style_id or "") if parrafo.style is not None else ""
    for candidato in (nombre, estilo_id):
        m = RE_NIVEL.search(candidato)
        if m:
            return min(int(m.group(1)), 6)
    if nombre.strip().lower() in ("title", "título", "titulo"):
        return 1
    ppr = parrafo._p.find(qn("w:pPr"))
    if ppr is not None:
        lvl = ppr.find(qn("w:outlineLvl"))
        if lvl is not None:
            try:
                return min(int(lvl.get(qn("w:val"))) + 1, 6)
            except (TypeError, ValueError):
                pass
    return 0


def formato_lista(parrafo: Paragraph, numeracion: dict) -> tuple[bool, bool, int]:
    """(es_lista, es_numerada, nivel). Consulta numbering.xml cuando está disponible."""
    ppr = parrafo._p.find(qn("w:pPr"))
    numpr = ppr.find(qn("w:numPr")) if ppr is not None else None
    nombre = (parrafo.style.name or "").lower() if parrafo.style is not None else ""
    if numpr is None:
        if nombre.startswith(("list bullet", "lista con viñetas", "párrafo de lista")):
            return True, False, 0
        if nombre.startswith(("list number", "lista con números")):
            return True, True, 0
        return False, False, 0
    nivel = 0
    ilvl = numpr.find(qn("w:ilvl"))
    if ilvl is not None:
        try:
            nivel = int(ilvl.get(qn("w:val")))
        except (TypeError, ValueError):
            nivel = 0
    num_id = numpr.find(qn("w:numId"))
    clave = (num_id.get(qn("w:val")) if num_id is not None else None, str(nivel))
    formato = numeracion.get(clave, "")
    if not formato and nombre.startswith("list number"):
        formato = "decimal"
    return True, formato not in ("", "bullet", "none"), nivel


def mapa_numeracion(documento) -> dict:
    """{(numId, ilvl): numFmt} leyendo numbering.xml. Vacío si el documento no lo trae."""
    try:
        parte = documento.part.part_related_by(RT.NUMBERING)
    except (KeyError, ValueError):
        return {}
    try:
        raiz = etree.fromstring(parte.blob)
    except etree.XMLSyntaxError:
        return {}
    abstractos: dict[str, dict[str, str]] = {}
    for abst in raiz.findall("w:abstractNum", NS):
        aid = abst.get(f"{{{NS['w']}}}abstractNumId")
        niveles = {}
        for lvl in abst.findall("w:lvl", NS):
            ilvl = lvl.get(f"{{{NS['w']}}}ilvl")
            fmt = lvl.find("w:numFmt", NS)
            niveles[ilvl] = fmt.get(f"{{{NS['w']}}}val") if fmt is not None else ""
        abstractos[aid] = niveles
    salida = {}
    for num in raiz.findall("w:num", NS):
        nid = num.get(f"{{{NS['w']}}}numId")
        ref = num.find("w:abstractNumId", NS)
        aid = ref.get(f"{{{NS['w']}}}val") if ref is not None else None
        for ilvl, fmt in abstractos.get(aid, {}).items():
            salida[(nid, ilvl)] = fmt
    return salida


def notas_al_pie(documento) -> dict[str, str]:
    """{id: texto} de las notas al pie. Vacío si el documento no tiene."""
    try:
        parte = documento.part.part_related_by(RT.FOOTNOTES)
    except (KeyError, ValueError):
        return {}
    try:
        raiz = etree.fromstring(parte.blob)
    except etree.XMLSyntaxError:
        return {}
    salida = {}
    for nota in raiz.findall("w:footnote", NS):
        nid = nota.get(f"{{{NS['w']}}}id")
        if nid in (None, "-1", "0"):  # separadores, no son notas reales
            continue
        texto = " ".join(t.text or "" for t in nota.iter(f"{{{NS['w']}}}t")).strip()
        if texto:
            salida[nid] = texto
    return salida


def texto_run(run_el) -> str:
    """Texto de un `w:r` con negrita/cursiva y saltos de línea."""
    partes = []
    for hijo in run_el.iter():
        if hijo.tag == qn("w:t"):
            partes.append(hijo.text or "")
        elif hijo.tag in (qn("w:br"), qn("w:cr")):
            partes.append("\n")
        elif hijo.tag == qn("w:tab"):
            partes.append(" ")
    texto = "".join(partes)
    if not texto.strip():
        return texto
    rpr = run_el.find(qn("w:rPr"))
    negrita = rpr is not None and rpr.find(qn("w:b")) is not None
    cursiva = rpr is not None and rpr.find(qn("w:i")) is not None
    izq = len(texto) - len(texto.lstrip())
    der = len(texto) - len(texto.rstrip())
    nucleo = escapar(texto.strip())
    if negrita and cursiva:
        nucleo = f"***{nucleo}***"
    elif negrita:
        nucleo = f"**{nucleo}**"
    elif cursiva:
        nucleo = f"*{nucleo}*"
    return texto[:izq] + nucleo + texto[len(texto) - der:] if (izq or der) else nucleo


def texto_parrafo(parrafo: Paragraph, documento, notas: dict[str, str],
                  usadas: dict[str, int]) -> str:
    """Markdown en línea de un párrafo: formato, enlaces y marcas de nota al pie."""
    piezas: list[str] = []
    for hijo in parrafo._p:
        if hijo.tag == qn("w:r"):
            for ref in hijo.iter(qn("w:footnoteReference")):
                nid = ref.get(qn("w:id"))
                if nid in notas:
                    usadas.setdefault(nid, len(usadas) + 1)
                    piezas.append(f"[^{usadas[nid]}]")
            piezas.append(texto_run(hijo))
        elif hijo.tag == qn("w:hyperlink"):
            interno = "".join(texto_run(r) for r in hijo.findall(qn("w:r")))
            rid = hijo.get(qn("r:id"))
            destino = ""
            if rid:
                try:
                    destino = documento.part.rels[rid].target_ref
                except KeyError:
                    destino = ""
            piezas.append(f"[{interno}]({destino})" if destino and interno.strip() else interno)
    return "".join(piezas).strip()


def imagenes_de(parrafo: Paragraph, documento) -> list[tuple[bytes, str]]:
    """(blob, extensión) de cada imagen del párrafo — inline y flotante (DrawingML y VML)."""
    ids: list[str] = []
    for blip in parrafo._p.iter(f"{{{NS['a']}}}blip"):
        rid = blip.get(f"{{{NS['r']}}}embed") or blip.get(f"{{{NS['r']}}}link")
        if rid:
            ids.append(rid)
    for datos in parrafo._p.iter(f"{{{NS['v']}}}imagedata"):
        rid = datos.get(f"{{{NS['r']}}}id")
        if rid:
            ids.append(rid)
    salida = []
    for rid in ids:
        try:
            parte = documento.part.related_parts[rid]
            blob = parte.blob
        except (KeyError, AttributeError):
            continue
        ext = Path(str(getattr(parte, "partname", "img.png"))).suffix or ".png"
        salida.append((blob, ext))
    return salida


def tabla_markdown(tabla: Table) -> str:
    """Tabla Markdown. Las celdas multipárrafo se unen con <br>."""
    filas = []
    for fila in tabla.rows:
        celdas = []
        for celda in fila.cells:
            txt = "<br>".join(p.text.strip() for p in celda.paragraphs if p.text.strip())
            celdas.append(txt.replace("|", "\\|") or " ")
        filas.append(celdas)
    if not filas:
        return ""
    ancho = max(len(f) for f in filas)
    filas = [f + [" "] * (ancho - len(f)) for f in filas]
    cabecera = filas[0]
    cuerpo = filas[1:] or [[" "] * ancho]
    lineas = ["| " + " | ".join(cabecera) + " |",
              "| " + " | ".join(["---"] * ancho) + " |"]
    lineas += ["| " + " | ".join(f) + " |" for f in cuerpo]
    return "\n".join(lineas)


# ------------------------------------------------------------------ conversión
def convertir(entrada: Path, salida: Path, adjuntos: str = "_adjuntos", nombre: str = "",
              deident: bool = True, sobrescribir: bool = False) -> Conversion:
    """Convierte `entrada` a Markdown dentro de `salida`. Devuelve el detalle de la conversión.

    Las figuras se acumulan en memoria y se escriben al final, cuando ya se conoce el nombre
    definitivo del `.md` (el enlace y la carpeta de adjuntos deben coincidir).
    """
    if not entrada.exists():
        raise FileNotFoundError(f"No existe el .docx: {entrada}")
    documento = docx.Document(str(entrada))
    numeracion = mapa_numeracion(documento)
    notas = notas_al_pie(documento)
    usadas: dict[str, int] = {}

    titulo = ""
    cuerpo: list[str] = []
    pendientes: list[str] = []
    imagenes: list[tuple[bytes, str, int]] = []
    contadores: dict[int, int] = {}   # numeración de listas ordenadas, por nivel de sangría
    n_fig = n_tab = 0

    def _marca(indice: int, ext: str) -> str:
        return f"![{{alt}}]({quote(adjuntos)}/__SLUG__/fig-{indice:02d}{ext})"

    def _volcar_pendientes(pie: str = "") -> None:
        nonlocal pendientes
        for marca in pendientes:
            cuerpo.append("")
            cuerpo.append(marca.replace("{alt}", (pie or f"Figura {n_fig}")[:120]))
            if pie:
                cuerpo.append(f"*{pie}*")
            cuerpo.append("")
        pendientes = []

    for bloque in bloques(documento):
        if isinstance(bloque, Table):
            md = tabla_markdown(bloque)
            if md:
                n_tab += 1
                contadores.clear()
                _volcar_pendientes()
                cuerpo += ["", md, ""]
            continue

        for blob, ext in imagenes_de(bloque, documento):
            n_fig += 1
            imagenes.append((blob, ext, n_fig))
            pendientes.append(_marca(n_fig, ext))

        texto = texto_parrafo(bloque, documento, notas, usadas)
        if not texto:
            continue

        if pendientes and RE_PIE.match(texto):
            _volcar_pendientes(pie=texto)   # el párrafo es el pie de la figura anterior
            continue
        _volcar_pendientes()

        nivel = nivel_titulo(bloque)
        if nivel:
            if nivel == 1 and not titulo:
                titulo = texto
                continue
            cuerpo += ["", f"{'#' * nivel} {texto}", ""]
            continue

        es_lista, numerada, sangria = formato_lista(bloque, numeracion)
        if es_lista:
            if numerada:
                for profundo in [k for k in contadores if k > sangria]:
                    del contadores[profundo]
                contadores[sangria] = contadores.get(sangria, 0) + 1
                vineta = f"{contadores[sangria]}."
            else:
                vineta = "-"
            cuerpo.append(f"{'    ' * sangria}{vineta} {texto}")
        else:
            contadores.clear()
            cuerpo += [texto, ""]
    _volcar_pendientes()

    if not titulo:
        titulo = (documento.core_properties.title or "").strip() or entrada.stem

    # Nombre definitivo del .md antes de fijar los enlaces a las figuras.
    salida.mkdir(parents=True, exist_ok=True)
    base = slugificar(nombre or titulo)
    destino = salida / f"{base}.md"
    if destino.exists() and not sobrescribir:
        n = 2
        while (salida / f"{base}-{n}.md").exists():
            n += 1
        base = f"{base}-{n}"
        destino = salida / f"{base}.md"

    md_texto = "\n".join(cuerpo).replace("__SLUG__", quote(base))
    if usadas:
        md_texto += "\n\n## Notas\n\n" + "\n".join(
            f"[^{n}]: {notas[nid]}" for nid, n in sorted(usadas.items(), key=lambda kv: kv[1]))

    enmascarados = 0
    if deident:
        md_texto, e1 = deidentificar(md_texto)
        titulo, e2 = deidentificar(titulo)
        enmascarados = e1 + e2

    sha = hashlib.sha256(entrada.read_bytes()).hexdigest()
    md_texto = re.sub(r"\n{3,}", "\n\n", md_texto).strip() + "\n"
    destino.write_text(_frontmatter(titulo, entrada, sha, n_fig, n_tab, deident, enmascarados)
                       + "\n# " + titulo + "\n\n" + md_texto, encoding="utf-8")

    advertencias: list[str] = []
    if imagenes:
        carpeta = salida / adjuntos / base
        carpeta.mkdir(parents=True, exist_ok=True)
        for blob, ext, indice in imagenes:
            (carpeta / f"fig-{indice:02d}{ext}").write_bytes(blob)
        advertencias.append(f"{n_fig} figura(s) en {carpeta}")
    if not md_texto.strip():
        advertencias.append("el documento no aportó texto: revisa si es un escaneo sin OCR")
    return Conversion(destino, titulo, n_fig, n_tab, enmascarados, len(usadas), advertencias)


def _frontmatter(titulo: str, entrada: Path, sha: str, figuras: int, tablas: int,
                 deident: bool, enmascarados: int) -> str:
    """YAML para Obsidian/Notion. Si se enmascaró PHI, no se guarda el nombre original (R8)."""
    campos = [
        "---",
        'titulo: "%s"' % titulo.replace('"', "'"),
        "tipo: resumen-clinico",
        "origen: docx",
        f"fecha_conversion: {date.today().isoformat()}",
        f"sha256_origen: {sha[:16]}",
        f"figuras: {figuras}",
        f"tablas: {tablas}",
        f"deidentificado: {'true' if deident else 'false'}",
    ]
    if enmascarados:
        campos.append(f"datos_enmascarados: {enmascarados}")
    else:
        campos.append('archivo_origen: "%s"' % entrada.name)
    campos += ["tags: [brain, resumen-clinico]", "---"]
    return "\n".join(campos) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Convierte un resumen clínico .docx a Markdown conservando las figuras.")
    p.add_argument("entrada", help="archivo .docx de entrada")
    p.add_argument("--salida", required=True, help="carpeta destino (p. ej. la de OneDrive)")
    p.add_argument("--adjuntos", default="_adjuntos", help="subcarpeta de figuras (defecto: _adjuntos)")
    p.add_argument("--slug", default="", help="nombre base del .md (por defecto, del título)")
    p.add_argument("--sin-deidentificar", action="store_true",
                   help="no enmascarar RUT/nombres/teléfonos (solo si el documento no tiene PHI)")
    p.add_argument("--sobrescribir", action="store_true")
    p.add_argument("--json", action="store_true", help="imprime el resultado como JSON")
    args = p.parse_args(argv)

    res = convertir(Path(args.entrada), Path(args.salida), args.adjuntos, args.slug,
                    deident=not args.sin_deidentificar, sobrescribir=args.sobrescribir)
    if args.json:
        print(json.dumps(res.como_dict(), ensure_ascii=False))
    else:
        print(f"{res.md}  ({res.figuras} figuras, {res.tablas} tablas, "
              f"{res.enmascarados} datos enmascarados)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
