"""Tests del pipeline hermes_brain (inventario → clasificación → Hermes → .md).

Correr con:  pytest -q tests/test_hermes_brain.py

Las dependencias de documentos (python-docx, pypdf) son opcionales en el harness: los tests
que las necesitan se saltan si no están instaladas.
"""
from __future__ import annotations

import json
import os
import subprocess
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


# --------------------------------------------------------------------------- detección del CLI
def test_detecta_ejecutable_en_el_path_y_captura_su_ayuda(tmp_path: Path, monkeypatch):
    from hermes_brain import detectar as det

    binario = tmp_path / "bin"
    binario.mkdir()
    falso = binario / ("hermes.cmd" if os.name == "nt" else "hermes")
    falso.write_text("#!/bin/sh\necho 'hermes 0.9 — uso: hermes chat --skill <nombre>'\n",
                     encoding="utf-8")
    falso.chmod(0o755)
    monkeypatch.setenv("PATH", str(binario), prepend=os.pathsep)

    candidatos = det.en_path("hermes")
    assert any(str(falso) == c.ruta for c in candidatos), candidatos
    if os.name != "nt":
        ayuda = det.pedir_ayuda(next(c for c in candidatos if c.ruta == str(falso)))
        assert "hermes chat" in ayuda.ayuda


def test_procesos_filtra_por_nombre(monkeypatch):
    """La línea de comandos de un Hermes ya abierto es la pista firme; hay que reconocerla."""
    from hermes_brain import detectar as det

    salida = ("  PID ARGS\n"
              " 1639 /opt/hermes/hermes chat --new --skill analisis-estudio\n"
              " 1700 /usr/bin/python -m hermes_brain detectar\n"
              " 1800 /usr/bin/firefox\n")
    monkeypatch.setattr(det, "_correr", lambda cmd, timeout=20: (0, salida))
    monkeypatch.setattr(det.os, "name", "posix")
    encontrados = det.procesos("hermes")
    assert len(encontrados) == 1                      # el propio worker no cuenta
    assert "--skill analisis-estudio" in encontrados[0]


def test_informe_propone_el_bloque_yaml_y_los_pasos(tmp_path: Path):
    from hermes_brain import detectar as det

    hallazgos = det.Hallazgos(ejecutables=[det.Candidato("C:/Apps/hermes.exe", "PATH", "uso: …")])
    texto = det.formatear(hallazgos, "hermes")
    assert "C:/Apps/hermes.exe" in texto
    assert "hermes:" in texto and "comando:" in texto
    assert "{prompt_file}" in texto and "{salida_json}" in texto


def test_deteccion_vacia_sugiere_otro_nombre(monkeypatch):
    from hermes_brain import detectar as det

    monkeypatch.setattr(det, "en_path", lambda base: [])
    monkeypatch.setattr(det, "en_carpetas", lambda *a, **k: [])
    monkeypatch.setattr(det, "procesos", lambda base: [])
    monkeypatch.setattr(det, "paquetes", lambda base: [])
    monkeypatch.setattr(det, "registro", lambda base: [])
    hallazgos = det.detectar("zzz", con_ayuda=False)
    assert hallazgos.notas and "--nombre" in hallazgos.notas[0]


def test_detectar_funciona_sin_pyyaml_ni_requests():
    """`detectar` es el primer comando que se corre: no puede exigir instalar nada antes."""
    guion = (
        "import sys\n"
        "class Bloqueo:\n"
        "    def find_spec(self, nombre, ruta=None, destino=None):\n"
        "        if nombre.split('.')[0] in ('yaml', 'requests'):\n"
        "            raise ImportError(nombre)\n"
        "        return None\n"
        "sys.meta_path.insert(0, Bloqueo())\n"
        f"sys.path.insert(0, {str(RAIZ / 'tools')!r})\n"
        "from hermes_brain import cli\n"
        "print('DETECTAR' if 'detectar' in cli.construir_parser().format_help() else 'FALTA')\n"
    )
    salida = subprocess.run([sys.executable, "-c", guion], capture_output=True, text=True,
                            timeout=60, check=False)
    assert salida.returncode == 0, salida.stderr
    assert "DETECTAR" in salida.stdout


# ------------------------------------------------- Word: convierte el worker, revisa Hermes
def _cfg_clinico(tmp_path: Path, origen: Path, comando: list[str] | None = None,
                 revisar: bool = True) -> Config:
    return Config(
        carpetas=[origen], destino_md=tmp_path / "brain", db=tmp_path / "cola.sqlite3",
        script_docx_md=RAIZ / "skills" / "resumen_clinico_md" / "scripts" / "docx_a_md.py",
        hermes=ConfigHermes(comando=comando or [], reintentos=0, timeout_s=90,
                            revisar_docx_con_hermes=revisar))


