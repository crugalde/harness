# Estado — Wiki LLM sobre el harness (segundo cerebro en Obsidian)

**Última actualización:** 2026-08-27
**Rama:** `claude/obsidian-wiki-llm-repo-3z704t` (7 commits, sin PR abierto) · último: `e50b377`
**Objetivo:** que el harness construya y mantenga un wiki de conocimiento en la bóveda
`obsidianneuro`, siguiendo el patrón *LLM Wiki*: fuentes crudas inmutables → páginas escritas y
mantenidas por el agente → un schema que gobierna cómo se ingiere, se consulta y se limpia.

---

## Qué existe ahora

### 1. El schema — `wiki/AGENTS.md`

La pieza central. Hereda del `AGENTS.md` raíz (R1–R13, gates, seguridad) sin relajar nada.
Define front-matter obligatorio, convenciones de enlace y citación, y las tres operaciones:

- **ingest** — una fuente toca 5–15 páginas, no una («archivar ≠ ingerir»); las contradicciones
  se registran, no se sobrescriben en silencio.
- **query** — responder citando páginas y declarando huecos; archivar la respuesta si tiene
  estructura propia.
- **lint** — contradicciones, afirmaciones superadas, huérfanas, conceptos sin página.

`wiki/CLAUDE.md` es solo un puntero para que Claude Code lo cargue al entrar a `wiki/`.

### 2. El CLI — `tools/wiki.py` (stdlib, sin dependencias)

```bash
python tools/wiki.py scan --dir "icloud/neuromuscular" --split   # paso 0: inventariar
python tools/wiki.py index                                        # catálogo desde el front-matter
python tools/wiki.py lint                                         # enlaces rotos, huérfanas, esbozos
python tools/wiki.py search "bloqueo de conduccion"               # BM25 sobre las páginas
python tools/wiki.py log ingest "<titulo>" --detalle "..."        # bitácora append-only
python tools/wiki.py stats | pack --out ctx.md | init --dest <ruta>
```

`scan` extrae DOI y título de PDF (pypdf), `.docx`, `.pptx`, `.md`/`.txt`; detecta duplicados por
hash; marca lo ya ingerido cruzando nombres y DOI contra `wiki/fuentes/`; y arma
`wiki/fuentes/Cola de ingesta <tema>.md`. Con `--split`, una cola por subcarpeta más
`Colas de ingesta.md` como índice. **Multiplataforma**: rutas de iCloud de macOS y Windows, y
detección de archivos que están solo en la nube (ficheros `.icloud` en macOS, atributos de recall
en Windows — no se abren, para no disparar descargas masivas).

### 3. La skill — `skills/wiki_llm/`

`wiki_search`, `wiki_read`, `wiki_scan`, `wiki_index`, `wiki_lint`, `wiki_log`. Las descubre
`tools/registry.py` sola. **No crea páginas a propósito**: escribirlas pasa por el flujo de
ingest del schema, para que ninguna entre saltándose la propagación.

### 4. El wiki — `wiki/`, 12 páginas, todo CIDP

| Sección | Páginas |
|---|---|
| `fuentes/` | Guía EAN/PNS 2021 · Epidemiología de Santiago (Cea 2020) · Cola de ingesta CIDP |
| `entidades/` | CIDP · Nodopatías autoinmunes |
| `conceptos/` | Variantes · Criterios electrodiagnósticos · Categorías diagnósticas · Tratamiento |
| `sintesis/` | Diagnóstico diferencial · Preguntas abiertas · Práctica clínica en Chile |

112 enlaces, 0 rotos, 0 huérfanas. Bitácora en `wiki/log.md`, catálogo en `wiki/index.md`.

---

## Decisiones tomadas (y por qué)

- **El wiki vive dentro del repo** (`harness/wiki/`). Como el repo está dentro de la bóveda,
  Obsidian lo ve sin sincronizar nada y queda versionado en git.
- **Nombres de archivo sin tildes**; el título con acentos va en el front-matter y el `# H1`
  (macOS normaliza distinto que Linux y rompe git y los wikilinks).
- **`raw/` y `projects/` son inmutables** para el agente: la trazabilidad de todo lo derivado
  depende de que las fuentes no se toquen.
