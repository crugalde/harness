---
name: publicar
description: "Publica una revisión o cualquier Markdown en sus dos destinos: una bóveda de Obsidian (nota con front-matter YAML, adjuntos copiados y enlaces reescritos, más un índice enlazado) y una database de Notion (página con propiedades rellenadas contra el esquema real de la database, y el cuerpo convertido a bloques). Úsala cuando se pida publicar, subir, mandar o guardar algo en Obsidian o en Notion, pasar una revisión a la bóveda, dejar un informe en la base de datos de papers, o cerrar el flujo paper → markdown → publicación. Encadena después de paper_review y de pdf_markdown."
---

# publicar

Cierra el flujo: `paper_review` produce `revision.md` + `revision.json`, y esta skill los
lleva a donde se leen. El motor está en `tools/publicar.py`.

## Cuándo usar

- "Sube esta revisión a Notion" · "déjalo en la bóveda de Obsidian" · "publícalo en neuro"
- Como último eslabón de: `pdf_markdown` → `paper_review` → **`publicar`**.

**No la uses** para escribir un `.docx` (`build_docx`) ni para crear una página suelta de
Notion sin database: esta skill publica *en una database*, que es lo que permite filtrar
y ordenar después.

## Los dos destinos no se parecen

| | Obsidian | Notion |
|---|---|---|
| Qué es | una carpeta de archivos | una API |
| Publicar es | escribir un `.md` y copiar adjuntos | crear una página con **propiedades** |
| Verificable | sí, mirando el disco | por la URL que devuelve |
| Riesgo | escribir donde no toca | ensuciar el esquema de la database |

**Obsidian.** Escribe solo dentro de la subcarpeta destino (`Revisiones` por defecto);
nunca toca el resto de la bóveda. Los adjuntos van a `<subcarpeta>/adjuntos/` con nombre
único **sin espacios** —`![](ruta con espacios.png)` no es Markdown válido y la figura se
vería rota aunque el archivo esté copiado— y los enlaces del Markdown se reescriben a esa
ruta. El índice enlaza cada nota con `[[wikilink]]` y no duplica al republicar.

**Notion.** Se consulta el esquema de la database y **solo se rellena lo que existe, con el
tipo que tiene**: una propiedad inventada hace que la API rechace la página entera. Y
nunca se inventan opciones de `select`/`multi_select`, porque enviar un valor nuevo **crea
la opción** y ensuciaría de forma permanente una lista curada a mano.

## Entradas / salidas

- **Entrada:** carpeta de `paper_review` (o un `.md` suelto), `vault`, `database`.
- **Salida:** ruta de la nota creada y/o URL de la página de Notion.
- **Configuración por entorno:** `OBSIDIAN_VAULT`, `OBSIDIAN_SUBCARPETA`, `NOTION_TOKEN`,
  `NOTION_DATABASE_ID`.

```bash
python tools/publicar.py obsidian revision/ --vault "C:/Users/Usuario/Obsidian/neuro"
python tools/publicar.py notion   revision/ --database <id>
python tools/publicar.py ambos    revision/ --dry-run    # sin escribir ni publicar
```

## Herramientas

Registra `publicar_obsidian` y `publicar_notion` (ver `tool.py`). Sin dependencias: Notion
se habla por HTTP con la stdlib.

## Notas de seguridad

- **Publicar es una acción con efecto externo (R9).** Una página de Notion queda en el
  workspace y una nota queda en la bóveda. Confirma el destino antes de publicar: si no
  te dieron `database` o `vault`, pregúntalos en vez de elegir uno.
- **R8:** lo que se publica es el texto tal cual. Si la revisión traía PHI que la
  de-identificación de `paper_review` no atrapó, se publica con ella. Revisa antes de
  mandar material clínico a un servicio externo.
- El `--dry-run` muestra qué se escribiría sin tocar disco ni API.
