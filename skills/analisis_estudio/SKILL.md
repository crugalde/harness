---
name: analisis-estudio
description: "Analiza críticamente UN estudio concreto —un paper, una guía, un ensayo— y publica la ficha resultante en Notion de forma automática, en la base «Resumen de estudios» de 📚 Biblioteca de Investigación. Verifica la identificación contra Crossref/PubMed, detecta el diseño, aplica la guía de reporte que le corresponde (SANRA, AMSTAR-2, CONSORT, STROBE, QUADAS-2, AGREE-II, CARE…), califica la confianza global y explica qué cambia para la práctica. Usa esta skill cuando se entregue un PDF, un DOI, un PMID o un enlace a un artículo y se pida 'analiza este estudio', 'qué te parece este paper', 'evalúa esta guía', 'vale la pena?', 'ficha de este artículo', o cuando se marque un paper para análisis en la base «Actualización de estudio». Es sobre UN trabajo: para el estado del arte de un tema completo, esa es medicalinfosummary."
---

# analisis-estudio

Convierte un estudio en una ficha crítica publicada, con un veredicto de calidad defendible y
una respuesta explícita a la única pregunta que importa: **¿esto cambia lo que hago el lunes?**

Tres cosas la separan de un resumen de abstract. **La identificación se verifica** contra
Crossref y PubMed antes de opinar (R2), porque evaluar con la guía de reporte equivocada
invalida todo el juicio que sigue. **La calificación se argumenta ítem por ítem** contra una
guía de reporte nombrada, no se asigna a ojo. Y **la ficha se publica sola**: al terminar ya
existe como fila en Notion, con sus propiedades pobladas, sin un paso manual de copiar y pegar.

## Contexto de uso

El usuario es neurólogo con subespecialidad neuromuscular, en Chile. Escribe en español (R3),
asume contexto clínico chileno y da por conocida la terminología: no expliques qué es un
intervalo de confianza. El nivel es el de un club de revista entre pares — se espera que
señales el defecto que el lector no vio, no que resumas lo que ya leyó.

---

## Dónde viven los archivos

Las fichas **se guardan junto a su PDF**, con el mismo nombre:

```
iCloudDrive/neuromuscular/
├── msa_jtranslmed_2023.pdf              ← el paper
├── msa_jtranslmed_2023.metadatos.json   ← identificación verificada (paso 1)
└── msa_jtranslmed_2023.md               ← la ficha (paso 4)
```

Así el `.md` y su PDF viajan juntos, y la copia en la nube sale gratis por el propio iCloud —
no hay un segundo sitio que sincronizar ni que recordar. **La copia en Notion es la ficha
renderizada, no el archivo**: si quieres el `.md`, está en iCloud.

---

## Flujo

### Paso 0 — ¿Uno o una carpeta entera?

Con **un** estudio, salta al paso 1. Con **una carpeta de PDFs**, corre antes la fase de lote:

```bash
export ENTREZ_EMAIL="cristian.ugalde@gmail.com"
python3 skills/analisis_estudio/scripts/lote_fichas.py \
    "C:/Users/Usuario/iCloudDrive/neuromuscular"
```

Recorre la carpeta y por cada PDF saca el DOI del propio archivo (metadatos XMP, diccionario
Info, o los streams inflados), lo verifica, **deduplica contra Notion** y escribe su
`metadatos.json`. Deja dos salidas: `LOTE.md`, que es la lista de trabajo priorizada, y
`manifiesto.json` para reanudar.

**El lote llega hasta aquí y no más.** Los pasos 2 a 5 siguen siendo de a un paper, y es
deliberado: leer cuarenta papers de corrido degrada el juicio crítico, y peor, obliga a inferir
patología y aspecto en vez de preguntarlos — que es justo lo que fragmenta los filtros de la
base. Lo que el lote te ahorra es la parte determinista y tediosa: saber **qué falta, qué ya
está publicado y qué está bloqueado**, todo de una vez.

