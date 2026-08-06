#!/usr/bin/env python3
"""Verificador del informe de `medicalinfosummary`.

Comprueba lo que se puede comprobar sin criterio clínico: estructura de las ocho
secciones, compatibilidad con Notion, sintaxis Mermaid, URLs de imagen vivas, y
—lo más importante— que **cada PMID citado exista y su título coincida** con lo
afirmado en la bibliografía (R2, anti-alucinación de citas).

Correrlo antes de entregar cuesta segundos y evita el único error que destruye
la confianza en una síntesis: una referencia inventada.

Uso:
    python3 verificar_informe.py <informe.md> [--fuentes <fuentes.json>] [--rapido]

    --rapido  omite las comprobaciones de red (PMIDs y URLs de imagen)

Salida: informe de checks por consola. Código 0 si todo pasa, 1 si algo falla.
Solo biblioteca estándar.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
EMAIL = os.environ.get("ENTREZ_EMAIL", "")
UA = "medicalinfosummary-verificador/1.0"

SECCIONES = [
    "Definición", "Epidemiología", "Fisiopatología", "Clínica",
    "Diagnóstico", "Diagnóstico diferencial", "", "Tratamiento",
]

OK, FALLO, AVISO = "  ok  ", " FALLO", " aviso"
resultados: list[tuple[str, str, str]] = []


def check(estado: str, nombre: str, detalle: str = "") -> None:
    resultados.append((estado, nombre, detalle))


# ------------------------------------------------------------------ estructura


def verificar_estructura(texto: str) -> None:
    encabezados = re.findall(r"^## (\d)\.\s+(.+)$", texto, re.M)
    nums = [int(n) for n, _ in encabezados]
    if nums == list(range(1, 9)):
        check(OK, "Las 8 secciones están y en orden",
              " · ".join(t[:22] for _, t in encabezados))
    else:
        faltan = sorted(set(range(1, 9)) - set(nums))
        check(FALLO, "Las 8 secciones están y en orden",
              f"encontradas {nums}, faltan {faltan}")

    for titulo in ("Referencias", "Qué quedó fuera"):
        estado = OK if re.search(rf"^## {re.escape(titulo)}", texto, re.M) else FALLO
        check(estado, f"Sección '{titulo}' presente")


def verificar_notion(texto: str) -> None:
    # Los bloques de código pueden contener # legítimos; los excluimos.
    sin_codigo = re.sub(r"```.*?```", "", texto, flags=re.S)

    h4 = re.findall(r"^#{4,}\s", sin_codigo, re.M)
    check(OK if not h4 else FALLO, "Sin encabezados de nivel 4+ (Notion los pierde)",
          f"{len(h4)} encontrados" if h4 else "")

    latex = re.findall(r"\$\$.+?\$\$", sin_codigo, re.S)
    check(OK if not latex else FALLO, "Sin bloques LaTeX $$ (no convierten al pegar)",
          f"{len(latex)} encontrados" if latex else "")

    # Tablas: toda fila separadora debe tener el mismo nº de columnas que su cabecera.
    malas = 0
    lineas = sin_codigo.split("\n")
    for i, ln in enumerate(lineas[:-1]):
        if re.match(r"^\s*\|[\s:|-]+\|\s*$", lineas[i + 1]) and ln.strip().startswith("|"):
            if ln.count("|") != lineas[i + 1].count("|"):
                malas += 1
    check(OK if not malas else FALLO, "Tablas bien formadas para Notion",
          f"{malas} con columnas desalineadas" if malas else "")


def verificar_mermaid(texto: str) -> None:
    bloques = re.findall(r"```mermaid\n(.*?)```", texto, re.S)
    if len(bloques) < 2:
        check(FALLO, "Al menos 2 diagramas Mermaid", f"{len(bloques)} encontrados")
        return
    problemas = []
    for i, b in enumerate(bloques, 1):
        if not re.match(r"\s*(flowchart|graph|sequenceDiagram|classDiagram|stateDiagram)",
                        b.strip()):
            problemas.append(f"#{i}: sin tipo de diagrama")
        if "<br>" in b or "<BR>" in b:
            problemas.append(f"#{i}: contiene HTML <br>")
        # Paréntesis o comas dentro de una etiqueta sin comillas rompen el parser.
        for etiqueta in re.findall(r"\[([^\]]*)\]", b):
            if not etiqueta.startswith('"') and re.search(r"[(),:]", etiqueta):
                problemas.append(f'#{i}: etiqueta sin comillas -> [{etiqueta[:28]}]')
    check(OK if not problemas else FALLO, f"Sintaxis Mermaid ({len(bloques)} diagramas)",
          "; ".join(problemas[:4]))


def _partes(texto: str) -> tuple[str, str]:
    """Devuelve (cuerpo, bloque_de_referencias).

    El cuerpo es todo menos la lista de referencias: incluye lo que va **después**
    de ella ('Qué quedó fuera'), donde también se citan fuentes.
    """
    if "## Referencias" not in texto:
        return texto, ""
    antes, resto = texto.split("## Referencias", 1)
    partes = re.split(r"^## ", resto, maxsplit=1, flags=re.M)
    bloque = partes[0]
    despues = "## " + partes[1] if len(partes) > 1 else ""
    return antes + despues, bloque


def verificar_citas(texto: str) -> None:
    cuerpo, bloque = _partes(texto)
    n_refs = max((int(r) for r in re.findall(r"^(\d+)\.\s", bloque, re.M)), default=0)

    citadas = set()
    for m in re.findall(r"\[(\d+(?:\s*,\s*\d+)*)\]", cuerpo):
        citadas.update(int(x) for x in m.split(","))

    huerfanas = sorted(n for n in citadas if n > n_refs)
    check(OK if not huerfanas else FALLO, "Toda cita [n] tiene su referencia",
          f"citas sin referencia: {huerfanas}" if huerfanas else f"{len(citadas)} refs citadas")

    sin_citar = sorted(set(range(1, n_refs + 1)) - citadas)
    check(OK if not sin_citar else AVISO, "Toda referencia se cita en el cuerpo",
          f"nunca citadas: {sin_citar}" if sin_citar else "")


def verificar_anios(texto: str) -> None:
    _, bloque = _partes(texto)
    anios = [int(a) for a in re.findall(r"\.\s(19\d{2}|20\d{2})\.", bloque)]
    viejos = [a for a in anios if a < 2000]
    check(OK if not viejos else FALLO, "Ninguna fuente anterior a 2000",
          f"{viejos}" if viejos else f"rango {min(anios)}–{max(anios)}" if anios else "")


# ------------------------------------------------------------------------ red


def _get_json(url: str, params: dict):
    qs = urllib.parse.urlencode({k: v for k, v in params.items() if v})
    req = urllib.request.Request(f"{url}?{qs}", headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except Exception:
        return None


def verificar_pmids(texto: str) -> None:
    """El check que más importa: que los PMIDs existan y su título coincida."""
    _, bloque = _partes(texto)
    entradas = re.findall(r"^\d+\.\s+(.*?)PMID:\s*(\d+)", bloque, re.M | re.S)
    if not entradas:
        check(AVISO, "Verificación de PMIDs", "no se encontraron PMIDs en la bibliografía")
        return

    pmids = [p for _, p in entradas]
    data = _get_json(EUTILS, {"db": "pubmed", "id": ",".join(pmids),
                              "retmode": "json", "email": EMAIL})
    if not data or "result" not in data:
        check(AVISO, "Verificación de PMIDs", "NCBI no respondió; reintenta")
        return

    res = data["result"]
    inexistentes, discordantes = [], []
    for cita, pmid in entradas:
        reg = res.get(pmid)
        if not reg or "error" in reg or not reg.get("title"):
            inexistentes.append(pmid)
            continue
        # ¿Coinciden? Comparamos por solapamiento de palabras significativas del título.
        real = set(re.findall(r"[a-z]{5,}", reg["title"].lower()))
        citado = set(re.findall(r"[a-z]{5,}", cita.lower()))
        if real and len(real & citado) / len(real) < 0.34:
            discordantes.append(f"{pmid} → «{reg['title'][:55]}»")

    check(OK if not inexistentes else FALLO,
          f"Los {len(pmids)} PMIDs existen en PubMed",
          f"inexistentes: {inexistentes}" if inexistentes else "")
    check(OK if not discordantes else FALLO, "Título citado coincide con el de PubMed",
          "; ".join(discordantes[:3]))


def verificar_imagenes(texto: str) -> None:
    urls = re.findall(r"!\[[^\]]*\]\((https?://[^)]+)\)", texto)
    if not urls:
        check(AVISO, "URLs de imagen", "sin imágenes externas (¿solo Mermaid?)")
        return
    rotas = []
    for u in urls:
        req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}, method="HEAD")
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                if r.status != 200:
                    rotas.append(f"{r.status} {u[:50]}")
        except Exception as exc:
            rotas.append(f"{type(exc).__name__} {u[:50]}")
        time.sleep(0.2)
    check(OK if not rotas else FALLO, f"Las {len(urls)} imágenes responden 200",
          "; ".join(rotas[:3]))


# ----------------------------------------------------------------------- main


def main() -> int:
    ap = argparse.ArgumentParser(description="Verifica un informe de medicalinfosummary.")
    ap.add_argument("informe")
    ap.add_argument("--fuentes", help="fuentes.json para contrastar (opcional)")
    ap.add_argument("--rapido", action="store_true", help="omite comprobaciones de red")
    args = ap.parse_args()

    texto = Path(args.informe).expanduser().read_text(encoding="utf-8")

    verificar_estructura(texto)
    verificar_notion(texto)
    verificar_mermaid(texto)
    verificar_citas(texto)
    verificar_anios(texto)
    if not args.rapido:
        verificar_pmids(texto)
        verificar_imagenes(texto)

    if args.fuentes and Path(args.fuentes).exists():
        f = json.loads(Path(args.fuentes).read_text(encoding="utf-8"))
        cosechados = {s["pmid"] for s in f["fuentes"]}
        citados = set(re.findall(r"PMID:\s*(\d+)", texto))
        externos = citados - cosechados
        check(OK if not externos else AVISO,
              "PMIDs citados provienen de la cosecha",
              f"{len(externos)} externos (verifícalos a mano): {sorted(externos)[:5]}"
              if externos else "")

    print(f"\nVerificación de {Path(args.informe).name}\n" + "─" * 68)
    for estado, nombre, detalle in resultados:
        print(f"[{estado}] {nombre}")
        if detalle:
            print(f"         {detalle}")
    fallos = sum(1 for e, _, _ in resultados if e == FALLO)
    avisos = sum(1 for e, _, _ in resultados if e == AVISO)
    print("─" * 68)
    print(f"{len(resultados) - fallos - avisos} ok · {avisos} avisos · {fallos} fallos\n")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
