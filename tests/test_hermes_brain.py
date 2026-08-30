"""Tests del pipeline hermes_brain (inventario → clasificación → Hermes → .md).

Correr con:  pytest -q tests/test_hermes_brain.py

Las dependencias de documentos (python-docx, pypdf) son opcionales en el harness: los tests
que las necesitan se saltan si no están instaladas.
"""
from __future__ import annotations

import json
import sys
import zlib
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "tools"))

from hermes_brain.cola import Cola
from hermes_brain.config import (
    Config,
    ConfigClasificador,
    ConfigHermes,
    ErrorConfig,
    cargar,
)

from hermes_brain import clasificador as clf
from hermes_brain import hermes as hm
from hermes_brain import inventario as inv


# --------------------------------------------------------------------------- fixtures
def _pdf(lineas: list[str], titulo: str = "", autor: str = "") -> bytes:
    """PDF mínimo válido con una página de texto, sin dependencias externas."""
    texto = "BT /F1 9 Tf 40 750 Td 12 TL\n" + "".join(
        "(" + l.replace("\\", "").replace("(", "").replace(")", "") + ") Tj T*\n" for l in lineas) + "ET"
    objetos = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        (b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]"
         b"/Resources<</Font<</F1 4 0 R>>>>/Contents 5 0 R>>"),
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
        f"<</Length {len(texto)}>>\nstream\n{texto}\nendstream".encode("latin-1"),
        f"<</Title ({titulo})/Author ({autor})>>".encode("latin-1"),
    ]
    salida = bytearray(b"%PDF-1.4\n")
    posiciones = []
    for i, cuerpo in enumerate(objetos, 1):
        posiciones.append(len(salida))
        salida += f"{i} 0 obj\n".encode() + cuerpo + b"\nendobj\n"
    inicio_xref = len(salida)
    salida += f"xref\n0 {len(objetos) + 1}\n0000000000 65535 f \n".encode()
    for pos in posiciones:
        salida += f"{pos:010d} 00000 n \n".encode()
    salida += (f"trailer\n<</Size {len(objetos) + 1}/Root 1 0 R/Info 6 0 R>>\n"
               f"startxref\n{inicio_xref}\n%%EOF\n").encode()
    return bytes(salida)


PAPER = [
    "Muscle & Nerve  Volume 68, Issue 4, October 2023, pp. 412-421",
    "ISSN 0148-639X  doi.org/10.1002/mus.27832  2023 Wiley Periodicals LLC",
    "Ultrasound of peripheral nerves in chronic inflammatory demyelinating polyneuropathy",
    "Cristian Ugalde-Diaz, MD 1,2; Dario Farina, PhD 3; Francesco Negro, PhD 3",
    "1 Department of Neurology, Pontificia Universidad Catolica de Chile, Santiago",
    "Correspondence: autor@uc.cl",
    "Received 15 March 2023  Revised 2 June 2023  Accepted 11 July 2023",
    "Abstract",
    "Introduction: Nerve ultrasound has emerged as a complementary tool in CIDP.",
    "Methods: We searched MEDLINE and Embase for cross-sectional area studies.",
    "Results: Twenty-two studies met inclusion criteria; sensitivity 0.84, specificity 0.91.",
    "Key words: nerve ultrasound; CIDP; polyneuropathy; diagnosis",
]
BOLETA = [
    "COMERCIAL LOS ANDES LTDA",
    "Boleta electronica N 44712  Fecha 12/03/2026",
    "Detalle: 2 sillas ergonomicas para oficina de la unidad",
    "Total: $ 340.000. Gracias por su compra. Despacho en 15 dias habiles.",
    "Condiciones: pago a 30 dias, garantia de dos anos por defectos de fabricacion.",
]