Lo que aparece bloqueado en `LOTE.md` se resuelve una sola vez, para toda la tanda:

- **Sin DOI** → crea `<pdf>.doi` con el DOI dentro, o añádelo a «Actualización de estudio»
  (el lote lo busca ahí solo, calzando por `Nombre esperado archivo`).
- **DOI no resuelto** → el aviso trae el DOI extraído; casi siempre viene con un sufijo de más.
- **Falta patología / aspecto** → se completan a mano en cada `metadatos.json`.

Es reanudable: lo ya verificado se salta, así que correrlo dos veces no repite red ni trabajo.

### Paso 1 — Identificación verificada

Antes de leer nada con opinión, fija qué estudio es. Un DOI o un PMID basta (si vienes del
paso 0, esto ya está hecho y el `metadatos.json` está junto al PDF):

```bash
export ENTREZ_EMAIL="cristian.ugalde@gmail.com"
python3 skills/analisis_estudio/scripts/verificar_metadatos.py \
    --doi 10.1186/s12967-023-03905-1 -o <ruta-del-pdf>.metadatos.json
```

Resuelve el identificador que falte, baja título, autores, año y revista de ambas bases,
**reporta las discrepancias en vez de resolverlas en silencio** y propone el diseño desde los
PublicationType de PubMed.

Dos cosas que este paso decide y conviene no delegar al piloto automático:

- **El tipo de estudio propuesto es una hipótesis.** La etiqueta del editor miente seguido: una
  "comprehensive review" sin método de búsqueda declarado es una revisión narrativa, y un
  documento que se autodenomina revisión sistemática pero emite recomendaciones es una guía y se
  evalúa con AGREE-II. Confirma contra el texto y corrige `tipo_estudio` si no calza.
- **Patología, aspecto, calidad y aporte no salen de ninguna base.** `calidad` y `aporte` los
  produces tú al analizar. `patologia` y `aspecto`, si el paper no los explicita, **se preguntan
  al usuario** — nunca se infieren, y sin ellos la publicación se detiene sola.

### Paso 2 — Texto completo

El abstract no trae lo que se evalúa: ni el método de búsqueda, ni el flujo de participantes, ni
las limitaciones, ni el conflicto de interés. Consíguelo antes de calificar.

1. **PDF local**, si el usuario lo aportó. Es la vía normal — deja su ruta en `archivo_local`
   como `file://` para poder reabrirlo desde la fila de Notion.
2. **PMC / acceso abierto**: `mcp__plugin_bio-research_pubmed__get_full_text_article`, que recibe
   `pmc_ids` (no PMIDs). Un artículo por llamada.
3. **Proxy UC** para el resto, con la skill `uc_library_fetcher`. Abre navegador y hace login
   real: pregunta antes de lanzarlo y no lo programes desatendido.

Si solo hay abstract, **se puede analizar igual, pero se declara** (R12): la ficha lo estampa en
el pie y varios ítems de la guía quedan como "no evaluable", no como "adecuado".

### Paso 3 — Guía de reporte según diseño

El diseño manda la guía. `verificar_metadatos.py` ya la propone en `guia_reporte`; el detalle de
qué mirar en cada ítem está en `references/guias_reporte.md`.

| Diseño | Guía |
|---|---|
| Revisión sistemática · Metaanálisis | PRISMA + AMSTAR-2 |
| Guía de práctica clínica | AGREE-II |
| Ensayo aleatorizado | CONSORT + RoB 2 |
| Ensayo no aleatorizado | TREND + ROBINS-I |
| Cohorte · Casos y controles · Transversal | STROBE + Newcastle-Ottawa |
| Precisión diagnóstica | STARD + QUADAS-2 |
| Reporte y serie de casos | CARE |
| Revisión narrativa | SANRA |
| Evaluación económica · Cualitativa · Preclínico | CHEERS · COREQ · ARRIVE |

