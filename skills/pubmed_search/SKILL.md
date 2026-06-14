---
name: pubmed_search
description: Busca y resume artículos en PubMed (Entrez); devuelve PMIDs, título y abstract. Úsala cuando se pida evidencia, papers o revisión bibliográfica.
---

# PubMed search

## Cuándo usar

Cuando el agente (típicamente `research`, a veces `med` o `signals`) necesita evidencia
publicada: localizar artículos, recuperar abstracts o construir una bibliografía. No la uses
para hechos volátiles no bibliográficos (precios, cargos) — eso es búsqueda web (R1).

## Entradas / salidas

- Entrada: `query` (términos MeSH o texto libre), `retmax` (n máximo, default 10).
- Salida: lista de `{pmid, title, abstract}`. Nunca inventa PMIDs (R2).

## Herramienta

Registra en el `ToolRegistry` de `loop.py`:

```python
from skills.pubmed_search.tool import pubmed_search   # implementación con Biopython/Entrez
reg.register(
    "pubmed_search",
    "Busca en PubMed y devuelve PMIDs, título y abstract.",
    {"type": "object",
     "properties": {"query": {"type": "string"}, "retmax": {"type": "integer"}},
     "required": ["query"]},
    pubmed_search,
)
```

`tool.py` debe usar `Entrez.email` desde una variable de entorno y respetar el rate limit de
NCBI. Devuelve texto plano o JSON serializable.

## Notas de seguridad

- Sin datos de pacientes en las queries (R8): casos clínicos siempre anonimizados.
- Solo lectura: no escribe en NCBI ni en ningún destino. No requiere gate.
