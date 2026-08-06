---
name: medicalinfosummary
description: "Construye una síntesis clínica completa y referenciada sobre una enfermedad o tema médico: definición, epidemiología, fisiopatología, clínica, diagnóstico (gold standard y exámenes complementarios), diagnóstico diferencial, controversias y vacíos de evidencia, y tratamiento. Busca en PubMed, Consensus y Semantic Scholar restringido a literatura posterior al año 2000, prioriza guías de sociedades y revisiones sistemáticas, resuelve paywalls con el proxy institucional UC, y entrega un archivo .md listo para pegar en Notion con diagramas Mermaid y figuras de acceso abierto. Usa esta skill siempre que se pida 'hazme un resumen de', 'revisa el tema', 'qué se sabe de', 'actualízame sobre', 'prepara para el examen', 'estado del arte de', o se mencione una enfermedad y se quiera entenderla a fondo — aunque no se diga explícitamente 'informe' ni 'revisión'. También cuando se pida solo una parte (fisiopatología, diferencial, tratamiento) de una entidad clínica concreta."
---

# medicalinfosummary

Produce una síntesis clínica de nivel especialista sobre una enfermedad, con las ocho secciones
que Cristian usa para estudiar y para preparar docencia, entregada como `.md` pegable en Notion.

La diferencia entre esta skill y pedirle un resumen a un modelo cualquiera está en tres cosas:
**todo afirmado se rastrea a una fuente real y verificable** (R2), **la sección de controversias
y vacíos existe y es sustantiva** — es la que un manual nunca trae y la que decide conductas en
casos difíciles —, y **el informe declara sus propios límites** en vez de aparentar completitud
(R12).

## Contexto de uso

El usuario es neurólogo con subespecialidad neuromuscular, en Chile. Escribe siempre en español
(R3), asume contexto clínico chileno (disponibilidad, FONASA/ISAPRE, registro ISP, Ley Ricarte
Soto) y da por conocida la terminología médica: no expliques qué es una sensibilidad ni definas
"idiopático". El nivel es el de una revisión para pares, no el de material para pacientes.

---

## Flujo

### Paso 1 — Encuadre (una sola tanda de preguntas)

Antes de buscar nada, pregunta **las tres cosas juntas en un solo turno**. Ir de a una pregunta
por vez desperdicia el tiempo del usuario y rompe el ritmo de trabajo:

1. **¿Hay un enfoque específico donde poner el énfasis?** Ofrece opciones concretas derivadas
   del tema, no una pregunta abierta. Para miastenia gravis, por ejemplo: "¿crisis miasténica,
   terapias anti-complemento y anti-FcRn, MG seronegativa, o panorama general?". Un enfoque
   nombrado activa un estrato de búsqueda dedicado y reordena el peso de las secciones; sin él,
   el informe sale equilibrado.
2. **¿Dónde guardo el `.md`?** Propón una ruta por defecto —
   `projects/<tema-en-kebab-case>/<tema>_sintesis.md` dentro del repo harness — y deja que la
   cambie.
3. **Profundidad.** Por defecto 25–40 fuentes con prioridad a guías y revisiones sistemáticas
   (~10–15 min). Confírmalo y menciona las alternativas rápida (10–15) y exhaustiva (50+) por si
   quiere otra cosa.

Si el tema es ambiguo (siglas como "ELA" vs "EM", o entidades con nombres solapados),
desambigua aquí mismo. Buscar sobre la enfermedad equivocada cuesta quince minutos.

### Paso 2 — Cosecha de fuentes

Corre el harvester, que hace la parte determinista y siempre igual: búsqueda PubMed por
estratos de evidencia, filtro por año, metadatos completos y resolución de acceso abierto.

```bash
export ENTREZ_EMAIL="cristian.ugalde@gmail.com"
python3 skills/medicalinfosummary/scripts/buscar_fuentes.py "<término en inglés>" \
    --enfoque "<énfasis en inglés, si lo hay>" \
    --n 35 \
    --out <directorio-de-salida>/fuentes
```

Busca **en inglés** aunque el informe salga en español: PubMed indexa MeSH en inglés y una query
en español devuelve una fracción de los resultados. Usa el término MeSH cuando lo sepas.

