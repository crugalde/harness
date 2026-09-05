# skills/ — Convención de habilidades del harness

Una **skill** es una carpeta con un `SKILL.md` que el harness descubre automáticamente
(`tools/skill_selector.py` escanea `skills/*/SKILL.md` en cada turno). Si la skill expone una
herramienta ejecutable, su script vive en la misma carpeta y se registra en el `ToolRegistry`.

A diferencia del comportamiento anterior —volcar el índice entero al contexto— ahora el
selector **rankea todo el pool contra la tarea** y carga las instrucciones completas solo de
las ganadoras, declarando cuáles eligió y con qué puntaje. Consecuencia práctica: la
`description` del front-matter ya no es decorativa, **es el texto contra el que se hace el
match**. Escríbela con las palabras que Cristian usaría al pedir la tarea (en español y en
inglés si aplica) o la skill no se seleccionará nunca.

Rutas extra de skills: `HARNESS_SKILL_PATHS=/ruta/a/otras/skills:/otra/mas`.

## Estructura

```
skills/
├── README.md                 # este archivo
└── <nombre_skill>/
    ├── SKILL.md              # front-matter + instrucciones (obligatorio)
    └── tool.py               # implementación opcional de la herramienta
```

## Formato de SKILL.md

El front-matter `name:` y `description:` es lo que el loop inyecta en el contexto (mantén la
descripción en una línea, accionable, para que el router y el agente sepan cuándo usarla).

```markdown
---
name: nombre_skill
description: Qué hace y cuándo usarla, en una frase.
---

# <Nombre>

## Cuándo usar
Disparadores concretos (no genéricos).

## Entradas / salidas
Qué recibe y qué devuelve.

## Herramienta (opcional)
Nombre de la tool que registra en el ToolRegistry y su esquema de entrada.

## Notas de seguridad
Restricciones de dominio (PHI, solo lectura, gates).
```

## Reglas

- Una skill = una capacidad acotada. Si hace tres cosas distintas, son tres skills.
- La descripción debe decir **cuándo** usarla, no solo qué es: es lo que se rankea.
- La sección "## Cuándo usar" también pesa en el match: pon ahí los disparadores literales.
- Si la skill ejecuta acciones con efecto externo, su tool va en `GATED_TOOLS` de `loop.py`.
- Las skills también son candidatas al autoaprendizaje: si una se usa mal de forma repetida,
  el ciclo §10 puede proponer afinar su `description` (nunca su seguridad).
