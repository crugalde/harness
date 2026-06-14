---
name: build_docx
description: Construye un documento Word (.docx) a partir de un título y secciones {heading, body}. Úsala para materializar informes y memos.
---

# Build DOCX

## Cuándo usar
Cuando `docs` (o cualquier agente) necesita materializar contenido ya redactado en un Word.
No genera contenido: solo lo estructura y escribe el archivo.

## Entradas / salidas
- Entrada: `title`, `sections` (lista de `{heading, body}`), `out` (ruta destino).
- Salida: ruta del `.docx` creado.

## Herramienta
Registra `build_docx` (ver `tool.py`). Dependencia: python-docx (import perezoso).

## Notas de seguridad
Sin PHI ni cifras internas sensibles en documentos de distribución amplia (R8). La escritura de
archivo es un entregable explícito, aprobado en Gate 2.