Deja `ENTREZ_EMAIL` exportado — sin él NCBI limita las peticiones y Unpaywall no responde. Si
existe `NCBI_API_KEY` en el entorno, el script la toma solo y va tres veces más rápido.

El script genera `fuentes.json`, `bibliografia.md` y `resumen_busqueda.md` (este último trae la
lista de DOIs tras paywall, lista para el paso 3).

**Complementa con las otras bases.** El script cubre PubMed; estas tres aportan lo que PubMed no
tiene y valen la llamada:

- `mcp__plugin_bio-research_consensus__search` — devuelve el consenso de la literatura sobre una
  pregunta concreta, con el grado de acuerdo entre estudios. Excelente insumo para la sección de
  controversias: pregunta directamente lo que está en disputa.
- `mcp__1e2b88ef-*__semanticSearch` — búsqueda semántica, encuentra trabajos que no comparten
  vocabulario con tu query. Útil cuando el tema tiene nomenclatura cambiante.
- `mcp__plugin_bio-research_c-trials__search_trials` con `status=RECRUITING` — ensayos en curso,
  que es literalmente la sección "qué viene" del bloque 7.

**Sobre Google Scholar:** no tiene API pública y bloquea el scraping automatizado, así que no
puedo consultarlo programáticamente. Dilo de frente si el usuario lo pide en vez de simular que
lo hiciste. Lo que sí cubre ese hueco: `WebSearch` para guías de sociedades (AAN, EAN, EFNS,
MGFA, ESC, IDSA) y documentos MINSAL, que a menudo **no están indexados en PubMed** y son
justamente las fuentes de mayor peso. Búscalas siempre — es el complemento más importante al
harvester. Y si el usuario quiere resultados concretos de Scholar, que pegue la lista y los
proceso.

**Poda antes de seguir.** El orden por relevancia de PubMed cuela resultados tangenciales: una
búsqueda de miastenia devuelve guías de timoma y de bloqueo neuromuscular. Revisa títulos y
abstracts, descarta lo que no corresponde, y si un estrato quedó flaco (frecuente con
`guideline[pt]`, cuya cobertura es irregular) compénsalo con búsqueda web dirigida.

### Paso 3 — Texto completo

El abstract alcanza para ubicar un estudio, no para extraer un dato operativo. Sensibilidades,
dosis, criterios de inclusión y limitaciones metodológicas viven en el cuerpo del artículo.
Consigue el texto completo de las fuentes que van a sostener afirmaciones concretas.

**Orden de intentos:**

1. **PMC / open access** — `mcp__plugin_bio-research_pubmed__get_full_text_article`. Gratis e
   inmediato, pero ojo con tres detalles que se descubren solo al usarla:
   - Recibe **`pmc_ids`** (`["PMC12500283"]`), **no** PMIDs. El `pmcid` ya viene en
     `fuentes.json`; si falta, conviértelo con `convert_article_ids`.
   - Devuelve el texto y los **pies** de figura, pero **no las URLs de las imágenes**. Para
     enlazar una figura hay que ir a la página del artículo (ver `references/figuras.md`).
   - **Borra los marcadores de cita del cuerpo**: los `[12]` del original llegan como `[]`
     vacíos. Sirve para leer y extraer datos, no para rastrear de qué referencia sale una
     afirmación concreta. Cuando eso importe, abre el PDF o el HTML del artículo.

   Esta herramienta exige atribución: al usar sus contenidos, menciona PubMed como fuente e
   incluye el DOI **como enlace** (`[DOI](https://doi.org/...)`). La plantilla ya lo cumple si
   pones los DOIs enlazados en la bibliografía.

   **Pide un artículo por llamada.** Dos textos completos juntos superan el límite de tokens
   de una respuesta y el resultado se desvía a un archivo. Si eso pasa, no reintentes: el
   archivo es JSON y se recorta mejor con Python que leyéndolo entero —

   ```python
   import json
   d = json.load(open("<ruta-del-archivo>"))
   t = d["articles"][0]["full_text"]
   # primero el índice de secciones, después solo el trozo que interesa
   print([l for l in t.split("\n") if l.strip() and len(l.strip()) < 70][:40])
   i = t.find("Recommendations"); print(t[i:i+8000])
   ```
