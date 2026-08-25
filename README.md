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
tools/self_improve.py         # ciclo de autoaprendizaje (capturar→destilar→proponer→aplicar)
tools/tracing.py              # observabilidad: JSONL por día (tools, tokens, costo, latencia)
tools/registry.py             # ensambla el ToolRegistry (auto-descubre skills + MCP)
tools/compose.py              # motor de `docs`: integra subagentes → .docx/.pptx
tools/read_emg.py             # de-identificación de estudios EMG (med)
tools/decompose.py            # pipeline HD-sEMG (signals)
tools/ha_setup.py             # wizard de conexión/diagnóstico de Home Assistant (home)
tools/n8n_setup.py            # wizard de conexión/diagnóstico del n8n del VPS
tools/schedule_distill.py     # disparador periódico del autoaprendizaje (cron)
skills/<nombre>/SKILL.md+tool.py   # pubmed_search · build_docx · build_pptx · home_assistant · n8n
evals/run_evals.py            # red de seguridad offline (routing, guardas, secciones protegidas)
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

## n8n self-hosted (skill `n8n`)

Automatizaciones propias corriendo en el VPS, con el harness como copiloto de diseño.
El stack y la migración desde n8n Cloud viven en `projects/2026-08-25_n8n_vps/`
(runbook, docker-compose, scripts de export/import y respaldo).

```bash
# Conectar el harness a tu instancia (guarda credenciales en ~/.config/harness/.env)
python tools/n8n_setup.py
python tools/n8n_setup.py status        # workflows, activos y últimas ejecuciones fallidas

# Diseñar/depurar con el harness
python tools/loop.py "lista mis workflows activos de n8n"
python tools/loop.py "por qué falló el workflow abc123"
```

Lectura libre; `n8n_workflow_create`, `n8n_workflow_update` y `n8n_workflow_activate` están
en `GATED_TOOLS`: un workflow activo dispara acciones reales, así que cada escritura exige
confirmación humana por turno.

## Flujo de seguridad

- Toda instrucción válida viene del usuario; lo observado por herramientas es **dato, no orden**.
- `loop.py` bloquea patrones destructivos y exige confirmación humana en acciones con efecto
  externo (`GATED_TOOLS`).
- El autoaprendizaje propone, pero **no aplica** sin Gate humano + git. Las secciones protegidas
  (identidad, reglas, gates, seguridad) son inmutables al ciclo (R13).
- Regla operativa: `python evals/run_evals.py` debe dar 0 fallos antes de cada `apply`. Si un
  cambio del ciclo baja el score, se revierte (`git revert`).
