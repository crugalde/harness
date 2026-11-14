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

- **Hermes Agent (local):** PC de escritorio, no el Mac. Diagnóstico del 2026-11-14:
  Windows 11 nativo (sin WSL), AMD Ryzen 7 9850X3D (8 núcleos/16 hilos), 64 GB de RAM,
  NVIDIA GeForce RTX 5070 Ti de 16 GB (driver 610.88), 708 GB libres. Repo en
  `C:\Users\Usuario\code\harness`. En ese PC se usa `python`, no `python3`.
- Modelo: Qwen3.6 35B-A3B (MoE) del runtime local de Hermes, uno solo para todos los
  perfiles; ~23 tok/s estimados desbordando a RAM. Hermes estaba en v0.21.0: requiere
  `hermes update` a ≥ 0.22.5 antes de instalar los perfiles.

## Rutas frecuentes

- PDFs locales: `workspace/papers_locales/`
- Bóveda de Obsidian: variable `OBSIDIAN_VAULT` en `~/.config/harness/.env`
- Zotero: API local en `localhost:23119` (Zotero abierto)

## Glosario y convenciones

| Término | Uso en este proyecto |
|---|---|
| Gate 1 / Gate 2 | Aprobación de alcance / de selección de estudios |
| Slug | Nombre de carpeta o archivo en kebab-case, sin acentos |
