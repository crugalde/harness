---
description: Responde una pregunta científica con evidencia de PubMed, OpenAlex y Semantic Scholar, con citas y certeza explícita
argument-hint: <pregunta>
---

Actúa como el orquestador definido en `AGENTS.md`. Tarea: **responder la pregunta científica**:

$ARGUMENTS

1. Si la pregunta es ambigua (población, intervención o desenlace no claros), hazme una sola
   tanda de preguntas antes de delegar.
2. Delega en el subagente `consultor`. Si devuelve pendientes de texto completo, propón qué
   estudios resumir con el `resumidor` y espera mi OK.
3. Entrégame la respuesta (3–5 líneas), la certeza, los límites y la ruta del archivo en
   `workspace/respuestas/`.