- **`scan` no ingiere**, solo inventaría. Leer e integrar es trabajo de juicio y se hace de a una
  fuente; un resumen automático produce páginas que nadie consulta dos veces.
- **Una cola con otro `origen` no se sobrescribe sin `--force`** — así el inventario de CIDP hecho
  desde Google Drive no se pierde al escanear la carpeta local.
- **El vault se podó a CIDP** (2026-08-27): se borraron 19 páginas de Tolosa-Hunt y DAPT porque
  esos clusters no se entrelazaban entre sí y solo los unía el índice. Las fuentes crudas siguen
  en `projects/`; `git revert d805bbd` devuelve las páginas.
- **Los esbozos se declaran**: una página escrita desde un resumen y no desde el paper se marca
  `estado: esbozo` y el lint la cobra. (Los 6 ensayos de DAPT eran de esos, y se fueron en la poda.)

## Arreglos al harness hechos de paso

- `tools/loop.py` — `load_skills()` leía el front-matter con un regex de una línea, así que un
  `description: >-` multilínea llegaba al contexto como `">-"`. `uc_library_fetcher` quedaba sin
  descripción y, por tanto, invisible para el router. Corregido con `skill_frontmatter()`, con
  test de regresión que falla contra la implementación anterior (`01afc84`).

---

## Pendientes

1. **Correr el scan sobre la carpeta real.** Aún no se ha inventariado
   `icloud/neuromuscular` desde la máquina del usuario; la cola de CIDP actual viene de Google
   Drive (25 archivos, 20 pendientes), no de iCloud.
2. **Ingerir las fuentes de más peso de la cola CIDP**, en este orden: Continuum «CIDP and Its
   Variants» y Allen 2017 (contrastan [[Variantes de CIDP]]) · Broers 2022, Países Bajos
   (contrasta la epidemiología chilena) · clases del Dr. Fadic (docencia local UC; hay PDF, DOCX
   y audio del mismo contenido: ingerir **una** versión) · guías propias de polineuropatías
   desmielinizantes (material no publicado: separar lo respaldado de la práctica local).
3. **Transcripción de audio** (diferida por el usuario): `CIDP.m4a` y `CIDP 2.m4a` son clases que
   no existen en otro formato. Whisper local → `.txt` junto al audio → se ingiere como texto.
4. **OCR** para PDFs escaneados, marcando en la cola los que no tienen capa de texto.
5. **Cron de lint mensual** que deje las acciones propuestas en `wiki/log.md`
   (`tools/schedule_distill.py` sirve de referencia).
6. **Huecos de conocimiento abiertos** en `wiki/sintesis/Preguntas abiertas.md`: cobertura de
   IVIg en el sistema público chileno, disponibilidad de anticuerpos nodo-paranodales, y la
   especificidad real de los criterios EAN/PNS 2021.

### Deuda técnica del repo (detectada, no tocada)

`loop.py` y `compose.py` duplicados en la raíz. El `loop.py` de la raíz es una copia vieja sin el
subagente `home`: le faltan sus palabras clave en el router y `ha_call_service`/`ha_lights_off`
en `GATED_TOOLS`. Nadie los importa — `tools/` es el runtime real. Son código muerto con guardas
de seguridad más débiles que las vigentes: conviene borrarlos.

---

## Entorno

- El usuario trabaja en **macOS y Windows**. El CLI cubre ambos.
- **No clonar el repo dentro de iCloud Drive en Windows**: iCloud sincroniza `.git/` y corrompe
  el índice. Clonar fuera (p. ej. `C:\dev\harness`) y usar
  `python tools/wiki.py sync --dest "<vault>\Harness"`.
- `pip install pypdf` para que los PDF den título y DOI; sin él, el scan degrada avisando.
- Antes de escanear: bajar a disco lo que la nube tenga como marcador (macOS `brctl download`;
  Windows, clic derecho → «Mantener siempre en este dispositivo»).

## Siguiente acción

Correr en la máquina del usuario:

```bash
python tools/wiki.py scan --dir "icloud/neuromuscular" --split
```

y, con los conteos por tema a la vista, elegir la primera fuente pendiente e ingerirla siguiendo
`wiki/AGENTS.md` §4. Regla del schema: **una fuente a la vez**, empezando por guías y revisiones,
que son las que siembran más páginas y fijan el vocabulario del tema.
