"""Detección del CLI de Hermes agent en el PC.

El worker no asume cómo se invoca Hermes: la línea de comandos se declara en el YAML. Este
módulo la encuentra. Busca por orden de utilidad —lo que ya está corriendo manda sobre lo que
está instalado— y termina proponiendo el bloque `hermes:` listo para pegar.

    python hermes_brain.py detectar
    python hermes_brain.py detectar --nombre nous --puertos --salida informe.txt

No modifica nada: solo lee el sistema y ejecuta `--help` sobre lo que encuentra.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

SUFIJOS_WIN = (".exe", ".cmd", ".bat", ".ps1", ".com")
BANDERAS_AYUDA = ("--help", "-h", "help")
PUERTOS_HABITUALES = (1234, 3000, 4891, 5000, 8000, 8080, 8888, 11434)
RUTAS_SONDA = ("/v1/models", "/api/tags", "/health", "/")
PROFUNDIDAD = 4
CARPETAS_IGNORADAS = {"node_modules", "__pycache__", ".git", "venv", ".venv", "site-packages",
                      "Windows", "WinSxS", "Installer", "assembly", "DriverStore"}


@dataclass
class Candidato:
    ruta: str
    origen: str
    ayuda: str = ""
    codigo: int | None = None


@dataclass
class Hallazgos:
    ejecutables: list[Candidato] = field(default_factory=list)
    procesos: list[str] = field(default_factory=list)
    paquetes: list[str] = field(default_factory=list)
    registro: list[str] = field(default_factory=list)
    puertos: list[str] = field(default_factory=list)
    notas: list[str] = field(default_factory=list)


def _correr(cmd: list[str], timeout: int = 25) -> tuple[int, str]:
    """Ejecuta un comando de solo lectura y devuelve (código, salida). Nunca lanza."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace", check=False)
        return p.returncode, ((p.stdout or "") + (p.stderr or "")).strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return -1, f"({type(exc).__name__})"


# --------------------------------------------------------------------------- fuentes
def nombres_probables(base: str) -> list[str]:
    variantes = [base, f"{base}-agent", f"{base}agent", f"{base}-cli", f"{base}cli", f"{base}d"]
    if os.name != "nt":
        return variantes
    return [v + s for v in variantes for s in ("", *SUFIJOS_WIN)]


def en_path(base: str) -> list[Candidato]:
    """Lo primero que hay que mirar: ¿está en el PATH?"""
    vistos: list[Candidato] = []
    for nombre in nombres_probables(base):
        ruta = shutil.which(nombre)
        if ruta and ruta not in [c.ruta for c in vistos]:
            vistos.append(Candidato(ruta, "PATH"))
    if os.name == "nt":
        codigo, salida = _correr(["where.exe", f"{base}*"])
        if codigo == 0:
            for linea in salida.splitlines():
                linea = linea.strip()
                if linea and linea not in [c.ruta for c in vistos]:
                    vistos.append(Candidato(linea, "where.exe"))
    return vistos


def raices_de_busqueda() -> list[Path]:
    """Carpetas donde un agente de escritorio se instala de verdad."""
    if os.name == "nt":
        env = os.environ
        crudas = [env.get("LOCALAPPDATA", "") + r"\Programs", env.get("LOCALAPPDATA", ""),
                  env.get("APPDATA", ""), env.get("ProgramFiles", ""),
                  env.get("ProgramFiles(x86)", ""), env.get("USERPROFILE", ""),
                  env.get("USERPROFILE", "") + r"\Desktop",
                  env.get("USERPROFILE", "") + r"\Documents", "C:\\opt", "C:\\tools"]
    else:
        casa = str(Path.home())
        crudas = ["/usr/local/bin", "/opt", f"{casa}/.local/bin", f"{casa}/bin", f"{casa}/Apps", casa]
    return [Path(r) for r in dict.fromkeys(filter(None, crudas)) if Path(r).is_dir()]


