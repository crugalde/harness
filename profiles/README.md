# profiles/ — Personas de runtime (Hermes local)

Un **perfil** es la persona con la que arranca un runtime concreto. A diferencia de
`AGENTS.md` (contrato agnóstico, lo lee cualquier runtime) y de `agents/<id>/AGENTS.md`
(subagentes del harness), un `SOUL.md` es el **system prompt que se hornea en un perfil de
Hermes** y viaja con él.

## `cientifico/SOUL.md`

Perfil de Hermes en la máquina local de Cristian:
`C:\Users\Usuario\AppData\Local\hermes\profiles\cientifico\SOUL.md`
Motor: `gpt-oss-hermes:latest` (ollama-launch) · pool de 35 skills vía `skills-hub`.

Es la contraparte local de la política de modelos del harness (`AGENTS.md` §11 +
`tools/model_policy.py`). La diferencia está en el grado de libertad disponible:

| | Harness (`tools/loop.py`) | Perfil Hermes (`SOUL.md`) |
|---|---|---|
| Motor | el router elige por clase de tarea (local / Haiku / Sonnet 5 / Opus 5) | **fijo** por perfil: el modelo local |
| Qué se optimiza | qué API se llama | **cuánto esfuerzo gasta cada tarea** y cuándo escalar a online |
| Escalada al tier caro | automática bajo el techo de costo | recomendación + confirmación humana (R9) |
| Selección de skill | `tools/skill_selector.py` rankea `skills/*/SKILL.md` | `skill_search` → `skill_load` sobre el hub |

Lo que **sí** es idéntico en ambos, porque es la decisión de fondo y no depende del runtime:
**fichar un artículo es trabajo barato que se repite N veces; juzgar el conjunto es una sola
pasada y es donde se paga capacidad.** Pagar el tier caro por artículo multiplica el costo sin
mejorar la ficha; pagar el barato en la síntesis final abarata lo único que no conviene
abaratar. En el harness eso es Sonnet 5 → Opus 5; aquí es local → escalada gated.

## Mantención

Este archivo es la **copia versionada**, no la que corre. Al editarlo hay que volver a
guardarlo en la ruta de Hermes (o pegarlo en el editor de perfiles). Si lo cambias allá
primero, tráelo de vuelta acá: si las dos copias divergen en silencio, la versionada deja de
servir para auditar por qué el agente se comportó como se comportó.

Dos cosas que dependen de la instalación y hay que revisar al portarlo a otra máquina o perfil:
la **ruta de escalada online** (§1, tabla de tiers) y los **namespaces del hub** (§2), que si
cambian hacen que el modelo componga ids inválidos.
