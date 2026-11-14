#!/usr/bin/env python3
"""extraer_texto.py — Texto y metadatos de un estudio en PDF, Word (.docx), .md o .txt.

Lo usa el agente 3 (resumen de un estudio) antes de leer, y fuentes_locales.py para buscar
en carpetas. Inserta marcas de página `[p. N]` en PDFs para que cada hallazgo citado en el
resumen sea rastreable a su página.

Uso:
    python3 scripts/extraer_texto.py workspace/papers_locales/estudio.pdf
    python3 scripts/extraer_texto.py estudio.docx --out workspace/agent_handoffs/estudio.md
    python3 scripts/extraer_texto.py estudio.pdf --json      # solo metadatos detectados

Dependencias: pypdf (PDF) y python-docx (Word). .md/.txt no requieren nada.
Limitación: un PDF escaneado sin capa de texto devuelve casi nada; el script lo advierte
(requiere OCR externo, p. ej. `ocrmypdf entrada.pdf salida.pdf`).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _comun import log, normalizar_doi  # noqa: E402

EXTENSIONES = {".pdf", ".docx", ".md", ".markdown", ".txt"}
RE_DOI = re.compile(r"\b(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+[A-Za-z0-9])")
RE_PMID = re.compile(r"\bPMID:?\s*(\d{6,9})\b", re.I)
RE_ANIO = re.compile(r"\b(19[5-9]\d|20[0-4]\d)\b")
MIN_CARACTERES_POR_PAGINA = 200  # por debajo, probablemente escaneado


@dataclass
class Documento:
    ruta: str
    formato: str
    titulo: str = ""
    autores: str = ""
    anio: str = ""
    doi: str = ""
    pmid: str = ""
    paginas: int = 0
    caracteres: int = 0
    advertencias: list[str] = field(default_factory=list)
    texto: str = ""


def _leer_pdf(ruta: Path, doc: Documento) -> None:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("Falta pypdf: pip install pypdf") from exc
    lector = PdfReader(str(ruta))
    if lector.is_encrypted:
        try:
            lector.decrypt("")
        except Exception as exc:  # pypdf lanza tipos variados según el cifrado
            raise RuntimeError(f"PDF cifrado y no se pudo abrir: {exc}") from exc
    meta = lector.metadata or {}
    doc.titulo = str(meta.get("/Title") or "").strip()
    doc.autores = str(meta.get("/Author") or "").strip()
    partes = []
    for i, pagina in enumerate(lector.pages, 1):
        try:
            contenido = pagina.extract_text() or ""
        except Exception as exc:  # una página corrupta no debe abortar el documento
            doc.advertencias.append(f"página {i} ilegible: {exc}")
            contenido = ""
        partes.append(f"[p. {i}]\n{contenido.strip()}")
    doc.paginas = len(lector.pages)
    doc.texto = "\n\n".join(partes)


def _leer_docx(ruta: Path, doc: Documento) -> None:
    try:
        import docx
    except ImportError as exc:
        raise RuntimeError("Falta python-docx: pip install python-docx") from exc
    d = docx.Document(str(ruta))
    props = d.core_properties
    doc.titulo = (props.title or "").strip()
    doc.autores = (props.author or "").strip()
    bloques = [p.text for p in d.paragraphs if p.text.strip()]
    for t_idx, tabla in enumerate(d.tables, 1):
        bloques.append(f"[tabla {t_idx}]")
        for fila in tabla.rows:
            bloques.append(" | ".join(celda.text.strip() for celda in fila.cells))
    doc.texto = "\n".join(bloques)


def _primer_titulo_plausible(texto: str) -> str:
    """Primera línea con aspecto de título (ni encabezado de revista ni DOI)."""
    for linea in texto.splitlines():
        s = linea.strip().lstrip("#").strip()
        if s.startswith("[p.") or not s:
            continue
        if 20 <= len(s) <= 250 and not RE_DOI.search(s) and not s.lower().startswith("http"):
            return s
    return ""


def extraer(ruta: Path) -> Documento:
    """Extrae texto y metadatos. Lanza RuntimeError con mensaje claro si no puede."""
    ruta = ruta.expanduser()
    if not ruta.is_file():
        raise RuntimeError(f"No existe el archivo: {ruta}")
    ext = ruta.suffix.lower()
    if ext not in EXTENSIONES:
        raise RuntimeError(f"Formato no soportado: {ext} (soportados: {sorted(EXTENSIONES)})")
    doc = Documento(ruta=str(ruta), formato=ext.lstrip("."))
    if ext == ".pdf":
        _leer_pdf(ruta, doc)
    elif ext == ".docx":
        _leer_docx(ruta, doc)
    else:
        doc.texto = ruta.read_text(encoding="utf-8", errors="replace")

    doc.caracteres = len(doc.texto)
    cabecera = doc.texto[:6000]
    if m := RE_DOI.search(cabecera):
        doc.doi = normalizar_doi(m.group(1).rstrip(".,;)"))
    if m := RE_PMID.search(doc.texto):
        doc.pmid = m.group(1)
    if not doc.titulo or doc.titulo.lower() in {"untitled", "microsoft word"}:
        doc.titulo = _primer_titulo_plausible(doc.texto)
    if anios := RE_ANIO.findall(cabecera):
        doc.anio = max(set(anios), key=anios.count)

    if ext == ".pdf" and doc.paginas:
        utiles = len(re.sub(r"\[p\. \d+\]|\s", "", doc.texto))
        if utiles / doc.paginas < MIN_CARACTERES_POR_PAGINA:
            doc.advertencias.append(
                "Muy poco texto por página: probablemente escaneado. Requiere OCR "
                "(p. ej. `ocrmypdf entrada.pdf salida.pdf`) antes de resumir."
            )
    if not doc.doi and not doc.pmid:
        doc.advertencias.append("No se detectó DOI ni PMID: verificar la identidad del estudio.")
    return doc


def a_markdown(doc: Documento) -> str:
    meta = {k: v for k, v in asdict(doc).items() if k not in ("texto", "advertencias")}
    lineas = ["---"] + [f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in meta.items()]
    lineas += ["---", ""]
    if doc.advertencias:
        lineas += ["> **Advertencias de extracción**"] + [f"> - {a}" for a in doc.advertencias]
        lineas.append("")
    return "\n".join(lineas) + doc.texto + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Extrae texto y metadatos de PDF/DOCX/MD/TXT.")
    ap.add_argument("archivo")
    ap.add_argument("--out", help="Guarda el texto con cabecera YAML en esta ruta (.md)")
    ap.add_argument("--json", action="store_true", help="Imprime solo metadatos en JSON")
    args = ap.parse_args(argv)
    try:
        doc = extraer(Path(args.archivo))
    except RuntimeError as exc:
        log.error("%s", exc)
        return 1
    for a in doc.advertencias:
        log.warning("%s", a)
    if args.json:
        meta = {k: v for k, v in asdict(doc).items() if k != "texto"}
        print(json.dumps(meta, ensure_ascii=False, indent=2))
        return 0
    salida = a_markdown(doc)
    if args.out:
        destino = Path(args.out).expanduser()
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(salida, encoding="utf-8")
        print(f"{doc.caracteres} caracteres, {doc.paginas or '-'} páginas -> {destino}")
    else:
        sys.stdout.write(salida)
    return 0


if __name__ == "__main__":
    sys.exit(main())
