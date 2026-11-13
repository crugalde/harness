# Contexto global del orquestador

> Memoria persistente compartida por Claude Code y Hermes. El orquestador la lee al iniciar y
> solo la modifica con confirmación del usuario. Sin datos de pacientes ni credenciales.

## Perfil y preferencias

- Usuario: médico neurólogo, nivel especialista. Responder en español, trato entre pares, sin
  explicar terminología básica.
- Contexto clínico por defecto: Chile (disponibilidad de fármacos, ISP, GES).
- Código: Python, completo y ejecutable.
- Formato preferido de entregables: `.md` (compatible con Obsidian); PDF cuando se pida.
- Citas: Vancouver con PMID/DOI.

## Objetivos activos

| Objetivo | Entregable | Estado | Fecha |
|---|---|---|---|
| _(vacío)_ | | | |

## Equipos

- **Hermes Agent (local):** PC de escritorio con NVIDIA de 16 GB de VRAM y 64 GB de RAM. No
  corre en el Mac. Modelo recomendado: Qwen3.6 35B-A3B (MoE) del runtime local de Hermes, uno
  solo para todos los perfiles. Detalle real del equipo: `scripts/diagnostico_pc.py`.

## Rutas frecuentes

- PDFs locales: `workspace/papers_locales/`
- Bóveda de Obsidian: variable `OBSIDIAN_VAULT` en `~/.config/harness/.env`
- Zotero: API local en `localhost:23119` (Zotero abierto)

## Glosario y convenciones

| Término | Uso en este proyecto |
|---|---|
| Gate 1 / Gate 2 | Aprobación de alcance / de selección de estudios |
| Slug | Nombre de carpeta o archivo en kebab-case, sin acentos |
