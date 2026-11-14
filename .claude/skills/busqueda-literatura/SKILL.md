---
name: busqueda-literatura
description: Procedimiento del agente buscador - busca papers en fuentes locales (carpeta de PDFs/Word/.md, Zotero, Obsidian) y remotas (PubMed por estratos de evidencia, OpenAlex, Semantic Scholar), deduplica y entrega una selección priorizada y trazable. Úsala cuando haya que encontrar literatura sobre un tema o localizar un estudio concreto.
---

# Búsqueda de literatura

## Valores por defecto (decláralos si los aplicas sin confirmación)

| Parámetro | Defecto |
|---|---|
| Fuentes remotas | `pubmed,openalex,s2` |
| Resultados por fuente | 30 (rápida: 10 · exhaustiva: 60) |
| Años | desde 2000; desde 2015 si el tema es terapéutico y evoluciona rápido |
| Salida | `workspace/busquedas/<slug>/` (slug en kebab-case, sin acentos) |

## Paso 1 — Traducir la pregunta a una estrategia

- Identifica conceptos (PICO si es clínica) y escribe la query **en inglés**.
- Para PubMed, combina texto libre y MeSH: `("myasthenia gravis"[MeSH] OR myasthenia) AND
  (efgartigimod OR "FcRn")`.
- Si el usuario pidió un foco, pásalo con `--enfoque` (estrato PubMed propio y prioritario).
- Anota la query en `seleccion.md`: la búsqueda debe ser reproducible.

## Paso 2 — Fuentes locales primero (evita rebuscar lo que ya tienes)

```bash
python3 scripts/fuentes_locales.py carpeta "términos clave" --json
python3 scripts/fuentes_locales.py zotero "términos clave" --json
python3 scripts/fuentes_locales.py obsidian "términos clave" --json
```

Si Zotero u Obsidian no están configurados, el script lo dice: regístralo como límite y sigue.
Revisa también `workspace/busquedas/` y `workspace/resumenes_papers/` por trabajo previo.

## Paso 3 — Fuentes remotas

```bash
python3 scripts/buscar_literatura.py "<query>" --fuentes pubmed,openalex,s2 \
  --n 30 --desde 2000 --out workspace/busquedas/<slug>
```

- Para un estudio concreto (DOI/PMID/título): `--fuentes pubmed --sin-estratos --n 5` con el
  identificador o el título entre comillas como query.
- Si una fuente falla (429, sin red), el script sigue con las demás: decláralo.

## Paso 4 — Cribado y priorización

Lee `fuentes.json` y clasifica cada trabajo por título y abstract:

1. **Relevancia** para la pregunta: alta / media / baja (descarta las bajas, pero cuéntalas).
2. **Jerarquía de evidencia**: guías → revisiones sistemáticas/metaanálisis → ECA →
   cohortes/casos-controles → series → revisiones narrativas → opinión.
3. **Recencia** e impacto (`citas`) como desempate, nunca como criterio principal.

Marca qué trabajos ya están en local (Zotero/carpeta) para no descargarlos de nuevo.

## Paso 5 — Entrega

Escribe `workspace/busquedas/<slug>/seleccion.md`:

```markdown
# Selección — <tema>

Query: `<query>` · Fuentes: pubmed, openalex, s2 · Años: 2000– · Fecha: AAAA-MM-DD
Brutos: N · Únicos: N · Relevancia alta: N · En local: N · Tras paywall: N

| # | Estudio | Diseño | N | Relevancia | Acceso | Por qué |
|---|---|---|---|---|---|---|
| 1 | Autor A, 2024 (PMID 123) | ECA | 167 | alta | PMC | desenlace primario = pregunta |

## Límites
- Fuentes que fallaron, filtros aplicados, idiomas, lo que no se buscó.
```

Devuelve al orquestador ≤10 líneas: totales, top-10, DOIs tras paywall (para `acceso-uc`) y
límites. Nunca inventes PMID/DOI: solo lo que devolvieron las fuentes.
