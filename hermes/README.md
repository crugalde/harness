# Hermes Agent — instalación local (PC con NVIDIA)

Hermes corre en el PC de escritorio (NVIDIA 16 GB de VRAM + 64 GB de RAM), no en el Mac. Los
perfiles **no se escriben a mano**: `scripts/instalar_hermes.py` los genera desde
`.claude/agents/*.md` y `AGENTS.md`, para que Claude Code y Hermes usen exactamente los mismos
agentes. Verificado contra la documentación y el catálogo de modelos de Hermes (repo
`NousResearch/hermes-agent`, noviembre 2026).

## 1. Diagnóstico del PC (primero)

```bash
python3 scripts/diagnostico_pc.py --out memory/diagnostico_pc.md
```

En Windows nativo usa `python` en lugar de `python3`. Lee GPU, VRAM, driver/CUDA, RAM, CPU,
sistema (Windows, Linux o WSL2), disco y si están Hermes y Ollama, y recomienda el modelo con la
misma fórmula de memoria y velocidad que usa Hermes. Solo lee; no cambia nada.

## 2. Modelo para 16 GB de VRAM + 64 GB de RAM

Hermes exige ≥ 64K de contexto. Con 16 GB ningún modelo del catálogo cabe entero en la GPU, así
que la elección la decide la velocidad al desbordar a RAM:

| Modelo (catálogo Hermes) | Build | Total con 64K | Estimación | Veredicto |
|---|---|---|---|---|
| **Qwen3.6 35B-A3B** (MoE, validado) | 22,7 GB | ~25,5 GB | ~23 tok/s | **Recomendado** |
| Qwen3.8 27B (denso) | 16,5 GB | ~22,3 GB | ~5 tok/s | Inusable para agentes |
| Qwen3.8 Flash Next / DeepSeek V4 Flash | 94–155 GB | — | — | No caben |

Un MoE "A3B" solo lee ~3 GB por token, así que desborda a RAM sin hundirse. Las cifras son la
estimación de Hermes (`catalog.py`: 80 GB/s de RAM); la real depende de tu GPU y de los canales
de memoria. **Un solo modelo para los 5 perfiles:** en 16 GB no caben dos a la vez.

## 3. Requisitos

1. **Hermes Agent ≥ 0.22.5** (lo exige el plugin `advanced-delegation`): `hermes --version`.
2. **Driver NVIDIA** reciente. En Linux, el runtime local de Hermes pide un driver con CUDA 13.
3. **WSL2:** por defecto ve solo una fracción de la RAM. Para desbordar el modelo a RAM, en
   `%UserProfile%\.wslconfig` pon `[wsl2]` y `memory=56GB`, luego `wsl --shutdown`.
4. Repo clonado **fuera de carpetas sincronizadas** (OneDrive, iCloud): Hermes salta archivos
   de contexto que tardan más de 5 s en leerse.

## 4. Instalar

Descarga el modelo con el runtime de Hermes (instala llama.cpp con CUDA y ajusta memoria solo):

```bash
hermes model
```

Elige *Local models* → **Qwen3.6 35B-A3B**. Luego genera y revisa los perfiles:

```bash
python3 scripts/instalar_hermes.py --modelo Qwen3.6-35B-A3B-UD-Q4_K_M --solo-generar
```

E instálalos junto con el plugin de delegación:

```bash
python3 scripts/instalar_hermes.py --modelo Qwen3.6-35B-A3B-UD-Q4_K_M --instalar-plugin
```

Con Ollama en vez del runtime de Hermes: crea una variante con `PARAMETER num_ctx 65536` en un
Modelfile (`ollama create <nombre> -f Modelfile`) y usa
`--proveedor custom --modelo <nombre> --base-url http://localhost:11434/v1`.

## 5. Qué se genera

| Perfil | Rol | SOUL.md desde |
|---|---|---|
| `orquestador` | Enruta y delega con `delegate_task` sobre `profile_routes` | `AGENTS.md` §1 |
| `buscador` | Agente 1 | `.claude/agents/buscador.md` |
| `consultor` | Agente 2 | `.claude/agents/consultor.md` |
| `resumidor` | Agente 3 | `.claude/agents/resumidor.md` |
| `integrador` | Agente 4 | `.claude/agents/integrador.md` |

Cada `config.yaml`: `model.provider: llamacpp` + `local_runtime.enabled: true` (o `custom`),
`fallback_providers: []`, `memory.write_approval: true`, `terminal.cwd` = raíz del repo (carga
`AGENTS.md`), `skills.external_dirs` = `.claude/skills`. El orquestador además lleva
`delegation.max_concurrent_children: 2` (cada subagente simultáneo reserva su propio contexto).

## 6. Usar

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
- **Por verificar en el PC:** que varios perfiles reutilicen el mismo servidor llama.cpp
  (Hermes detecta uno ya corriendo) y la velocidad real con 2 subagentes en paralelo. Si va
  lento, baja a `--max-hijos 1`.
- Tras cambiar `AGENTS.md` o `.claude/agents/`, vuelve a ejecutar `instalar_hermes.py`. Si
  `hermes profile install` rechaza un perfil existente, usa `hermes profile update <perfil>` o
  bórralo y reinstálalo (no verificado para orígenes locales).