@pytest.fixture
def docx_clinico(tmp_path: Path) -> Path:
    docx = pytest.importorskip("docx")
    d = docx.Document()
    d.add_heading("Miastenia gravis - resumen clinico", level=1)
    d.add_heading("Definición", level=2)
    p = d.add_paragraph("Enfermedad autoinmune de la ")
    p.add_run("unión neuromuscular").bold = True
    d.add_paragraph("Paciente: Juan Pérez González")
    d.add_paragraph("RUT: 12.345.678-9")
    d.add_heading("Epidemiología", level=2)
    d.add_paragraph("Incidencia de 8-10 por millón de habitantes al año.")
    d.add_heading("Cuadro clínico", level=2)
    for t in ("Ptosis fluctuante", "Diplopía", "Debilidad bulbar"):
        d.add_paragraph(t, style="List Bullet")
    d.add_heading("Diagnóstico", level=2)
    for t in ("Anticuerpos anti-AChR", "Estimulación repetitiva a 3 Hz"):
        d.add_paragraph(t, style="List Number")
    tabla = d.add_table(rows=2, cols=2)
    for fila, vals in zip(tabla.rows, [["Prueba", "Sensibilidad"], ["Anti-AChR", "85%"]]):
        for celda, v in zip(fila.cells, vals):
            celda.text = v
    d.add_picture(str(_png(tmp_path)))
    d.add_paragraph("Figura 1. Decremento en estimulación repetitiva.", style="Caption")
    d.add_heading("Tratamiento", level=2)
    d.add_paragraph("Piridostigmina 60 mg cada 6 h; corticoides en escalada lenta.")
    ruta = tmp_path / "resumen_clinico.docx"
    d.save(str(ruta))
    return ruta


@pytest.fixture
def docx_administrativo(tmp_path: Path) -> Path:
    docx = pytest.importorskip("docx")
    d = docx.Document()
    d.add_heading("Cotización de equipos", level=1)
    d.add_paragraph("Orden de compra N° 4471. Presupuesto total: $ 3.400.000. Factura pendiente "
                    "de emisión. Se adjunta el detalle para revisión de la subdirección "
                    "administrativa. El proveedor confirma despacho en 15 días hábiles y "
                    "garantía de dos años por defectos de fabricación.")
    d.add_paragraph("Condiciones comerciales: pago a 30 días, descuento por volumen del 8%, "
                    "flete incluido dentro de la Región Metropolitana. Cualquier modificación "
                    "debe formalizarse por escrito ante la unidad de abastecimiento.")
    ruta = tmp_path / "cotizacion.docx"
    d.save(str(ruta))
    return ruta


