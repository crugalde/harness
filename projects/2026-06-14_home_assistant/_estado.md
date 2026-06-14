# Estado — Integración Home Assistant (subagente `home`)

**Última actualización:** 2026-06-14
**Objetivo:** Agente experto en domótica conectado a Home Assistant + automatizaciones.

## Conexión (verificada)

- HA en **`http://192.168.4.60:8123`** (la `.62` original era errónea; corregida en todo el repo).
- Token Long-Lived Access guardado en `~/.config/harness/.env` (`HA_BASE_URL`, `HA_TOKEN`, chmod 600).
- Diagnóstico: `python tools/ha_setup.py status`.

## Hechos clave de la instalación

- **Las luces son entidades `switch`** (Zigbee2MQTT). NO hay dominio `light`. 19 luces.
- Luz a mantener de noche: `switch.0xa4c138a5bf2c0a9f` ("luces exterior"). No existe "luz patio".
- **Los enchufes NUNCA se apagan** en apagados masivos (regla del usuario). Miden consumo
  (`sensor.<id>_power`, etc.) por si se controlan uno a uno en el futuro.
- Aviso: `notify.iphone_de_cristian` (accionable). No hay Telegram.
- Presencia: `zone.home` (conteo de personas). El REST puede responder `[]` aunque la acción
  se aplique → siempre verificar releyendo estado.

## Hecho hasta ahora

- [x] Subagente `agents/home/AGENTS.md` (registrado en `AGENTS.md` raíz + `loop.py`).
- [x] Skill `skills/home_assistant/` con tools: `ha_states`, `ha_services`, `ha_lights` (leer),
      `ha_call_service`, `ha_lights_off` (gated, excluye enchufes). Verifican por re-lectura.
- [x] Wizard `tools/ha_setup.py` (setup/status).
- [x] Prueba real: apagado de "Luz oficina 2do piso" ✓.
- [x] 3 automatizaciones en `agents/home/automations/` (validadas contra HA: todas las
      entidades existen, ningún enchufe en listas de apagado):
  - `apagar_luces_medianoche.yaml` — 00:00, aviso accionable iPhone, confirmar/5min→apaga
    luces (mantiene exterior).
  - `luces_exterior_con_sol.yaml` — sol bajo→on / sol alto→off de exterior.
  - `nadie_en_casa.yaml` — `zone.home < 1` por 5min → avisa + apaga luces (NO enchufes).

## Pendiente (retomar aquí)

1. **Bug a investigar:** en la prueba "apagar todas 10 s y restaurar", 5/6 luces volvieron;
   **`switch.0xa4c13822d90872da` (Luz oficina 2do piso) NO volvió a `on`** — probable comando
   Zigbee perdido por ráfaga. Idea: añadir reintento con verificación (2–3 intentos, ~2 s entre
   cada uno) en una tool tipo `ha_lights_restore`, o espaciar los comandos. **OJO: esa luz
   probablemente sigue apagada físicamente.**
2. Pegar los 3 YAML en HA (UI → Automatizaciones → Editar en YAML) y probar.
3. Probar `apagar_luces_medianoche.yaml` a medianoche (el usuario lo hará).
4. Opcional: tool `ha_lights_off` con reintento/verificación; manejar latencia Zigbee.

## Siguiente acción

Investigar/implementar el reintento de comandos Zigbee (pendiente #1) y dejar la luz de
oficina en el estado deseado.