2. **Proxy UC** para lo que quedó tras paywall. `resumen_busqueda.md` ya trae los DOIs
   agrupados. Usa la skill `uc_library_fetcher`:

   ```bash
   uv run --with playwright skills/uc_library_fetcher/scripts/fetch_uc_paper.py \
       "10.1002/mus.27832" "<directorio>/pdfs/mus27832.pdf"
   ```

   Requiere `UC_USER` y `UC_PASSWORD` en `~/.config/harness/.env` (el script los carga solo vía
   `tools/env_loader.py`). **Si faltan, nunca pidas las credenciales por el chat** — entrega los
   comandos que documenta `uc_library_fetcher/SKILL.md` para que las guarde él mismo.

   **Abre una ventana de navegador visible y hace un login institucional real.** Eso tiene dos
   consecuencias para el flujo: pregúntale al usuario antes de lanzarlo por lotes, y no lo
   programes desatendido — si el selector del PDF falla, el script espera 2 minutos a que
   alguien descargue a mano.
   **Springer descarga solo; Elsevier/ScienceDirect no** — encuentra el botón pero la descarga
   expira, porque sirve el PDF tras una página con antibot. Para DOIs `10.1016/*` cuenta con
   descarga manual desde la ventana ya autenticada. Detalle por editorial en
   `uc_library_fetcher/SKILL.md`.

3. **Carga manual** para lo que no se consigue por ninguna vía automatizada. Siempre queda un
   resto —ScienceDirect, NEJM, NCCN— y no es un resto cualquiera: suelen ser los ECAs pivotales,
   justo las fuentes de donde salen las cifras. En vez de resignarte al abstract, pídeselas al
   usuario de forma accionable:

   ```bash
   python3 skills/medicalinfosummary/scripts/pdfs_pendientes.py listar <dir-proyecto> --top 12
   ```

   Genera `pdfs/PENDIENTES.md`: una tabla priorizada **por relevancia al tema y luego por
   estrato**, con un nombre de archivo exacto para cada uno y el enlace para abrirlo. El usuario
   descarga desde el navegador con su sesión UC y deja los PDFs en `pdfs/` con ese nombre.

   Cuando avise, incorpóralos:

   ```bash
   python3 skills/medicalinfosummary/scripts/pdfs_pendientes.py revisar <dir-proyecto>
   ```

   Valida que sean PDFs reales —un HTML de error renombrado a `.pdf` es el fallo silencioso más
   común—, marca `acceso: "manual"` en `fuentes.json` y avisa de los archivos con nombre que no
   corresponde a ninguna fuente.

   El listado separa además las fuentes **fuera de tema**, que el orden por relevancia de PubMed
   cuela (una búsqueda de miastenia devuelve guías de timoma). No hagas que el usuario las
   busque: descártalas del informe.

4. **Si aun así falta**, no insistas más de dos veces por artículo. Trabaja con el abstract y
   **anótalo**: en el informe, esa fuente se marca como leída solo por resumen. Es una
   limitación real que el lector necesita saber, y va en «Qué quedó fuera».

No descargues los 35 PDFs. Prioriza: guías completas siempre, revisiones sistemáticas siempre,
originales solo si de ellos sale un número que vas a citar.

### Paso 4 — Análisis

Con las fuentes en mano, extrae por sección antes de redactar. Dos cosas que separan una
síntesis útil de una acumulación de resúmenes:

**Cuando las fuentes discrepan, no promedies.** Si una guía europea y una americana recomiendan
distinto, o dos estudios dan sensibilidades incompatibles, eso *es* el hallazgo. Preséntalo como
discrepancia, con quién sostiene cada postura y desde qué evidencia. Promediar en una frase
neutra destruye la información más valiosa que tienes.

**Distingue el peso de cada afirmación.** No es lo mismo una recomendación de un meta-análisis de
ECAs que una de una serie retrospectiva de 34 pacientes. El lector necesita esa diferencia para
decidir. Nómbrala donde importe, con el diseño y el n.

### Paso 5 — Redacción

Sigue `references/plantilla_informe.md` — trae la estructura de las ocho secciones y las
restricciones de markdown que Notion impone al pegar (solo tres niveles de encabezado, sin
LaTeX, tablas simples).

Reglas que no se negocian:

- **Cada afirmación sustantiva lleva su `[n]`.** Cifras, sensibilidades, dosis, recomendaciones.
  Un párrafo sin marcas de referencia es un párrafo que el lector no puede verificar.
