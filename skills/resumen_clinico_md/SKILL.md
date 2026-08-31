---
name: resumen_clinico_md
description: "Convierte un resumen clínico en Word (.docx/.doc) a un archivo .md listo para la bóveda «brain md», conservando figuras, tablas, listas y estructura de títulos, y de-identificando datos de paciente. Usa esta skill cuando se te entregue un documento Word de resumen de una patología o de un caso clínico y haya que pasarlo a Markdown, cuando el flujo de Hermes derive un archivo reconocido como resumen clínico, o cuando se pida 'pasa este Word a md', 'convierte el resumen a Markdown' o 'súbelo al brain'. No la uses para PDFs de revistas científicas: esos van a la skill de análisis de estudio."
---

# resumen_clinico_md

Pasa un resumen clínico de Word a Markdown **sin perder nada de lo que hace útil al documento**:
las figuras (con su pie), las tablas, la jerarquía de títulos y el orden real del texto. La
conversión es determinista —la hace un script, no el modelo—, así que el mismo `.docx` produce
siempre el mismo `.md`. El trabajo del agente empieza después: revisar y corregir.

La diferencia con "copiar y pegar el texto" está en tres cosas: **las figuras se extraen y se
enlazan** en el punto exacto donde estaban, **las tablas siguen siendo tablas** (no párrafos
aplastados), y **los identificadores de paciente se enmascaran antes de escribir nada** (R8).

## Cuándo usar

- El flujo `hermes_brain` derivó un archivo Word clasificado como resumen clínico.
- Cristian entrega un `.docx` de una patología ("pásalo al brain", "conviértelo a md").
- Hay que reprocesar un `.md` mal convertido a partir del Word original.

**Cuándo NO usar:** PDFs de revista científica (→ skill de análisis de estudio), documentos
administrativos, o Word que no sea un resumen clínico. Si dudas de si el documento es clínico,
pregúntalo antes de convertir; no conviertas "por si acaso".

## Entradas / salidas

| | |
|---|---|
| **Entrada** | ruta de un `.docx` (el `.doc` legado se convierte antes con LibreOffice) |
| **Salida** | `<destino>/<slug>.md` + `<destino>/_adjuntos/<slug>/fig-NN.png` |
| **Destino por defecto** | `C:\Users\Usuario\OneDrive\brain md` |
| **Devuelve** | JSON en stdout: `{"md", "titulo", "figuras", "tablas", "enmascarados", "notas"}` |

## Flujo

### Paso 1 — Conversión determinista

Ejecuta el script tal cual. No reescribas el documento a mano: el script preserva el orden de
bloques del XML de Word, que es lo que se pierde al leer el texto plano.

```bash
python skills/resumen_clinico_md/scripts/docx_a_md.py "<ruta del .docx>" \
    --salida "C:\Users\Usuario\OneDrive\brain md" \
    --adjuntos _adjuntos \
    --json
```

Opciones que importan:

- `--slug nombre-del-archivo` fuerza el nombre del `.md` (por defecto sale del título del
  documento). Úsalo cuando el título del Word sea genérico ("Documento1").
- `--sin-deidentificar` desactiva el enmascarado. **Solo** para documentos de patología sin
  ningún dato de paciente. Ante la duda, no lo pases.
- `--sobrescribir` reemplaza el `.md` existente; sin él se crea `nombre-2.md`.

El script devuelve `enmascarados: N`. Si `N > 0`, el documento traía identificadores directos
(RUT, nombre, teléfono, correo, N° de ficha) y quedaron como `[DATO PERSONAL OMITIDO]`. En ese
caso el front-matter **no** guarda el nombre del archivo original, solo su hash: el nombre de
archivo también es PHI.

### Paso 2 — Revisión del `.md`

Abre el `.md` generado y arregla lo que el conversor no puede saber. Esto es lo que falla de
verdad en documentos reales, en orden de frecuencia:

1. **Títulos que no eran títulos.** Word usa negrita en vez de estilos de encabezado más
   seguido de lo que debería. Si ves párrafos en negrita que estructuran el documento,
   conviértelos en `##`/`###` según su nivel.
2. **Figuras sin pie.** El script solo pega el pie cuando el párrafo siguiente empieza por
   "Figura/Fig./Tabla/Gráfico". Si una figura quedó con alt genérico (`Figura 3`), escribe un
   pie descriptivo: qué muestra, no "imagen del documento".
3. **Tablas descuadradas.** Las celdas combinadas de Word se repiten al aplanarse. Revisa
   cabeceras duplicadas y colapsa lo que corresponda.
4. **Listas anidadas.** La numeración de Word puede reiniciarse por sección; verifica que la
   secuencia del `.md` sea la del documento.

### Paso 3 — Front-matter y enlaces de bóveda

El script escribe un front-matter mínimo. Complétalo con lo que hace navegable la bóveda:

```yaml
---
titulo: "Miastenia gravis — resumen clínico"
tipo: resumen-clinico
origen: docx
fecha_conversion: 2026-08-30
sha256_origen: ef8f70406ae03b3b
figuras: 4
tablas: 2
deidentificado: true
tags: [brain, resumen-clinico]          # añade la patología y el sistema: [miastenia, union-neuromuscular]
---
```

Añade a `tags` la patología y su dominio. Si la bóveda ya tiene una nota del mismo tema,
enlázala con `[[nota]]` en una línea `Relacionado:` al final — la utilidad del brain está en
los enlaces, no en la acumulación.

### Paso 4 — Verificación antes de cerrar

No des por buena la conversión sin comprobar estas cuatro cosas:

- el `.md` abre en la bóveda y **todas** las figuras se ven (rutas relativas correctas);
- el número de figuras del `.md` coincide con el del Word;
- no quedó ningún identificador de paciente (busca `RUT`, `ficha`, `@`, teléfonos);
- el documento conserva sus secciones (definición, clínica, diagnóstico, tratamiento…).

Si algo falla, corrígelo en el `.md`; no vuelvas a correr el script sobre el mismo destino sin
`--sobrescribir` o quedarán duplicados `nombre-2.md`.

## Límites conocidos

Declarados de frente (R12), porque se descubren solo al usar el script sobre documentos reales:

- **Ecuaciones OMML** (editor de ecuaciones de Word) no se convierten a LaTeX: se pierden. Si
  el documento tiene fórmulas, transcríbelas a `$…$` a mano.
- **Cuadros de texto y SmartArt** viven fuera del flujo del cuerpo: sus imágenes se extraen,
  pero el texto que contienen puede quedar fuera de orden.
- **Celdas combinadas** se aplanan repitiendo contenido.
- **Control de cambios**: se exporta el texto final; los comentarios de revisión se ignoran.
- **Escaneos incrustados**: si el Word es una foto de un documento, sale un `.md` con una
  figura y sin texto. El script lo avisa en `advertencias`; eso pide OCR, no conversión.

## Notas de seguridad

- **De-identificación por defecto** (R8). Solo se desactiva con `--sin-deidentificar` y bajo
  criterio explícito de Cristian para documentos sin PHI.
- El enmascarado cubre identificadores **directos** (RUT, nombre en campo, teléfono, correo,
  ficha). No detecta PHI narrativa ("el hijo del alcalde de…"). Si el documento es un caso
  clínico real, léelo antes de publicarlo en cualquier destino compartido.
- Todo ocurre en el PC: el script no hace red. Nada del contenido llega al VPS ni a n8n
  (el flujo solo recibe contadores).
- Escribir en OneDrive es una acción con efecto persistente: si vas a sobrescribir un `.md`
  existente, avisa antes (Gate 2).
