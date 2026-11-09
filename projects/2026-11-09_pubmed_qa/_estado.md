# _estado — skill `pubmed_qa` (preguntas científicas con abstracts libres)

**Objetivo:** skill que responde preguntas científicas con una síntesis analítica respaldada por
abstracts de acceso libre (PubMed + Europe PMC), con citas verificadas automáticamente (R2).

**Última sesión:** 2026-11-09

## Decisiones tomadas

- Gate 1 aprobado por Cristian con énfasis explícito: "lo primordial es la respuesta a la pregunta
  con respaldo de las fuentes; analizar y resumir lo encontrado" → la salida es una respuesta
  argumentada (respuesta breve + síntesis temática + certeza), no una lista de papers.
- Generación **híbrida**: el script busca/rankea/verifica (stdlib); la redacción la hace el agente
  que ejecuta la skill, o la API de Anthropic con `--llm` (SDK oficial, `claude-opus-5-5` por
  defecto, fallback server-side ante rechazos).
- Fuentes: **PubMed + Europe PMC** (Europe PMC degrada a aviso si cae). Preprints excluidos por
  defecto; retractadas y versiones anteriores de una misma obra se excluyen siempre.
- Verificador obligatorio: rechaza citas fuera del paquete; avisa cifras ausentes de los abstracts
  citados y oraciones sin cita; genera referencias Vancouver desde metadatos reales.
- Red del entorno cloud: se creó el entorno personal `harness` con `eutils.ncbi.nlm.nih.gov` y
  `www.ebi.ac.uk` permitidos (el Default bloqueaba NCBI con 403).

## Prueba en vivo (3 preguntas neuromusculares)

| # | Pregunta | Paquete | Verificación |
|---|----------|---------|--------------|
| 01 | Efgartigimod en MG generalizada | 12 fuentes de 94 | Aprobada · 12 citas · cobertura 100% · 0 cifras sin respaldo |
| 02 | Ecografía de nervio en CIDP | 10 de 94 | Aprobada · 10 citas · 100% · 0 |
| 03 | HD-sEMG vs aguja para fasciculaciones en ELA | 10 de 85 | Aprobada · 10 citas · 100% · 0 |

Hallazgos de la prueba que se corrigieron en el código: PubMed etiqueta como ECA análisis post hoc,
comparaciones indirectas y monografías; protocolos de revisión aparecían como RS; versiones Cochrane
duplicadas; estudios en ratones en preguntas clínicas; el separador de oraciones cortaba tras "vs.";
decimales con punto medio (The Lancet) no se reconocían; la sección Funding se descartaba.

## Pendientes

- [ ] Probar `--llm` con credencial real (sin `ANTHROPIC_API_KEY` en esta sesión; la forma de la
      llamada está cubierta por tests con SDK simulado).
- [ ] Definir `ENTREZ_EMAIL` (y opcional `NCBI_API_KEY`) en `~/.config/harness/.env`.
- [ ] Decidir si `pubmed_search` se mantiene o se reemplaza por `pubmed_qa` (hoy conviven).
- [ ] Gate 2: decidir si las 3 respuestas de prueba pasan a Notion o quedan solo aquí.

## Siguiente acción

Usar la skill con una pregunta real del trabajo clínico/investigación y ajustar umbrales
(relevancia mínima 0,15; pesos 0,65 relevancia / 0,30 nivel / 0,05 recencia) si el ranking no
calza con el juicio experto.
