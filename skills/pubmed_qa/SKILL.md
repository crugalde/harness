---
name: pubmed_qa
description: Responde una pregunta científica o clínica puntual con una síntesis analítica respaldada por abstracts de acceso libre (PubMed + Europe PMC) — busca, rankea por relevancia y nivel de evidencia, redacta con citas [PMID] y verifica que ninguna cita ni cifra sea inventada. Úsala ante "¿qué dice la evidencia sobre…?", "¿es efectivo X en Y?", "¿sirve X para diagnosticar Y?", "¿X aumenta el riesgo de Y?" o cualquier pregunta que deba contestarse con literatura.
---

# pubmed_qa — preguntas científicas respondidas con evidencia verificable

Convierte una pregunta en una **respuesta analizada y resumida**, no en una lista de papers.
Lo central es la respuesta: qué dice la evidencia, con qué magnitud, con qué certeza y con qué
límites — y cada afirmación trazable a un abstract real (R2, R12).

| Skill | Para qué |
|-------|----------|
| `pubmed_qa` (esta) | Una pregunta concreta → respuesta argumentada de 300–700 palabras con citas verificadas |
| `pubmed_search` | Listar PMIDs/abstracts crudos, sin análisis |
| `medicalinfosummary` | Síntesis completa de una enfermedad (8 secciones, 25–40 fuentes) |

## Cuándo usar

- Preguntas de eficacia/seguridad ("¿efgartigimod mejora la MG-ADL?"), rendimiento diagnóstico
  ("¿la ecografía de nervio distingue CIDP de CMT?"), pronóstico, asociación o mecanismo.
- Cuando el usuario pide "respaldo", "evidencia", "qué dicen los estudios" sobre algo acotado.

**No usar** para hechos volátiles no bibliográficos (precios, disponibilidad, cargos → búsqueda
web, R1), ni para datos de un paciente concreto (R8): la pregunta se formula en términos generales.

## Flujo

### 1. Encuadre (preguntar solo si hace falta)

Identifica P-I-C-O (población, intervención/exposición/prueba, comparador, desenlace). Si falta
algo que cambia la búsqueda (p. ej. "¿en qué población?", "¿qué desenlace?"), haz **una** tanda
de preguntas aclaratorias con opciones concretas. Si la pregunta es clara, sigue sin preguntar.

### 2. Paquete de evidencia

Traduce la pregunta a una query PubMed **en inglés** (PubMed indexa en inglés): conceptos
esenciales con AND, sinónimos con OR, MeSH si lo conoces. Sin filtros de fecha/tipo: el script
los agrega.

```bash
python3 skills/pubmed_qa/scripts/pubmed_qa.py buscar \
    "<pregunta tal como la hizo el usuario>" \
    --query "<query PubMed en inglés>" \
    --out projects/<YYYY-MM-DD>_<tema>/pubmed_qa/<slug>
```

El script busca en PubMed (Best Match + estrato de alta evidencia: RS/MA, guías, ECA), completa
con Europe PMC, excluye retractadas, sin abstract, preprints y versiones anteriores de una misma
obra (p. ej. actualizaciones Cochrane), rankea (BM25 × nivel de evidencia × recencia) y guarda
`evidencia.json` + `evidencia.md` con las `--n` (default 10) mejores fuentes. El nivel de
evidencia corrige por título lo que PubMed etiqueta mal: análisis post hoc, de subgrupos o
comparaciones indirectas no cuentan como ECA primario; protocolos y estudios preclínicos pesan
poco. Sin `--query`, una pregunta en español se rechaza (exit 2) en vez de devolver ruido.

Revisa los avisos: si quedan < 3 fuentes o la relevancia es baja, **reformula la query**
(sinónimos, MeSH, quitar un concepto) hasta 2 veces antes de concluir que no hay evidencia.
Opciones útiles: `--desde 2015` (evidencia reciente), `--n 15`, `--incluir-preprints`,
`--sin-europepmc`.

### 3. Análisis y redacción

Lee **todo** `evidencia.md` y redacta `respuesta.md` en el mismo directorio siguiendo
`skills/pubmed_qa/references/formato_respuesta.md` (reglas + plantilla). Resumen de lo esencial:

