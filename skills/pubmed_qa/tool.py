"""Skill pubmed_qa — preguntas científicas respondidas con abstracts libres (PubMed + Europe PMC).

Registra dos herramientas en el ToolRegistry (tools/registry.py descubre register_skill):

- pubmed_qa: pregunta -> paquete de evidencia en markdown + reglas de redacción, para que el
  agente redacte la respuesta con citas [PMID:x].
- pubmed_qa_verificar: respuesta redactada -> informe anti-alucinación y, si pasa, la respuesta
  final con referencias Vancouver generadas desde los metadatos reales.

La lógica vive en scripts/pubmed_qa.py (también usable como CLI). Solo lectura hacia NCBI y
Europe PMC; los paquetes se guardan en ~/.cache/harness/pubmed_qa/.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

_CORE_PATH = Path(__file__).resolve().parent / "scripts" / "pubmed_qa.py"
_MOD_NAME = "harness_pubmed_qa_core"


def _core() -> ModuleType:
    """Carga scripts/pubmed_qa.py una sola vez (registrado en sys.modules por las dataclasses)."""
    mod = sys.modules.get(_MOD_NAME)
    if mod is None:
        spec = importlib.util.spec_from_file_location(_MOD_NAME, _CORE_PATH)
        if spec is None or spec.loader is None:
            raise ImportError(f"No se pudo cargar {_CORE_PATH}")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[_MOD_NAME] = mod
        try:
            spec.loader.exec_module(mod)
        except Exception:
            sys.modules.pop(_MOD_NAME, None)
            raise
    return mod


def pubmed_qa(args: dict) -> str:
    core = _core()
    pregunta = str(args.get("pregunta", "")).strip()
    if not pregunta:
        return "ERROR: falta 'pregunta'."
    try:
        cfg = core.Config.desde_entorno(
            n=int(args.get("n", 10)),
            desde=int(args.get("desde", 2000)),
            europepmc=bool(args.get("europepmc", True)),
        )
        paquete = core.construir_paquete(pregunta, args.get("query") or None, cfg)
        out = core.guardar_paquete(paquete)
    except core.ErrorRed as exc:
        return f"ERROR de red: {exc}"
    except (ValueError, OSError) as exc:  # incluye ErrorPrivacidad (R8)
        return f"ERROR: {exc}"
    if not paquete.registros:
        avisos = "\n".join(paquete.metricas.get("avisos", []))
        return (
            "Sin fuentes relevantes para esta query. Reformúlala en inglés (sinónimos, MeSH, "
            f"menos conceptos) antes de concluir que no hay evidencia.\n{avisos}"
        )
    return (
        core.paquete_markdown(paquete)
        + "\n---\n"
        + core.cargar_formato()
        + f"\n---\nPaquete guardado en: {out}\n"
        "Redacta la respuesta con esas reglas y verifícala con la herramienta "
        f"pubmed_qa_verificar (paquete='{out}') antes de entregarla."
    )


def pubmed_qa_verificar(args: dict) -> str:
    core = _core()
    respuesta = str(args.get("respuesta", "")).strip()
    ruta = Path(str(args.get("paquete", ""))).expanduser()
    if not respuesta or not str(args.get("paquete", "")).strip():
        return "ERROR: faltan 'respuesta' y/o 'paquete'."
    base = core.DEFAULT_OUT_BASE.resolve()
    destino = ruta.resolve()
    if destino != base and base not in destino.parents:
        return f"ERROR: el paquete debe estar dentro de {base}."
    try:
        paquete = core.cargar_paquete(destino)
        v = core.verificar(respuesta, paquete)
        (destino / "respuesta.md").write_text(respuesta + "\n", encoding="utf-8")
        informe = core.informe_verificacion(v)
        if not v.ok:
            return informe + "\n\nCorrige la respuesta y vuelve a verificar."
        final = core.anexar_referencias(respuesta, paquete, v)
        (destino / "respuesta_final.md").write_text(final, encoding="utf-8")
    except (ValueError, OSError) as exc:
        return f"ERROR: {exc}"
    return informe + "\n\n---\n" + final


def register_skill(reg) -> None:
    reg.register(
        "pubmed_qa",
        "Responde una pregunta científica con evidencia: busca abstracts libres en PubMed y "
        "Europe PMC, los rankea por relevancia y nivel de evidencia y devuelve el paquete con "
        "las reglas para redactar la respuesta con citas [PMID:x]. Query en inglés; sin datos "
        "de pacientes.",
        {
            "type": "object",
            "properties": {
                "pregunta": {"type": "string", "description": "Pregunta del usuario."},
                "query": {
                    "type": "string",
                    "description": "Query PubMed en inglés (conceptos con AND, sinónimos con OR).",
                },
                "n": {"type": "integer", "description": "Fuentes en el paquete (default 10)."},
                "desde": {"type": "integer", "description": "Año mínimo (default 2000)."},
                "europepmc": {"type": "boolean", "description": "Completar con Europe PMC."},
            },
            "required": ["pregunta"],
        },
        pubmed_qa,
    )
    reg.register(
        "pubmed_qa_verificar",
        "Verifica una respuesta redactada con pubmed_qa: rechaza citas fuera del paquete, "
        "señala cifras que no están en los abstracts citados y oraciones sin cita; si pasa, "
        "devuelve la respuesta final con referencias Vancouver.",
        {
            "type": "object",
            "properties": {
                "respuesta": {"type": "string", "description": "Respuesta en markdown."},
                "paquete": {
                    "type": "string",
                    "description": "Ruta del paquete devuelta por pubmed_qa.",
                },
            },
            "required": ["respuesta", "paquete"],
        },
        pubmed_qa_verificar,
    )
