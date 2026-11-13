---
name: respuesta-cientifica
description: Procedimiento del agente consultor - responde una pregunta científica o clínica con evidencia de PubMed, OpenAlex y Semantic Scholar, citas [n] verificables y certeza explícita en cuatro niveles. Úsala para preguntas del tipo "¿qué dice la evidencia sobre…?", "¿sirve X para Y?", "¿cuál es el rendimiento diagnóstico de…?".
---

# Respuesta científica

Plantilla: `plantilla.md` (en esta carpeta). Salida: `workspace/respuestas/<slug>.md`.

## Paso 1 — Encuadre

- Reescribe la pregunta en **PICO** (Población, Intervención/exposición, Comparador,
  Desenlace) y clasifícala: terapia, diagnóstico, pronóstico, etiología/riesgo o mecanismo.
- El tipo decide qué diseños pesan: terapia → revisiones sistemáticas de ECA y ECA;
  diagnóstico → estudios de exactitud con estándar de referencia; pronóstico → cohortes.

## Paso 2 — Evidencia

1. Busca trabajo previo en `workspace/busquedas/` y `workspace/respuestas/`.
2. Si no hay, ejecuta:
   ```bash
   python3 scripts/buscar_literatura.py "<query PICO en inglés>" --n 20 \
     --out workspace/busquedas/<slug>
   ```
3. Lee los abstracts de los trabajos más relevantes (prioriza por diseño, no por número).
4. Si la respuesta depende de un dato que los abstracts no traen (subgrupo, dosis, evento
   adverso, definición del desenlace), **no lo supongas**: márcalo como pendiente de texto
   completo para que el orquestador lo pida al `resumidor`.

## Paso 3 — Redacción (plantilla)

- **1. Respuesta:** 2–5 líneas que contestan la pregunta tal como se hizo, con la magnitud del
  efecto cuando exista (p. ej. "reduce el MG-ADL en ~2 puntos frente a placebo [1]").
- **2. Evidencia:** los estudios clave, del más al menos sólido, cada uno con diseño, N y
  resultado con su métrica `[n]`.
- **3. Certeza:** alta / moderada / baja / muy baja, y por qué (riesgo de sesgo,
  inconsistencia, evidencia indirecta, imprecisión, sesgo de publicación).
- **4. Lo no encontrado:** qué no responde la evidencia, qué estudio lo resolvería, fuentes
  que fallaron o no se consultaron.
- **Referencias:** Vancouver numeradas con PMID/DOI, tomadas de `fuentes.json`.

Datos volátiles (aprobación regulatoria, disponibilidad en Chile, guía vigente): verifícalos
con una búsqueda reciente o márcalos "no verificado a la fecha".

## Paso 4 — Verificación

```bash
python3 scripts/verificar.py workspace/respuestas/<slug>.md --tipo respuesta \
  --fuentes workspace/busquedas/<slug>/fuentes.json
```

0 fallos antes de entregar. Devuelve al orquestador la respuesta en 3–5 líneas, la certeza y
la ruta.
