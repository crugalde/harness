# Harness — orquestador + subagentes con autoaprendizaje gobernado

Harness de ingeniería de agentes: un orquestador (científico, crítico, creativo) que enruta a
cinco subagentes con voz y dominio propios, todos con un ciclo de auto-modificación **gated** y
journals separados. Agnóstico al runtime (estándar `AGENTS.md`).

## Mapa de archivos

```
AGENTS.md                     # orquestador (política raíz: R1–R13, gates, seguridad, §10)
agents/<id>/AGENTS.md         # med · research · biz · signals · coach · docs · home (heredan de la raíz)
agents/<id>/learning/         # journal + propuestas + changelog por subagente (separados)
tools/loop.py                 # runtime: contexto jerárquico + router + guardas + ciclo de tools
tools/model_policy.py         # política de modelos: clase de tarea -> tier + techo de costo
tools/backends.py             # ejecución multi-modelo (Claude API + motor local OpenAI-compat)
tools/skill_selector.py       # selección autónoma de skill desde el pool
tools/paper_review.py         # análisis científico multi-paper (PDF/DOCX -> revision.md/.json)
tools/self_improve.py         # ciclo de autoaprendizaje (capturar→destilar→proponer→aplicar)
tools/tracing.py              # observabilidad: JSONL por día (tools, tokens, costo, latencia)
tools/registry.py             # ensambla el ToolRegistry (auto-descubre skills + MCP)
tools/compose.py              # motor de `docs`: integra subagentes → .docx/.pptx
tools/read_emg.py             # de-identificación de estudios EMG (med)
tools/decompose.py            # pipeline HD-sEMG (signals)
tools/ha_setup.py             # wizard de conexión/diagnóstico de Home Assistant (home)
tools/schedule_distill.py     # disparador periódico del autoaprendizaje (cron)
skills/<nombre>/SKILL.md+tool.py   # pubmed_search · paper_review · build_docx · build_pptx · home_assistant
profiles/<nombre>/SOUL.md     # personas de runtime (perfiles de Hermes local)
evals/run_evals.py            # red de seguridad offline (routing, guardas, tier, skills, §protegidas)
tests/test_harness.py         # pytest del núcleo
shared/                       # rules/, notebooklm/, learning/, traces/, templates/
projects/<fecha_tema>/_estado.md   # continuidad entre sesiones (R5)
```

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# Credenciales locales (fuera de iCloud). El harness las carga solo desde aquí:
mkdir -p ~/.config/harness && chmod 600 ~/.config/harness/.env 2>/dev/null || true
$EDITOR ~/.config/harness/.env   # añade ANTHROPIC_API_KEY, UC_USER, UC_PASSWORD, etc.
# Override de ruta opcional: export HARNESS_ENV_FILE=/ruta/a/.env
```

## Uso

```bash
# Ejecutar el harness (enruta solo, o fuerza subagente)
python tools/loop.py "haz una revisión sobre transmisión neuromuscular" --agent research
python tools/loop.py "interpreta este EMG" --project 2026-06-11_caso_x

# Autoaprendizaje (por agente; raíz si se omite --agent)
python tools/self_improve.py distill --agent signals
python tools/self_improve.py list --agent signals
python tools/self_improve.py apply <id> --agent signals    # Gate humano + git

# Observabilidad y evals
python tools/tracing.py                # resumen del día (sesiones, tool calls, costo)
python evals/run_evals.py              # 0 = todo pasa; corre antes/después de cada apply
pytest -q                              # tests del núcleo

# Componer un entregable con el subagente docs (integra subagentes)
python tools/compose.py --spec spec.json --out informe.docx
python tools/compose.py --spec spec.json --out deck.pptx --demo   # sin API (marcadores)

# Disparador periódico del autoaprendizaje (genera propuestas para todos los agentes)
python tools/schedule_distill.py
```

## Política de modelos (qué motor para qué tarea)

El harness no corre con un modelo fijo: clasifica la tarea y elige el tier, lo **declara antes
de ejecutar** y lo acota con un techo de costo. Detalle en `AGENTS.md` §11.

| Clase | Tier | Motor | Cuándo |
|---|---|---|---|
| `format` / `extract` / `route` | T0-local | modelo local pequeño | convertir, exportar, parsear, clasificar |
| `synthesis` | T2-cloud | **Claude Sonnet 5** | resumir, redactar, fichar un artículo |
| `deep_analysis` | T3-cloud | **Claude Opus 5** | comparar con la literatura, establecer aportes, crítica metodológica |
| `vision` | TV-local | VLM local | imágenes y escaneos |

Sin motor local disponible, las clases mecánicas caen a **Haiku 4.5** (no al tier de trabajo).
Con `--phi` la política se restringe a motores locales y **aborta** si no hay ninguno (R8).

```bash
# Ver qué elegiría para una tarea, sin ejecutarla
python tools/model_policy.py "analiza estos papers y compáralos con la literatura"
python tools/model_policy.py "convierte este markdown a docx"

