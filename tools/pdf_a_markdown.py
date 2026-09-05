#!/usr/bin/env python3
"""pdf_a_markdown.py — Convierte un PDF a Markdown y extrae sus imágenes.

Lo que lo distingue de un `extract_text()` a secas:

- **Columnas.** Un paper a dos columnas extraído de corrido entrelaza las columnas y el
  texto sale revuelto. Aquí se detecta el corredor vertical vacío y cada columna se lee
  por separado, en orden de lectura.
- **Encabezados.** El tamaño de fuente mediano del cuerpo se usa como referencia: lo que
  lo supera de forma consistente se promueve a `#`/`##`.
- **Tablas.** Van como tablas Markdown, y sus palabras se excluyen del flujo de texto
  para que no aparezcan dos veces.
- **Imágenes.** Las imágenes incrustadas se guardan en `imagenes/` y quedan referenciadas
  en su página. Un PDF con figuras vectoriales (frecuente en revistas) no tiene imágenes
  incrustadas que extraer: eso se informa, no se silencia.

Uso:
  python tools/pdf_a_markdown.py entrada.pdf --out carpeta [--columnas auto|1|2] [--dpi 300]
Req: pip install pdfplumber pypdf pypdfium2
"""
from __future__ import annotations

import argparse
import re
import statistics
import sys
from pathlib import Path

def _pdfplumber():
    """Import perezoso: el registry del harness carga esta tool sin que pdfplumber esté
    instalado, y el CI corre la suite en un entorno pelado a propósito. Fallar al
    importar rompería ambos; fallar al usarla es lo correcto."""
    try:
        import pdfplumber
    except ImportError as e:
        raise RuntimeError("Falta pdfplumber: pip install pdfplumber") from e
    return pdfplumber


# ---------------------------------------------------------------------------
# Columnas
# ---------------------------------------------------------------------------
def punto_de_corte(page, base: float) -> float | None:
    """x del medianil entre dos columnas, o None si la página es de una sola.

    Mide **cobertura**: por cada franja de 1 pt cuenta cuántas palabras la cruzan
    (usando x0..x1, no el centro: un medianil de 15 pt se emborrona si se miden centros).
    El medianil es la franja más ancha con cobertura casi nula dentro del tercio central
    del **texto** — no de la página, que incluye márgenes y desplaza el tercio central
    fuera del medianil real.

    "Casi nula" y no "nula": un título o un pie a ancho completo cruzan el medianil y
    dejarían el corredor en cero palabras solo por casualidad. Se tolera un 2% de la
    cobertura máxima.
    """
    palabras = page.extract_words()
    if len(palabras) < 60:
        return None
    x_ini = int(min(w["x0"] for w in palabras))
    x_fin = int(max(w["x1"] for w in palabras)) + 1
    if x_fin - x_ini < 100:
        return None

    cobertura = [0] * (x_fin - x_ini + 1)
    for w in palabras:
        for i in range(max(0, int(w["x0"]) - x_ini), min(len(cobertura), int(w["x1"]) - x_ini + 1)):
            cobertura[i] += 1
    con_texto = [c for c in cobertura if c > 0]
    if not con_texto:
        return None
    # Umbral relativo a la cobertura típica del texto, no al máximo: en el medianil
    # medido de un paper del NEJM la cobertura cae de ~49 a 4 (las pocas líneas a ancho
    # completo que lo cruzan), así que exigir cero descarta medianiles perfectamente
    # buenos. Un cuarto de la cobertura mediana separa medianil de columna con holgura.
    umbral = max(2, statistics.median(con_texto) * 0.25)

    ancho = x_fin - x_ini
    lo, hi = int(ancho * 0.30), int(ancho * 0.70)
    mejor, ini_run = None, None
    for i in range(lo, hi):
        if cobertura[i] <= umbral:
            ini_run = i if ini_run is None else ini_run
        elif ini_run is not None:
            if mejor is None or (i - ini_run) > (mejor[1] - mejor[0]):
                mejor = (ini_run, i)
            ini_run = None
    if ini_run is not None and (mejor is None or (hi - ini_run) > (mejor[1] - mejor[0])):
        mejor = (ini_run, hi)

    # Un medianil real mide al menos medio cuerpo de texto (el del NEJM: ~8 pt).
    if mejor and (mejor[1] - mejor[0]) >= base * 0.5:
        return x_ini + (mejor[0] + mejor[1]) / 2
    return None