def _png(carpeta: Path) -> Path:
    """PNG rojo de 8x8 generado a mano (sin Pillow)."""
    import struct

    def trozo(tipo: bytes, datos: bytes) -> bytes:
        c = tipo + datos
        return struct.pack(">I", len(datos)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    crudo = b"".join(b"\x00" + b"\xc8\x3c\x3c" * 8 for _ in range(8))
    png = (b"\x89PNG\r\n\x1a\n"
           + trozo(b"IHDR", struct.pack(">IIBBBBB", 8, 8, 8, 2, 0, 0, 0))
           + trozo(b"IDAT", zlib.compress(crudo)) + trozo(b"IEND", b""))
    ruta = carpeta / "fig.png"
    ruta.write_bytes(png)
    return ruta


@pytest.fixture
def umbrales() -> ConfigClasificador:
    return ConfigClasificador()


# --------------------------------------------------------------------------- clasificador
def test_pdf_de_revista_se_reconoce(tmp_path: Path, umbrales):
    pytest.importorskip("pypdf")
    ruta = tmp_path / "paper.pdf"
    ruta.write_bytes(_pdf(PAPER, titulo="Ultrasound of peripheral nerves in CIDP",
                          autor="Ugalde C, Farina D"))
    r = clf.clasificar(ruta, umbrales)
    assert r.decision == "cientifico", r.motivo
    assert r.evidencia["nucleo"] == 4
    assert r.evidencia["doi"] and r.evidencia["abstract"]


def test_pdf_administrativo_se_descarta(tmp_path: Path, umbrales):
    pytest.importorskip("pypdf")
    ruta = tmp_path / "boleta.pdf"
    ruta.write_bytes(_pdf(BOLETA, titulo="Microsoft Word - boleta.doc", autor="Usuario"))
    r = clf.clasificar(ruta, umbrales)
    assert r.decision == "no_cientifico", r.motivo


def test_autor_del_metadato_no_confunde_el_nombre_del_pc():
    """Word rellena /Author con la cuenta del PC: eso no es autoría de artículo."""
    assert not clf._autor_creible("Usuario")
    assert not clf._autor_creible("windows user")
    assert not clf._autor_creible("")
    assert clf._autor_creible("Ugalde C, Farina D")
    assert clf._autor_creible("Cristian Ugalde")


def test_pdf_sin_capa_de_texto_queda_dudoso(tmp_path: Path, umbrales):
    pytest.importorskip("pypdf")
    ruta = tmp_path / "escaneo.pdf"
    ruta.write_bytes(_pdf(["x"]))
    r = clf.clasificar(ruta, umbrales)
    assert r.decision == "dudoso"
    assert r.evidencia.get("sin_texto")


def test_word_clinico_se_reconoce(docx_clinico: Path, umbrales):
    r = clf.clasificar(docx_clinico, umbrales)
    assert r.decision == "clinico", r.motivo
    assert "diagnostico" in r.evidencia["secciones_en_titulos"]
    assert r.evidencia["phi_probable"] is True


def test_word_administrativo_se_descarta(docx_administrativo: Path, umbrales):
    r = clf.clasificar(docx_administrativo, umbrales)
    assert r.decision == "no_clinico", r.motivo


def test_zona_gris_produce_dudoso(tmp_path: Path):
    """Con umbrales estrechos, un documento intermedio no se decide solo: va a revisión."""
    docx = pytest.importorskip("docx")
    d = docx.Document()
    d.add_heading("Notas de la reunión sobre el paciente índice", level=1)
    d.add_paragraph("Se revisó el tratamiento y el diagnóstico diferencial del caso, con "
                    "acuerdo de solicitar exámenes complementarios y repetir la evaluación "
                    "clínica en dos semanas para definir la conducta terapéutica.")
    ruta = tmp_path / "intermedio.docx"
    d.save(str(ruta))
    r = clf.clasificar(ruta, ConfigClasificador(docx_umbral_si=4.0, docx_umbral_no=0.5))
    assert r.decision == "dudoso", r.motivo


def test_doc_legado_sin_libreoffice_pide_revision(tmp_path: Path, umbrales):
    ruta = tmp_path / "viejo.doc"
    ruta.write_bytes(b"\xd0\xcf\x11\xe0")
    r = clf.clasificar(ruta, umbrales)
    assert r.decision == "dudoso" and "legado" in r.motivo


# --------------------------------------------------------------------------- conversión docx→md
def _convertidor():
    import importlib.util
    ruta = RAIZ / "skills" / "resumen_clinico_md" / "scripts" / "docx_a_md.py"
    if "docx_a_md" in sys.modules:
        return sys.modules["docx_a_md"]
    spec = importlib.util.spec_from_file_location("docx_a_md", ruta)
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["docx_a_md"] = modulo   # @dataclass necesita el módulo registrado
    spec.loader.exec_module(modulo)
    return modulo


def test_conversion_docx_a_md(docx_clinico: Path, tmp_path: Path):
    pytest.importorskip("docx")
    conv = _convertidor()
    salida = tmp_path / "brain md"
    res = conv.convertir(docx_clinico, salida, "_adjuntos")
    texto = res.md.read_text(encoding="utf-8")

    assert res.md.exists() and res.md.parent == salida
    assert res.figuras == 1 and res.tablas == 1
    assert (salida / "_adjuntos" / res.md.stem / "fig-01.png").exists()
    assert "## Epidemiología" in texto                      # títulos preservados
    assert "- Ptosis fluctuante" in texto                   # lista con viñetas
    assert "1. Anticuerpos anti-AChR" in texto              # lista numerada
    assert "| Prueba | Sensibilidad |" in texto             # tabla
    assert "*Figura 1. Decremento en estimulación repetitiva.*" in texto  # pie de figura
    assert "**unión neuromuscular**" in texto               # negrita
    assert texto.startswith("---\n")                        # front-matter


def test_conversion_deidentifica_por_defecto(docx_clinico: Path, tmp_path: Path):
    pytest.importorskip("docx")
    conv = _convertidor()
    res = conv.convertir(docx_clinico, tmp_path / "brain", "_adjuntos")
    texto = res.md.read_text(encoding="utf-8")
    assert "12.345.678-9" not in texto and "Juan Pérez" not in texto
    assert "[DATO PERSONAL OMITIDO]" in texto
    assert res.enmascarados >= 2
    # Si hubo PHI, el nombre del archivo original tampoco se guarda (R8).
    assert "archivo_origen:" not in texto and "sha256_origen:" in texto


def test_conversion_no_sobrescribe(docx_clinico: Path, tmp_path: Path):
    pytest.importorskip("docx")
    conv = _convertidor()
    salida = tmp_path / "brain"
    primero = conv.convertir(docx_clinico, salida, "_adjuntos")
    segundo = conv.convertir(docx_clinico, salida, "_adjuntos")
    assert primero.md != segundo.md and segundo.md.stem.endswith("-2")
    # El enlace a las figuras apunta a la carpeta del .md que lo contiene, no a la del primero.
    assert f"_adjuntos/{segundo.md.stem}/fig-01.png" in segundo.md.read_text(encoding="utf-8")


def test_deidentificar_cubre_identificadores_directos():
    conv = _convertidor()
    texto, n = conv.deidentificar(
        "RUT: 12.345.678-9\nTeléfono: +56 9 8765 4321\ncorreo juan@ejemplo.cl\nficha N° 44821")
    assert n >= 4
    for rastro in ("12.345.678-9", "8765 4321", "juan@ejemplo.cl", "44821"):
        assert rastro not in texto


# --------------------------------------------------------------------------- cola
def test_cola_registra_y_deduplica(tmp_path: Path):
    with Cola(tmp_path / "cola.sqlite3") as cola:
        assert cola.registrar("L1", tmp_path / "a.pdf", ".pdf", 100, 1.0, "sha-a") is True
        assert cola.registrar("L1", tmp_path / "a.pdf", ".pdf", 100, 1.0, "sha-a") is False
        cola.registrar("L1", tmp_path / "copia.pdf", ".pdf", 100, 1.0, "sha-a")
        assert cola.resumen("L1")["total"] == 2

        a = cola.pendientes("L1")[0]
        cola.actualizar(a.id, estado="hecho")
        assert cola.marcar_duplicados() == 1
        assert cola.resumen("L1")["omitido"] == 1


def test_cola_toma_una_sola_vez(tmp_path: Path):
    with Cola(tmp_path / "cola.sqlite3") as cola:
        cola.registrar("L", tmp_path / "a.pdf", ".pdf", 1, 1.0, "sha")
        archivo = cola.pendientes()[0]
        assert cola.tomar(archivo.id) is True
        assert cola.tomar(archivo.id) is False       # ya está en proceso
        assert cola.liberar_colgados(segundos=0) == 1
        assert cola.tomar(archivo.id) is True


def test_cola_reencola_errores(tmp_path: Path):
    with Cola(tmp_path / "cola.sqlite3") as cola:
        cola.registrar("L", tmp_path / "a.pdf", ".pdf", 1, 1.0, "sha")
        cola.actualizar(cola.pendientes()[0].id, estado="error", error="timeout")
        assert cola.reencolar("L") == 1
        assert cola.resumen("L")["clasificado"] == 1


def test_id_opaco_no_expone_el_nombre(tmp_path: Path):
    with Cola(tmp_path / "cola.sqlite3") as cola:
        cola.registrar("L", tmp_path / "paciente_perez.pdf", ".pdf", 1, 1.0, "abc123def456789")
        archivo = cola.pendientes()[0]
        assert "perez" not in archivo.id_opaco
        assert archivo.id_opaco == "abc123def456789"


# --------------------------------------------------------------------------- inventario
def test_inventario_entra_en_subcarpetas_y_salta_temporales(tmp_path: Path):
    (tmp_path / "sub" / "hondo").mkdir(parents=True)
    (tmp_path / "raiz.pdf").write_bytes(b"%PDF-1.4 contenido")
    (tmp_path / "sub" / "medio.docx").write_bytes(b"PK contenido")
    (tmp_path / "sub" / "hondo" / "fondo.pdf").write_bytes(b"%PDF-1.4 otro")
    (tmp_path / "sub" / "~$temporal.docx").write_bytes(b"basura")
    (tmp_path / "sub" / "notas.txt").write_text("no corresponde")

    encontrados = sorted(p.name for p in inv.recorrer(tmp_path, [".pdf", ".docx"], ["~$*", ".*"]))
    assert encontrados == ["fondo.pdf", "medio.docx", "raiz.pdf"]


def test_escaneo_ignora_el_destino_y_los_grandes(tmp_path: Path):
    origen = tmp_path / "papers"
    destino = tmp_path / "brain md"
    (origen / "sub").mkdir(parents=True)
    destino.mkdir()
    (origen / "bueno.pdf").write_bytes(b"%PDF contenido suficiente")
    (origen / "sub" / "grande.pdf").write_bytes(b"x" * 2048)
    (destino / "ya_convertido.pdf").write_bytes(b"%PDF salida previa")

    cfg = Config(carpetas=[origen, destino], destino_md=destino, tamano_max_mb=0,
                 db=tmp_path / "cola.sqlite3", hermes=ConfigHermes(comando=["x"]))
    cfg.tamano_max_mb = 0.001  # 1 KB
    with Cola(cfg.db) as cola:
        res = inv.escanear(cfg, cola, "L", [origen, destino])
        assert res.nuevos == 1                       # solo bueno.pdf
        assert res.demasiado_grandes == 1
        assert res.excluidos == 1                    # lo que ya vive en destino_md


# --------------------------------------------------------------------------- adaptador Hermes
def _cli_falso(tmp_path: Path, cuerpo: str) -> Path:
    ruta = tmp_path / "hermes_falso.py"
    ruta.write_text(cuerpo, encoding="utf-8")
    return ruta


CLI_OK = """
import json, sys
from pathlib import Path
args = dict(zip(sys.argv[1::2], sys.argv[2::2]))
destino = Path(args["--destino"]); destino.mkdir(parents=True, exist_ok=True)
md = destino / (args["--slug"] + ".md")
md.write_text("# generado por el chat\\n", encoding="utf-8")
Path(args["--salida"]).write_text(json.dumps(
    {"md": str(md), "notion_url": "https://notion.so/pagina", "sesion": "chat-1"}), encoding="utf-8")
print("chat abierto y cerrado")
"""

CLI_SIN_MD = """
import sys
print("no pude analizar el archivo")
sys.exit(0)
"""

CLI_CONVIERTE = """
import json, subprocess, sys
from pathlib import Path
args = dict(zip(sys.argv[1::2], sys.argv[2::2]))
cmd = [sys.executable, "CONVERSOR", args["--archivo"], "--salida", args["--destino"], "--json"]
if args.get("--slug"):
    cmd += ["--slug", args["--slug"]]
salida = subprocess.run(cmd, capture_output=True, text=True)
if salida.returncode:
    print(salida.stderr); sys.exit(salida.returncode)
Path(args["--salida"]).write_text(
    json.dumps({"md": json.loads(salida.stdout)["md"]}), encoding="utf-8")
print("chat completado")
"""

CLI_CAIDO = """
import sys
print("boom"); sys.exit(3)
"""


def test_adaptador_hermes_devuelve_el_md(tmp_path: Path):
    script = _cli_falso(tmp_path, CLI_OK)
    cfg = ConfigHermes(comando=[sys.executable, str(script), "--archivo", "{archivo}",
                                "--destino", "{destino}", "--slug", "{slug}",
                                "--salida", "{salida_json}"], reintentos=0, timeout_s=60)
    res = hm.ejecutar_chat(cfg, archivo=tmp_path / "x.pdf", skill="analisis-estudio",
                           prompt="analiza", destino=tmp_path / "brain",
                           adjuntos=tmp_path / "brain" / "_adjuntos", nombre_slug="estudio-x")
    assert res.ok and res.md.endswith("estudio-x.md")
    assert res.notion_url == "https://notion.so/pagina" and res.sesion == "chat-1"


def test_adaptador_no_reintenta_si_hermes_termina_sin_md(tmp_path: Path):
    """Salir con éxito pero sin .md no es un fallo transitorio: reintentar daría lo mismo."""
    script = _cli_falso(tmp_path, CLI_SIN_MD)
    cfg = ConfigHermes(comando=[sys.executable, str(script)], reintentos=3,
                       espera_reintento_s=0, timeout_s=60)
    res = hm.ejecutar_chat(cfg, archivo=tmp_path / "x.pdf", skill="s", prompt="p",
                           destino=tmp_path / "brain", adjuntos=tmp_path, nombre_slug="x")
    assert not res.ok and "sin producir .md" in res.error


def test_adaptador_reporta_codigo_de_salida(tmp_path: Path):
    script = _cli_falso(tmp_path, CLI_CAIDO)
    cfg = ConfigHermes(comando=[sys.executable, str(script)], reintentos=0, timeout_s=60)
    res = hm.ejecutar_chat(cfg, archivo=tmp_path / "x.pdf", skill="s", prompt="p",
                           destino=tmp_path / "brain", adjuntos=tmp_path, nombre_slug="x")
    assert not res.ok and "código 3" in res.error


def test_adaptador_corta_por_timeout(tmp_path: Path):
    script = _cli_falso(tmp_path, "import time\ntime.sleep(30)\n")
    cfg = ConfigHermes(comando=[sys.executable, str(script)], reintentos=0, timeout_s=1)
    res = hm.ejecutar_chat(cfg, archivo=tmp_path / "x.pdf", skill="s", prompt="p",
                           destino=tmp_path / "brain", adjuntos=tmp_path, nombre_slug="x")
    assert not res.ok and "timeout" in res.error


def test_slug_normaliza_titulos():
    assert hm.slug("Miastenia gravis: crisis miasténica (2024)") == "miastenia-gravis-crisis-miastenica-2024"
    assert hm.slug("") == "documento"


# --------------------------------------------------------------------------- extremo a extremo
def test_lote_completo_con_hermes_falso(tmp_path: Path, docx_clinico: Path,
                                        docx_administrativo: Path):
    """Un lote real en miniatura: PDF científico + Word clínico + dos que deben omitirse."""
    pytest.importorskip("pypdf")
    from hermes_brain.procesador import procesar_lote

    origen = tmp_path / "papers"
    (origen / "sub").mkdir(parents=True)
    (origen / "paper.pdf").write_bytes(_pdf(PAPER, "Ultrasound in CIDP", "Ugalde C, Farina D"))
    (origen / "sub" / "boleta.pdf").write_bytes(_pdf(BOLETA, "Microsoft Word - boleta.doc", "Usuario"))
    (origen / "sub" / docx_clinico.name).write_bytes(docx_clinico.read_bytes())
    (origen / docx_administrativo.name).write_bytes(docx_administrativo.read_bytes())

    script = _cli_falso(tmp_path, CLI_OK)
    cfg = Config(
        carpetas=[origen], destino_md=tmp_path / "brain md", db=tmp_path / "cola.sqlite3",
        hermes=ConfigHermes(
            comando=[sys.executable, str(script), "--archivo", "{archivo}", "--destino",
                     "{destino}", "--slug", "{slug}", "--salida", "{salida_json}"],
            reintentos=0, timeout_s=60))
    with Cola(cfg.db) as cola:
        res = inv.escanear(cfg, cola, "lote-test")
        assert res.nuevos == 4
        prog = procesar_lote(cfg, cola, "lote-test")

        assert prog.hechos == 2, cola.resumen("lote-test")     # el paper y el resumen clínico
        assert prog.omitidos == 2                              # boleta y cotización
        assert prog.errores == 0
        clases = cola.resumen_clasificacion("lote-test")
        assert clases["cientifico"] == 1 and clases["clinico"] == 1
        assert len(list((tmp_path / "brain md").glob("*.md"))) == 2

        # Los registros que salen al VPS no llevan nombres ni rutas.
        for archivo in cola.por_estado("hecho", "lote-test"):
            assert archivo.ruta.name not in archivo.id_opaco


def test_informe_lista_dudosos_y_errores(tmp_path: Path):
    from hermes_brain import informe

    with Cola(tmp_path / "cola.sqlite3") as cola:
        cola.registrar("L", tmp_path / "duda.docx", ".docx", 10, 1.0, "sha1")
        cola.registrar("L", tmp_path / "roto.pdf", ".pdf", 10, 1.0, "sha2")
        cola.actualizar(cola.pendientes()[0].id, estado="dudoso", motivo="zona gris")
        cola.actualizar(cola.pendientes()[0].id, estado="error", error="timeout tras 900s")
        texto = informe.generar(cola, "L", tmp_path / "informe.md")

    assert "duda.docx" in texto and "zona gris" in texto
    assert "timeout tras 900s" in texto
    assert "hermes_brain.py revisar" in texto
    assert (tmp_path / "informe.md").exists()


# --------------------------------------------------------------------------- configuración
def test_config_exige_comando_de_hermes(tmp_path: Path):
    ruta = tmp_path / "cfg.yaml"
    ruta.write_text("carpetas: ['/tmp/x']\ndestino_md: '/tmp/y'\n", encoding="utf-8")
    with pytest.raises(ErrorConfig, match="hermes.comando"):
        cargar(ruta)


def test_config_exige_token_si_hay_n8n(tmp_path: Path):
    ruta = tmp_path / "cfg.yaml"
    ruta.write_text("carpetas: ['/tmp/x']\ndestino_md: '/tmp/y'\n"
                    "hermes:\n  comando: ['hermes']\n"
                    "n8n:\n  base_url: 'https://x/webhook'\n", encoding="utf-8")
    with pytest.raises(ErrorConfig, match="token"):
        cargar(ruta)


def test_config_carga_el_ejemplo(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HERMES_TOKEN", "secreto")
    cfg = cargar(RAIZ / "tools" / "hermes_brain" / "config.example.yaml")
    assert cfg.hermes.skill_docx == "resumen-clinico-md"
    assert cfg.n8n.token == "secreto"          # ${HERMES_TOKEN} se expande desde el entorno
    assert cfg.n8n.enviar_nombres is False     # por defecto no salen nombres al VPS
    assert cfg.destino_md.name == "brain md"


# --------------------------------------------------------------------------- flujo n8n
def test_flujo_n8n_es_importable():
    """El JSON del flujo debe tener nodos, conexiones coherentes y las rutas que usa el worker."""
    from hermes_brain.cliente_n8n import RUTAS

    flujo = json.loads((RAIZ / "n8n" / "flujo_hermes_brain.json").read_text(encoding="utf-8"))
    nombres = {n["name"] for n in flujo["nodes"]}
    assert flujo["nodes"] and flujo["connections"]
    for origen, salidas in flujo["connections"].items():
        assert origen in nombres, origen
        for salida in salidas["main"]:
            for destino in salida:
                assert destino["node"] in nombres, destino["node"]

    rutas_flujo = {n["parameters"]["path"] for n in flujo["nodes"]
                   if n["type"] == "n8n-nodes-base.webhook"}
    for ruta in RUTAS.values():
        assert ruta.lstrip("/") in rutas_flujo, ruta


def test_el_nombre_del_md_no_hereda_phi_del_nombre_del_word(tmp_path: Path, docx_clinico: Path):
    """Un Word con datos de paciente no puede prestar su nombre al .md (R8).

    El CLI falso hace lo que hará Hermes: llamar al conversor de la skill. Sin `--slug`, el
    nombre sale del título del documento, que la conversión de-identifica.
    """
    from hermes_brain.procesador import procesar_archivo

    origen = tmp_path / "docs"
    origen.mkdir()
    (origen / "resumen perez juan 12345678.docx").write_bytes(docx_clinico.read_bytes())
    conversor = RAIZ / "skills" / "resumen_clinico_md" / "scripts" / "docx_a_md.py"
    script = _cli_falso(tmp_path, CLI_CONVIERTE.replace("CONVERSOR", str(conversor).replace("\\", "/")))
    cfg = Config(
        carpetas=[origen], destino_md=tmp_path / "brain", db=tmp_path / "cola.sqlite3",
        hermes=ConfigHermes(
            comando=[sys.executable, str(script), "--archivo", "{archivo}", "--destino",
                     "{destino}", "--slug", "{slug}", "--salida", "{salida_json}"],
            reintentos=0, timeout_s=120))
    with Cola(cfg.db) as cola:
        inv.escanear(cfg, cola, "L")
        registro = procesar_archivo(cfg, cola, cola.pendientes()[0])
        assert registro["estado"] == "hecho", registro
        assert registro["clasificacion"] == "clinico"

    generados = [p.name for p in (tmp_path / "brain").glob("*.md")]
    assert generados == ["miastenia-gravis-resumen-clinico.md"], generados
    texto = (tmp_path / "brain" / generados[0]).read_text(encoding="utf-8")
    assert "12.345.678-9" not in texto and "Juan Pérez" not in texto


def test_prompt_docx_omite_el_slug_cuando_viene_vacio(tmp_path: Path):
    cfg = Config(carpetas=[tmp_path], destino_md=tmp_path / "brain",
                 hermes=ConfigHermes(comando=["hermes"]))
    con_slug = hm.prompt_docx(cfg, tmp_path / "x.docx", "Miastenia", "miastenia")
    sin_slug = hm.prompt_docx(cfg, tmp_path / "x.docx", "", "")
    assert '--slug "miastenia"' in con_slug
    assert "--slug" not in sin_slug
