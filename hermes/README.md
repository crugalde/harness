# Hermes Agent — instalación local

Los perfiles de Hermes **no se escriben a mano**: `scripts/instalar_hermes.py` los genera desde
`.claude/agents/*.md` y `AGENTS.md`, para que Claude Code y Hermes usen exactamente los mismos
agentes. Verificado contra la documentación de Hermes (repo `NousResearch/hermes-agent`,
noviembre 2026).

## Qué se genera

| Perfil | Rol | SOUL.md desde |
|---|---|---|
| `orquestador` | Enruta y delega con `delegate_task` sobre `profile_routes` | `AGENTS.md` §1 |
| `buscador` | Agente 1 | `.claude/agents/buscador.md` |
| `consultor` | Agente 2 | `.claude/agents/consultor.md` |
| `resumidor` | Agente 3 | `.claude/agents/resumidor.md` |
| `integrador` | Agente 4 | `.claude/agents/integrador.md` |

Cada `config.yaml`: modelo local, `fallback_providers: []`, `memory.write_approval: true`,
`terminal.cwd` = raíz del repo (carga `AGENTS.md`), `skills.external_dirs` = `.claude/skills`.

## Requisitos

1. **Hermes Agent ≥ 0.22.5** (lo exige el plugin `advanced-delegation`). `hermes --version`.
2. **Un modelo local con ≥ 64K de contexto.** Hermes rechaza al arrancar modelos con menos.
   Ollama usa 2048 por defecto, así que crea una variante con más contexto:

   ```bash
   ollama pull gemma4:31b
   printf 'FROM gemma4:31b\nPARAMETER num_ctx 65536\n' > /tmp/Modelfile
   ollama create gemma4-64k -f /tmp/Modelfile
   ```

   `gemma4:31b` es el que la guía de Hermes recomienda hoy para trabajo agéntico local; usa
   otro si tu hardware no da. Estimación orientativa (no de la documentación): un modelo denso
   de ~30B en Q4 con 64K de contexto ocupa del orden de 30–36 GB; uno de ~8B, ~13 GB.
3. El repo clonado **fuera de iCloud** (Hermes salta archivos de contexto que tardan >5 s).

## Instalar

```bash
python3 scripts/instalar_hermes.py --modelo gemma4-64k --solo-generar   # revisar build/hermes/
```

```bash
python3 scripts/instalar_hermes.py --modelo gemma4-64k --instalar-plugin
```

Modelo distinto para el orquestador (conviene el más capaz: enruta y verifica):

```bash
python3 scripts/instalar_hermes.py --modelo qwen3-8b-64k --modelo-orquestador gemma4-64k --instalar-plugin
```

## Usar

```bash
orquestador chat
```

Pídele en lenguaje natural ("busca papers sobre…", "resume este PDF: workspace/papers_locales/x.pdf",
"integra estos 4 resúmenes y dame un PDF con esquema"). Cada agente también funciona solo:
`resumidor chat`, `buscador chat`, etc.

## Límites conocidos

- Los subagentes de Hermes no pueden preguntarte (`clarify` bloqueado): por diseño, todas las
  preguntas y gates las hace el orquestador.
- Los perfiles no aíslan el sistema de archivos: con `terminal.backend: local` el agente tiene
  tus permisos de usuario. No uses `--yolo`.
- Tras cambiar `AGENTS.md` o `.claude/agents/`, vuelve a ejecutar `instalar_hermes.py`. Si
  `hermes profile install` rechaza un perfil existente, actualízalo con
  `hermes profile update <perfil>` o bórralo y reinstálalo (no verificado para orígenes locales).