# ---------------------------------------------------------------------------
# Texto -> Markdown
# ---------------------------------------------------------------------------
def tam_cuerpo(pdf) -> float:
    """Tamaño de fuente mediano del documento: la referencia para detectar títulos."""
    tams = []
    for page in pdf.pages[: min(5, len(pdf.pages))]:
        tams += [round(w.get("size", 0), 1) for w in page.extract_words(extra_attrs=["size"])]
    tams = [t for t in tams if t > 0]
    return statistics.median(tams) if tams else 10.0


def _linea(grupo: list[dict], base: float) -> dict | None:
    grupo = sorted(grupo, key=lambda w: w["x0"])
    texto = " ".join(w["text"] for w in grupo).strip()
    if not texto:
        return None
    return {"texto": texto,
            "tam": statistics.median([w.get("size", base) for w in grupo]),
            "top": min(w["top"] for w in grupo),
            "x0": min(w["x0"] for w in grupo),
            "x1": max(w["x1"] for w in grupo)}


def lineas_de_pagina(page, base: float, corte: float | None = None) -> list[dict]:
    """Líneas de la página, ya separadas por columna.

    El orden importa: si se agrupan las palabras en líneas a lo ancho de toda la página
    y recién después se separan las columnas, una palabra de la izquierda y otra de la
    derecha a la misma altura quedan fusionadas en una sola línea que cruza el corte, y
    el texto sale entrelazado. Por eso la separación ocurre **dentro** del agrupamiento:
    un grupo de palabras a la misma altura se parte en dos líneas salvo que el texto
    cruce el corte de forma continua (un título o un pie a ancho completo), lo que se
    distingue por el tamaño del hueco: un espacio entre palabras mide ~1/3 del cuerpo y
    el medianil cerca del cuerpo entero, así que el umbral va a la mitad.
    """
    palabras = page.extract_words(extra_attrs=["size"])
    if not palabras:
        return []
    palabras.sort(key=lambda w: (round(w["top"], 1), w["x0"]))

    filas, actual, top_ref = [], [], None
    for w in palabras:
        if top_ref is None or abs(w["top"] - top_ref) <= max(2.0, base * 0.4):
            actual.append(w)
            top_ref = w["top"] if top_ref is None else top_ref
        else:
            filas.append(actual)
            actual, top_ref = [w], w["top"]
    if actual:
        filas.append(actual)

    lineas = []
    for g in filas:
        if corte is None:
            ln = _linea(g, base)
            if ln:
                lineas.append(ln)
            continue
        izq = [w for w in g if (w["x0"] + w["x1"]) / 2 < corte]
        der = [w for w in g if (w["x0"] + w["x1"]) / 2 >= corte]
        if not izq or not der:
            ln = _linea(g, base)
            if ln:
                lineas.append(ln)
            continue
        hueco = min(w["x0"] for w in der) - max(w["x1"] for w in izq)
        # Medido en el PDF de prueba: espacio entre palabras ~3 pt, medianil ~9 pt con un
        # cuerpo de 10. El umbral va entre ambos; ponerlo en `base` tomaba el medianil por
        # un espacio y devolvía las dos columnas fusionadas en una línea.
        if hueco < base * 0.5:                 # texto continuo: es ancho completo
            ln = _linea(g, base)
            if ln:
                lineas.append(ln)
        else:                                  # medianil: son dos líneas distintas
            for parte in (izq, der):
                ln = _linea(parte, base)
                if ln:
                    lineas.append(ln)
    return lineas


