# Plantilla de la ficha crítica

Seis secciones, todas obligatorias. Si una no aplica, se escribe por qué — no se borra.

El `# H1` **no va en el cuerpo**: el título vive en la propiedad `Título` y repetirlo lo duplica
en la página. `publicar_notion.py` lo quita si aparece, pero es mejor no escribirlo.

## Restricciones de formato

El cuerpo se convierte a bloques de la API con `notion_md.py`. Lo que sobrevive:

- **Encabezados `##` y `###`.** Nada de `#` (es el título). Los `####` se degradan a `###`.
- **Tablas de pipes**, con la fila separadora. Sin celdas combinadas ni saltos dentro de celda.
- **Callouts**: `<callout icon="⚠️" color="orange_bg">` … `</callout>`. Es el bloque del
  veredicto de calidad, y conviene reservarlo para eso: un callout por ficha se lee, cinco no.
- **Mermaid** en bloque de código, para mecanismos y flujos de participantes.
- Formato inline: `**negrita**`, `*cursiva*`, `` `código` ``, `[texto](url)`, `~~tachado~~`.
- **Nada de LaTeX ni `$$`.** No renderiza. Los estadísticos van en prosa: "HR 0,72 (IC95%
  0,55–0,94)".

---

## Estructura

```markdown
## Identificación del estudio
- **Título:** <tal como se publicó>
- **Autores principales:** <primer autor; autor senior y filiación si importa>
- **Año:** <año> · **Revista:** <abreviatura NLM> · **DOI:** [<doi>](https://doi.org/<doi>) · **PMID:** <pmid>
- **Tipo de estudio:** **<diseño>** — evaluado con <guía>. <Por qué ese diseño y no el que
  declara el título, cuando difieren.>
- **Financiamiento:** <fuente> · **Conflictos:** <declarados o ninguno>
- **Registro:** <NCT/PROSPERO si lo hay> · <fechas de recepción y aceptación>

## Resumen clínico
### <Población / corpus revisado>
n, criterios de inclusión y exclusión, procedencia geográfica, seguimiento.
Para revisiones: n de estudios incluidos, bases, ventana temporal.

### Hallazgos principales
Los que sostienen el veredicto, con magnitud, intervalo y n. No todos: los que importan.

## Evaluación de calidad — <guía>
Un ítem por viñeta, con el juicio y la **evidencia textual** que lo sostiene — cita o página.
Los ítems que no aplican al diseño se anotan como tales, no se omiten.

<callout icon="⚠️" color="orange_bg">
	**Calificación global: <Alta|Moderada|Baja|Críticamente baja>.** <Qué ítem la determinó y qué
	consecuencia tiene para leer los resultados.>
</callout>

## Discusión y limitaciones
Tuya, no de los autores. Qué se sobreinterpretó, qué confusor quedó suelto, qué pesa más de lo
que el texto sugiere. Cierra con **qué significa en Chile** — incluido "nada operativo", que es
una conclusión legítima y frecuente.

## Explicación fisiopatológica
El mecanismo que el estudio propone o asume, y dónde se rompe. Si el trabajo no toca mecanismo
(una guía, una evaluación económica), dilo en una línea y sigue.

## Aporte al área
- **Novedad:** qué aporta que no existiera.
- **Utilidad práctica:** qué conducta cambia. Si ninguna, decirlo así.
- **A quién aplica:** qué lector se lo lleva.
- **Qué queda pendiente:** la pregunta concreta que sigue abierta.

---
*Ficha generada con la skill `analisis-estudio` · <fecha> · texto <completo|abstract>.*
```

## El pie no es decorativo

`texto completo` y `texto abstract` significan cosas distintas para quien lee la ficha después.
Si solo hubo abstract, varios ítems de la guía son **no evaluables** —no "adecuados"— y el pie es
lo que se lo dice al lector dentro de seis meses (R12).
