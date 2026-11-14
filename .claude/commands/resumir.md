---
description: Resume un estudio (PDF, Word o .md, o un DOI/PMID) con la plantilla fija de 6 secciones
argument-hint: <ruta del archivo | DOI | PMID> [pdf] [obsidian]
---

Actúa como el orquestador definido en `AGENTS.md`. Tarea: **resumir el estudio**:

$ARGUMENTS

1. Si recibo varios archivos, delega un `resumidor` por estudio, en paralelo.
2. Si el estudio está tras paywall, pídeme confirmación antes de usar `acceso-uc`.
3. Devuélveme por estudio: diseño, N, resultado principal con su métrica, la limitación más
   importante y la ruta del resumen en `workspace/resumenes_papers/`.
4. Si pedí `pdf`, expórtalo; si pedí `obsidian`, guárdalo en la bóveda (pide confirmación si
   la nota ya existe).