def ordenar_por_columnas(lineas: list[dict], corte: float | None, tol: float = 6.0) -> list[dict]:
    """Reordena a orden de lectura: por bandas, izquierda completa y luego derecha.

    Una línea que cruza el corte (título, pie de figura, encabezado de revista) es de
    ancho completo y actúa como separador de banda: cierra la banda anterior y se emite
    en su lugar. Sin esto, dos columnas salen entrelazadas línea a línea.
    """
    if corte is None:
        return sorted(lineas, key=lambda l: (l["top"], l["x0"]))

    salida, izq, der = [], [], []

    def volcar():
        salida.extend(sorted(izq, key=lambda l: l["top"]))
        salida.extend(sorted(der, key=lambda l: l["top"]))
        izq.clear(); der.clear()

    for ln in sorted(lineas, key=lambda l: (l["top"], l["x0"])):
        if ln["x1"] <= corte + tol:
            izq.append(ln)
        elif ln["x0"] >= corte - tol:
            der.append(ln)
        else:                                    # cruza el corte: ancho completo
            volcar()
            salida.append(ln)
    volcar()
    return salida


def tabla_markdown(tabla: list[list]) -> str:
    """Markdown de una tabla. Devuelve "" si no parece una tabla de verdad.

    `find_tables()` marca como tabla cualquier rejilla de líneas — un diagrama de flujo
    CONSORT incluido. Una "tabla" de una sola columna es casi siempre eso: se descarta y
    su texto se deja al flujo normal, en vez de emitir una fila gigante ilegible.
    """
    filas = [[(c or "").replace("\n", " ").replace("|", "/").strip() for c in fila]
             for fila in tabla if any(c for c in fila)]
    if len(filas) < 2 or max(len(f) for f in filas) < 2:
        return ""
    ancho = max(len(f) for f in filas)
    filas = [f + [""] * (ancho - len(f)) for f in filas]
    cab, resto = filas[0], filas[1:]
    out = ["| " + " | ".join(cab) + " |", "|" + "---|" * ancho]
    out += ["| " + " | ".join(f) + " |" for f in resto]
    return "\n".join(out)


def unir_parrafos(lineas_md: list[str]) -> list[str]:
    """Une líneas cortadas por el ancho de columna y repara guiones de fin de línea."""
    out, buf = [], ""
    for ln in lineas_md:
        if ln.startswith(("#", "|", "!", "- ")) or not ln.strip():
            if buf:
                out.append(buf); buf = ""
            out.append(ln)
            continue
        if not buf:
            buf = ln
        elif buf.endswith("-"):
            buf = buf[:-1] + ln          # palabra partida con guión
        else:
            buf += " " + ln
        # Un punto final con espacio a continuación cierra el párrafo.
        if re.search(r"[.!?]['\")\]]?$", buf) and len(buf) > 200:
            out.append(buf); buf = ""
    if buf:
        out.append(buf)
    return out


# ---------------------------------------------------------------------------
# Imágenes: rasters incrustados + figuras vectoriales rasterizadas
# ---------------------------------------------------------------------------
def extraer_rasters(pdf_path: Path, destino: Path) -> list[tuple[int, str]]:
    """Guarda las imágenes raster incrustadas. Devuelve [(página, archivo)].

    Cubre PDFs con fotos o capturas. Un paper de revista normalmente **no** tiene
    ninguna: sus figuras son vectoriales y las cubre `rasterizar_figuras`.
    """
    try:
        from pypdf import PdfReader
    except ImportError:
        print("  aviso: sin pypdf no se extraen rasters (pip install pypdf)", file=sys.stderr)
        return []
    destino.mkdir(parents=True, exist_ok=True)
    encontradas = []
    reader = PdfReader(str(pdf_path))
    for n, page in enumerate(reader.pages, 1):
        try:
            imagenes = list(page.images)
        except Exception as e:                       # XObject corrupto o no soportado
            print(f"  aviso: página {n} sin rasters legibles ({e})", file=sys.stderr)
            continue
        for i, img in enumerate(imagenes):
            sufijo = Path(img.name).suffix or ".png"
            nombre = f"p{n:02d}_raster{i:02d}{sufijo}"
            (destino / nombre).write_bytes(img.data)
            encontradas.append((n, nombre))
    return encontradas