def test_word_clinico_no_necesita_a_hermes(tmp_path: Path, docx_clinico: Path):
    """La conversión es determinista: sin CLI de Hermes configurado, el .md igual se escribe."""
    from hermes_brain.procesador import procesar_archivo

    origen = tmp_path / "docs"
    origen.mkdir()
    (origen / "resumen.docx").write_bytes(docx_clinico.read_bytes())
    cfg = _cfg_clinico(tmp_path, origen, comando=[], revisar=False)

    with Cola(cfg.db) as cola:
        inv.escanear(cfg, cola, "L")
        registro = procesar_archivo(cfg, cola, cola.pendientes()[0])
        assert registro["estado"] == "hecho" and registro["md"] is True

    md = list((tmp_path / "brain").glob("*.md"))
    assert len(md) == 1
    texto = md[0].read_text(encoding="utf-8")
    assert "## Epidemiología" in texto and "12.345.678-9" not in texto
    assert (tmp_path / "brain" / "_adjuntos" / md[0].stem / "fig-01.png").exists()


def test_revision_fallida_no_pierde_el_md(tmp_path: Path, docx_clinico: Path):
    """Si Hermes se cae en la revisión, el archivo sigue contando como hecho, con nota."""
    from hermes_brain.procesador import procesar_archivo

    origen = tmp_path / "docs"
    origen.mkdir()
    (origen / "resumen.docx").write_bytes(docx_clinico.read_bytes())
    script = _cli_falso(tmp_path, CLI_CAIDO)
    cfg = _cfg_clinico(tmp_path, origen, comando=[sys.executable, str(script)])

    with Cola(cfg.db) as cola:
        inv.escanear(cfg, cola, "L")
        archivo = cola.pendientes()[0]
        registro = procesar_archivo(cfg, cola, archivo)
        guardado = cola.obtener(archivo.id)

    assert registro["estado"] == "hecho", registro
    assert "revisión de Hermes falló" in guardado.error
    assert Path(guardado.salida_md).exists()
    assert len(list((tmp_path / "brain").glob("*.md"))) == 1   # no se convirtió dos veces


def test_prompts_para_cli_de_un_solo_disparo(tmp_path: Path):
    """Sin bandera de adjunto ni de salida JSON: la ruta va en el texto y el resultado en stdout."""
    cfg = Config(carpetas=[tmp_path], destino_md=tmp_path / "brain",
                 hermes=ConfigHermes(comando=["hermes"]))
    pdf = hm.prompt_pdf(cfg, tmp_path / "paper.pdf", "Ultrasound in CIDP", "ultrasound-cidp")
    assert str(tmp_path / "paper.pdf") in pdf          # el adjunto viaja dentro del prompt
    assert pdf.rstrip().endswith('"notion_url": "<url o cadena vacía>"}')

    md = tmp_path / "brain" / "miastenia.md"
    revision = hm.prompt_revision_docx(cfg, md, tmp_path / "x.docx", 3, 2)
    assert "ya fue convertido" in revision and "no la conversión" in revision
    assert revision.rstrip().endswith(f'{{"md": "{md}"}}')


def test_chat_sin_md_puede_ser_exito_cuando_no_se_exige(tmp_path: Path):
    """La pasada de revisión no produce un .md nuevo: no puede fallar por no devolver ruta."""
    script = _cli_falso(tmp_path, CLI_SIN_MD)
    cfg = ConfigHermes(comando=[sys.executable, str(script)], reintentos=0, timeout_s=60)
    comun = {"archivo": tmp_path / "x.md", "skill": "s", "prompt": "p",
             "destino": tmp_path / "brain", "adjuntos": tmp_path, "nombre_slug": "x"}
    assert hm.ejecutar_chat(cfg, exige_md=False, **comun).ok is True
    assert hm.ejecutar_chat(cfg, exige_md=True, **comun).ok is False


# --------------------------------------------------------------------------- diagnóstico
CLI_ONESHOT = """
import argparse, sys
p = argparse.ArgumentParser(add_help=False)
p.add_argument("-s", "--skills", action="append", default=[])
p.add_argument("-z", "--oneshot", default="")
a, _ = p.parse_known_args()
if a.skills and "inexistente" in a.skills[0]:
    print("error: unknown skill " + a.skills[0], file=sys.stderr); sys.exit(2)
if "LISTO" in a.oneshot:
    print("LISTO"); sys.exit(0)
print("respuesta")
"""