**La calificación global sale de aplicar la guía, no al revés.** Se califica `Alta`, `Moderada`,
`Baja` o `Críticamente baja` con vocabulario AMSTAR-2/GRADE, y el veredicto va argumentado en un
callout: qué ítem lo hundió y por qué. Una revisión narrativa bien hecha sigue siendo `Baja` —
por su naturaleza, no por defectos de ejecución, y eso se dice con esas palabras.

### Paso 4 — Redacción de la ficha

Sigue `references/plantilla_ficha.md`. Seis secciones, todas obligatorias: identificación,
resumen clínico, evaluación de calidad, discusión y limitaciones, explicación fisiopatológica,
aporte al área.

Escríbela en `<mismo-nombre-que-el-pdf>.md`, junto al PDF.

Reglas que no se negocian:

- **Cifras con su contexto.** Un n, un intervalo de confianza y la población de origen. "Mejoró
  significativamente" sin magnitud no sirve para decidir nada.
- **Nunca inventes datos de identificación** (R2). Salen de `metadatos.json`.
- **Separa lo que el estudio muestra de lo que los autores concluyen.** La distancia entre ambos
  es, muy seguido, el hallazgo de la ficha.
- **Aterriza en Chile**: disponibilidad, cobertura, registro ISP. Si no cambia nada aquí, dilo
  con todas sus letras — es una conclusión, no un vacío.

### Paso 5 — Publicación automática en Notion

**Este paso no pregunta.** El destino es fijo y ya está descrito: la base **«Resumen de
estudios»** dentro de **📚 Biblioteca de Investigación**. No hay que buscar la página, ni elegir
padre, ni confirmar ubicación. Al terminar la ficha, se publica:

```bash
python3 skills/analisis_estudio/scripts/publicar_notion.py <paper>.md \
    --metadatos <paper>.metadatos.json
```

Eso es todo el paso. El script hace lo demás: mapea las once propiedades, convierte el markdown
a bloques de la API, crea la fila con su icono, y escribe el enlace de vuelta en «Actualización
de estudio» si el paper venía de la vigilancia semanal.

**Es idempotente.** Busca por DOI/PMID antes de crear: si la ficha ya existe la actualiza en vez
de duplicarla. Correr la skill dos veces sobre el mismo paper no ensucia la base, así que
reanalizar tras conseguir el texto completo es seguro.

**Cuatro cosas detienen la publicación**, y las cuatro devuelven un mensaje accionable en vez de
publicar algo malo:

1. `metadatos.json` sin `verificado: true` — no se contrastó contra Crossref/PubMed.
2. Falta un campo obligatorio. Típicamente `patologia` o `aspecto`: pregúntalos y reintenta.
3. Un valor de `select` que no existe en la base — una patología nueva, por ejemplo. **Añade la
   opción a la base primero**; el script no la inventa a propósito, porque una opción inventada
   fragmenta los filtros en silencio.
4. Sin DOI ni PMID: la ficha quedaría sin enlace y sin clave para detectar duplicados.

Si el caso es real y la verificación no se pudo hacer, `--sin-verificar` publica igual y estampa
el aviso de **METADATOS NUNCA VERIFICADOS** en la cabecera de la ficha. Es la salida honesta: la
ficha existe, y el lector sabe que su identificación es provisional.

**Dos vías, según el entorno.** Con `NOTION_TOKEN` en `~/.config/harness/.env`, el script publica
solo por la API REST — es la vía automática, sin modelo de por medio. Sin token, emite el payload
para el conector:

```bash
python3 skills/analisis_estudio/scripts/publicar_notion.py <paper>.md \
    --metadatos <paper>.metadatos.json --payload-mcp <paper>.payload.json
```

y se publica con **una sola** llamada a `notion-create-pages` pasando ese objeto tal cual. No
queda ninguna decisión pendiente en esa llamada: parent, propiedades, icono y cuerpo ya vienen
resueltos.

`--dry-run` valida y resume sin escribir nada. Úsalo si cambiaste la plantilla y quieres ver
cuántos bloques salen antes de publicar.

Al terminar, devuelve **la URL** y cierra con el veredicto en dos líneas: la calificación con el
ítem que la determinó, y si cambia o no la conducta. Eso es lo que se lee primero.