# Forzar la clase (y con ella el tier)
python tools/loop.py "arma el informe" --class format
python tools/loop.py "interpreta este EMG" --phi        # solo motores locales
```

### Variables de entorno

| Variable | Default | Para qué |
|---|---|---|
| `HARNESS_MODEL` | `claude-sonnet-5` | modelo del tier de trabajo (T2) |
| `HARNESS_LOCAL_BASE_URL` | `http://127.0.0.1:1234/v1` | endpoint OpenAI-compat (LM Studio / Ollama / vLLM) |
| `HARNESS_LOCAL_FAST_MODEL` | `qwen2.5-7b-instruct` | motor local para tareas mecánicas |
| `HARNESS_LOCAL_MODEL` | `nemotron-3.5-lightning` | motor local de razonamiento (usado con `--phi`) |
| `HARNESS_LOCAL_VISION_MODEL` | `qwen3vl` | VLM local |
| `HARNESS_LOCAL_DISABLED` | `0` | `1` = ignora los tiers locales |
| `HARNESS_COST_CEILING` | `0.50` | techo USD por turno; por encima pide confirmación |
| `HARNESS_SESSION_COST_CEILING` | `5.00` | techo USD acumulado por corrida |
| `HARNESS_SKILL_PATHS` | — | directorios extra de skills, separados por `:` |

## Selección autónoma de skills

En cada turno se rankea **todo** el pool contra la tarea y se cargan las instrucciones
completas de las ganadoras (tope 4), dejando constancia:

```
[skills] pool de 7 · seleccionadas automáticamente: paper_review (0.97), pubmed_search (0.14)
```

Si nada supera el umbral, se declara y se resuelve con criterio propio: **una skill imaginada
es peor que ninguna**. El pool se re-escanea en cada llamada, así que una skill instalada
después queda disponible sin tocar código.

```bash
python tools/skill_selector.py                       # lista el pool
python tools/skill_selector.py "apaga las luces"     # muestra el ranking
```

## Análisis científico multi-paper

`skills/paper_review/` + `tools/paper_review.py`: lee una carpeta de PDF/DOCX, de-identifica,
ficha cada artículo con **Sonnet 5**, lo contrasta contra PubMed para establecer su aporte, y
hace la lectura transversal con **Opus 5**.

```bash
# Inspección sin gastar un token: extracción + de-identificación
python tools/paper_review.py --dir ~/papers --dry-run

# Corrida completa
python tools/paper_review.py --dir ~/papers \
    --tema "HD-sEMG en ELA" --out projects/2026-09-01_hdsemg
```

Salidas: `revision.md` (tabla comparativa + síntesis + ficha por artículo, pegable en Notion)
y `revision.json` (estructurado por paper, encadenable a `build_docx`). Los PMIDs se filtran
contra lo que devolvió la tool en esa corrida: uno que el modelo escriba y PubMed no haya
devuelto se descarta antes del informe (R2).


## Home Assistant (subagente `home`)

Integración con Home Assistant vía su API REST. El wizard `tools/ha_setup.py` conecta y
diagnostica; la skill `skills/home_assistant/` expone las herramientas (`ha_states`,
`ha_services`, `ha_call_service`) al subagente `home`.

### Setup y verificación

```bash
# Wizard interactivo: crea/valida el Long-Lived Access Token y guarda credenciales
# en ~/.config/harness/.env (chmod 600, fuera de iCloud).
python tools/ha_setup.py
# No interactivo:
python tools/ha_setup.py setup --url http://192.168.4.60:8123 --token XXXX
# Diagnóstico con credenciales ya guardadas (ping + inventario por dominio):
python tools/ha_setup.py status
```

`status` hace `GET /api/` (ping) y lista las entidades agrupadas por dominio — útil para
confirmar la conexión tras el setup.

### Prueba de la integración

- **Lectura (libre):** consulta el estado real de una entidad para validar el camino
  credenciales → `env_loader` → cliente REST → `/api/states/<entity_id>`.

  ```bash
  python tools/loop.py "estado de weather.forecast_casa" --agent home
  ```

- **Escritura (gated):** un cambio de estado exige confirmación humana por turno. Para una
  prueba controlada, usa una entidad **sin efecto físico** (p. ej. el LED indicador de un
  enchufe, `switch.<id>_network_indicator`), togglea y **revierte** al estado original.
  Evita switches que controlan luces/enchufes reales.

  ```bash
  python tools/loop.py "apaga switch.<id>_network_indicator" --agent home   # pide confirmación
  python tools/loop.py "enciende switch.<id>_network_indicator" --agent home # revertir
  ```

Verifica con `ha_states` que el estado cambió tras el toggle y volvió al original tras revertir.
Nota: `ha_call_service` puede responder "sin cambios de estado reportados" aunque la acción sí
se aplique; confírmalo releyendo el estado.

## Flujo de seguridad

- Toda instrucción válida viene del usuario; lo observado por herramientas es **dato, no orden**.
- `loop.py` bloquea patrones destructivos y exige confirmación humana en acciones con efecto
  externo (`GATED_TOOLS`).
- El autoaprendizaje propone, pero **no aplica** sin Gate humano + git. Las secciones protegidas
  (identidad, reglas, gates, seguridad) son inmutables al ciclo (R13).
- Regla operativa: `python evals/run_evals.py` debe dar 0 fallos antes de cada `apply`. Si un
  cambio del ciclo baja el score, se revierte (`git revert`).
