# Registro de Aprendizaje Automático (Journal)

## [2026-06-14] Reglas de Formato de Presentación (PPTX)
**Evidencia**: El usuario corrigió explícitamente el formato visual de la presentación generada automáticamente, dictando reglas estrictas.
**Patrón a Fijar**:
- Diapositiva 1 (Portada): Debe contener siempre el título de la presentación y el autor ("Dr. Cristian Ugalde").
- Tipografía: Uso universal de `Calibri`.
- Jerarquía de Tamaños:
  - Títulos: `30 pt`
  - Subtítulos: `26 pt`
  - Contenido (texto o viñetas): `20 pt`
  - Pie de página (Referencias + Autor): `10 pt`
- Distribución de Diapositiva (Contenido):
  - 50% reservado para texto o viñetas.
  - 50% reservado para foto o esquema (extraído directo de los papers o generado a partir de texto).
- Pie de Página: Debe ir alineado a la izquierda.
- Estructura Obligatoria: Toda presentación final debe incluir diapositiva de Conclusión y diapositiva de Bibliografía en formato Vancouver.

**Acción**: Se ha generado el archivo `shared/templates/pptx_rules.json` para que los scripts consuman estas reglas dinámicamente y permitan auto-aprendizaje.

## [2026-06-14] Domótica — hechos de la instalación Home Assistant (subagente `home`)
**Evidencia**: Primera conexión real al HA del usuario (`192.168.4.60:8123`, no `.62` como decía la doc inicial). Prueba exitosa de apagado de "Luz oficina 2do piso".
**Patrón a Fijar**:
- IP correcta de HA: `192.168.4.60` (la `.62` era errónea; corregida en todo el harness).
- **Las luces son entidades `switch`** (Zigbee2MQTT); **no existe dominio `light`**. Usar
  `switch.turn_on`/`switch.turn_off`. 19 luces; mantener de noche `switch.0xa4c138a5bf2c0a9f`
  ("luces exterior"). No hay "luz patio".
- Distinguir luces de **enchufes** (nombre "enchufe") y del bridge Zigbee2MQTT.
- Canal de aviso: `notify.iphone_de_cristian` (accionable). **No hay Telegram.**
- **El REST de `call_service` puede devolver `[]`** ("sin cambios") aunque la acción se aplique
  → siempre verificar releyendo el estado.
**Acción**: La skill `home_assistant` ahora verifica por re-lectura y expone `ha_lights`/
`ha_lights_off` (exclusión de enchufes). Automatización de medianoche en
`agents/home/automations/apagar_luces_medianoche.yaml`.

## [2026-11-09] Skill `pubmed_qa` — señales de la primera prueba en vivo
**Evidencia**: Gate 1 de la skill y prueba con 3 preguntas (`projects/2026-11-09_pubmed_qa/`).
**Corrección explícita del usuario**: en Gate 1, "lo primordial acá es la respuesta a la pregunta
con respaldo de las fuentes. Debes analizar y resumir lo encontrado" → en preguntas de evidencia,
entregar respuesta argumentada (respuesta breve + síntesis + certeza), no listados de papers.
**Errores y arreglos**:
- El entorno cloud Default bloquea `eutils.ncbi.nlm.nih.gov` (403 del proxy) → entorno `harness`
  con NCBI y Europe PMC permitidos.
- PubMed asigna "Randomized Controlled Trial" a análisis post hoc, comparaciones indirectas y
  monografías de fármacos → clasificar por título antes de confiar en el tipo de publicación.
- El verificador detectó una cita a una fuente que salió del paquete al regenerarlo → regenerar
  el paquete obliga a re-verificar la respuesta (el gate funcionó como se diseñó).
**Patrón a fijar (candidato, 1 corrección explícita)**: toda respuesta basada en literatura pasa por
`pubmed_qa verificar` antes de entregarse.
