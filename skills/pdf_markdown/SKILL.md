---
name: pdf_markdown
description: "Convierte un PDF a Markdown y extrae sus imágenes: respeta el orden de lectura en documentos a dos columnas, pasa las tablas a tablas Markdown, guarda los rasters incrustados y rasteriza las figuras vectoriales (las de cualquier paper de revista) dejándolas referenciadas en su página. Úsala cuando se pida convertir, pasar o transformar un PDF a Markdown o a texto, sacar las figuras o imágenes de un PDF, extraer sus tablas, o preparar un artículo para leerlo, pegarlo en Notion o dárselo a otra skill. También cuando un PDF se lea revuelto o entrelazado, o cuando 'no aparecen las figuras'."
---

# pdf_markdown

Convierte un PDF a Markdown con sus imágenes. El motor está en `tools/pdf_a_markdown.py`;
esta skill es el contrato de cuándo y cómo invocarlo.

## Cuándo usar

- "Pásame este PDF a Markdown" · "sácale las figuras a este paper" · "extrae las tablas"
- Antes de mandar un artículo a Notion, a un `.docx`, o a otra skill que trabaje sobre texto.
- Cuando un PDF **se lee revuelto**: es el síntoma de un documento a dos columnas leído de
  corrido.

**No la uses** para leer un PDF escaneado (imagen sin capa de texto): eso necesita OCR, y esta
skill devolverá una extracción vacía y lo dirá. Tampoco para *analizar* el contenido — eso es
`paper_review`, que puede tomar esta salida como entrada.

## Dos mecanismos distintos para las imágenes

No es lo mismo extraer que rasterizar, y confundirlos es la causa de "no aparecen las figuras":

| Tipo | Cómo se obtiene | Cuándo aplica |
|---|---|---|
| Raster incrustado | `pypdf` lo saca tal cual | fotos, capturas, escaneos |
| Figura vectorial | se detecta la región de dibujo y se **rasteriza** a 200 dpi | gráficos de revista |

Un paper del NEJM tiene **cero** rasters incrustados: sus figuras son curvas y rectángulos.
Sin rasterizado, la conversión "termina bien" y sin ninguna imagen.

## Entradas / salidas

- **Entrada:** `pdf` (ruta), `out` (carpeta destino), opcionales `columnas`
  (`auto`|`1`|`2`), `dpi` (200), `figuras` (true).
- **Salida:** `<nombre>.md` + carpeta `imagenes/`. Cada figura queda referenciada con
  `![...](imagenes/pNN_figuraNN.png)` **en la página donde está**, no amontonada al final.

## Herramienta

Registra `pdf_a_markdown` (ver `tool.py`). Dependencias con import perezoso: `pdfplumber`
(texto y tablas), `pypdf` (rasters), `pypdfium2` (rasterizado de figuras). Sin `pypdfium2` la
conversión sigue, avisa, y no produce figuras vectoriales.

```bash
python tools/pdf_a_markdown.py paper.pdf --out revision/ --dpi 300
python tools/pdf_a_markdown.py paper.pdf --out revision/ --columnas 2   # forzar 2 columnas
```

## Notas de seguridad

- La salida es texto plano del documento: si el PDF trae datos de paciente, el `.md`
  **también los trae**. De-identifica antes de mandarlo a cualquier servicio externo (R8).
  `tools/paper_review.py` lo hace en su etapa 3; esta skill no.
- Solo lee el PDF y escribe en la carpeta que se le indique. No toca el original.