- **Nunca inventes PMIDs, DOIs, autores ni títulos** (R2). Todos salen de `fuentes.json`. Si
  necesitas citar algo que no cosechaste, búscalo primero y verifica que existe.
- **Las ocho secciones van siempre.** Si una no tiene evidencia, escribe el vacío explícitamente.
- Español, terminología técnica sin glosa, contexto chileno donde aplique.

### Paso 6 — Figuras

Sigue `references/figuras.md`. Como mínimo: un Mermaid del mecanismo fisiopatológico y otro del
algoritmo diagnóstico. Suma figuras de acceso abierto (PMC OA subset, Wikimedia Commons) solo
cuando la licencia lo permita y la URL responda `200` — un enlace muerto en Notion es peor que
no poner figura.

### Paso 7 — Verificación

Antes de entregar, corre el verificador. Cuesta segundos y comprueba lo único que destruye la
confianza en una síntesis clínica: una referencia que no existe o que no dice lo que afirmas.

```bash
ENTREZ_EMAIL="cristian.ugalde@gmail.com" \
python3 skills/medicalinfosummary/scripts/verificar_informe.py <informe.md> \
    --fuentes <directorio>/fuentes/fuentes.json
```

Comprueba las 8 secciones, la compatibilidad con Notion (sin `####`, sin `$$`, tablas
alineadas), la sintaxis Mermaid, que toda cita `[n]` tenga referencia **y viceversa**, que
ninguna fuente sea anterior a 2000, que todos los PMIDs existan y que **el título citado
coincida con el de PubMed**, y que las URLs de imagen respondan 200.

Cómo leer los dos avisos que salen a menudo:

- *"Toda referencia se cita en el cuerpo"* con una lista → esas referencias son relleno.
  Cítalas donde de verdad sostengan algo, o **quítalas**. Una bibliografía inflada aparenta un
  respaldo que el texto no tiene.
- *"PMIDs citados provienen de la cosecha: n externos"* → normal si añadiste guías por búsqueda
  web. Verifica cada una a mano contra PubMed antes de darla por buena.

Arregla lo que salga en rojo y vuelve a correrlo. No entregues con fallos pendientes.

### Paso 8 — Entrega y salida a Notion

Escribe el `.md` en la ruta acordada. Junto a él deja `fuentes/` con el JSON y la bibliografía,
que es lo que permite retomar el tema después sin rehacer la búsqueda.

El destino final es Notion, y hay **dos vías**. Pregúntale al usuario cuál quiere; no asumas:

**a) Pegado manual** (sin conector, control total). El `.md` ya cumple las restricciones de la
plantilla, así que se pega y funciona. Es la vía por defecto si no hay conector de Notion activo.

**b) Publicación directa** vía el conector de Notion, cuando esté disponible.

> **El markdown que se pega y el que acepta la API no son el mismo formato.** La diferencia es
> silenciosa: la API acepta el texto sin error y lo renderiza mal. La divergencia más grande es
> que **la API no entiende tablas de pipes** — hay que convertirlas a XML `<table>/<tr>/<td>`.

Convierte con el script antes de publicar; hace las tres transformaciones necesarias:

```bash
python3 skills/medicalinfosummary/scripts/md_a_notion.py <informe.md> -o <informe_notion.md>
python3 skills/medicalinfosummary/scripts/md_a_notion.py <informe.md> --titulo   # para properties.title
```

1. Tablas de pipes → XML `<table>` · 2. Mermaid: `\n` → `<br>` en las etiquetas · 3. Citas `[n]`
→ `\[n\]` (los corchetes son sintaxis reservada) · 4. Fusiona líneas `>` consecutivas en una sola
cita con `<br>`, porque **cada línea `>` es un blockquote independiente** y un encabezado de
cuatro líneas se rompe en cuatro cajas.

Si necesitas algo que el script no cubre (callouts, columnas, toggles), lee el spec con
`notion-fetch` sobre `notion://docs/enhanced-markdown-spec`. **No adivines la sintaxis.**

Flujo:

1. `notion-search` con el nombre de la página o base donde va, para conseguir el `page_id` /
   `data_source_id` del padre. Si el usuario no dice dónde, **pregúntale** — publicar en la raíz
   del workspace crea una página privada suelta que después hay que ordenar a mano.
