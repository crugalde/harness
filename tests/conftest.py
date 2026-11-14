"""Utilidades compartidas por los tests (todos corren sin red)."""

from __future__ import annotations

from pathlib import Path

import pytest


def pdf_minimo(paginas: list[str]) -> bytes:
    """PDF válido de texto plano (Helvetica), una página por cadena. Sin dependencias."""
    n = len(paginas)
    fuente = 3 + 2 * n
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(n))
    objetos = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode(),
    ]
    for i, texto in enumerate(paginas):
        objetos.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {4 + 2 * i} 0 R "
                f"/Resources << /Font << /F1 {fuente} 0 R >> >> >>"
            ).encode()
        )
        flujo = f"BT /F1 11 Tf 72 720 Td ({texto}) Tj ET".encode()
        objetos.append(b"<< /Length %d >>\nstream\n" % len(flujo) + flujo + b"\nendstream")
    objetos.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    salida, offsets = b"%PDF-1.4\n", []
    for i, obj in enumerate(objetos, 1):
        offsets.append(len(salida))
        salida += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(salida)
    salida += f"xref\n0 {len(objetos) + 1}\n0000000000 65535 f \n".encode()
    salida += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    salida += (
        f"trailer\n<< /Size {len(objetos) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    ).encode()
    return salida


@pytest.fixture
def raiz() -> Path:
    return Path(__file__).resolve().parent.parent
