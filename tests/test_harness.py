"""Tests del harness. Correr con: pytest -q  (desde la raíz del paquete)."""
import importlib
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load(mod, sub="tools"):
    """Carga un módulo del harness por ruta.

    Se registra en `sys.modules` antes de ejecutarlo: `dataclasses` resuelve las
    anotaciones diferidas (`from __future__ import annotations`) buscando el módulo ahí,
    y sin registrarlo revienta al decorar la primera dataclass.
    """
    spec = importlib.util.spec_from_file_location(mod, ROOT / sub / f"{mod}.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules[mod] = m
    spec.loader.exec_module(m)
    return m


L = _load("loop")
SI = _load("self_improve")
TR = _load("tracing")
MP = _load("model_policy")
SS = _load("skill_selector")
BE = _load("backends")
PR = _load("paper_review")
PM = _load("pdf_a_markdown")
SY = _load("sync_skills")
PB = _load("publicar")
MS = _load("mcp_server")


def test_router_scoring():
    cases = {"necesito una revisión en pubmed": "research",
             "interpreta este EMG de aguja": "med",
             "descompón la señal HD-sEMG con CKC": "signals",
             "propuesta de costo para el directorio": "biz",
             "plan de nutrición y recuperación": "coach",
             "redacta el informe final en un documento": "docs"}
    for msg, expect in cases.items():
        assert L.route(msg, backend=None) == expect, msg


def test_guards():
    assert L.guard_tool("read_shell", {"cmd": "rm -rf /"}).startswith("BLOQUEADO")
    assert L.guard_tool("send_email", {"to": "x"}).startswith("GATE")
    assert L.guard_tool("read_shell", {"cmd": "ls"}) is None


def test_protected_sections():
    SI.resolve(None)
    assert SI.meta()["protected"] == [1, 3, 4, 7]
    for a in ["med", "research", "biz", "signals", "coach", "docs"]:
        SI.resolve(a)
        assert SI.meta()["protected"] == [1, 3, 7], a


def test_skills_discovery():
    idx = L.load_skills()
    for name in ["pubmed_search", "build_docx", "build_pptx"]:
        assert name in idx


def test_trace_roundtrip():
    t = TR.Trace("med", "test")
    t.turn("assistant", "ok"); t.tool("read_shell", True); t.usage("claude-sonnet-4-6", 100, 50)
    f = t.close()
    assert f.exists()
    assert "sesiones" in TR.summarize()


# --- Política de modelos -----------------------------------------------------

def test_task_classification():
    cases = {"convierte este markdown a docx": "format",
             "extrae los metadatos del pdf": "extract",
             "clasifica estos archivos por tema": "route",
             "resume el caso y dame el diferencial": "synthesis",
             "analiza estos papers y compáralos con la literatura": "deep_analysis",
             "describe esta imagen del escaneo": "vision"}
    for msg, expect in cases.items():
        assert MP.classify(msg)[0] == expect, msg


def test_tier_por_clase():
    """Formato -> local rápido y gratis; análisis científico -> el modelo más capaz."""
    assert MP.plan("format", allow_local=True).tier.id == "T0-local"
    assert MP.plan("format", allow_local=True).est_cost_usd == 0.0
    assert MP.plan("deep_analysis").model == "claude-opus-5"
    assert MP.plan("synthesis").model == "claude-sonnet-5"
    # Sin motor local, la tarea mecánica cae al cloud más barato, no al de trabajo.
    degradado = MP.plan("format", allow_local=False)
    assert degradado.model == "claude-haiku-4-5" and degradado.degraded_from == "T0-local"


def test_techo_de_costo():
    guard = MP.CostGuard(per_call=0.01, per_session=100.0)
    caro = MP.plan("deep_analysis", est_in_tokens=500_000, est_out_tokens=50_000, guard=guard)
    assert caro.needs_confirmation and "techo" in caro.reason
    barato = MP.plan("deep_analysis", est_in_tokens=100, est_out_tokens=100, guard=guard)
    assert not barato.needs_confirmation


def test_phi_solo_local():
    """R8: con PHI la política no ofrece cloud; sin motor local, aborta en vez de filtrar."""
    d = MP.plan("deep_analysis", phi=True, allow_local=True)
    assert d.provider == "local"
    try:
        MP.plan("deep_analysis", phi=True, allow_local=False)
    except RuntimeError as e:
        assert "PHI" in str(e)
    else:
        raise AssertionError("con PHI y sin motor local debe abortar")


def test_capacidades_por_modelo():
    """Haiku 4.5 es familia previa: effort y thinking adaptive le dan error."""
    assert MP.caps("claude-opus-5")["effort"] is True
    assert MP.caps("claude-opus-5")["thinking"] == "adaptive"
    assert MP.caps("claude-haiku-4-5")["effort"] is False


# --- Selección autónoma de skills -------------------------------------------

def test_skill_selection():
    cases = {"analiza estos papers y establece el aporte frente a la literatura": "paper_review",
             "conviérteme el informe a un documento Word": "build_docx",
             "apaga las luces del living": "home_assistant",
             "hazme un resumen del tema miastenia gravis": "medicalinfosummary"}
    for task, expect in cases.items():
        hits = SS.select(task, k=2)
        assert hits, task
        assert hits[0].skill.id == expect, f"{task} -> {hits[0].skill.id}"


def test_skill_no_inventada():
    """Si nada supera el umbral, no se fuerza una skill: se declara y se sigue sin ella."""
    hits = SS.select("qwerty zxcvbn plugh xyzzy")
    assert hits == []
    assert "ninguna supera el umbral" in SS.declare("qwerty zxcvbn", hits)


def test_front_matter_plegado():
    """uc_library_fetcher usa `description: >-`; el parser debe leerlo igual."""
    pool = {s.id: s for s in SS.index()}
    assert pool["uc_library_fetcher"].description.startswith("Automatiza")
    assert "paper_review" in pool


# --- Backends ----------------------------------------------------------------

def test_conversion_a_openai():
    """El motor local habla chat/completions: los bloques de Anthropic deben traducirse."""
    msgs = [{"role": "user", "content": "hola"},
            {"role": "assistant", "content": [
                {"type": "text", "text": "voy"},
                {"type": "tool_use", "id": "t1", "name": "pubmed_search",
                 "input": {"query": "x"}}]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": "PMID 1"}]}]
    out = BE._to_openai("SYS", msgs)
    assert out[0] == {"role": "system", "content": "SYS"}
    assert out[2]["tool_calls"][0]["function"]["name"] == "pubmed_search"
    assert out[3] == {"role": "tool", "tool_call_id": "t1", "content": "PMID 1"}


# --- Pipeline de papers ------------------------------------------------------

def test_deidentificacion():
    texto = ("Paciente: Juan Perez Soto, RUT 12.345.678-9, ficha N° 44210. "
             "Fecha de nacimiento: 03/04/1961. Contacto: jperez@uc.cl, +56 9 8765 4321.")
    limpio, n = PR.deidentify(texto)
    assert n >= 5
    for fuga in ("12.345.678-9", "jperez@uc.cl", "44210", "1961"):
        assert fuga not in limpio, fuga


def test_json_tolerante():
    assert PR._json_from('ruido {"a": 1, "b": {"c": 2}} más ruido') == {"a": 1, "b": {"c": 2}}


def test_pipeline_papers_end_to_end(tmp_path):
    """discover -> extract -> de-identificar -> render -> revision.json/.md, sin modelo.

    Los tests de arriba cubren las piezas por separado; este cubre que el pipeline
    completo corra y, sobre todo, que **no se filtre PHI al informe**, que es la
    propiedad que no puede romperse en silencio (R8).
    """
    papers = tmp_path / "papers"; papers.mkdir()
    (papers / "estudio.md").write_text(
        "HD-sEMG decomposition in ALS: cross-sectional study. J Neurophysiol 2024.\n"
        "Paciente: Nombre Apellido, RUT 9.876.543-2, ficha N 44210.\n"
        "Contacto: autor@ejemplo.cl, +56 9 1111 2222.\n"
        "Se registraron 24 pacientes y 20 controles.\n", encoding="utf-8")

    out = tmp_path / "rev"
    payload = PR.run(papers, out, "humo", dry_run=True)

    paper = payload["papers"][0]
    assert paper["redacciones_phi"] >= 4, paper
    assert not paper["errores"], paper["errores"]
    assert payload["modelos"]["ficha"] and payload["modelos"]["sintesis"]

    informe = (out / "revision.md").read_text(encoding="utf-8")
    for fuga in ("9.876.543-2", "autor@ejemplo.cl", "44210", "Nombre Apellido"):
        assert fuga not in informe, f"PHI filtrada al informe: {fuga}"
    assert (out / "revision.json").exists()


# --- Conversor PDF -> Markdown ---------------------------------------------
# La lógica pura se prueba siempre; lo que necesita pdfplumber/pillow se salta cuando no
# están, porque el CI corre la suite en un entorno sin dependencias opcionales.

def test_fusion_de_cajas_respeta_el_medianil():
    """El margen de fusión debe ser menor que el medianil entre columnas (~9 pt).

    Con un margen mayor, la caja de una figura de la columna izquierda se fusiona con lo
    que haya en la derecha y el recorte se estira a toda la página, metiendo texto del
    cuerpo dentro de la imagen.
    """
    figura = (31, 58, 298, 389)          # figura en la columna izquierda
    filete = (307, 105, 505, 105)        # filete en la derecha, a 9 pt del medianil
    assert len(PM._fusionar([figura, filete])) == 2
    # Dos cajas realmente contiguas sí se fusionan (figura + su pie).
    pie = (31, 389, 298, 452)
    assert len(PM._fusionar([figura, pie])) == 1


def test_tabla_descarta_lo_que_no_es_tabla():
    """Una rejilla de una sola columna es un diagrama, no una tabla."""
    diagrama = [["4881 Patients underwent randomization"], ["2432 Were assigned"]]
    assert PM.tabla_markdown(diagrama) == ""
    real = PM.tabla_markdown([["Característica", "A", "B"], ["Edad", "65.0", "65.0"]])
    assert real.startswith("| Característica | A | B |")
    assert "|---|---|---|" in real


def test_nivel_de_encabezado():
    """Un fragmento corto con cuerpo grande es un logotipo, no un título."""
    assert PM._nivel("of", 20.0, 10.0) is None
    assert PM._nivel("Clopidogrel and Aspirin in Acute Ischemic Stroke", 20.0, 10.0) == "##"
    assert PM._nivel("Texto normal del cuerpo del artículo", 10.0, 10.0) is None


def _opcional(nombre):
    """Importa una dependencia opcional o salta el test.

    `pytest.importorskip` no basta: una dependencia instalada pero rota (p. ej. pdfminer
    contra un `cryptography` incompatible) lanza un panic de pyo3, que hereda de
    BaseException y no de ImportError, y el test explota en vez de saltarse.
    """
    try:
        return importlib.import_module(nombre)
    except BaseException as e:                      # noqa: BLE001 — incluye PanicException
        pytest.skip(f"{nombre} no utilizable aquí: {type(e).__name__}")


def test_conversion_pdf_completa(tmp_path):
    """De punta a punta sobre un PDF con un raster incrustado."""
    _opcional("pdfplumber")
    Image = _opcional("PIL.Image")
    ImageDraw = _opcional("PIL.ImageDraw")

    pagina = Image.new("RGB", (1200, 1600), "white")
    d = ImageDraw.Draw(pagina)
    d.text((80, 80), "Informe de prueba con imagen incrustada", fill="black")
    foto = Image.new("RGB", (400, 300), (200, 60, 60))
    ImageDraw.Draw(foto).ellipse((50, 50, 350, 250), fill=(40, 90, 200))
    pagina.paste(foto, (80, 200))
    pdf = tmp_path / "prueba.pdf"
    pagina.save(pdf, "PDF", resolution=150)

    out = tmp_path / "salida"
    r = PM.convertir(pdf, out, figuras=False)

    md = (out / "prueba.md").read_text(encoding="utf-8")
    assert r["rasters"] >= 1, r
    assert "![Imagen de la página 1](imagenes/" in md
    referida = md.split("(imagenes/")[1].split(")")[0]
    assert (out / "imagenes" / referida).is_file(), "la imagen referida debe existir"


# --- Publicación de skills hacia Hermes -------------------------------------

def test_skills_del_repo_son_publicables():
    """Sin `name` o `description` el hub indexa mal la skill, y falla en silencio."""
    ok, problemas = SY.validar()
    assert not problemas, problemas
    nombres = {s.name for s in ok}
    assert {"paper_review", "pdf_markdown", "pubmed_search"} <= nombres


def test_sync_no_toca_lo_que_no_es_suyo(tmp_path):
    """El destino es la carpeta de skills de Hermes: ahí vive trabajo ajeno al repo.

    `--limpiar` solo puede retirar lo que figure en el manifiesto que el propio script
    escribió. Cualquier otra carpeta se queda, aunque no venga del repo.
    """
    destino = tmp_path / "hermes_skills"
    ajena = destino / "skill_de_hermes"
    ajena.mkdir(parents=True)
    (ajena / "SKILL.md").write_text("no me borres", encoding="utf-8")

    SY.sincronizar(destino)
    assert (destino / "paper_review" / "SKILL.md").is_file()
    assert (ajena / "SKILL.md").read_text(encoding="utf-8") == "no me borres"

    # Una entrada del manifiesto que ya no existe en el repo sí se retira.
    manifiesto = destino / SY.MANIFIESTO
    datos = json.loads(manifiesto.read_text(encoding="utf-8"))
    datos["skills"].append("skill_fantasma")
    manifiesto.write_text(json.dumps(datos), encoding="utf-8")
    (destino / "skill_fantasma").mkdir()
    (destino / "otra_ajena").mkdir()

    r = SY.sincronizar(destino, limpiar=True)
    assert "skill_fantasma" in r["retiradas"]
    assert not (destino / "skill_fantasma").exists()
    assert (destino / "otra_ajena").is_dir(), "no estaba en el manifiesto: no se toca"
    assert ajena.is_dir()


def test_sync_dry_run_no_escribe(tmp_path):
    destino = tmp_path / "vacio"
    r = SY.sincronizar(destino, dry_run=True)
    assert r["sincronizadas"] and not destino.exists()


# --- Publicación: Obsidian y Notion -----------------------------------------

def test_obsidian_publica_sin_tocar_lo_ajeno(tmp_path):
    """La bóveda es del usuario: solo se escribe dentro de la subcarpeta destino."""
    vault = tmp_path / "neuro"
    ajena = vault / "Diario" / "mi_nota.md"
    ajena.parent.mkdir(parents=True)
    ajena.write_text("no me toques", encoding="utf-8")

    origen = tmp_path / "rev"
    (origen / "imagenes").mkdir(parents=True)
    (origen / "imagenes" / "p01_figura00.png").write_bytes(b"\x89PNG fake")
    md = "# Título\n\nCuerpo.\n\n![Figura](imagenes/p01_figura00.png)\n"
    datos = {"tema": "Miastenia y timectomía", "fecha": "2026-09-05",
             "papers": [{"ficha": {"pmids_citados": ["12345678"]}}]}

    r = PB.publicar_obsidian(md, datos, origen, vault=vault, tema=datos["tema"])

    nota = r["nota"].read_text(encoding="utf-8")
    assert nota.startswith("---\n"), "falta el front-matter"
    assert "pmids: [12345678]" in nota
    assert ajena.read_text(encoding="utf-8") == "no me toques"

    # El enlace reescrito tiene que resolver a un archivo real, no solo verse bien.
    rutas = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", nota)
    assert rutas, "se perdió el enlace a la figura"
    for ruta in rutas:
        assert " " not in ruta, "un espacio en la ruta rompe el Markdown"
        assert (r["nota"].parent / ruta).is_file(), f"enlace roto: {ruta}"


def test_obsidian_no_duplica_el_indice(tmp_path):
    vault = tmp_path / "neuro"; vault.mkdir()
    origen = tmp_path / "rev"; origen.mkdir()
    datos = {"tema": "Tema", "fecha": "2026-09-05"}
    for _ in range(3):
        PB.publicar_obsidian("# T\n\ncuerpo\n", datos, origen, vault=vault, tema="Tema")
    indice = (vault / "Revisiones" / "Revisiones.md").read_text(encoding="utf-8")
    assert indice.count("[[2026-09-05 Tema]]") == 1


def test_markdown_a_bloques():
    bloques = PB.markdown_a_bloques(
        "# Uno\n## Dos\n- viñeta\n> cita\n| a | b |\n|---|---|\n\ntexto\n")
    tipos = [b["type"] for b in bloques]
    assert tipos[:4] == ["heading_1", "heading_2", "bulleted_list_item", "quote"]
    assert "code" in tipos, "la tabla debe ir como bloque de código"
    assert "paragraph" in tipos
    # Un párrafo larguísimo se parte: la API rechaza más de 2000 caracteres por bloque.
    largos = PB.markdown_a_bloques("palabra " * 900)
    assert len(largos) > 1
    for b in largos:
        texto = b["paragraph"]["rich_text"][0]["text"]["content"]
        assert len(texto) <= PB.MAX_TEXTO_POR_BLOQUE


def test_propiedades_se_adaptan_al_esquema():
    """Réplica del esquema real de la database "Revisión de Literatura" del usuario.

    Enviar una propiedad que la database no tiene hace que la API rechace la página
    entera, y mandar un valor nuevo a un select **crea la opción**: publicar con
    etiquetas improvisadas ensuciaría de forma permanente una lista curada a mano.
    """
    esquema = {"properties": {
        "Título": {"type": "title"},
        "Autores": {"type": "rich_text"},
        "PMID": {"type": "rich_text"},
        "Puntos a destacar": {"type": "rich_text"},
        "Notas personales": {"type": "rich_text"},
        "Fecha publicación": {"type": "date"},
        "DOI/Link": {"type": "url"},
        "Tipo de publicación": {"type": "select", "select": {"options": [
            {"name": "Revisión"}, {"name": "Original"}, {"name": "Otro"}]}},
        "Temas": {"type": "multi_select", "multi_select": {"options": [
            {"name": "Neurología"}, {"name": "Revisión Sistemática"},
            {"name": "Caso Clínico"}]}},
        "Fecha agregado": {"type": "created_time"},
    }}
    datos = {"fecha": "2026-09-05", "costo_usd_estimado": 0.5,
             "modelos": {"ficha": "claude-sonnet-5", "sintesis": "claude-opus-5"},
             "papers": [{"ficha": {"pmids_citados": ["29766750"]}}, {}]}
    props = PB.propiedades_notion(esquema, datos, "DAPT en ACV menor",
                                  resumen="Reduce ictus recurrente a costa de hemorragia.")

    assert props["Título"]["title"][0]["text"]["content"] == "DAPT en ACV menor"
    assert props["Fecha publicación"]["date"]["start"] == "2026-09-05"
    assert props["PMID"]["rich_text"][0]["text"]["content"] == "29766750"
    assert "Reduce ictus" in props["Puntos a destacar"]["rich_text"][0]["text"]["content"]
    assert "claude-opus-5" in props["Notas personales"]["rich_text"][0]["text"]["content"]
    assert props["Tipo de publicación"]["select"]["name"] == "Revisión"

    # Solo opciones que ya existen: "Neuromuscular" no está en esta database.
    temas = {t["name"] for t in props["Temas"]["multi_select"]}
    assert temas <= {"Neurología", "Revisión Sistemática", "Caso Clínico"}
    assert "Neuromuscular" not in temas

    # Nada de lo que la database no tiene, ni las propiedades de solo lectura.
    assert "Fecha agregado" not in props
    assert set(props) <= set(esquema["properties"])


def test_propiedades_sin_titulo_no_revientan():
    """Una database sin propiedad de título no puede recibir páginas: se devuelve vacío."""
    assert PB.propiedades_notion({"properties": {"X": {"type": "rich_text"}}},
                                 {}, "Tema") == {}


def test_aporte_neto_alimenta_el_resumen():
    md = ("## Qué muestra el conjunto\nbla bla\n\n"
          "## Aporte neto\n- Reduce el ictus recurrente\n- A costa de hemorragia\n\n"
          "## Vacíos y qué haría falta\notra cosa\n")
    assert PB._aporte_neto(md) == "- Reduce el ictus recurrente - A costa de hemorragia"
    assert PB._aporte_neto("## Otra cosa\nnada") == ""


# --- Puente MCP: contención de rutas -----------------------------------------

def _raices(monkeypatch, *rutas):
    import os
    monkeypatch.setenv("HARNESS_FILE_ROOTS", os.pathsep.join(str(r) for r in rutas))


def test_sin_raices_no_se_toca_nada(monkeypatch):
    """Sin HARNESS_FILE_ROOTS el servidor falla cerrado: la alternativa es exponer C:/."""
    monkeypatch.delenv("HARNESS_FILE_ROOTS", raising=False)
    assert MS.raices() == []
    with pytest.raises(PermissionError):
        MS._resolver(str(ROOT))


def test_traversal_no_escapa_de_la_raiz(tmp_path, monkeypatch):
    permitida = tmp_path / "permitida"
    (permitida / "sub").mkdir(parents=True)
    (tmp_path / "secreta").mkdir()
    (tmp_path / "secreta" / "clave.txt").write_text("no", encoding="utf-8")
    _raices(monkeypatch, permitida)

    # Dentro: pasa, y devuelve la ruta ya resuelta.
    assert MS._resolver(str(permitida / "sub")) == (permitida / "sub").resolve()

    # `..` que sale de la raíz: se colapsa al resolver y la comparación lo rechaza.
    with pytest.raises(PermissionError):
        MS._resolver(str(permitida / "sub" / ".." / ".." / "secreta" / "clave.txt"))


def test_ruta_absoluta_fuera_de_la_raiz(tmp_path, monkeypatch):
    permitida = tmp_path / "permitida"
    permitida.mkdir()
    fuera = tmp_path / "fuera"
    fuera.mkdir()
    _raices(monkeypatch, permitida)
    with pytest.raises(PermissionError):
        MS._resolver(str(fuera))
    # Un hermano cuyo nombre empieza igual no debe colarse por prefijo de cadena.
    hermano = tmp_path / "permitida_bis"
    hermano.mkdir()
    with pytest.raises(PermissionError):
        MS._resolver(str(hermano))


def test_symlink_que_apunta_afuera(tmp_path, monkeypatch):
    permitida = tmp_path / "permitida"
    permitida.mkdir()
    fuera = tmp_path / "fuera"
    fuera.mkdir()
    (fuera / "clave.txt").write_text("no", encoding="utf-8")
    puente = permitida / "atajo"
    try:
        puente.symlink_to(fuera, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("este sistema no permite crear enlaces simbólicos")
    _raices(monkeypatch, permitida)
    # El enlace *está* dentro de la raíz, pero su destino no: resolver antes de comparar
    # es justamente lo que lo detecta.
    with pytest.raises(PermissionError):
        MS._resolver(str(puente / "clave.txt"))


def test_leer_archivo_respeta_el_tipo_y_el_tope(tmp_path, monkeypatch):
    _raices(monkeypatch, tmp_path)
    (tmp_path / "nota.md").write_text("hola", encoding="utf-8")
    (tmp_path / "paper.pdf").write_bytes(b"%PDF-1.7")
    assert MS.leer_archivo(str(tmp_path / "nota.md")) == "hola"
    assert "no es texto" in MS.leer_archivo(str(tmp_path / "paper.pdf"))
    grande = tmp_path / "grande.txt"
    grande.write_text("x" * (MS.MAX_LECTURA + 500), encoding="utf-8")
    salida = MS.leer_archivo(str(grande))
    assert "recortado: 500 caracteres" in salida
    assert len(salida.split("\n\n[...")[0]) == MS.MAX_LECTURA


def test_listado_y_busqueda_solo_dentro(tmp_path, monkeypatch):
    permitida = tmp_path / "papers"
    (permitida / "2024").mkdir(parents=True)
    (permitida / "2024" / "miastenia.pdf").write_bytes(b"%PDF")
    (permitida / "otro.md").write_text("x", encoding="utf-8")
    _raices(monkeypatch, permitida)
    listado = MS.listar_carpeta(str(permitida))
    assert "2024" in listado and "otro.md" in listado
    hallazgos = MS.buscar_archivos("*.pdf")
    assert "miastenia.pdf" in hallazgos
    with pytest.raises(PermissionError):
        MS.buscar_archivos("*.pdf", subcarpeta=str(tmp_path))


def test_estado_no_filtra_credenciales(monkeypatch):
    monkeypatch.setenv("NOTION_TOKEN", "secret_no-debe-aparecer")
    monkeypatch.delenv("HARNESS_FILE_ROOTS", raising=False)
    salida = MS.estado()
    assert "secret_no-debe-aparecer" not in salida
    assert json.loads(salida)["notion_token"] == "presente"


def test_el_puente_importa_sin_el_sdk():
    """El módulo carga sin `mcp` instalado: el import va dentro de construir_servidor()
    para que CI y estos tests corran en un entorno pelado."""
    src = (ROOT / "tools" / "mcp_server.py").read_text(encoding="utf-8")
    fuera = src.split("def construir_servidor")[0]
    assert "import mcp" not in fuera and "from mcp" not in fuera


def test_el_error_llega_legible_a_la_tool(tmp_path, monkeypatch):
    """El SDK descarta el texto de la excepción; `blindado` lo devuelve como resultado
    para que el modelo sepa *por qué* falló y no solo *que* falló."""
    _raices(monkeypatch, tmp_path / "permitida")
    (tmp_path / "permitida").mkdir()
    salida = MS.blindado(MS.listar_carpeta)(str(tmp_path / "fuera"))
    assert salida.startswith("ERROR de permisos:")
    assert "Permitidas:" in salida
    # Y no se traga los aciertos.
    assert MS.blindado(MS.listar_carpeta)(str(tmp_path / "permitida")).startswith(
        str((tmp_path / "permitida").resolve()))
