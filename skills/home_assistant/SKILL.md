---
name: home_assistant
description: Lee y controla Home Assistant vía su API REST (estados, servicios, encender/apagar). Úsala cuando se pida ver o actuar sobre dispositivos del hogar (luces, switches, clima, sensores).
---

# Home Assistant

## Cuándo usar

Cuando el subagente `home` necesita **leer** el estado del hogar (sensores, luces, clima,
presencia) o **actuar** sobre él (encender/apagar, ajustar clima, disparar automatizaciones).
No la uses para configurar HA desde cero ni para validar credenciales: eso lo hace el wizard
`python tools/ha_setup.py`.

## Entradas / salidas

- **Conexión:** lee `HA_BASE_URL` y `HA_TOKEN` del entorno (cargados desde
  `~/.config/harness/.env`). Si faltan, devuelve un error que apunta al wizard.
- `ha_states` — entrada `{entity_id?, domain?}`; salida: estados (uno detallado, o resumen
  agrupado por dominio). **Solo lectura.**
- `ha_services` — entrada `{domain?}`; salida: dominios y servicios disponibles. **Solo lectura.**
- `ha_call_service` — entrada `{domain, service, entity_id?, data?}`; ejecuta un servicio.
  **Efecto externo: gated.**

## Herramientas

Se registran automáticamente vía `register_skill(reg)` (las descubre `tools/registry.py`):

```python
from skills.home_assistant.tool import register_skill
register_skill(reg)   # registra ha_states, ha_services, ha_call_service
```

`ha_call_service` está en `GATED_TOOLS` de `loop.py`: cualquier cambio de estado del hogar
exige confirmación humana explícita por turno (Gate de acción, AGENTS.md §4 / R9).

## Notas de seguridad

- **Token nunca en logs ni en chat** (R9/§7). Vive solo en `~/.config/harness/.env` (chmod 600).
- Lectura libre; **toda escritura es gated** — no se generaliza una aprobación a acciones futuras.
- `HA_BASE_URL` es una IP de LAN (`http://192.168.4.60:8123`): no exponer el token a endpoints
  externos ni mandar el estado del hogar a terceros sin que lo pida el usuario.