def _fusionar(cajas: list[tuple], margen: float = 6.0) -> list[tuple]:
    """Agrupa cajas que se tocan o casi, hasta que no queden fusiones posibles.

    El margen tiene que ser **menor que el medianil entre columnas** (medido: 9 pt en el
    PDF de prueba). Con un margen mayor, la caja de una figura de la columna izquierda se
    fusiona con los filetes de la derecha y el recorte se estira a toda la página,
    llevándose el texto del cuerpo dentro de la imagen.
    """
    cajas = [tuple(c) for c in cajas]
    cambio = True
    while cambio:
        cambio = False
        salida: list[tuple] = []
        for c in cajas:
            for i, s in enumerate(salida):
                if (c[0] <= s[2] + margen and s[0] <= c[2] + margen
                        and c[1] <= s[3] + margen and s[1] <= c[3] + margen):
                    salida[i] = (min(c[0], s[0]), min(c[1], s[1]),
                                 max(c[2], s[2]), max(c[3], s[3]))
                    cambio = True
                    break
            else:
                salida.append(c)
        cajas = salida
    return cajas


def regiones_de_figura(page, bboxes_tabla: list[tuple]) -> list[tuple]:
    """Regiones con dibujo vectorial que parecen una figura.

    Descarta lo que ya salió como tabla (sus bordes son líneas y rectángulos, no una
    figura), los filetes de encabezado (muy anchos y de un pelo de alto) y cualquier
    cosa demasiado pequeña para ser una figura.
    """
    objetos = list(page.curves) + list(page.lines) + list(page.rects) + list(page.images)
    if not objetos:
        return []
    ancho_pag = page.bbox[2] - page.bbox[0]
    area_pagina = ancho_pag * (page.bbox[3] - page.bbox[1])

    cajas = []
    for o in objetos:
        w, h = o["x1"] - o["x0"], o["bottom"] - o["top"]
        # Filete decorativo (la raya bajo el encabezado de la revista): ancho de página y
        # un pelo de alto. No es figura y, si se deja, arrastra la caja a todo lo ancho.
        if w > ancho_pag * 0.6 and h < 3:
            continue
        cajas.append((o["x0"], o["top"], o["x1"], o["bottom"]))
    if not cajas:
        return []

    regiones = []
    for c in _fusionar(cajas):
        ancho, alto = c[2] - c[0], c[3] - c[1]
        if ancho < 60 or alto < 60:                       # filete o viñeta, no figura
            continue
        if ancho * alto < area_pagina * 0.03:             # demasiado chica
            continue
        solapa = any(max(c[0], t[0]) < min(c[2], t[2]) and max(c[1], t[1]) < min(c[3], t[3])
                     and ((min(c[2], t[2]) - max(c[0], t[0])) *
                          (min(c[3], t[3]) - max(c[1], t[1]))) > 0.5 * ancho * alto
                     for t in bboxes_tabla)
        if solapa:                                        # es el borde de una tabla
            continue
        # Una figura se dibuja con muchas primitivas; un marco decorativo, con dos o tres.
        # Esto descarta el logotipo de la portada sin necesidad de reglas ad hoc.
        dentro = sum(1 for b in cajas
                     if b[0] >= c[0] - 1 and b[2] <= c[2] + 1
                     and b[1] >= c[1] - 1 and b[3] <= c[3] + 1)
        if dentro < 5:
            continue
        regiones.append(c)
    return regiones


def rasterizar_figuras(pdf_path: Path, regiones: dict[int, list[tuple]], destino: Path,
                       dpi: int = 200) -> list[tuple[int, str]]:
    """Renderiza a PNG cada región de figura. Devuelve [(página, archivo)].

    Es lo que hace falta para las figuras de un paper: son vectoriales, no hay un raster
    incrustado que extraer, así que se dibujan a `dpi` y se recortan a su región.
    """
    if not regiones:
        return []
    try:
        import pypdfium2 as pdfium
    except ImportError:
        print("  aviso: sin pypdfium2 no se rasterizan figuras vectoriales "
              "(pip install pypdfium2)", file=sys.stderr)
        return []
    destino.mkdir(parents=True, exist_ok=True)
    salida = []
    doc = pdfium.PdfDocument(str(pdf_path))
    try:
        for n_pag, cajas in sorted(regiones.items()):
            pagina = doc[n_pag - 1]
            ancho_pt, alto_pt = pagina.get_width(), pagina.get_height()
            for i, (x0, top, x1, bottom) in enumerate(cajas):
                pad = 6
                izq = max(0, x0 - pad)
                der = max(0, ancho_pt - min(ancho_pt, x1 + pad))
                # pdfplumber mide `top` desde arriba; pdfium recorta desde cada borde.
                arriba = max(0, top - pad)
                abajo = max(0, alto_pt - min(alto_pt, bottom + pad))
                try:
                    bitmap = pagina.render(scale=dpi / 72,
                                           crop=(izq, abajo, der, arriba))
                    imagen = bitmap.to_pil()
                except Exception as e:
                    print(f"  aviso: no pude rasterizar la figura {i} de la página "
                          f"{n_pag} ({e})", file=sys.stderr)
                    continue
                nombre = f"p{n_pag:02d}_figura{i:02d}.png"
                imagen.save(destino / nombre)
                salida.append((n_pag, nombre))
    finally:
        doc.close()
    return salida