### Paso 6 — El PDF

El script no sube el PDF: la API de archivos de Notion es un flujo aparte y un `file://` de
iCloud no viaja. La ficha deja la ruta local en `Archivo`, que es clicable en el escritorio. Si
quieres el PDF adjunto en la fila, súbelo a la propiedad `PDF` desde Notion — una vez, a mano.
Dilo al entregar en lugar de dejar el campo vacío sin explicación.

---

## Errores que arruinan la ficha

**Aceptar la etiqueta del editor.** "Systematic review" en el título no hace sistemática una
revisión. Si no declara bases, fechas y criterios de elegibilidad, es narrativa y se evalúa con
SANRA. Ese solo cambio mueve la calificación global dos escalones.

**Calificar sin nombrar el ítem.** "Calidad baja por limitaciones metodológicas" no es una
evaluación, es una impresión. La evaluación dice qué ítem de qué guía falló y qué consecuencia
tiene para leer los resultados.

**Confundir significancia con relevancia.** Un p < 0,001 sobre una diferencia de 1,2 puntos en
una escala de 60 no cambia ninguna conducta. Nombra la magnitud y la mínima diferencia
clínicamente importante cuando exista.

**Resumir la discusión de los autores como si fuera el hallazgo.** La sección de discusión de la
ficha es tuya: es donde se dice qué se sobreinterpretó, qué confusor quedó sin controlar y qué
pesa más de lo que el texto sugiere.

**Publicar sin verificar la identificación.** Es el error que envenena la base: una ficha con el
año o el diseño equivocado se cita después como si fuera correcta.

---

## Seguridad y límites

- **Sin datos de pacientes** en la ficha ni en las consultas (R8). El análisis es sobre el
  estudio publicado, no sobre casos del usuario.
- **Verifica dosis y disponibilidad** contra la fuente vigente antes de afirmarlas (R1).
- **Credenciales**: `NOTION_TOKEN`, `UC_USER` y `UC_PASSWORD` viven solo en
  `~/.config/harness/.env`. Nunca por el chat, nunca en la ficha, nunca en un log.
- **Excepción documentada al Gate 2.** La política raíz exige aprobación antes de escribir en un
  destino persistente. Aquí el usuario levantó ese gate **para este destino y solo para él**: la
  publicación es el propósito de la skill. Lo que sustituye al gate humano son las cuatro
  detenciones del paso 5, la idempotencia por DOI y el hecho de que una fila de Notion se archiva
  en un clic. Cualquier otro destino —otra base, otra página, borrar filas— **sigue con gate**.
- La ficha es material de estudio para un profesional. No sustituye el juicio clínico.

## Archivos de la skill

| Archivo | Cuándo usarlo |
|---|---|
| `scripts/lote_fichas.py` | Paso 0, solo con una carpeta. Inventaría, verifica y deduplica; deja `LOTE.md`. |
| `scripts/verificar_metadatos.py` | Paso 1, siempre primero. Crossref + PubMed → `metadatos.json`. |
| `references/guias_reporte.md` | Paso 3. Qué mirar en cada ítem de cada guía de reporte. |
| `references/plantilla_ficha.md` | Paso 4. Las seis secciones y las restricciones de Notion. |
| `scripts/publicar_notion.py` | Paso 5. Publica solo. Valida, deduplica y enlaza de vuelta. |
| `scripts/notion_md.py` | Lo usa el publicador; suelto sirve para depurar el renderizado. |
| `references/destino_notion.md` | Los identificadores del destino y el esquema de la base. |
| `references/hermes.md` | Cómo instalarla y correrla en la workstation con Hermes. |
| `evals/evals.json` | Solo si vas a modificar la skill: casos de prueba con sus aserciones. |

Los cuatro scripts corren con el `python3` del sistema, sin `pip install` — solo biblioteca
estándar. Es deliberado: una skill que exige instalar dependencias falla justo cuando la
necesitas.
