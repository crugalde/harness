"""Tests de la skill analisis-estudio. Correr con: pytest -q

Todo corre offline: las funciones que tocan red se prueban con payloads grabados,
que es donde de verdad se rompen las cosas (el parseo de Crossref y de PubMed).
"""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skills" / "analisis_estudio" / "scripts"


def _load(nombre):
    spec = importlib.util.spec_from_file_location(nombre, SCRIPTS / f"{nombre}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


NM = _load("notion_md")
PN = _load("publicar_notion")
VM = _load("verificar_metadatos")


def _tipos(bloques):
    return [b["type"] for b in bloques]


def _texto(bloque):
    return "".join(r["text"]["content"] for r in bloque[bloque["type"]]["rich_text"])


# --------------------------------------------------------------- notion_md

def test_encabezados_y_listas():
    b = NM.a_bloques("## Uno\n### Dos\n- item\n1. otro\ntexto suelto")
    assert _tipos(b) == ["heading_2", "heading_3", "bulleted_list_item",
                         "numbered_list_item", "paragraph"]


def test_encabezado_profundo_se_degrada_a_tres():
    # Notion solo tiene tres niveles; perder el bloque sería peor que degradarlo.
    assert _tipos(NM.a_bloques("##### Cuarto nivel")) == ["heading_3"]


def test_tabla_de_pipes():
    md = "| Gen | Pob |\n| --- | --- |\n| SNCA | Europea |\n| COQ2 | Japonesa |"
    tabla = NM.a_bloques(md)[0]
    assert tabla["type"] == "table"
    assert tabla["table"]["table_width"] == 2
    assert tabla["table"]["has_column_header"] is True
    assert len(tabla["table"]["children"]) == 3          # cabecera + 2 filas


def test_tabla_con_filas_desparejas_se_rellena():
    # Notion rechaza la tabla entera si una fila trae menos celdas que el ancho.
    md = "| a | b | c |\n| --- | --- | --- |\n| 1 | 2 |"
    tabla = NM.a_bloques(md)[0]
    assert all(len(f["table_row"]["cells"]) == 3 for f in tabla["table"]["children"])


def test_callout_traduce_el_color():
    md = '<callout icon="⚠️" color="orange_bg">\n\t**Baja.** Motivo.\n</callout>'
    c = NM.a_bloques(md)[0]
    assert c["type"] == "callout"
    assert c["callout"]["color"] == "orange_background"   # _bg no es válido en la API
    assert c["callout"]["icon"]["emoji"] == "⚠️"


def test_citas_consecutivas_son_un_solo_bloque():
    # Cada línea `>` suelta sería una caja distinta: un encabezado se partiría en cuatro.
    b = NM.a_bloques("> uno\n> dos\n> tres")
    assert _tipos(b) == ["quote"]
    assert _texto(b[0]) == "uno dos tres"


def test_bloque_de_codigo_conserva_lenguaje_y_literalidad():
    b = NM.a_bloques("```mermaid\ngraph TD\n  A --> B\n```")[0]
    assert b["code"]["language"] == "mermaid"
    assert "**no es negrita**" not in b["code"]["rich_text"][0]["text"]["content"]
    assert "A --> B" in b["code"]["rich_text"][0]["text"]["content"]


def test_lenguaje_desconocido_cae_a_plain_text():
    # Un lenguaje inválido devuelve 400 y tumba la publicación entera.
    assert NM.a_bloques("```brainfuck\n+++\n```")[0]["code"]["language"] == "plain text"


def test_formato_inline():
    b = NM.a_bloques("**negrita** y *cursiva* y `code` y [texto](https://x.cl)")[0]
    rt = b["paragraph"]["rich_text"]
    assert rt[0]["annotations"]["bold"] is True
    assert any(r.get("annotations", {}).get("italic") for r in rt)
    assert any(r.get("annotations", {}).get("code") for r in rt)
    assert any(r["text"].get("link", {}).get("url") == "https://x.cl" for r in rt)


def test_marcas_anidadas_toman_la_que_abre_antes():
    # Buscar por orden de patrón en vez de por posición rompía este caso:
    # la cursiva abre en 0 y debe envolver al código de adentro.
    rt = NM.a_bloques("*cursiva con `code` dentro*")[0]["paragraph"]["rich_text"]
    assert all(r["annotations"].get("italic") for r in rt)
    assert any(r["annotations"].get("code") for r in rt)


def test_escapes_de_notion_se_deshacen():
    # La ficha llega con \[3\] y \~62% escapados; el lector no debe ver las barras.
    t = _texto(NM.a_bloques(r"Exactitud \~62% en la cohorte \[3\]")[0])
    assert t == "Exactitud ~62% en la cohorte [3]"


def test_texto_largo_se_parte_bajo_el_limite_de_la_api():
    b = NM.a_bloques("x " * 3000)[0]
    trozos = b["paragraph"]["rich_text"]
    assert len(trozos) > 1
    assert all(len(t["text"]["content"]) <= NM.LIMITE_TEXTO for t in trozos)


def test_trocear_respeta_el_maximo_de_bloques():
    bloques = NM.a_bloques("\n".join(f"- item {i}" for i in range(250)))
    lotes = NM.trocear(bloques)
    assert len(lotes) == 3 and all(len(l) <= NM.LIMITE_BLOQUES for l in lotes)


def test_lineas_en_blanco_no_generan_bloques_vacios():
    assert _tipos(NM.a_bloques("uno\n\n\n\ndos")) == ["paragraph", "paragraph"]


# --------------------------------------------------------------- publicar_notion

META = {
    "titulo": "The genetic basis of multiple system atrophy",
    "autor": "Tseng FS et al.", "anio": 2023, "revista": "J Transl Med",
    "doi": "10.1186/s12967-023-03905-1", "pmid": "36765380",
    "tipo_estudio": "Revisión narrativa", "patologia": "Atrofia multisistémica",
    "area": "Neurodegenerativo", "aspecto": "General", "calidad": "Baja",
    "aporte": "Catálogo de genes candidatos.",
    "verificacion": {"verificado": True},
}
ESQUEMA = {
    "Patología": {"type": "select", "select": {"options": [{"name": "Atrofia multisistémica"},
                                                           {"name": "CIDP"}]}},
    "Calidad": {"type": "select", "select": {"options": [{"name": "Baja"}, {"name": "Alta"}]}},
}


def test_url_paper_prefiere_doi():
    assert PN.url_paper(META) == "https://doi.org/10.1186/s12967-023-03905-1"


def test_url_paper_cae_a_pubmed_sin_doi():
    m = {k: v for k, v in META.items() if k != "doi"}
    assert PN.url_paper(m) == "https://pubmed.ncbi.nlm.nih.gov/36765380/"


def test_propiedades_serializan_cada_tipo():
    p = PN.propiedades(META)
    assert p["Título"]["title"][0]["text"]["content"].startswith("The genetic")
    assert p["Año"]["number"] == 2023
    assert p["Calidad"]["select"]["name"] == "Baja"
    assert p["Paper"]["url"].startswith("https://doi.org/")


def test_validacion_limpia_no_reporta_problemas():
    assert PN.validar(META, ESQUEMA, sin_verificar=False) == []


def test_validacion_exige_metadatos_verificados():
    m = dict(META, verificacion={"verificado": False})
    assert any("no verificados" in p.lower() or "NO verificados" in p
               for p in PN.validar(m, ESQUEMA, sin_verificar=False))
    assert PN.validar(m, ESQUEMA, sin_verificar=True) == []


def test_validacion_exige_patologia_y_aspecto():
    m = {k: v for k, v in META.items() if k not in ("patologia", "aspecto")}
    problemas = PN.validar(m, None, sin_verificar=False)
    assert any("patologia" in p and "aspecto" in p for p in problemas)


def test_select_fuera_del_vocabulario_detiene_la_publicacion():
    # Inventar la opción fragmentaría el filtro por patología en silencio.
    m = dict(META, patologia="Síndrome de Susac")
    problemas = PN.validar(m, ESQUEMA, sin_verificar=False)
    assert any("no es una opción válida" in p for p in problemas)


def test_sin_doi_ni_pmid_no_se_publica():
    m = {k: v for k, v in META.items() if k not in ("doi", "pmid")}
    assert any("DOI" in p for p in PN.validar(m, ESQUEMA, sin_verificar=False))


def test_cuerpo_quita_el_h1_y_estampa_el_aviso(tmp_path):
    f = tmp_path / "ficha.md"
    f.write_text("# Título duplicado\n\n## Identificación\ncuerpo\n", encoding="utf-8")

    limpio = PN.cuerpo_ficha(f, META, sin_verificar=False)
    assert "# Título duplicado" not in limpio and "## Identificación" in limpio

    m = dict(META, verificacion={"verificado": False})
    con_aviso = PN.cuerpo_ficha(f, m, sin_verificar=True)
    assert "METADATOS NUNCA VERIFICADOS" in con_aviso
    assert NM.a_bloques(con_aviso)[0]["type"] == "callout"


def test_payload_mcp_usa_data_source_no_database():
    # La API REST quiere database_id y el conector quiere data_source_id; no son lo mismo.
    props = PN.propiedades_mcp(META)
    assert props["Patología"] == "Atrofia multisistémica"     # plano, no anidado
    assert PN.DS_RESUMEN != PN.DB_RESUMEN


# --------------------------------------------------------------- verificar_metadatos

def test_tipo_de_estudio_toma_la_etiqueta_mas_especifica():
    # Un ECA viene además etiquetado como "Clinical Trial": no debe ganar la genérica.
    assert VM.tipo_desde_pubmed(
        ["Journal Article", "Clinical Trial", "Randomized Controlled Trial"]
    ) == "Ensayo clínico aleatorizado"
    assert VM.tipo_desde_pubmed(["Review", "Systematic Review"]) == "Revisión sistemática"
    assert VM.tipo_desde_pubmed(["Review"]) == "Revisión narrativa"
    assert VM.tipo_desde_pubmed(["Journal Article"]) is None


def test_cada_diseno_tiene_guia_de_reporte():
    assert VM.GUIAS["Revisión narrativa"] == "SANRA"
    assert VM.GUIAS["Guía de práctica clínica"] == "AGREE-II"
    assert VM.GUIAS["Precisión diagnóstica"] == "STARD + QUADAS-2"


def test_discrepancias_entre_fuentes_se_reportan_no_se_resuelven():
    cr = {"titulo": "A", "anio": 2022, "revista": "J Transl Med"}
    pm = {"titulo": "A", "anio": 2023, "revista": "J Transl Med"}
    d = VM.comparar(cr, pm)
    assert len(d) == 1 and "año" in d[0]
    assert VM.comparar(cr, cr) == []


def test_parseo_de_crossref(monkeypatch):
    payload = {"message": {
        "title": ["The genetic basis of multiple system atrophy"],
        "container-title": ["Journal of Translational Medicine"],
        "short-container-title": ["J Transl Med"],
        "published-print": {"date-parts": [[2023, 2, 10]]},
        "author": [{"family": "Tseng", "given": "Fan Shuen"}, {"family": "Tan", "given": "Eng King"}],
        "type": "journal-article"}}
    monkeypatch.setattr(VM, "_get", lambda url, correo: payload)
    d = VM.de_crossref("10.1186/s12967-023-03905-1", "x@y.cl")
    assert d["anio"] == 2023
    assert d["revista"] == "J Transl Med"          # abreviatura NLM, no el nombre largo
    assert d["autor"] == "Tseng FS et al."


def test_parseo_de_pubmed(monkeypatch):
    payload = {"result": {"36765380": {
        "title": "The genetic basis of multiple system atrophy.",
        "source": "J Transl Med", "pubdate": "2023 Feb 10",
        "authors": [{"name": "Tseng FS"}, {"name": "Tan EK"}],
        "pubtype": ["Journal Article", "Review"]}}}
    monkeypatch.setattr(VM, "_get", lambda url, correo: payload)
    d = VM.de_pubmed("36765380", "x@y.cl")
    assert d["titulo"].endswith("atrophy")         # sin el punto final
    assert d["anio"] == 2023
    assert d["autor"] == "Tseng FS et al."
    assert VM.tipo_desde_pubmed(d["pubtypes"]) == "Revisión narrativa"


def test_ficha_de_ejemplo_se_convierte_entera():
    """La ficha de ejemplo trae todo lo que la plantilla permite, extremo a extremo."""
    md = ROOT / "skills" / "analisis_estudio" / "evals" / "ficha_ejemplo.md"
    bloques = NM.a_bloques(md.read_text(encoding="utf-8"))
    tipos = set(_tipos(bloques))
    assert {"heading_2", "heading_3", "bulleted_list_item", "table",
            "callout", "code", "divider", "paragraph"} <= tipos
    assert json.dumps(bloques)                     # serializable: es lo que viaja a la API
    assert all(len(t["text"]["content"]) <= NM.LIMITE_TEXTO
               for b in bloques if b["type"] not in ("table", "divider")
               for t in b[b["type"]]["rich_text"])


def test_ficha_de_ejemplo_pasa_la_validacion_de_publicacion(tmp_path):
    """El ejemplo debe poder publicarse tal cual: si no, la plantilla miente."""
    ficha = ROOT / "skills" / "analisis_estudio" / "evals" / "ficha_ejemplo.md"
    assert PN.validar(META, ESQUEMA, sin_verificar=False) == []
    cuerpo = PN.cuerpo_ficha(ficha, META, sin_verificar=False)
    assert "METADATOS NUNCA VERIFICADOS" not in cuerpo   # están verificados
    assert len(NM.trocear(NM.a_bloques(cuerpo))) == 1    # cabe en una sola petición


# --------------------------------------------------------------- lote_fichas (fase A)

LF = _load("lote_fichas")


def _pdf_xmp(doi: str) -> bytes:
    return (b"%PDF-1.7\n<x:xmpmeta xmlns:x='adobe:ns:meta/'><rdf:RDF><rdf:Description>"
            b"<prism:doi>" + doi.encode() + b"</prism:doi>"
            b"</rdf:Description></rdf:RDF></x:xmpmeta>\n%%EOF")


def test_doi_desde_xmp(tmp_path):
    p = tmp_path / "a.pdf"
    p.write_bytes(_pdf_xmp("10.1186/s12967-023-03905-1"))
    assert LF.doi_de_pdf(p) == ("10.1186/s12967-023-03905-1", "XMP")


def test_doi_desde_stream_comprimido(tmp_path):
    import zlib
    cuerpo = zlib.compress(b"BT (https://doi.org/10.1212/WNL.0000000000207200) Tj ET")
    p = tmp_path / "c.pdf"
    p.write_bytes(b"%PDF-1.5\n4 0 obj<</Filter/FlateDecode>>stream\n" + cuerpo
                  + b"\nendstream endobj\n%%EOF")
    doi, origen = LF.doi_de_pdf(p)
    assert doi == "10.1212/WNL.0000000000207200" and origen == "stream"


def test_pdf_sin_doi_no_inventa(tmp_path):
    p = tmp_path / "d.pdf"
    p.write_bytes(b"%PDF-1.4\nsin nada util\n%%EOF")
    assert LF.doi_de_pdf(p) == (None, "no encontrado")


def test_sidecar_rescata_el_doi(tmp_path):
    p = tmp_path / "d.pdf"
    p.write_bytes(b"%PDF-1.4\n%%EOF")
    (tmp_path / "d.doi").write_text("https://doi.org/10.1093/brain/awad123\n")
    assert LF.doi_de_sidecar(p) == "10.1093/brain/awad123"


def test_limpiar_doi_quita_la_basura_del_pdf():
    # El DOI extraído de un PDF arrastra el paréntesis o el punto que lo seguía.
    assert LF.limpiar_doi("10.1186/s12967-023-03905-1).") == "10.1186/s12967-023-03905-1"
    assert LF.limpiar_doi("doi:10.1002/mus.27832,") == "10.1002/mus.27832"
    assert LF.limpiar_doi("https://doi.org/10.1212/WNL.207200") == "10.1212/WNL.207200"


def _stub_red(monkeypatch, pubtypes=("Journal Article", "Review")):
    """Simula Crossref + PubMed sin tocar la red."""
    monkeypatch.setattr(LF.VM, "resolver_ids", lambda d, p, c: (d, "36765380"))
    monkeypatch.setattr(LF.VM, "de_crossref", lambda d, c: {
        "titulo": "The genetic basis of multiple system atrophy", "anio": 2023,
        "revista": "J Transl Med", "autor": "Tseng FS et al.", "tipo_crossref": "journal-article"})
    monkeypatch.setattr(LF.VM, "de_pubmed", lambda p, c: {
        "titulo": "The genetic basis of multiple system atrophy", "anio": 2023,
        "revista": "J Transl Med", "autor": "Tseng FS et al.", "pubtypes": list(pubtypes)})
    monkeypatch.setattr(LF.time, "sleep", lambda s: None)


def test_lote_escribe_metadatos_verificados(tmp_path, monkeypatch):
    _stub_red(monkeypatch)
    pdf = tmp_path / "msa.pdf"
    pdf.write_bytes(_pdf_xmp("10.1186/s12967-023-03905-1"))

    e = LF.procesar(pdf, None, "x@y.cl", rehacer=False)
    assert e["estado"] == "listo"
    assert e["tipo_estudio"] == "Revisión narrativa" and e["guia"] == "SANRA"

    meta = json.loads((tmp_path / "msa.metadatos.json").read_text(encoding="utf-8"))
    assert meta["verificacion"]["verificado"] is True
    assert meta["archivo_local"].startswith("file://")     # ruta clicable, ya resuelta
    # Lo que ningún script puede derivar queda pendiente y visible.
    assert set(e["falta"]) == {"patologia", "aspecto", "calidad", "aporte"}


def test_lote_es_reanudable(tmp_path, monkeypatch):
    _stub_red(monkeypatch)
    pdf = tmp_path / "msa.pdf"
    pdf.write_bytes(_pdf_xmp("10.1186/s12967-023-03905-1"))
    LF.procesar(pdf, None, "x@y.cl", rehacer=False)

    llamadas = []
    monkeypatch.setattr(LF.VM, "de_crossref",
                        lambda d, c: llamadas.append(d) or {})
    e = LF.procesar(pdf, None, "x@y.cl", rehacer=False)
    assert e["estado"] == "ya_verificado"
    assert llamadas == []                                  # no volvió a la red


def test_reanudar_no_miente_sobre_lo_que_falta(tmp_path, monkeypatch):
    """El bug que tuvo: al reanudar decía «Falta: —» con patología aún sin asignar."""
    _stub_red(monkeypatch)
    pdf = tmp_path / "msa.pdf"
    pdf.write_bytes(_pdf_xmp("10.1186/s12967-023-03905-1"))
    LF.procesar(pdf, None, "x@y.cl", rehacer=False)

    e = LF.procesar(pdf, None, "x@y.cl", rehacer=False)
    assert "patologia" in e["falta"] and "aspecto" in e["falta"]
    assert e["anio"] == 2023 and e["guia"] == "SANRA"      # y trae los datos, no "?"


def test_ficha_ya_escrita_se_distingue(tmp_path, monkeypatch):
    _stub_red(monkeypatch)
    pdf = tmp_path / "msa.pdf"
    pdf.write_bytes(_pdf_xmp("10.1186/s12967-023-03905-1"))
    LF.procesar(pdf, None, "x@y.cl", rehacer=False)
    (tmp_path / "msa.md").write_text("## Identificación del estudio\n", encoding="utf-8")
    assert LF.procesar(pdf, None, "x@y.cl", rehacer=False)["estado"] == "ficha_escrita"


def test_sin_doi_da_instruccion_accionable(tmp_path, monkeypatch):
    _stub_red(monkeypatch)
    pdf = tmp_path / "capitulo.pdf"
    pdf.write_bytes(b"%PDF-1.4\nsin doi\n%%EOF")
    e = LF.procesar(pdf, None, "x@y.cl", rehacer=False)
    assert e["estado"] == "sin_doi"
    assert "capitulo.doi" in e["nota"]                      # dice exactamente qué crear


def test_informe_del_lote_se_escribe_y_es_legible(tmp_path, monkeypatch):
    _stub_red(monkeypatch)
    for n in ("a", "b"):
        (tmp_path / f"{n}.pdf").write_bytes(_pdf_xmp(f"10.1186/s1296{n and 7}-023-0390{5}-1"))
    (tmp_path / "roto.pdf").write_bytes(b"%PDF-1.4\nsin doi\n%%EOF")

    entradas = [LF.procesar(p, None, "x@y.cl", rehacer=False)
                for p in sorted(tmp_path.glob("*.pdf"))]
    destino = LF.escribir_lote(tmp_path, entradas)
    texto = destino.read_text(encoding="utf-8")

    assert destino.name == "LOTE.md"
    assert "Listo para analizar" in texto and "Sin DOI" in texto
    assert "publicar_notion.py" in texto                    # el siguiente paso, a mano
    assert "patologia" in texto                             # y el bloqueo recordado


# --------------------------------------------------------------- subida del PDF

def test_multipart_bien_formado():
    cuerpo, tipo = PN._multipart("msa.pdf", b"%PDF-1.7 datos", "application/pdf")
    frontera = tipo.split("boundary=")[1]
    assert tipo.startswith("multipart/form-data; boundary=")
    assert cuerpo.startswith(f"--{frontera}\r\n".encode())
    assert cuerpo.endswith(f"\r\n--{frontera}--\r\n".encode())
    assert b'name="file"; filename="msa.pdf"' in cuerpo
    assert b"Content-Type: application/pdf" in cuerpo
    assert b"%PDF-1.7 datos" in cuerpo          # los bytes viajan intactos


def test_pdf_grande_no_se_intenta_subir(tmp_path, monkeypatch):
    """21 MB por la vía de una parte devuelve 400; mejor decirlo antes de subirlo."""
    pdf = tmp_path / "gordo.pdf"
    pdf.write_bytes(b"x" * (PN.LIMITE_PDF + 1))
    llamadas = []
    monkeypatch.setattr(PN, "_peticion", lambda *a, **k: llamadas.append(a) or {})

    try:
        PN.subir_pdf("tok", pdf)
        assert False, "debió negarse"
    except PN.ErrorPublicacion as e:
        assert "20 MB" in str(e) and "gordo.pdf" in str(e)
    assert llamadas == []                        # ni siquiera abrió la petición


def test_pdf_se_encuentra_por_el_nombre_compartido(tmp_path):
    (tmp_path / "msa.md").write_text("## x", encoding="utf-8")
    pdf = tmp_path / "msa.pdf"
    pdf.write_bytes(b"%PDF-1.7")
    assert PN.pdf_de_la_ficha(tmp_path / "msa.md", {}) == pdf


def test_pdf_se_encuentra_por_archivo_local(tmp_path):
    pdf = tmp_path / "otro_nombre.pdf"
    pdf.write_bytes(b"%PDF-1.7")
    hallado = PN.pdf_de_la_ficha(tmp_path / "msa.md", {"archivo_local": pdf.as_uri()})
    assert hallado == pdf


def test_sin_pdf_devuelve_none_en_vez_de_fallar(tmp_path):
    assert PN.pdf_de_la_ficha(tmp_path / "msa.md", {}) is None
    assert PN.pdf_de_la_ficha(tmp_path / "msa.md",
                              {"archivo_local": "file:///no/existe/x.pdf"}) is None


def test_subida_encadena_los_dos_pasos(tmp_path, monkeypatch):
    pdf = tmp_path / "msa.pdf"
    pdf.write_bytes(b"%PDF-1.7 contenido")
    enviados = {}
    monkeypatch.setattr(PN, "_peticion", lambda m, r, t, c=None: {
        "id": "fu_123", "upload_url": "https://api.notion.com/v1/file_uploads/fu_123/send"})
    monkeypatch.setattr(PN, "_enviar_bytes",
                        lambda url, tok, cuerpo, tipo: enviados.update(url=url, n=len(cuerpo)))

    assert PN.subir_pdf("tok", pdf) == "fu_123"
    assert enviados["url"].endswith("/send")
    assert enviados["n"] > len(b"%PDF-1.7 contenido")   # multipart envuelve los bytes


def test_adjuntar_usa_el_tipo_file_upload(tmp_path, monkeypatch):
    pdf = tmp_path / "msa.pdf"
    pdf.write_bytes(b"%PDF-1.7")
    monkeypatch.setattr(PN, "subir_pdf", lambda t, p: "fu_999")
    capturado = {}
    monkeypatch.setattr(PN, "_peticion",
                        lambda m, r, t, c=None: capturado.update(metodo=m, ruta=r, cuerpo=c) or {})

    PN.adjuntar_pdf("tok", "page_1", pdf)
    archivos = capturado["cuerpo"]["properties"]["PDF"]["files"]
    assert capturado["metodo"] == "PATCH" and capturado["ruta"] == "/pages/page_1"
    assert archivos[0]["type"] == "file_upload"
    assert archivos[0]["file_upload"]["id"] == "fu_999"
    assert archivos[0]["name"] == "msa.pdf"


def test_no_resube_si_la_fila_ya_trae_adjunto(monkeypatch):
    monkeypatch.setattr(PN, "_peticion",
                        lambda *a, **k: {"properties": {"PDF": {"files": [{"name": "x.pdf"}]}}})
    assert PN.tiene_pdf("tok", "page_1") is True
    monkeypatch.setattr(PN, "_peticion", lambda *a, **k: {"properties": {"PDF": {"files": []}}})
    assert PN.tiene_pdf("tok", "page_1") is False