def en_carpetas(base: str, raices: list[Path], profundidad: int = PROFUNDIDAD) -> list[Candidato]:
    """Recorrido acotado: sin esto, buscar en C:\\ entero tarda más que preguntar."""
    encontrados: list[Candidato] = []
    ejecutables = SUFIJOS_WIN if os.name == "nt" else ("", ".sh", ".py", ".AppImage")
    for raiz in raices:
        base_nivel = len(raiz.parts)
        for carpeta, subcarpetas, archivos in os.walk(raiz, onerror=lambda _e: None):
            actual = Path(carpeta)
            if len(actual.parts) - base_nivel >= profundidad:
                subcarpetas.clear()
                continue
            subcarpetas[:] = [s for s in subcarpetas
                              if s not in CARPETAS_IGNORADAS and not s.startswith(".")]
            for archivo in archivos:
                nombre = archivo.lower()
                if not nombre.startswith(base.lower()):
                    continue
                if os.name == "nt" and not nombre.endswith(SUFIJOS_WIN):
                    continue
                if os.name != "nt":
                    completo = actual / archivo
                    if not (os.access(completo, os.X_OK) or nombre.endswith(ejecutables[1:])):
                        continue
                ruta = str(actual / archivo)
                if ruta not in [c.ruta for c in encontrados]:
                    encontrados.append(Candidato(ruta, f"carpeta {raiz}"))
    return encontrados


def procesos(base: str) -> list[str]:
    """La señal más valiosa: si Hermes está abierto, su línea de comandos es la respuesta."""
    if os.name == "nt":
        ps = ("Get-CimInstance Win32_Process | "
              f"Where-Object {{ $_.Name -match '{base}' -or $_.CommandLine -match '{base}' }} | "
              "Select-Object ProcessId,Name,CommandLine | ConvertTo-Json -Compress")
        codigo, salida = _correr(["powershell", "-NoProfile", "-Command", ps], timeout=40)
        if codigo != 0 or not salida or salida.startswith("("):
            return []
        try:
            datos = json.loads(salida)
        except json.JSONDecodeError:
            return [salida[:500]]
        datos = datos if isinstance(datos, list) else [datos]
        return [f"PID {d.get('ProcessId')}  {d.get('CommandLine') or d.get('Name')}" for d in datos]
    codigo, salida = _correr(["ps", "-eo", "pid,args"], timeout=20)
    if codigo != 0:
        return []
    return [l.strip() for l in salida.splitlines()[1:]
            if base.lower() in l.lower() and "hermes_brain" not in l and "detectar" not in l]


def paquetes(base: str) -> list[str]:
    """Instalado como paquete: npm global, pipx o pip."""
    salidas: list[str] = []
    for etiqueta, cmd in (("npm -g", ["npm", "ls", "-g", "--depth=0"]),
                          ("pipx", ["pipx", "list", "--short"]),
                          ("pip", ["pip", "list", "--format=freeze"])):
        codigo, salida = _correr(cmd, timeout=60)
        if codigo != 0:
            continue
        for linea in salida.splitlines():
            if base.lower() in linea.lower():
                salidas.append(f"{etiqueta}: {linea.strip()}")
    return salidas


def registro(base: str) -> list[str]:
    """Programas instalados que mencionan el nombre (solo Windows)."""
    if os.name != "nt":
        return []
    encontrados: list[str] = []
    for llave in (r"HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall",
                  r"HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall"):
        codigo, salida = _correr(["reg", "query", llave, "/s", "/f", base, "/t", "REG_SZ"], timeout=60)
        if codigo == 0:
            encontrados += [l.strip() for l in salida.splitlines()
                            if base.lower() in l.lower() and l.strip()]
    return encontrados[:20]


def puertos_locales(puertos=PUERTOS_HABITUALES) -> list[str]:
    """Por si Hermes no es un CLI sino un servicio local con API HTTP."""
    try:
        import urllib.error
        import urllib.request
    except ImportError:  # pragma: no cover
        return []
    vivos: list[str] = []
    for puerto in puertos:
        for ruta in RUTAS_SONDA:
            url = f"http://127.0.0.1:{puerto}{ruta}"
            try:
                # Solo 127.0.0.1: sondear la propia máquina, nunca una URL de fuera.
                with urllib.request.urlopen(url, timeout=1.5) as r:
                    cuerpo = r.read(300).decode("utf-8", "replace").replace("\n", " ")
                vivos.append(f"{url} → {r.status} {cuerpo[:160]}")
                break
            except urllib.error.HTTPError as exc:
                vivos.append(f"{url} → HTTP {exc.code} (algo escucha en el puerto)")
                break
            except OSError:        # puerto cerrado o sin respuesta: es el caso normal
                continue
    return vivos