2. `notion-create-pages` con:
   - `parent`: `{type: "page_id", page_id: "..."}` (o `data_source_id` si va dentro de una base)
   - `pages`: `[{properties: {title: "<Enfermedad> — síntesis clínica"}, content: "<cuerpo>", icon: "🧠"}]`
   - **El título no se repite dentro de `content`**: va solo en `properties.title`, o queda
     duplicado. El script ya lo quita.
3. **Vuelve a leer la página con `notion-fetch`** y confirma que las tablas, el mermaid y las
   imágenes quedaron bien. Es la única forma de detectar un renderizado roto; publicar sin
   verificar deja errores que el usuario descubre después.
4. Devuelve la URL.

Mejoras opcionales que rinden en Notion y el script no hace solo: convertir los avisos
importantes en `<callout icon="⚠️" color="red_bg">` en vez de blockquote, y poner un `icon` a la
página.

Publicar en Notion es una acción con efecto externo sobre el espacio de trabajo del usuario:
**confirma antes de crear la página**, y no la crees si el destino no está claro.

Cierra el mensaje con: cuántas fuentes entraron y de qué tipo, qué quedó fuera y por qué, y las
dos o tres cosas que más te llamaron la atención al leer — controversias, evidencia más débil de
lo esperado, guías desactualizadas. Ese comentario en corto suele ser lo primero que se lee.

---

## Errores que arruinan el informe

**Sección 7 rellena de trivialidades.** "Se necesitan más estudios" no es un vacío de evidencia,
es una muletilla. El vacío real se nombra: qué pregunta clínica concreta no tiene respuesta, qué
estudio haría falta, qué se hace mientras tanto y con qué fundamento.

**Recomendaciones sin nivel de evidencia.** "Se recomienda X" obliga al lector a ir a buscar de
dónde sale. "Recomendado por la guía AAN 2020 con nivel B, sobre dos ECAs abiertos con n
combinado de 180 [4,7]" se puede usar directamente.

**Confundir frecuente con característico.** Un síntoma presente en el 80% de los casos puede no
servir para el diagnóstico si también aparece en todos los diferenciales. Separa siempre
frecuencia de valor discriminante.

**Citar el abstract como si fuera el artículo.** Si no leíste el texto completo, dilo. Los
abstracts omiten sistemáticamente las limitaciones.

**Datos extranjeros presentados como locales.** Una prevalencia noruega no es la prevalencia
chilena. Nombra la población de origen siempre.

---

## Seguridad y límites

- **Sin datos de pacientes** en queries ni en el informe (R8). Si el usuario trae un caso, la
  búsqueda va sobre la entidad clínica, nunca sobre datos identificables.
- **Verifica dosis y disponibilidad** contra la fuente vigente antes de afirmarlas (R1). El
  informe lleva la advertencia de posología de la plantilla.
- **Credenciales UC**: nunca por el chat; solo vía `~/.config/harness/.env`.
- Esta síntesis es material de estudio y referencia para un profesional. No sustituye el juicio
  clínico ni el protocolo institucional.

## Archivos de la skill

| Archivo | Cuándo usarlo |
|---|---|
| `scripts/buscar_fuentes.py` | Paso 2. Cosecha PubMed por estratos. Sin dependencias; corre con el python3 del sistema. |
| `scripts/pdfs_pendientes.py` | Paso 3. `listar` prioriza lo que el usuario debe aportar; `revisar` lo incorpora. |
| `references/plantilla_informe.md` | Antes de redactar (paso 5). Estructura y reglas de Notion. |
| `references/figuras.md` | Al armar diagramas e imágenes (paso 6). Patrones Mermaid y licencias. |
| `scripts/verificar_informe.py` | Paso 7, siempre antes de entregar. Verifica PMIDs, estructura, Mermaid e imágenes. |
| `scripts/md_a_notion.py` | Paso 8, solo si se publica por API. Markdown estándar → Notion-flavored. |
| `evals/evals.json` | Solo si vas a modificar la skill: casos de prueba con sus aserciones. |

Los cuatro scripts corren con el `python3` del sistema, sin `pip install` — solo biblioteca
estándar. Es deliberado: el entorno de este harness no tiene `requests` ni `biopython`, y una
skill que exige instalar dependencias falla justo cuando la necesitas.
