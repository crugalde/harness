"""Carga y validación de la configuración del worker (YAML)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

RUTA_CONFIG_DEFECTO = Path.home() / ".config" / "harness" / "hermes_brain.yaml"
# El conversor vive en el repo, no en el directorio desde el que se lance el worker.
RAIZ_REPO = Path(__file__).resolve().parents[2]
SCRIPT_DOCX_MD = RAIZ_REPO / "skills" / "resumen_clinico_md" / "scripts" / "docx_a_md.py"


class ErrorConfig(RuntimeError):
    """Configuración ausente, mal formada o incoherente."""


@dataclass
class ConfigHermes:
    """Cómo invocar el CLI de Hermes agent. Un proceso = un chat (se abre y se cierra)."""

    comando: list[str]
    comando_cierre: list[str] = field(default_factory=list)
    timeout_s: int = 900
    reintentos: int = 2
    espera_reintento_s: int = 20
    cwd: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    skill_pdf: str = "analisis-estudio"
    skill_docx: str = "resumen-clinico-md"
    prompt_pdf: str = ""
    prompt_docx: str = ""
    # La conversión .docx → .md es determinista y no necesita un agente. Hacerla en el worker
    # evita depender de que el CLI de Hermes pueda ejecutar comandos.
    convertir_docx_en_worker: bool = True
    revisar_docx_con_hermes: bool = True


@dataclass
class ConfigClasificador:
    pdf_umbral_si: float = 4.0
    pdf_umbral_no: float = 2.0
    docx_umbral_si: float = 4.0
    docx_umbral_no: float = 2.0
    paginas_pdf: int = 2
    palabras_docx: int = 1200
    convertir_doc_con_soffice: bool = False
    soffice: str = "soffice"


@dataclass
class ConfigN8n:
    base_url: str = ""
    token: str = ""
    timeout_s: int = 30
    lote_resultados: int = 25
    enviar_nombres: bool = False
    verificar_tls: bool = True


@dataclass
class Config:
    carpetas: list[Path]
    destino_md: Path
    adjuntos: str = "_adjuntos"
    db: Path = Path.home() / ".hermes_brain" / "cola.sqlite3"
    extensiones: list[str] = field(default_factory=lambda: [".pdf", ".docx", ".doc"])
    excluir: list[str] = field(default_factory=lambda: ["~$*", ".*", "_adjuntos"])
    tamano_max_mb: int = 200
    concurrencia: int = 1
    procesar_solo_en_la_nube: bool = False
    hermes: ConfigHermes = field(default_factory=lambda: ConfigHermes(comando=[]))
    clasificador: ConfigClasificador = field(default_factory=ConfigClasificador)
    n8n: ConfigN8n = field(default_factory=ConfigN8n)
    deidentificar: bool = True
    python: str = ""
    script_docx_md: Path = SCRIPT_DOCX_MD

    @property
    def dir_adjuntos(self) -> Path:
        return self.destino_md / self.adjuntos


def _expandir(valor: Any) -> Any:
    """Expande ${VAR} y ~ en strings; recursivo en listas y dicts."""
    if isinstance(valor, str):
        return os.path.expandvars(valor)
    if isinstance(valor, list):
        return [_expandir(v) for v in valor]
    if isinstance(valor, dict):
        return {k: _expandir(v) for k, v in valor.items()}
    return valor


def _ruta(valor: str) -> Path:
    return Path(os.path.expandvars(str(valor))).expanduser()


def cargar(ruta: Path | str | None = None) -> Config:
    """Lee el YAML de configuración y devuelve un `Config` validado.

    Busca en este orden: `ruta` explícita, `$HERMES_BRAIN_CONFIG`, `~/.config/harness/hermes_brain.yaml`.
    """
    try:
        import yaml
    except ImportError as exc:   # se importa aquí para que `detectar` corra sin dependencias
        raise ErrorConfig("Falta PyYAML. Instala con: pip install pyyaml") from exc

    candidata = Path(ruta) if ruta else Path(os.environ.get("HERMES_BRAIN_CONFIG", RUTA_CONFIG_DEFECTO))
    if not candidata.exists():
        raise ErrorConfig(
            f"No existe el archivo de configuración: {candidata}\n"
            "Copia tools/hermes_brain/config.example.yaml y ajústalo."
        )
    datos = _expandir(yaml.safe_load(candidata.read_text(encoding="utf-8")) or {})
    if not isinstance(datos, dict):
        raise ErrorConfig(f"{candidata}: el YAML raíz debe ser un mapa de claves.")

    carpetas = [_ruta(c) for c in datos.get("carpetas", [])]
    if not carpetas:
        raise ErrorConfig("Configura al menos una carpeta en 'carpetas:'.")
    destino = datos.get("destino_md")
    if not destino:
        raise ErrorConfig("Falta 'destino_md:' (carpeta OneDrive donde se guardan los .md).")

    bruto_hermes = datos.get("hermes", {}) or {}
    comando = bruto_hermes.get("comando") or []
    if isinstance(comando, str):
        raise ErrorConfig("'hermes.comando' debe ser una lista de argumentos, no un string.")
    hermes = ConfigHermes(
        comando=list(comando),
        comando_cierre=list(bruto_hermes.get("comando_cierre") or []),
        timeout_s=int(bruto_hermes.get("timeout_s", 900)),
        reintentos=int(bruto_hermes.get("reintentos", 2)),
        espera_reintento_s=int(bruto_hermes.get("espera_reintento_s", 20)),
        cwd=bruto_hermes.get("cwd"),
        env={str(k): str(v) for k, v in (bruto_hermes.get("env") or {}).items()},
        skill_pdf=bruto_hermes.get("skill_pdf", "analisis-estudio"),
        skill_docx=bruto_hermes.get("skill_docx", "resumen-clinico-md"),
        prompt_pdf=bruto_hermes.get("prompt_pdf", ""),
        prompt_docx=bruto_hermes.get("prompt_docx", ""),
        convertir_docx_en_worker=bool(bruto_hermes.get("convertir_docx_en_worker", True)),
        revisar_docx_con_hermes=bool(bruto_hermes.get("revisar_docx_con_hermes", True)),
    )
    if not hermes.comando:
        raise ErrorConfig(
            "Falta 'hermes.comando'. Es la línea de comandos que abre UN chat de Hermes; "
            "acepta los marcadores {archivo}, {skill}, {prompt}, {salida_json}, {destino}."
        )

    bruto_clf = datos.get("clasificador", {}) or {}
    clasificador = ConfigClasificador(
        pdf_umbral_si=float(bruto_clf.get("pdf_umbral_si", 4.0)),
        pdf_umbral_no=float(bruto_clf.get("pdf_umbral_no", 2.0)),
        docx_umbral_si=float(bruto_clf.get("docx_umbral_si", 4.0)),
        docx_umbral_no=float(bruto_clf.get("docx_umbral_no", 2.0)),
        paginas_pdf=int(bruto_clf.get("paginas_pdf", 2)),
        palabras_docx=int(bruto_clf.get("palabras_docx", 1200)),
        convertir_doc_con_soffice=bool(bruto_clf.get("convertir_doc_con_soffice", False)),
        soffice=bruto_clf.get("soffice", "soffice"),
    )

    bruto_n8n = datos.get("n8n", {}) or {}
    n8n = ConfigN8n(
        base_url=str(bruto_n8n.get("base_url", "")).rstrip("/"),
        token=str(bruto_n8n.get("token", "")),
        timeout_s=int(bruto_n8n.get("timeout_s", 30)),
        lote_resultados=max(1, int(bruto_n8n.get("lote_resultados", 25))),
        enviar_nombres=bool(bruto_n8n.get("enviar_nombres", False)),
        verificar_tls=bool(bruto_n8n.get("verificar_tls", True)),
    )
    if n8n.base_url and not n8n.token:
        raise ErrorConfig("Configuraste 'n8n.base_url' sin 'n8n.token'. El webhook exige token.")

    cfg = Config(
        carpetas=carpetas,
        destino_md=_ruta(destino),
        adjuntos=datos.get("adjuntos", "_adjuntos"),
        db=_ruta(datos.get("db", Path.home() / ".hermes_brain" / "cola.sqlite3")),
        extensiones=[e.lower() if e.startswith(".") else f".{e.lower()}" for e in
                     (datos.get("extensiones") or [".pdf", ".docx", ".doc"])],
        excluir=list(datos.get("excluir") or ["~$*", ".*", "_adjuntos"]),
        tamano_max_mb=int(datos.get("tamano_max_mb", 200)),
        concurrencia=max(1, int(datos.get("concurrencia", 1))),
        procesar_solo_en_la_nube=bool(datos.get("procesar_solo_en_la_nube", False)),
        hermes=hermes,
        clasificador=clasificador,
        n8n=n8n,
        deidentificar=bool(datos.get("deidentificar", True)),
        python=datos.get("python", ""),
        script_docx_md=_ruta(datos.get("script_docx_md") or SCRIPT_DOCX_MD),
    )
    return cfg
