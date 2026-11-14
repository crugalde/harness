#!/usr/bin/env python3
"""verificar.py — Control de calidad de los entregables antes de darlos por terminados.

Valida lo comprobable sin criterio experto, según el tipo de documento:
  resumen    (agente 3) campos bibliográficos, resumen estructurado completo,
             >=2 aspectos positivos, >=2 negativos, aporte global, hallazgos con página.
  analisis   (agente 4) secciones en orden, tabla de estudios (>=2 filas), esquema Mermaid,
             citas [n] <-> referencias.
  respuesta  (agente 2) respuesta, evidencia citada, certeza declarada, límites.

En todos: sin marcadores de plantilla {{...}} sin llenar, tablas bien formadas, sintaxis
Mermaid básica y —lo más importante— que cada PMID citado exista en PubMed y su título
coincida con lo afirmado (anti-alucinación de citas). Heredado de verificar_informe.py.

Uso:
    python3 scripts/verificar.py workspace/resumenes_papers/estudio.md
    python3 scripts/verificar.py workspace/analisis_globales/x.md --tipo analisis
    python3 scripts/verificar.py informe.md --rapido          # sin red (omite PMIDs)
    python3 scripts/verificar.py informe.md --fuentes workspace/busquedas/x/fuentes.json

El tipo se infiere de `tags:` en el frontmatter si no se pasa --tipo.
Código de salida: 0 si no hay fallos, 1 si hay alguno (los avisos no fallan).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _comun import http_get, load_env  # noqa: E402

ESUMMARY = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
OK, FALLO, AVISO = "  ok  ", " FALLO", " aviso"

# Fuente única de la estructura de cada plantilla (tests/test_estructura.py comprueba que
# las plantillas en .claude/skills/*/plantilla.md coinciden con esto).
TIPOS: dict[str, dict[str, list[str]]] = {
    "resumen": {
        "frontmatter": ["titulo", "autores", "anio", "tipo_estudio", "fuente", "texto_analizado"],
        "secciones": [
            "1. Resumen estructurado",
            "2. Aspectos positivos",
            "3. Aspectos negativos",
            "4. Aporte global al tema",
            "5. Hallazgos destacados declarados por los autores",
            "6. Trazabilidad y límites del resumen",
        ],
        "campos_resumen": [
            "Tipo de estudio",
            "Población",
            "Objetivo",
            "Método",
            "Resultados",
            "Conclusiones",
        ],
    },
    "analisis": {
        "frontmatter": ["titulo", "fecha", "n_estudios", "nivel_lectura"],
        "secciones": [
            "1. Resumen ejecutivo",
            "2. Estudios incluidos",
            "3. Hallazgos convergentes",
            "4. Divergencias y heterogeneidad",
            "5. Certeza de la evidencia",
            "6. Esquema integrador",
            "7. Detalles a considerar",
            "8. Vacíos y próximos pasos",
            "Referencias",
        ],
    },
    "respuesta": {
        "frontmatter": ["pregunta", "fecha", "fuentes_consultadas", "certeza"],
        "secciones": [
            "1. Respuesta",
            "2. Evidencia que la sustenta",
            "3. Certeza y por qué",
            "4. Lo que no se encontró o queda abierto",
            "Referencias",
        ],
    },
}
CERTEZAS = {"alta", "moderada", "baja", "muy baja"}
TIPOS_MERMAID = (
    "flowchart",
    "graph",
    "mindmap",
    "sequenceDiagram",
    "classDiagram",
    "stateDiagram",
    "quadrantChart",
    "timeline",
    "erDiagram",
    "pie",
)


class Informe:
    def __init__(self) -> None:
        self.filas: list[tuple[str, str, str]] = []

    def check(self, estado: str, nombre: str, detalle: str = "") -> None:
        self.filas.append((estado, nombre, detalle))

    @property
    def fallos(self) -> int:
        return sum(1 for e, _, _ in self.filas if e == FALLO)

    def imprimir(self, titulo: str) -> None:
        print(f"\nVerificación de {titulo}\n" + "─" * 70)
        for estado, nombre, detalle in self.filas:
            print(f"[{estado}] {nombre}")
            if detalle:
                print(f"         {detalle}")
        avisos = sum(1 for e, _, _ in self.filas if e == AVISO)
        print("─" * 70)
        print(
            f"{len(self.filas) - self.fallos - avisos} ok · {avisos} avisos · {self.fallos} fallos\n"
        )


# --------------------------------------------------------------------- parseo


def frontmatter(texto: str) -> tuple[dict[str, str], str]:
    """(campos, cuerpo). Parser mínimo `clave: valor` (sin dependencias)."""
    m = re.match(r"^---\n(.*?)\n---\n?", texto, re.S)
    if not m:
        return {}, texto
    campos = {}
    for linea in m.group(1).splitlines():
        if ":" in linea and not linea.startswith((" ", "\t", "-")):
            k, _, v = linea.partition(":")
            campos[k.strip()] = v.strip().strip('"').strip("'")
    return campos, texto[m.end() :]


def secciones(cuerpo: str) -> dict[str, str]:
    """{título_de_## : contenido} en orden de aparición."""
    partes = re.split(r"^## +(.+?)\s*$", cuerpo, flags=re.M)
    return {partes[i].strip(): partes[i + 1] for i in range(1, len(partes) - 1, 2)}


def sin_codigo(texto: str) -> str:
    return re.sub(r"```.*?```", "", texto, flags=re.S)


def inferir_tipo(campos: dict[str, str]) -> str | None:
    tags = campos.get("tags", "")
    for tipo in TIPOS:
        if tipo in tags:
            return tipo
    return None


# ---------------------------------------------------------------- comprobaciones


def verificar_frontmatter(inf: Informe, campos: dict[str, str], tipo: str) -> None:
    faltan = [k for k in TIPOS[tipo]["frontmatter"] if not campos.get(k)]
    inf.check(
        OK if not faltan else FALLO,
        "Frontmatter con campos obligatorios",
        f"faltan o vacíos: {faltan}" if faltan else "",
    )
    if tipo == "respuesta" and campos.get("certeza"):
        valido = campos["certeza"].lower() in CERTEZAS
        inf.check(
            OK if valido else FALLO,
            "Certeza en escala válida",
            "" if valido else f"'{campos['certeza']}' no está en {sorted(CERTEZAS)}",
        )


def verificar_secciones(inf: Informe, secs: dict[str, str], tipo: str) -> None:
    esperadas = TIPOS[tipo]["secciones"]
    presentes = [s for s in secs if s in esperadas]
    faltan = [s for s in esperadas if s not in secs]
    en_orden = presentes == [s for s in esperadas if s in presentes]
    inf.check(
        OK if not faltan and en_orden else FALLO,
        f"Las {len(esperadas)} secciones están y en orden",
        (f"faltan: {faltan}. " if faltan else "") + ("" if en_orden else "orden alterado"),
    )
    # Un bloque de código cuenta como contenido: el esquema integrador es solo Mermaid.
    vacias = [s for s in esperadas if s in secs and not secs[s].strip()]
    inf.check(
        OK if not vacias else FALLO, "Ninguna sección vacía", f"vacías: {vacias}" if vacias else ""
    )


def _items(texto: str) -> list[str]:
    return [
        i.strip() for i in re.findall(r"^\s*(?:\d+[.)]|[-*])\s+(.+)$", texto, re.M) if i.strip()
    ]


def verificar_resumen(inf: Informe, secs: dict[str, str], campos: dict[str, str]) -> None:
    estructurado = secs.get("1. Resumen estructurado", "")
    faltan = []
    for campo in TIPOS["resumen"]["campos_resumen"]:
        # [ \t]* y no \s*: un campo vacío no debe "robar" el contenido de la línea siguiente.
        m = re.search(rf"\*\*{re.escape(campo)}[^*\n]*\*\*[ \t]*:?[ \t]*(.*)", estructurado)
        if not m or len(m.group(1).strip()) < 3:
            faltan.append(campo)
    inf.check(
        OK if not faltan else FALLO,
        "Resumen estructurado con los 6 campos llenos",
        f"faltan o vacíos: {faltan}" if faltan else "",
    )
    for sec, nombre in (
        ("2. Aspectos positivos", "positivos"),
        ("3. Aspectos negativos", "negativos"),
    ):
        n = len(_items(secs.get(sec, "")))
        inf.check(OK if n >= 2 else FALLO, f"Al menos 2 aspectos {nombre}", f"{n} encontrados")
    hallazgos = _items(secs.get("5. Hallazgos destacados declarados por los autores", ""))
    inf.check(OK if hallazgos else FALLO, "Al menos 1 hallazgo destacado", f"{len(hallazgos)}")
    if campos.get("texto_analizado", "").lower().startswith("complet") and hallazgos:
        sin_pag = [h[:40] for h in hallazgos if not re.search(r"\(p\.\s*\d+", h)]
        inf.check(
            OK if not sin_pag else AVISO,
            "Hallazgos con página de origen (p. N)",
            f"sin página: {sin_pag[:3]}" if sin_pag else "",
        )
    if campos.get("doi") and not re.match(r"^10\.\d{4,9}/\S+$", campos["doi"]):
        inf.check(FALLO, "DOI con formato válido", campos["doi"])


def verificar_analisis(inf: Informe, secs: dict[str, str]) -> None:
    tabla = secs.get("2. Estudios incluidos", "")
    filas = [ln for ln in tabla.splitlines() if ln.strip().startswith("|")]
    datos = max(0, len(filas) - 2)
    inf.check(
        OK if datos >= 2 else FALLO, "Tabla de estudios con al menos 2 filas", f"{datos} filas"
    )
    esquema = secs.get("6. Esquema integrador", "")
    n = len(re.findall(r"```mermaid", esquema))
    inf.check(OK if n >= 1 else FALLO, "Esquema integrador en Mermaid", f"{n} diagramas")


def verificar_respuesta(inf: Informe, secs: dict[str, str]) -> None:
    texto = secs.get("1. Respuesta", "") + secs.get("2. Evidencia que la sustenta", "")
    n = len(re.findall(r"\[\d+(?:\s*[,–-]\s*\d+)*\]", texto))
    inf.check(OK if n else FALLO, "Respuesta y evidencia con citas [n]", f"{n} citas")


def verificar_placeholders(inf: Informe, texto: str) -> None:
    restos = re.findall(r"\{\{[^}]*\}\}", texto)
    inf.check(
        OK if not restos else FALLO,
        "Sin marcadores de plantilla {{...}} sin llenar",
        f"{len(restos)}: {restos[:3]}" if restos else "",
    )


def verificar_tablas(inf: Informe, texto: str) -> None:
    lineas = sin_codigo(texto).split("\n")
    malas = 0
    for i, ln in enumerate(lineas[:-1]):
        sep = lineas[i + 1]
        if re.match(r"^\s*\|[\s:|-]+\|\s*$", sep) and ln.strip().startswith("|"):
            if ln.count("|") != sep.count("|"):
                malas += 1
    inf.check(
        OK if not malas else FALLO, "Tablas bien formadas", f"{malas} desalineadas" if malas else ""
    )


def verificar_mermaid(inf: Informe, texto: str) -> None:
    bloques = re.findall(r"```mermaid\n(.*?)```", texto, re.S)
    if not bloques:
        return
    problemas = []
    for i, b in enumerate(bloques, 1):
        cabeza = b.strip()
        if not cabeza.startswith(TIPOS_MERMAID):
            problemas.append(f"#{i}: tipo de diagrama no reconocido")
            continue
        if "<br>" in b.lower():
            problemas.append(f"#{i}: contiene HTML <br>")
        if cabeza.startswith(("flowchart", "graph")):
            for etiqueta in re.findall(r"\[([^\]]*)\]", b):
                if not etiqueta.startswith('"') and re.search(r"[(),:;]", etiqueta):
                    problemas.append(f"#{i}: etiqueta sin comillas -> [{etiqueta[:28]}]")
    inf.check(
        OK if not problemas else FALLO,
        f"Sintaxis Mermaid ({len(bloques)} diagramas)",
        "; ".join(problemas[:4]),
    )


def _partes(cuerpo: str) -> tuple[str, str]:
    if "## Referencias" not in cuerpo:
        return cuerpo, ""
    antes, resto = cuerpo.split("## Referencias", 1)
    partes = re.split(r"^## ", resto, maxsplit=1, flags=re.M)
    return antes + ("## " + partes[1] if len(partes) > 1 else ""), partes[0]


def verificar_citas(inf: Informe, cuerpo: str) -> None:
    texto, bloque = _partes(cuerpo)
    if not bloque:
        return
    n_refs = max((int(r) for r in re.findall(r"^(\d+)\.\s", bloque, re.M)), default=0)
    citadas: set[int] = set()
    for grupo in re.findall(r"\[(\d+(?:\s*[,–-]\s*\d+)*)\]", sin_codigo(texto)):
        for parte in re.split(r"\s*,\s*", grupo):
            if re.match(r"^\d+\s*[–-]\s*\d+$", parte):
                a, b = (int(x) for x in re.split(r"\s*[–-]\s*", parte))
                citadas.update(range(a, b + 1))
            else:
                citadas.add(int(parte))
    huerfanas = sorted(n for n in citadas if n > n_refs or n < 1)
    inf.check(
        OK if not huerfanas else FALLO,
        "Toda cita [n] tiene su referencia",
        f"sin referencia: {huerfanas}" if huerfanas else f"{len(citadas)} referencias citadas",
    )
    nunca = sorted(set(range(1, n_refs + 1)) - citadas)
    inf.check(
        OK if not nunca else AVISO,
        "Toda referencia se cita en el texto",
        f"nunca citadas: {nunca}" if nunca else "",
    )


def _coincide(titulo_real: str, citado: str) -> bool:
    real = set(re.findall(r"[a-z]{5,}", titulo_real.lower()))
    return not real or len(real & set(re.findall(r"[a-z]{5,}", citado.lower()))) / len(real) >= 0.34


def verificar_pmids(inf: Informe, cuerpo: str, campos: dict[str, str]) -> None:
    """El check que más importa: los PMIDs existen y el título coincide."""
    _, bloque = _partes(cuerpo)
    entradas = re.findall(r"^\d+\.\s+(.*?)PMID:\s*(\d+)", bloque, re.M | re.S)
    if campos.get("pmid", "").isdigit():
        entradas.append((campos.get("titulo", ""), campos["pmid"]))
    if not entradas:
        inf.check(AVISO, "Verificación de PMIDs", "no hay PMIDs que verificar")
        return
    pmids = sorted({p for _, p in entradas})
    data = http_get(ESUMMARY, {"db": "pubmed", "id": ",".join(pmids), "retmode": "json"})
    if not data or "result" not in data:
        inf.check(AVISO, "Verificación de PMIDs", "NCBI no respondió; reintenta con red")
        return
    res = data["result"]
    inexistentes, discordantes = [], []
    for citado, pmid in entradas:
        reg = res.get(pmid) or {}
        if "error" in reg or not reg.get("title"):
            inexistentes.append(pmid)
        elif not _coincide(reg["title"], citado):
            discordantes.append(f"{pmid} → «{reg['title'][:55]}»")
    inf.check(
        OK if not inexistentes else FALLO,
        f"Los {len(pmids)} PMIDs existen en PubMed",
        f"inexistentes: {inexistentes}" if inexistentes else "",
    )
    inf.check(
        OK if not discordantes else FALLO,
        "Título citado coincide con el de PubMed",
        "; ".join(discordantes[:3]),
    )


def verificar_contra_busqueda(inf: Informe, texto: str, fuentes_json: Path) -> None:
    datos = json.loads(fuentes_json.read_text(encoding="utf-8"))
    cosechados = {str(f.get("pmid")) for f in datos.get("fuentes", []) if f.get("pmid")}
    externos = set(re.findall(r"PMID:\s*(\d+)", texto)) - cosechados
    inf.check(
        OK if not externos else AVISO,
        "PMIDs citados provienen de la búsqueda registrada",
        f"{len(externos)} externos (verificar a mano): {sorted(externos)[:5]}" if externos else "",
    )


# ------------------------------------------------------------------------ main


def verificar(
    texto: str, tipo: str | None, rapido: bool, fuentes: Path | None
) -> tuple[Informe, str]:
    inf = Informe()
    campos, cuerpo = frontmatter(texto)
    tipo = tipo or inferir_tipo(campos)
    if tipo not in TIPOS:
        inf.check(
            FALLO, "Tipo de documento", "pasa --tipo resumen|analisis|respuesta o tags: [...]"
        )
        return inf, "desconocido"
    secs = secciones(cuerpo)
    verificar_frontmatter(inf, campos, tipo)
    verificar_secciones(inf, secs, tipo)
    {
        "resumen": lambda: verificar_resumen(inf, secs, campos),
        "analisis": lambda: verificar_analisis(inf, secs),
        "respuesta": lambda: verificar_respuesta(inf, secs),
    }[tipo]()
    verificar_placeholders(inf, texto)
    verificar_tablas(inf, cuerpo)
    verificar_mermaid(inf, cuerpo)
    verificar_citas(inf, cuerpo)
    if not rapido:
        verificar_pmids(inf, cuerpo, campos)
    if fuentes and fuentes.is_file():
        verificar_contra_busqueda(inf, texto, fuentes)
    return inf, tipo


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Verifica un resumen, análisis o respuesta.")
    ap.add_argument("archivo")
    ap.add_argument("--tipo", choices=sorted(TIPOS))
    ap.add_argument("--rapido", action="store_true", help="Omite comprobaciones de red")
    ap.add_argument("--fuentes", help="fuentes.json de buscar_literatura.py para contrastar")
    args = ap.parse_args(argv)
    load_env()
    ruta = Path(args.archivo).expanduser()
    if not ruta.is_file():
        print(f"No existe: {ruta}", file=sys.stderr)
        return 1
    inf, tipo = verificar(
        ruta.read_text(encoding="utf-8"),
        args.tipo,
        args.rapido,
        Path(args.fuentes).expanduser() if args.fuentes else None,
    )
    inf.imprimir(f"{ruta.name} ({tipo})")
    return 1 if inf.fallos else 0


if __name__ == "__main__":
    sys.exit(main())
