---
tipo: indice
titulo: Cola de ingesta — Material del repo
aliases: ["Cola de ingesta"]
tags: [wiki/indice, ingesta]
estado: en-progreso
confianza: alta
pendientes: 2
generado: true
actualizado: 2026-08-27
---

# Cola de ingesta — Material del repo

Inventario de `projects`, generado por `python tools/wiki.py scan` el 2026-08-27.
Lo regenera el comando: no lo edites a mano. Marca `ingerido` cuando el nombre del
archivo o su DOI ya aparecen en alguna página de `fuentes/`.

**8 archivos · 2 pendientes**

| Archivo | Tipo | KB | DOI | Título detectado | Estado |
|---|---|---|---|---|---|
| `2026-06-12_dapt_acv/_estado.md` | md | 2 | — | Estado del Proyecto: DAPT en ACV & Automatización UC Library | pendiente |
| `2026-06-14_home_assistant/_estado.md` | md | 3 | — | Estado — Integración Home Assistant (subagente `home`) | pendiente |
| `2026-06-12_dapt_acv/analisis_DAPT_en_ACV/POINT_trial.pdf` | pdf | 360 | — | — | ingerido · sin pypdf utilizable: metadatos incompletos |
| `2026-06-12_dapt_acv/analisis_dapt_acv.md` | md | 8 | — | Guía Clínica Resumen: Doble Antiagregación Plaquetaria (DAPT) en ACV Isquémico y AIT | ingerido |
| `tolosa-hunt/fuentes/bibliografia.md` | md | 7 | [10.17116/oftalma2025141061114](https://doi.org/10.17116/oftalma2025141061114) | Bibliografía — Tolosa-Hunt syndrome | ingerido |
| `tolosa-hunt/fuentes/resumen_busqueda.md` | md | 2 | [10.17116/oftalma2025141061114](https://doi.org/10.17116/oftalma2025141061114) | Resumen de búsqueda — Tolosa-Hunt syndrome | ingerido |
| `tolosa-hunt/tolosa_hunt_notion.md` | md | 40 | — | 1. Definición | ingerido |
| `tolosa-hunt/tolosa_hunt_sintesis.md` | md | 36 | — | Síndrome de Tolosa-Hunt — síntesis clínica | ingerido |

## Cómo se usa esta cola

1. Toma **una** fila `pendiente` (empieza por revisiones y guías, no por casos).
2. Léela completa e ingiérela siguiendo `AGENTS.md` §4: página de fuente, propagación
   a entidades y conceptos, contradicciones registradas.
3. `python tools/wiki.py index && python tools/wiki.py log ingest "<titulo>"`.
4. Vuelve a correr el scan: la fila pasa sola a `ingerido`.
