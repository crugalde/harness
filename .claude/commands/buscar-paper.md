---
description: Busca papers sobre un tema en PubMed, OpenAlex, Semantic Scholar y fuentes locales (carpeta, Zotero, Obsidian)
argument-hint: <tema, pregunta, DOI o PMID> [desde AAAA] [n N]
---

Actúa como el orquestador definido en `AGENTS.md`. Tarea: **búsqueda de literatura** sobre:

$ARGUMENTS

1. Si el pedido implica más de 15 fuentes o una revisión, presenta el alcance (Gate 1:
   query en inglés, fuentes, n, años, salida) y espera mi aprobación.
2. Delega en el subagente `buscador` con el tema, los filtros y la salida
   `workspace/busquedas/<slug>/`.
3. Muéstrame la tabla priorizada de `seleccion.md` (Gate 2) y pregúntame qué estudios resumir
   o si paso directo a responder o integrar.