def _en_tabla(ln: dict, bboxes: list[tuple]) -> bool:
    """¿El centro de la línea cae dentro de una tabla ya emitida?"""
    cx, cy = (ln["x0"] + ln["x1"]) / 2, ln["top"]
    return any(bb[0] <= cx <= bb[2] and bb[1] <= cy <= bb[3] for bb in bboxes)


def _nivel(texto: str, tam: float, base: float) -> str | None:
    """Nivel de encabezado, o None si es cuerpo.

    Se exige un mínimo de 8 caracteres: los fragmentos sueltos de una cabecera de revista
    ("The", "of") tienen cuerpo grande y no son títulos.
    """
    if len(texto) < 8 or len(texto) > 120:
        return None
    if tam >= base * 1.45:
        return "##"
    if tam >= base * 1.18:
        return "###"
    return None


def _leer_paginas(pdf, columnas: str, con_figuras: bool
                  ) -> tuple[list[dict], dict[int, list[tuple]], float, dict]:
    """Pasada de lectura: por página, sus tablas, sus líneas en orden y sus figuras.

    Separada de la escritura porque hay dos consumidores con necesidades distintas:
    `convertir()` quiere archivos en disco con las imágenes referenciadas, y
    `texto_markdown()` solo quiere el texto bien ordenado, en memoria.
    """
    paginas: list[dict] = []
    regiones: dict[int, list[tuple]] = {}
    base = tam_cuerpo(pdf)
    meta = dict(pdf.metadata or {})

    for n, page in enumerate(pdf.pages, 1):
        tablas_md, bboxes = [], []
        for t in page.find_tables():
            texto_tabla = tabla_markdown(t.extract())
            if texto_tabla:                           # solo tablas reales
                tablas_md.append(texto_tabla)
                bboxes.append(t.bbox)

        if columnas == "auto":
            corte = punto_de_corte(page, base)
        elif columnas == "1":
            corte = None
        else:
            corte = (page.bbox[0] + page.bbox[2]) / 2

        lineas = [ln for ln in lineas_de_pagina(page, base, corte)
                  if not _en_tabla(ln, bboxes)]
        paginas.append({"n": n, "tablas": tablas_md, "corte": corte,
                        "lineas": ordenar_por_columnas(lineas, corte)})

        if con_figuras:
            cajas = regiones_de_figura(page, bboxes)
            if cajas:
                regiones[n] = cajas
    return paginas, regiones, base, meta


def _render(paginas: list[dict], base: float, meta: dict, titulo_fallback: str,
            por_pagina: dict[int, list[str]] | None = None) -> tuple[str, int]:
    """Arma el Markdown desde las páginas ya leídas. Devuelve (markdown, nº de tablas)."""
    md: list[str] = [f"# {(meta.get('Title') or titulo_fallback).strip()}\n"]
    if meta.get("Subject"):
        md.append(f"*{meta['Subject'].strip()}*\n")
    n_tablas = 0
    for pg in paginas:
        md.append(f"\n<!-- página {pg['n']} -->\n")
        for t in pg["tablas"]:
            md.append(t + "\n")
            n_tablas += 1
        crudas = []
        for ln in pg["lineas"]:
            nivel = _nivel(ln["texto"], ln["tam"], base)
            crudas.append(f"\n{nivel} {ln['texto']}\n" if nivel else ln["texto"])
        md += unir_parrafos(crudas)
        for nombre in (por_pagina or {}).get(pg["n"], []):
            etiqueta = "Figura" if "figura" in nombre else "Imagen"
            md.append(f"\n![{etiqueta} de la página {pg['n']}](imagenes/{nombre})\n")
    return "\n".join(md) + "\n", n_tablas