def _config_completa(tmp_path: Path, skill_pdf: str = "analisis-estudio") -> Path:
    origen = tmp_path / "papers"
    origen.mkdir()
    (origen / "algo.pdf").write_bytes(_pdf(PAPER, "T", "Ugalde C, Farina D"))
    script = tmp_path / "hermes_falso.py"
    script.write_text(CLI_ONESHOT, encoding="utf-8")
    ruta = tmp_path / "cfg.yaml"
    ruta.write_text(
        f"carpetas: ['{origen.as_posix()}']\n"
        f"destino_md: '{(tmp_path / 'brain').as_posix()}'\n"
        f"db: '{(tmp_path / 'cola.sqlite3').as_posix()}'\n"
        "hermes:\n"
        f"  comando: ['{Path(sys.executable).as_posix()}', '{script.as_posix()}',"
        " '-s', '{skill}', '-z', '{prompt}']\n"
        "  timeout_s: 60\n"
        "  reintentos: 0\n"
        f"  skill_pdf: '{skill_pdf}'\n"
        "  skill_docx: 'resumen-clinico-md'\n", encoding="utf-8")
    return ruta


def test_comprobar_sin_configuracion_dice_como_arreglarlo(tmp_path: Path):
    from hermes_brain import comprobar as comp

    d = comp.diagnosticar(str(tmp_path / "no_existe.yaml"), rapido=True)
    fallas = {c.nombre for c in d.fallas}
    assert "Configuración" in fallas
    assert "config.example.yaml" in comp.formatear(d)


def test_comprobar_entorno_completo_no_encuentra_fallas(tmp_path: Path):
    pytest.importorskip("pypdf")
    from hermes_brain import comprobar as comp

    d = comp.diagnosticar(str(_config_completa(tmp_path)), rapido=False)
    assert not d.fallas, [(c.nombre, c.detalle) for c in d.fallas]
    nombres = " ".join(c.nombre for c in d.items)
    for esperado in ("Dependencias", "Destino brain md", "Conversor", "Hermes responde",
                     "Skill PDF", "n8n"):
        assert esperado in nombres


def test_comprobar_detecta_una_skill_que_no_existe(tmp_path: Path):
    pytest.importorskip("pypdf")
    from hermes_brain import comprobar as comp

    d = comp.diagnosticar(str(_config_completa(tmp_path, skill_pdf="inexistente-xyz")))
    assert any("Skill PDF" in c.nombre for c in d.fallas), [c.nombre for c in d.items]


def test_comprobar_detecta_dependencias_faltantes(tmp_path: Path, monkeypatch):
    from hermes_brain import comprobar as comp

    monkeypatch.setattr(comp.importlib.util, "find_spec",
                        lambda nombre: None if nombre == "pypdf" else object())
    d = comp.Diagnostico()
    comp._dependencias(d, None)
    assert d.fallas and "pip install pypdf" in d.fallas[0].arreglo


def test_sustituir_descarta_la_bandera_de_un_marcador_vacio():
    """`-s ""` hace fallar al CLI: sin skill, la bandera no se pasa."""
    plantilla = ["hermes", "-s", "{skill}", "-z", "{prompt}"]
    assert hm._sustituir(plantilla, {"skill": "", "prompt": "hola"}) == ["hermes", "-z", "hola"]
    assert hm._sustituir(plantilla, {"skill": "x", "prompt": "hola"}) == \
        ["hermes", "-s", "x", "-z", "hola"]


def test_archivos_solo_en_la_nube_se_reconocen():
    """OneDrive «Archivos a petición»: hashearlos forzaría descargar la biblioteca entera."""
    class Stat:
        st_file_attributes = inv.ATTR_RECALL_DATOS | 0x20

    assert inv.solo_en_la_nube(Stat()) is True
    assert inv.solo_en_la_nube(os.stat(__file__)) is False


def test_ruta_del_conversor_no_depende_del_directorio_de_trabajo():
    from hermes_brain.config import SCRIPT_DOCX_MD, Config, ConfigHermes

    cfg = Config(carpetas=[RAIZ], destino_md=RAIZ, hermes=ConfigHermes(comando=["x"]))
    assert cfg.script_docx_md.is_absolute() and cfg.script_docx_md.exists()
    assert SCRIPT_DOCX_MD.name == "docx_a_md.py"
