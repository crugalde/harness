"""Exportación: HTML siempre; PDF solo si hay un Chromium utilizable en el entorno."""

from __future__ import annotations

import os
from pathlib import Path

import exportar as ex
import pytest

MD = """---
titulo: "Análisis de prueba"
tags: [analisis]
---

# Análisis

| A | B |
|---|---|
| 1 | 2 |

```mermaid
flowchart TD
    A["x"] --> B["y"]
```
"""


def test_md_a_html_tabla_mermaid_y_meta():
    html, n = ex.md_a_html(MD, "prueba")
    assert n == 1
    assert "<table>" in html and '<pre class="mermaid">' in html
    assert "MERMAIDBLOQUE" not in html
    assert "Análisis de prueba" in html and "mermaid@11.4.1" in html
    assert "&gt;" in html  # el código del diagrama va escapado


def test_md_sin_diagramas_no_carga_mermaid():
    html, n = ex.md_a_html("# Hola\n\nTexto.", "x")
    assert n == 0 and "mermaid.min.js" not in html and "mermaid.run" not in html


def test_cli_html(tmp_path):
    origen = tmp_path / "a.md"
    origen.write_text(MD, encoding="utf-8")
    assert ex.main([str(origen), "--html", str(tmp_path / "a.html")]) == 0
    assert (tmp_path / "a.html").read_text(encoding="utf-8").startswith("<!doctype html>")


def _chromium() -> str | None:
    candidatos = [
        os.environ.get("CHROMIUM_PATH"),
        "/opt/pw-browsers/chromium-1243/chrome-linux64/chrome",
    ]
    return next((c for c in candidatos if c and Path(c).exists()), None)


@pytest.mark.skipif(_chromium() is None, reason="sin Chromium disponible")
def test_pdf_real_sin_red(tmp_path, monkeypatch):
    """Sin red, mermaid.js no carga: el PDF debe generarse igual (degradación con aviso)."""
    pytest.importorskip("playwright")
    monkeypatch.setenv("CHROMIUM_PATH", _chromium())
    origen = tmp_path / "a.md"
    origen.write_text(MD, encoding="utf-8")
    pdf = tmp_path / "a.pdf"
    assert ex.main([str(origen), "--pdf", str(pdf)]) == 0
    assert pdf.read_bytes()[:5] == b"%PDF-"