def texto_markdown(pdf_path: Path, columnas: str = "auto") -> str:
    """Markdown del PDF **en memoria**: no escribe archivos ni rasteriza figuras.

    Es lo que consume `tools/paper_review.py`. Un fichado de artículo necesita el texto
    en orden de lectura y con las tablas legibles; no necesita PNGs en disco, y
    rasterizar figuras costaría segundos por página para nada. Al no tocar las figuras,
    tampoco arrastra la dependencia de `pypdfium2`.
    """
    with _pdfplumber().open(str(Path(pdf_path))) as pdf:
        paginas, _, base, meta = _leer_paginas(pdf, columnas, con_figuras=False)
    md, _ = _render(paginas, base, meta, Path(pdf_path).stem)
    return md


def convertir(pdf_path: Path, out_dir: Path, columnas: str = "auto",
              figuras: bool = True, dpi: int = 200) -> dict:
    """PDF -> Markdown + imágenes. Devuelve un resumen de lo producido.

    Dos pasadas a propósito: la primera lee cada página (tablas, texto y regiones de
    figura) y la segunda escribe, ya sabiendo qué imágenes existen. Así cada figura
    queda referenciada en la página donde está, y no todas amontonadas al final.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    img_dir = out_dir / "imagenes"

    with _pdfplumber().open(str(pdf_path)) as pdf:
        paginas, regiones, base, meta = _leer_paginas(pdf, columnas, con_figuras=figuras)
        n_paginas = len(pdf.pages)

    # --- imágenes: primero los rasters incrustados, después las figuras vectoriales ---
    imagenes = extraer_rasters(pdf_path, img_dir)
    n_rasters = len(imagenes)
    if figuras:
        imagenes += rasterizar_figuras(pdf_path, regiones, img_dir, dpi=dpi)
    n_figuras = len(imagenes) - n_rasters
    if not imagenes and img_dir.exists() and not any(img_dir.iterdir()):
        img_dir.rmdir()

    por_pagina: dict[int, list[str]] = {}
    for pag, nombre in imagenes:
        por_pagina.setdefault(pag, []).append(nombre)

    texto, n_tablas = _render(paginas, base, meta, pdf_path.stem, por_pagina)
    destino_md = out_dir / f"{pdf_path.stem}.md"
    destino_md.write_text(texto, encoding="utf-8")
    return {"md": destino_md, "rasters": n_rasters, "figuras": n_figuras,
            "tablas": n_tablas, "paginas": n_paginas,
            "dos_columnas": sum(1 for p in paginas if p["corte"] is not None),
            "caracteres": len(texto)}


def main() -> int:
    ap = argparse.ArgumentParser(description="Convierte un PDF a Markdown y extrae sus imágenes.")
    ap.add_argument("pdf")
    ap.add_argument("--out", default="salida_md", help="Carpeta destino.")
    ap.add_argument("--columnas", default="auto", choices=["auto", "1", "2"],
                    help="Disposición de columnas (auto por defecto).")
    ap.add_argument("--sin-figuras", action="store_true",
                    help="No rasterizar las figuras vectoriales (solo rasters incrustados).")
    ap.add_argument("--dpi", type=int, default=200,
                    help="Resolución de las figuras rasterizadas (200 por defecto).")
    a = ap.parse_args()
    pdf_path = Path(a.pdf).expanduser()
    if not pdf_path.is_file():
        print(f"ERROR: no existe {pdf_path}", file=sys.stderr)
        return 1
    r = convertir(pdf_path, Path(a.out).expanduser(), a.columnas,
                  figuras=not a.sin_figuras, dpi=a.dpi)
    print(f"OK: {r['md']}")
    print(f"  {r['paginas']} páginas ({r['dos_columnas']} a dos columnas) · "
          f"{r['caracteres']:,} caracteres · {r['tablas']} tablas")
    print(f"  imágenes: {r['rasters']} rasters incrustados + {r['figuras']} figuras "
          f"vectoriales rasterizadas → {r['md'].parent / 'imagenes'}")
    if r["rasters"] + r["figuras"] == 0:
        print("  nota: el PDF no trae rasters ni dibujo vectorial que parezca figura.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
