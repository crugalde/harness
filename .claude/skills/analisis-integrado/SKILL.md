---
name: analisis-integrado
description: Procedimiento del agente integrador - analiza los hallazgos de varios estudios (desde resúmenes o texto completo según lo que pida la pregunta) y produce un documento .md o PDF con matriz comparativa, convergencias, divergencias explicadas, certeza, detalles a considerar, vacíos y un esquema Mermaid integrador. Úsala para comparar, sintetizar o integrar evidencia de 2 o más estudios.
---

# Análisis integrado de varios estudios

Plantilla: `plantilla.md` (en esta carpeta). Salida: `workspace/analisis_globales/<slug>.md`
(+ `.pdf` y esquemas SVG si se piden).

## Paso 1 — Inventario y nivel de lectura

- Lista las entradas: resúmenes en `workspace/resumenes_papers/` y archivos de texto completo.
  Los estudios sin resumen se devuelven al orquestador para el `resumidor` (no los resumas tú
  a medias).
- Decide el **nivel de lectura** y decláralo en `nivel_lectura`:
  - *resúmenes* — basta para panoramas y comparaciones de diseño/resultado principal;
  - *texto completo* — necesario si la pregunta toca subgrupos, dosis, seguridad,
    definiciones de desenlace o detalles metodológicos
    (`python3 scripts/extraer_texto.py <archivo>`);
  - *mixto* — resúmenes + texto completo para los estudios clave.

## Paso 2 — Matriz comparativa (antes de redactar)

Una fila por estudio: diseño, N, población, intervención/exposición, comparador, desenlace
principal, resultado clave (efecto con IC 95 %), seguimiento y riesgo de sesgo
(bajo / algunas dudas / alto). Las conclusiones salen de la matriz, no de la memoria.

## Paso 3 — Síntesis

- **Convergentes:** hallazgos sostenidos por ≥2 estudios, con sus citas `[n]`.
- **Divergencias:** cada una con su explicación probable (población, dosis, diseño, desenlace,
  seguimiento, riesgo de sesgo) o "sin explicación clara".
- **Certeza por desenlace:** alta / moderada / baja / muy baja, con la razón.
- **Detalles a considerar:** aplicabilidad (población, contexto chileno, disponibilidad),
  seguridad, costos si constan, matices que cambian la interpretación.
- **Vacíos y próximos pasos:** qué no se sabe y qué estudio o búsqueda lo resolvería.
- **Sin metaanálisis implícito:** no promedies efectos entre estudios.

## Paso 4 — Esquema integrador (Mermaid)

Elige el tipo según el mensaje:

| Mensaje | Tipo |
|---|---|
| Cadena evidencia → conclusión | `flowchart TD` |
| Mapa de subtemas | `mindmap` |
| Evolución temporal de la evidencia | `timeline` |

Reglas de sintaxis (las comprueba `verificar.py`): etiquetas con paréntesis, comas o dos
puntos **entre comillas** (`A["MG-ADL: −2,1 (IC −2,9 a −1,3)"]`), sin `<br>`, un diagrama
legible (≤15 nodos).

## Paso 5 — Verificar, exportar y entregar

```bash
python3 scripts/verificar.py workspace/analisis_globales/<slug>.md --tipo analisis
python3 scripts/exportar.py workspace/analisis_globales/<slug>.md \
  --pdf workspace/analisis_globales/<slug>.pdf \
  --esquemas workspace/analisis_globales/<slug>_esquemas
```

El PDF y los SVG solo si se pidieron. Devuelve al orquestador la conclusión global (3–5
líneas), la certeza y las rutas.