def pedir_ayuda(candidato: Candidato, timeout: int = 25) -> Candidato:
    """Prueba `--help`, `-h` y `help` hasta que uno devuelva algo con forma de ayuda."""
    for bandera in BANDERAS_AYUDA:
        codigo, salida = _correr([candidato.ruta, bandera], timeout=timeout)
        if salida and not salida.startswith("(") and len(salida) > 40:
            candidato.ayuda, candidato.codigo = salida[:4000], codigo
            return candidato
    candidato.ayuda = "(no respondió a --help / -h / help)"
    return candidato


# --------------------------------------------------------------------------- informe
def detectar(base: str = "hermes", con_ayuda: bool = True, con_puertos: bool = False,
             profundidad: int = PROFUNDIDAD) -> Hallazgos:
    h = Hallazgos()
    h.ejecutables = en_path(base)
    rutas = {c.ruta for c in h.ejecutables}
    h.ejecutables += [c for c in en_carpetas(base, raices_de_busqueda(), profundidad)
                      if c.ruta not in rutas]
    h.procesos = procesos(base)
    h.paquetes = paquetes(base)
    h.registro = registro(base)
    if con_puertos:
        h.puertos = puertos_locales()
    if con_ayuda:
        h.ejecutables = [pedir_ayuda(c) for c in h.ejecutables[:8]]
    if not (h.ejecutables or h.procesos or h.paquetes or h.registro):
        h.notas.append(
            f"No apareció nada con el nombre «{base}». Prueba con otro nombre "
            "(--nombre nous, --nombre agent, el nombre del .exe que abres a diario) "
            "o mira las notas del informe.")
    return h


def formatear(h: Hallazgos, base: str) -> str:
    cabecera = (f"Detección de «{base}» en {platform.node()} "
                f"({platform.system()} {platform.release()})")
    lineas = [cabecera, "=" * 78, ""]

    def bloque(titulo: str, filas: list[str], vacio: str) -> None:
        lineas.append(f"## {titulo}")
        lineas.extend([f"  {f}" for f in filas] if filas else [f"  {vacio}"])
        lineas.append("")

    bloque("Procesos en ejecución", h.procesos,
           "ninguno (si Hermes está abierto, ábrelo y repite: su línea de comandos es la pista firme)")
    lineas.append("## Ejecutables encontrados")
    if not h.ejecutables:
        lineas += ["  ninguno", ""]
    for c in h.ejecutables:
        lineas += [f"  {c.ruta}    [{c.origen}]"]
        if c.ayuda:
            lineas += ["  " + "-" * 74]
            lineas += [f"  | {l}" for l in c.ayuda.splitlines()[:60]]
            lineas += ["  " + "-" * 74]
        lineas.append("")
    bloque("Paquetes instalados", h.paquetes, "nada en npm -g, pipx ni pip")
    bloque("Registro de Windows", h.registro, "sin coincidencias (o no es Windows)")
    if h.puertos:
        bloque("Servicios HTTP locales", h.puertos, "-")
    for nota in h.notas:
        lineas += [f"! {nota}", ""]

    lineas += [
        "## Qué hacer con esto",
        "",
        "  1. Pega este informe completo en el chat: con la ayuda del CLI se calibra el",
        "     bloque `hermes:` del YAML sin adivinar.",
        "  2. Si no salió nada, revisa el acceso directo con el que abres Hermes:",
        "     clic derecho → Propiedades → «Destino» trae la ruta real del ejecutable.",
        "  3. Si Hermes solo tiene ventana y ningún CLI, dilo: el adaptador necesita otra",
        "     vía (API HTTP local) y eso se resuelve distinto.",
        "",
        "## Bloque a completar en hermes_brain.yaml",
        "",
        "  hermes:",
        "    comando: [\"<ruta del ejecutable>\", \"<subcomando de chat>\",",
        "              \"--skill\", \"{skill}\", \"--attach\", \"{archivo}\",",
        "              \"--prompt-file\", \"{prompt_file}\", \"--output-json\", \"{salida_json}\"]",
        "",
        "  Los marcadores entre llaves los rellena el worker; los nombres de las banderas",
        "  salen de la ayuda de arriba.",
    ]
    return "\n".join(lineas)