- Respuesta directa primero, con magnitud y certeza (GRADE simplificado).
- Síntesis temática que pondera por diseño, compara estudios y explica discrepancias.
- Cada oración de *Respuesta breve* y *Síntesis* con cita `[PMID:x]`; cifras copiadas tal cual.
- Declara qué no responde la evidencia y que solo se leyeron abstracts (R12).

### 4. Verificación anti-alucinación (obligatoria)

```bash
python3 skills/pubmed_qa/scripts/pubmed_qa.py verificar --dir <mismo --out>
```

Falla (exit 1) si se cita algo fuera del paquete o faltan secciones. Avisa si hay cifras que no
aparecen en los abstracts citados u oraciones sin cita. Corrige `respuesta.md` y repite hasta que
pase **sin cifras sin respaldo** (o con cada excepción justificada como `(cálculo propio)`).
Al pasar, escribe `respuesta_final.md` = respuesta + Referencias Vancouver generadas desde los
metadatos reales + métricas de búsqueda (D4).

### 5. Entrega

Muestra la respuesta final en el chat. Escribirla en un destino persistente (Notion, carpeta de
proyecto definitiva, repo) pasa por Gate 2.

### Modo autónomo (`--llm`)

Con el SDK instalado (`pip install anthropic`) y credencial de Anthropic, un solo comando busca,
redacta con el modelo usando `formato_respuesta.md` como prompt de sistema, verifica y hace una
ronda de corrección automática:

```bash
python3 skills/pubmed_qa/scripts/pubmed_qa.py buscar "<pregunta>" --llm --out <dir>
```

Sin `--query`, el modelo traduce la pregunta a una query PubMed. Modelo: `--modelo`, o
`PUBMED_QA_MODEL`, o `HARNESS_MODEL`, o `claude-opus-5-5`.

## Herramientas en el harness

`tool.py` registra dos herramientas en el `ToolRegistry` (auto-descubiertas por
`tools/registry.py`):

- `pubmed_qa` — `{pregunta, query?, n?, desde?, europepmc?}` → paquete de evidencia en markdown +
  reglas de redacción. Guarda el paquete en `~/.cache/harness/pubmed_qa/<fecha>_<slug>/`.
- `pubmed_qa_verificar` — `{respuesta, paquete}` → informe de verificación y, si pasa, la
  respuesta final con referencias. Solo acepta paquetes dentro de `~/.cache/harness/pubmed_qa/`.

## Configuración

| Variable | Uso |
|----------|-----|
| `ENTREZ_EMAIL` | Correo de contacto para NCBI (recomendado por sus términos de uso) |
| `NCBI_API_KEY` | Opcional: sube el límite de NCBI de 3 a 10 req/s |
| `PUBMED_QA_MODEL` | Opcional: modelo para `--llm` |
| `ANTHROPIC_API_KEY` | Solo para `--llm` (o un perfil de `ant auth login`) |

Hosts de red necesarios: `eutils.ncbi.nlm.nih.gov`, `www.ebi.ac.uk` (y `api.anthropic.com` para
`--llm`). Sin Europe PMC la skill degrada a solo PubMed con aviso. Buscar y verificar no tienen
dependencias externas (biblioteca estándar).

## Limitaciones conocidas

- Solo abstracts: sin tablas, análisis de subgrupos ni conflictos de interés completos. Para una
  decisión clínica importante, leer el texto completo de las 2–3 fuentes clave (`evidencia.md`
  marca cuáles tienen texto completo libre en PMC).
- El ranking es léxico (BM25): una query mal formulada trae fuentes tangenciales. Por eso el paso
  de revisar avisos y reformular.
- `n` y "k estudios" se extraen con heurísticas del texto del abstract (marcados con ≈).
- El verificador comprueba que las cifras existan en los abstracts citados, no que estén bien
  interpretadas: la lectura crítica sigue siendo tuya.

## Notas de seguridad

- R8: el script bloquea preguntas con RUT, correo, teléfono, fechas completas o números de ficha.
  Aun así, nunca pongas datos de un paciente en la pregunta: formúlala en términos generales.
- Solo lectura hacia NCBI/Europe PMC. No requiere gate; escribir el resultado en un destino
  persistente sí (Gate 2).
