---
name: resumen-estudio
description: Procedimiento del agente resumidor - resume un estudio individual desde PDF, Word (.docx) o .md con plantilla fija (título, autores, año, resumen estructurado con tipo de estudio, población, objetivo, método, resultados y conclusiones, al menos 2 aspectos positivos y 2 negativos, aporte global al tema, hallazgos destacados con página). Úsala cuando haya que resumir o evaluar críticamente un paper concreto.
---

# Resumen de un estudio

Plantilla: `plantilla.md` (en esta carpeta).
Salida: `workspace/resumenes_papers/<primer-autor>-<año>-<slug>.md`.

## Paso 1 — Obtener el texto

```bash
python3 scripts/extraer_texto.py <archivo.pdf|.docx|.md> --out memory/agent_handoffs/<slug>.md
```

- Lee las advertencias: **PDF escaneado** → detente y devuélvelo como pendiente (requiere
  OCR); **sin DOI/PMID** → confirma la identidad del estudio por título y autores.
- Si solo hay DOI/PMID: busca el PDF en `workspace/papers_locales/` y en Zotero
  (`scripts/fuentes_locales.py zotero`); si es acceso abierto, descárgalo de la URL de
  `buscar_literatura.py`; si está tras paywall, devuélvelo como pendiente para `acceso-uc`.
- Si al final solo dispones del abstract, resume igual pero con
  `texto_analizado: "solo abstract"` y dilo en la sección 6.

## Paso 2 — Lectura crítica según el diseño

| Diseño | Qué mirar (marco) |
|---|---|
| Ensayo clínico | aleatorización, ocultamiento, cegamiento, ITT, pérdidas, desenlace primario preespecificado (CONSORT) |
| Cohorte / casos y controles | sesgo de selección, confusión y su ajuste, medición de exposición, seguimiento (STROBE) |
| Revisión sistemática | protocolo, búsqueda, riesgo de sesgo de los incluidos, heterogeneidad, sesgo de publicación (PRISMA) |
| Exactitud diagnóstica | espectro de pacientes, estándar de referencia, cegamiento de la lectura (STARD) |
| Serie / reporte de casos | selección, generalizabilidad; nivel de evidencia bajo por diseño |

## Paso 3 — Llenar la plantilla

- **Frontmatter:** título exacto, autores (primeros 3 + et al.), año, revista, DOI, PMID si
  existe, tipo de estudio, fuente (ruta o ID de Zotero), `texto_analizado` (completo / solo
  abstract) y fecha.
- **1. Resumen estructurado:** los 6 campos. En *Resultados*, primero el desenlace primario,
  con la cifra exacta del texto (efecto, IC 95 %, p) y su página.
- **2 y 3. Aspectos positivos / negativos:** ≥2 cada uno, **específicos** de este estudio y
  anclados en el Paso 2. Son tu evaluación, no la de los autores.
- **4. Aporte global al tema:** qué cambia o confirma respecto de la evidencia previa. Si no
  puedes situarlo sin buscar más, dilo.
- **5. Hallazgos destacados declarados:** lo que los **autores** afirman como principal, en
  cita textual corta o paráfrasis fiel, con `(p. N)`.
- **6. Trazabilidad y límites:** secciones no disponibles, cifras no encontradas, supuestos.

Nunca redondees ni recalcules cifras sin decirlo. No completes un campo con plausibilidad: si
el estudio no lo reporta, escribe "no reportado".

## Paso 4 — Verificar y entregar

```bash
python3 scripts/verificar.py workspace/resumenes_papers/<archivo>.md --tipo resumen
```

0 fallos. Opcional, si lo pide el usuario:

- PDF: `python3 scripts/exportar.py <archivo>.md --pdf <archivo>.pdf`
- Obsidian (Gate de acción si ya existe la nota):
  `python3 scripts/fuentes_locales.py guardar-obsidian <archivo>.md`

Devuelve al orquestador: diseño, N, resultado principal con métrica, limitación principal y
ruta.
