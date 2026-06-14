---
name: build_pptx
description: Construye una presentación (.pptx) a partir de un título y slides {title, bullets}. Úsala para materializar decks.
---

# Build PPTX

## Cuándo usar
Cuando `docs` necesita materializar un esquema de presentación ya definido en un PPTX. Una idea
por slide, viñetas concisas; no genera contenido, lo estructura.

## Entradas / salidas
- Entrada: `title`, `slides` (lista de `{title, bullets:[...]}`), `out` (ruta destino).
- Salida: ruta del `.pptx` creado.

## Herramienta
Registra `build_pptx` (ver `tool.py`). Dependencia: python-pptx (import perezoso).

## Notas de seguridad
Slide de fuentes al final; sin PHI ni datos sensibles (R8). Escritura aprobada en Gate 2.
