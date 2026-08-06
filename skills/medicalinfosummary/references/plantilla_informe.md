# Plantilla del informe

Estructura obligatoria del `.md` de salida. Los ocho bloques van siempre y en este orden:
el lector entra buscando una sección concreta y el orden fijo hace que la encuentre sin leer
todo. Si una sección no tiene evidencia suficiente, **no la borres**: escríbela declarando el
vacío (R12). Un "no hay datos poblacionales chilenos" es información clínica útil; una sección
ausente parece un olvido.

## Restricciones de Notion

El destino es pegar el archivo en Notion, así que el markdown tiene que sobrevivir ese pegado:

- **Solo tres niveles de encabezado.** Notion mapea `#`, `##`, `###` a H1/H2/H3 y convierte
  `####` en párrafo suelto. Para el cuarto nivel usa `**negrita**` al inicio de la línea.
- **Tablas simples.** Sin celdas combinadas ni saltos de línea dentro de una celda. Notion las
  convierte a base de datos en línea solo si la fila de separación `|---|` está bien formada.
- **Sin LaTeX.** `$$...$$` no se convierte al pegar. Escribe fórmulas en texto
  (`sensibilidad = VP / (VP + FN)`).
- **Mermaid sí.** Notion renderiza bloques ` ```mermaid ` de forma nativa.
- **Imágenes por URL.** `![pie](https://...)` en su propia línea se convierte en bloque de
  imagen. Debe ser enlace directo al archivo (`.png`, `.jpg`, `.svg`), no a la página que lo
  contiene.
- **Callouts.** `> ` se convierte en cita; sirve para advertencias y notas de dosis.

---

## Plantilla

````markdown
# <Enfermedad> — síntesis clínica

> **Enfoque solicitado:** <lo que pidió el usuario, o "panorama general">
> **Fuentes:** <n> (<n> guías · <n> revisiones sistemáticas · <n> ECAs · <n> otras) · <año min>–<año max>
> **Generado:** <fecha> · Contexto asumido: Chile, práctica especializada

## 1. Definición

Qué es la entidad, con la definición operativa que usan las guías vigentes. Si hay más de una
definición en competencia (p. ej. criterios de sociedades distintas), pon ambas y di cuál
predomina hoy y desde cuándo. Incluye la clasificación o estadificación de uso corriente.

Cierra con los códigos de nomenclatura cuando existan (CIE-10, OMIM, Orphanet).

## 2. Epidemiología

Incidencia y prevalencia con su unidad y población de referencia, no cifras sueltas. Distribución
por edad y sexo, factores de riesgo con su magnitud de efecto, y mortalidad/supervivencia.

Prioriza datos chilenos o latinoamericanos si existen; si no, di de qué población vienen las
cifras y por qué podrían no trasladarse. Una tabla suele leerse mejor que un párrafo:

| Parámetro | Valor | Población | Fuente |
|---|---|---|---|
| Incidencia | x/100.000 hab-año | ... | [n] |
| Prevalencia | x/100.000 | ... | [n] |

## 3. Fisiopatología

La cadena causal desde el evento inicial hasta la manifestación clínica. Esta es la sección donde
un esquema rinde más que el texto: incluye un diagrama Mermaid del mecanismo (ver
`figuras.md`) y, si hay una figura open-access que lo muestre mejor, enlázala con su crédito.

Marca explícitamente qué eslabones están establecidos y cuáles son hipótesis en discusión —
esa distinción es justamente lo que se pierde en los resúmenes de manual.

## 4. Clínica

Presentación típica, formas atípicas y curso natural. Distingue lo frecuente de lo característico:
un síntoma puede ser muy común y poco discriminante, u ocurrir en el 5% pero ser casi
patognomónico. Cuando la fuente lo reporte, da frecuencias.

| Manifestación | Frecuencia | Valor discriminante |
|---|---|---|
| ... | ...% | alta / media / baja |

Incluye banderas rojas y criterios de gravedad o derivación urgente.

## 5. Diagnóstico

**Gold standard.** Cuál es, qué rendimiento tiene y cuáles son sus limitaciones reales. Si el
patrón de oro es imperfecto o es un diagnóstico de exclusión, dilo — es un dato que cambia la
interpretación de todo lo demás.

**Exámenes complementarios.** Tabla con rendimiento operativo, porque es lo que se consulta:

| Examen | Sensibilidad | Especificidad | Cuándo pedirlo | Fuente |
|---|---|---|---|---|
| ... | ...% | ...% | ... | [n] |

**Algoritmo diagnóstico.** Un Mermaid `flowchart TD` con la secuencia de decisión.

Añade una nota sobre disponibilidad y costo en Chile cuando sea relevante (FONASA/ISAPRE,
centros que lo realizan, si requiere derivación).

## 6. Diagnóstico diferencial

Ordenado por probabilidad o por gravedad si hay entidades que no se pueden pasar por alto.
Para cada una, el dato que la distingue — no basta con listarlas:

| Entidad | Qué la sugiere | Qué la descarta |
|---|---|---|
| ... | ... | ... |

## 7. Disyuntivas, controversias y vacíos

La sección con más valor y la que casi ningún resumen trae. Aquí va lo que la literatura **no**
resuelve:

- **Controversias activas:** donde guías o escuelas discrepan. Nombra las posturas y quién
  sostiene cada una.
- **Vacíos de evidencia:** preguntas clínicas sin ensayos que las respondan.
- **Limitaciones metodológicas:** cuando la recomendación descansa en estudios pequeños,
  abiertos, con desenlaces subrogados o poblaciones no representativas.
- **Qué viene:** ensayos en curso o líneas de investigación con lectura próxima.

Sé concreto sobre el nivel de evidencia. "Falta evidencia" no dice nada; "la recomendación
descansa en una serie retrospectiva de 34 pacientes sin grupo control [n]" sí.

## 8. Tratamiento

Por línea y por escenario clínico. Para cada intervención: mecanismo, indicación precisa,
evidencia que la respalda con su nivel, y los efectos adversos que cambian la decisión.

> **Dosis:** verifica todo esquema posológico contra la ficha del producto vigente antes de
> prescribir. Las dosis de esta síntesis vienen de la literatura citada y pueden no coincidir
> con el registro ISP chileno.

| Línea | Intervención | Evidencia | Consideraciones |
|---|---|---|---|
| 1ª | ... | ECA / meta-análisis [n] | ... |

Incluye tratamiento de soporte, manejo de complicaciones, criterios de respuesta y seguimiento.
Marca qué está disponible en Chile y qué requiere gestión especial (Ley Ricarte Soto, uso
compasivo, importación).

## Referencias

Numeradas y en Vancouver, en el mismo orden en que aparecen los `[n]` del texto. Cada una con
su PMID o DOI real — nunca inventados (R2). Marca la vía de acceso:

1. Autor A, Autor B, et al. Título. Revista. Año. doi:... PMID: ... — *guía* · PMC (libre)

## Qué quedó fuera

Declaración explícita de límites (R12): qué preguntas no se cubrieron, qué fuentes no se
pudieron abrir, qué idiomas o bases quedaron sin revisar, y qué tan reciente es el corte de
búsqueda.
````
