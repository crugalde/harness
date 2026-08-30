# Destino en Notion — «Resumen de estudios»

El destino de esta skill es **fijo**. No se busca, no se pregunta, no se elige padre.

```
Weekly Plan
└── 📚 Biblioteca de Investigación
    ├── Resumen de estudios          ← aquí publica la ficha
    ├── Actualización de estudio     ← aquí se escribe el enlace de vuelta
    └── Papers de Investigación
```

## Identificadores

| Qué | Id | Dónde se usa |
|---|---|---|
| Base «Resumen de estudios» | `19f24c9a-7dc8-4fee-93df-0d940f21f84d` | `parent.database_id` en la API REST |
| Data source de esa base | `075ef50d-5a72-4feb-9a8e-4a7cec98d1b8` | `parent.data_source_id` en `notion-create-pages` |
| Base «Actualización de estudio» | `615808d0-0fbb-4b89-92b4-5b8ae4e96fca` | back-link en `Link de análisis` |
| Página 📚 Biblioteca de Investigación | `33a95efc-cd59-818b-bf43-fd12e83b8f49` | contexto; no se escribe en ella |

Están cableados en `publicar_notion.py` y se pueden sobreescribir por entorno
(`NOTION_DB_RESUMEN`, `NOTION_DS_RESUMEN`, `NOTION_DB_ACTUALIZACION`) para probar contra una
copia sin tocar la base real. **La copia de prueba es la forma correcta de probar cambios**: no
publiques borradores en la base buena para verlos y luego archivarlos.

> La API REST quiere `database_id`; el conector MCP quiere `data_source_id`. Son cosas distintas
> y no son intercambiables: pasar uno donde va el otro devuelve un 400 que no dice por qué.

## Propiedades y de dónde sale cada una

| Propiedad | Tipo | Origen |
|---|---|---|
| `Título` | title | `metadatos.json` ← PubMed |
| `Autor` | text | `metadatos.json` ← PubMed (primer autor + `et al.`) |
| `Año` | number | `metadatos.json` ← PubMed |
| `Revista` | text | `metadatos.json` ← abreviatura NLM |
| `Paper` | url | DOI (`https://doi.org/…`) o, sin DOI, PubMed |
| `Tipo de estudio` | select | derivado de PublicationType, **confirmado contra el texto** |
| `Patología` | select | del paper o **preguntado al usuario**. Nunca inferido |
| `Área` | select | del paper |
| `Aspecto` | select | del paper o **preguntado al usuario** |
| `Calidad` | select | del análisis, tras aplicar la guía de reporte |
| `Aporte` | text | del análisis: una línea, qué cambia |
| `Archivo` | url | ruta `file://` al PDF local |
| `PDF` | file | subido por el script (tope 20 MB en una parte) |

## Vocabularios cerrados

`publicar_notion.py` valida contra el esquema **vivo** de la base, no contra una copia. Si se
añade una opción hoy, se acepta hoy. Esta lista es de referencia, para saber si hace falta crear
una opción antes de publicar.

- **Tipo de estudio** — Revisión sistemática · Metaanálisis · Ensayo clínico aleatorizado ·
  Ensayo clínico no aleatorizado · Cohorte · Casos y controles · Transversal · Precisión
  diagnóstica · Reporte de caso · Serie de casos · Evaluación económica · Investigación
  cualitativa · Revisión narrativa · Guía de práctica clínica · Estudio preclínico o básico
- **Calidad** — Alta · Moderada · Baja · Críticamente baja
- **Área** — Vascular · Epilepsia · Cognitivo · Neuromuscular · Neuroinmunología ·
  Neurodegenerativo · Otra
- **Aspecto** — Clínica · Diagnóstico · Epidemiología · Tratamiento · General
- **Patología** — vocabulario largo (neuromuscular, vascular, epilepsia, cognitivo,
  neuroinmunología, `Atrofia multisistémica`, `Transversal / no aplica`…). Es el que más se
  queda corto. Si el estudio no encaja en ninguna, **añade la opción a la base antes de
  publicar**; no la aproximes a la más parecida ni uses `Transversal / no aplica` como cajón de
  sastre — eso vacía de sentido el filtro por patología, que es para lo que existe la base.

## El circuito con «Actualización de estudio»

La vigilancia semanal deja filas ahí con `Seleccionado para descarga` marcado. Cuando esta skill
termina la ficha, escribe su URL en `Link de análisis` de la fila que calce por DOI. Así el
paper marcado el lunes queda con su análisis enlazado, sin buscarlo a mano.

Si el back-link falla —la fila no existe, o el DOI no calza— **la publicación no se revierte**:
la ficha ya está y el enlace es accesorio. El script lo avisa por `stderr` y sigue.
