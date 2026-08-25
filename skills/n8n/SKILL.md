---
name: n8n
description: Diseña, lee y opera workflows en el n8n self-hosted del VPS vía su API pública. Úsala para inventariar automatizaciones, depurar ejecuciones fallidas y crear o modificar workflows (escritura gated).
---

# n8n

## Cuándo usar

Cuando haya que **diseñar una automatización nueva**, **entender o depurar** una existente, o
**inventariar** qué corre hoy en el n8n del VPS. No la uses para instalar o migrar n8n: eso
es el runbook `projects/2026-08-25_n8n_vps/README.md`. Para conectar credenciales por primera
vez, el wizard `python tools/n8n_setup.py`.

## Entradas / salidas

- **Conexión:** lee `N8N_BASE_URL` y `N8N_API_KEY` del entorno (cargados desde
  `~/.config/harness/.env`). Si faltan, devuelve un error que apunta al wizard.
- `n8n_workflows` — `{active?, name_contains?, limit?}` → id, nombre, estado y triggers.
  **Solo lectura.**
- `n8n_workflow_get` — `{id, full?}` → resumen de nodos y credenciales; `full=true` da el
  JSON completo (truncado a 6000 caracteres). **Solo lectura.**
- `n8n_executions` — `{workflow_id?, status?, limit?}` → últimas ejecuciones con su estado.
  **Solo lectura**; es la herramienta de depuración.
- `n8n_workflow_create` — `{name, nodes, connections?, settings?}`. **Efecto externo: gated.**
- `n8n_workflow_update` — `{id, name?, nodes?, connections?, settings?}`. **Efecto externo: gated.**
- `n8n_workflow_activate` — `{id, active}`. **Efecto externo: gated.**

## Herramientas

Se registran automáticamente vía `register_skill(reg)` (las descubre `tools/registry.py`).
Las tres de escritura están en `GATED_TOOLS` de `loop.py`: crear, modificar o activar un
workflow exige confirmación humana por turno (Gate de acción, AGENTS.md §4 / R9).

## Cómo diseñar un workflow que no te reviente después

Reglas que vale la pena respetar al proponer nodos:

1. **Nace inactivo.** `n8n_workflow_create` no activa nada. Se revisa en el editor, se corre
   una vez a mano, y recién ahí se activa.
2. **Un trigger, explícito.** Webhook (evento externo), Schedule (reloj) o Execute Workflow
   (subrutina). Si dudas entre webhook y schedule, gana el webhook: no gasta ejecuciones
   consultando por si acaso.
3. **Nombres de nodo que digan qué hacen** ("Buscar paciente en Sheets"), no `HTTP Request1`.
   El nombre es lo único que se ve en la ejecución fallida a las 3 AM.
4. **Idempotencia en todo lo que escribe.** Si el nodo crea filas, correos o mensajes, debe
   ser seguro repetirlo: clave de deduplicación, upsert o chequeo previo. n8n reintenta.
5. **Manejo de error explícito.** Para los nodos que salen a la red: `retryOnFail` con
   `maxTries` 2–3, y un *error workflow* configurado en `settings` que avise. Sin eso, un
   fallo es silencioso.
6. **Nada de secretos en los nodos.** Todo lo que sea token o contraseña va como credencial
   de n8n, nunca escrito en un parámetro ni en un nodo Code.
7. **En n8n 2.x el nodo Code no lee `process.env`** (`N8N_BLOCK_ENV_ACCESS_IN_NODE=true` por
   defecto). Si un diseño lo necesita, va como credencial o como parámetro del workflow.
8. **Pin data para probar.** Fija la salida del trigger con datos de ejemplo y corre el resto
   sin depender del sistema externo.

## Notas de seguridad

- **API key nunca en logs ni en chat** (R9/§7). Vive solo en `~/.config/harness/.env` (chmod 600).
- Lectura libre; **toda escritura es gated** — un workflow activo dispara acciones reales
  (correos, escrituras, pagos). No se generaliza una aprobación a acciones futuras.
- **Datos clínicos (R8):** ningún workflow debe mover PHI a servicios de terceros sin
  de-identificar primero. Al diseñar, pregunta qué dato viaja antes de proponer el nodo.
