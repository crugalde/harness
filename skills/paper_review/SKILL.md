---
name: paper_review
description: "Analiza científicamente varios papers (PDF/DOCX) de una carpeta: ficha cada uno (diseño, n, población, hallazgo, limitaciones), los contrasta con PubMed para establecer qué aporta cada trabajo frente a lo ya publicado, y produce una lectura transversal a nivel de neurólogo académico. Entrega revision.md pegable en Notion y revision.json estructurado por paper. Úsala cuando se pida analizar, comparar, criticar o sintetizar varios artículos, evaluar el aporte de un paper frente a la literatura, hacer un estado del arte a partir de archivos propios, o preparar la discusión de un manuscrito. También cuando se mencionen 'estos papers', 'esta carpeta de PDFs', 'qué aporta este trabajo' o 'compáralo con la literatura'."
---

# paper_review

Análisis científico multi-paper con **un modelo distinto por etapa**. El pipeline vive en
`tools/paper_review.py`; esta skill es el contrato de cuándo y cómo invocarlo.

## Cuándo usar

- "Analiza estos papers y dime qué aportan" · "compara esta carpeta con la literatura"
- "¿Qué agrega este trabajo a lo ya publicado?" · "arma la discusión del manuscrito"
- "Estado del arte a partir de los PDFs que tengo en X"
- Cualquier tarea donde el material de entrada son **archivos propios** (no una búsqueda) y
  el entregable es un juicio crítico, no un resumen.

**No la uses** para: resumir *un* tema desde cero sin archivos (eso es `medicalinfosummary`),
buscar papers que aún no tienes (`pubmed_search`), o bajar un PDF con paywall
(`uc_library_fetcher`). Encadena: `uc_library_fetcher` → `paper_review` → `build_docx`.

## Política de modelo (por qué esta skill no usa un solo motor)

| Etapa | Trabajo | Tier | Razón |
|---|---|---|---|
| Extraer texto | pypdf / python-docx | ninguno | es E/S, no inferencia |
| De-identificar | regex PHI | ninguno | R8, antes de cualquier salida externa |
| Fichar cada paper | N llamadas | `synthesis` → Sonnet 5 | mejor capacidad/velocidad por documento; el costo se multiplica por N |
| Contrastar con PubMed | tool + 1 llamada/paper | `synthesis` → Sonnet 5 | juicio acotado sobre material ya extraído |
| Lectura transversal | 1 llamada | `deep_analysis` → Opus 5 | es donde se gana el análisis, y se paga una sola vez |

El tier lo resuelve `tools/model_policy.py` y se **declara antes de ejecutar**. El techo de
costo (`HARNESS_COST_CEILING`, `HARNESS_SESSION_COST_CEILING`) corta si la corrida se dispara.

## Entradas / salidas

- **Entrada:** `dir` (carpeta con PDF/DOCX/MD), `tema` (la pregunta de la revisión),
  `out` (carpeta destino), opcionales `max_papers`, `use_pubmed`, `dry_run`.
- **Salida:**
  - `revision.md` — tabla comparativa + síntesis + ficha por artículo + incidencias. Pegable
    en Notion tal cual.
  - `revision.json` — `{tema, modelos, costo_usd_estimado, papers:[{ficha, aporte,
    pmids_relacionados, confianza, errores}], sintesis_md}`. Encadenable a `build_docx`.

## Herramienta

Registra `paper_review` (ver `tool.py`). Dependencias con import perezoso: `pypdf`,
`python-docx`, `biopython`.

Para inspeccionar sin gastar un token — útil para verificar la extracción de un PDF escaneado
o revisar qué se de-identificó:

```bash
python tools/paper_review.py --dir ~/papers --dry-run
```

## Notas de seguridad

- **R8:** la de-identificación corre **antes** de la primera llamada al modelo, no después.
  El conteo de redacciones queda en cada registro. Un PDF con PHI que no matchea los patrones
  sigue siendo tu responsabilidad: revisa el `--dry-run` antes de mandar material clínico.
- **R2:** los PMIDs se filtran contra lo que devolvió la tool en esa corrida. Un PMID que el
  modelo escriba y la tool no haya devuelto se descarta antes de llegar al informe.
- **R12:** truncados, extracciones vacías (PDF escaneado sin OCR) y fallos de parseo van a
  `errores` e `Incidencias`, no se silencian.
