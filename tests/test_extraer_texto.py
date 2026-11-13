"""Extracción de texto y metadatos desde PDF, DOCX y MD."""

from __future__ import annotations

import docx
import extraer_texto as et
import pytest
from conftest import pdf_minimo


def test_pdf_con_marcas_de_pagina_y_doi(tmp_path):
    ruta = tmp_path / "estudio.pdf"
    ruta.write_bytes(
        pdf_minimo(["Efgartigimod trial doi 10.1234/abcd.5678 published 2021", "Results page two"])
    )
    doc = et.extraer(ruta)
    assert doc.paginas == 2
    assert "[p. 1]" in doc.texto and "[p. 2]" in doc.texto
    assert doc.doi == "10.1234/abcd.5678"
    assert doc.anio == "2021"
    # Muy poco texto por página: debe advertir posible escaneo.
    assert any("escaneado" in a for a in doc.advertencias)


def test_docx_con_tabla(tmp_path):
    ruta = tmp_path / "estudio.docx"
    d = docx.Document()
    d.core_properties.title = "Ensayo de prueba en miastenia"
    d.add_paragraph("PMID: 12345678. Resultados principales.")
    tabla = d.add_table(rows=1, cols=2)
    tabla.rows[0].cells[0].text = "MG-ADL"
    tabla.rows[0].cells[1].text = "-2.1"
    d.save(ruta)
    doc = et.extraer(ruta)
    assert doc.titulo == "Ensayo de prueba en miastenia"
    assert doc.pmid == "12345678"
    assert "MG-ADL | -2.1" in doc.texto


def test_md_titulo_plausible_y_sin_identificadores(tmp_path):
    ruta = tmp_path / "nota.md"
    ruta.write_text("# Un título suficientemente largo para ser título\n\nTexto.", encoding="utf-8")
    doc = et.extraer(ruta)
    assert doc.titulo == "Un título suficientemente largo para ser título"
    assert any("DOI ni PMID" in a for a in doc.advertencias)


def test_formato_no_soportado_y_archivo_inexistente(tmp_path):
    (tmp_path / "x.xlsx").write_text("x")
    with pytest.raises(RuntimeError, match="no soportado"):
        et.extraer(tmp_path / "x.xlsx")
    with pytest.raises(RuntimeError, match="No existe"):
        et.extraer(tmp_path / "nada.pdf")


def test_cli_escribe_markdown_con_frontmatter(tmp_path, capsys):
    origen = tmp_path / "a.md"
    origen.write_text("Contenido del estudio con doi 10.5555/xyz123 aquí.", encoding="utf-8")
    destino = tmp_path / "out" / "a_extraido.md"
    assert et.main([str(origen), "--out", str(destino)]) == 0
    texto = destino.read_text(encoding="utf-8")
    assert texto.startswith("---\n") and 'doi: "10.5555/xyz123"' in texto
    assert et.main([str(tmp_path / "no.pdf")]) == 1
