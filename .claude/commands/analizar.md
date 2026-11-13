---
description: Integra los hallazgos de varios estudios en un documento .md/PDF con matriz comparativa y esquema Mermaid
argument-hint: <pregunta o tema> <rutas de resúmenes, carpeta o búsqueda> [pdf] [esquema]
---

Actúa como el orquestador definido en `AGENTS.md`. Tarea: **análisis integrado**:

$ARGUMENTS

1. Presenta el alcance (Gate 1): pregunta que guía el análisis, estudios a incluir, nivel de
   lectura (resúmenes / texto completo / mixto) y formato de salida. Espera mi aprobación.
2. Para los estudios sin resumen en `workspace/resumenes_papers/`, delega primero en
   `resumidor` (en paralelo).
3. Delega en `integrador` con la lista final de entradas y la salida
   `workspace/analisis_globales/<slug>.md`.
4. Entrégame la conclusión global, su certeza y las rutas (.md, y .pdf/SVG si los pedí).
