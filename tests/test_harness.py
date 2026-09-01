"""Tests del harness. Correr con: pytest -q  (desde la raíz del paquete)."""
import importlib
import importlib.util
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
