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
