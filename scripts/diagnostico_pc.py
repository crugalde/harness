#!/usr/bin/env python3
"""diagnostico_pc.py — Lee el hardware del PC donde correrá Hermes y recomienda el modelo local.

Detecta sistema (Windows, Linux o WSL2), CPU, RAM, GPU NVIDIA (VRAM, driver, versión CUDA),
espacio en disco y software instalado (hermes, ollama, git). Con eso estima, para cada modelo
del catálogo local de Hermes, si cabe en la GPU con 64K de contexto y a qué velocidad
decodificaría, usando la MISMA fórmula que Hermes (hermes_cli/local_runtime/catalog.py):
    tok/s ≈ ancho_de_banda / (tamaño_del_build × fracción_leída_por_token)
con 1000 GB/s si el modelo cabe entero en la GPU y 80 GB/s si desborda a la RAM.

Uso (en el PC, desde la raíz del repo):
    python3 scripts/diagnostico_pc.py
    python3 scripts/diagnostico_pc.py --out memory/diagnostico_pc.md
    python3 scripts/diagnostico_pc.py --json
En Windows nativo usa `python` o `py` en lugar de `python3`.

Solo lee: no instala ni modifica nada.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CONTEXTO = 65_536  # Hermes exige >= 64K
OVERHEAD_GB = 1.5  # buffers de cómputo + CUDA; margen conservador
FRACCION_RAM_UTIL = 0.75  # deja RAM para el sistema y el navegador
BW_GPU, BW_RAM = 1000.0, 80.0  # GB/s, constantes de Hermes (catalog.py)
UMBRAL_AGRADABLE, UMBRAL_USABLE = 20.0, 6.0  # tok/s, umbrales de Hermes
HERMES_MIN = (0, 22, 5)  # el plugin advanced-delegation lo exige (catálogo de plugins de Hermes)

# Catálogo local de Hermes (hermes_cli/local_runtime/catalog.json, commit 491f984, nov-2026).
# Excluye entradas con recommend: false. kv = capas de atención completa × bytes/token/capa.
CATALOGO = [
    {
        "id": "qwen3.8-27b",
        "nombre": "Qwen3.8 27B (denso)",
        "gguf": "Qwen3.8-27B-UD-Q4_K_M",
        "gb": 16.46,
        "fraccion": 1.0,
        "capas_kv": 16,
        "bytes_capa": 4096,
        "calidad": 90,
        "validado": False,
    },
    {
        "id": "qwen3.6-35b-a3b",
        "nombre": "Qwen3.6 35B-A3B (MoE)",
        "gguf": "Qwen3.6-35B-A3B-UD-Q4_K_M",
        "gb": 22.66,
        "fraccion": 0.15,
        "capas_kv": 10,
        "bytes_capa": 2048,
        "calidad": 80,
        "validado": True,
    },
    {
        "id": "qwen3.8-flash-next",
        "nombre": "Qwen3.8 Flash Next (MoE)",
        "gguf": "Qwen3.8-Flash-Next-UD-IQ4_XS",
        "gb": 93.69,
        "fraccion": 0.08,
        "capas_kv": 12,
        "bytes_capa": 2048,
        "calidad": 95,
        "validado": False,
    },
    {
        "id": "deepseek-v4-flash",
        "nombre": "DeepSeek V4 Flash (MoE)",
        "gguf": "DeepSeek-V4-Flash-0731-UD-Q4_K_XL",
        "gb": 155.1,
        "fraccion": 0.10,
        "capas_kv": 43,
        "bytes_capa": 1152,
        "calidad": 85,
        "validado": False,
    },
]


@dataclass
class GPU:
    nombre: str
    vram_gb: float
    driver: str = ""


@dataclass
class Hardware:
    sistema: str
    detalle_sistema: str
    wsl: bool
    cpu: str
    nucleos: int
    ram_gb: float
    gpus: list[GPU] = field(default_factory=list)
    cuda: str = ""
    disco_libre_gb: float = 0.0
    software: dict[str, str] = field(default_factory=dict)


# ------------------------------------------------------------------------ lectura


def _cmd(args: list[str], timeout: int = 15) -> str | None:
    """stdout de un comando, o None si no existe, falla o se cuelga."""
    try:
        # UTF-8 tolerante: en Windows el default (cp1252) corrompe o rompe la salida de
        # herramientas que escriben UTF-8 (hermes, nvidia-smi con caracteres de caja).
        r = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def parse_cuda(texto: str) -> str:
    """Versión CUDA del driver: 'CUDA Version: 13.4' (cabecera) o 'CUDA Version  : 13.4' (-q)."""
    m = re.search(r"CUDA\s+Version\s*:\s*([\d.]+)", texto, re.I)
    return m.group(1) if m else ""


def parse_version(texto: str) -> tuple[int, int, int] | None:
    """(0, 21, 0) desde 'Hermes Agent v0.21.0 (2026.8.31) ...'."""
    m = re.search(r"v?(\d+)\.(\d+)\.(\d+)", texto)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def _es_wsl() -> bool:
    try:
        return "microsoft" in Path("/proc/version").read_text(encoding="utf-8").lower()
    except OSError:
        return False


def leer_cpu(sistema: str) -> str:
    if sistema == "Linux":
        try:
            for linea in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
                if linea.startswith("model name"):
                    return linea.split(":", 1)[1].strip()
        except OSError:
            pass
    elif sistema == "Windows":
        ps = "(Get-CimInstance Win32_Processor | Select-Object -First 1).Name"
        if salida := _cmd(["powershell", "-NoProfile", "-Command", ps]):
            return salida
    elif sistema == "Darwin":
        if salida := _cmd(["sysctl", "-n", "machdep.cpu.brand_string"]):
            return salida
    return platform.processor() or "desconocida"


def leer_ram_gb(sistema: str) -> float:
    if sistema == "Linux":
        try:
            m = re.search(r"MemTotal:\s+(\d+)", Path("/proc/meminfo").read_text(encoding="utf-8"))
            return int(m.group(1)) / 1024**2 if m else 0.0
        except OSError:
            return 0.0
    if sistema == "Windows":

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        estado = MEMORYSTATUSEX()
        estado.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(estado)):  # type: ignore[attr-defined]
            return estado.ullTotalPhys / 1024**3
        return 0.0
    if salida := _cmd(["sysctl", "-n", "hw.memsize"]):
        return int(salida) / 1024**3
    return 0.0


def parse_nvidia_smi(csv: str) -> list[GPU]:
    """Filas 'nombre, MiB, driver' de nvidia-smi --query-gpu."""
    gpus = []
    for linea in csv.splitlines():
        partes = [p.strip() for p in linea.split(",")]
        if len(partes) >= 3 and partes[1].replace(".", "").isdigit():
            gpus.append(GPU(partes[0], round(float(partes[1]) / 1024, 1), partes[2]))
    return gpus


def leer_gpus() -> tuple[list[GPU], str]:
    candidatos = ["nvidia-smi", "/usr/lib/wsl/lib/nvidia-smi"]
    ejecutable = next((c for c in candidatos if shutil.which(c) or Path(c).is_file()), None)
    if not ejecutable:
        return [], ""
    csv = _cmd(
        [
            ejecutable,
            "--query-gpu=name,memory.total,driver_version",
            "--format=csv,noheader,nounits",
        ]
    )
    cuda = parse_cuda(_cmd([ejecutable]) or "") or parse_cuda(_cmd([ejecutable, "-q"]) or "")
    return parse_nvidia_smi(csv or ""), cuda


def leer_software() -> dict[str, str]:
    out = {"python": platform.python_version()}
    for nombre, args in {
        "hermes": ["hermes", "--version"],
        "ollama": ["ollama", "--version"],
        "git": ["git", "--version"],
    }.items():
        salida = _cmd(args)
        out[nombre] = salida.splitlines()[0] if salida else "no instalado"
    return out


def leer_hardware() -> Hardware:
    sistema = platform.system()
    gpus, cuda = leer_gpus()
    return Hardware(
        sistema=sistema,
        detalle_sistema=f"{platform.system()} {platform.release()} ({platform.machine()})",
        wsl=sistema == "Linux" and _es_wsl(),
        cpu=leer_cpu(sistema),
        nucleos=os.cpu_count() or 0,
        ram_gb=round(leer_ram_gb(sistema), 1),
        gpus=gpus,
        cuda=cuda,
        disco_libre_gb=round(shutil.disk_usage(RAIZ).free / 1024**3, 1),
        software=leer_software(),
    )


# ----------------------------------------------------------------- recomendación


def evaluar(modelo: dict, vram_gb: float, ram_gb: float) -> dict:
    """Ajuste y velocidad estimada de un modelo en esta máquina (fórmula de Hermes)."""
    kv_gb = modelo["capas_kv"] * modelo["bytes_capa"] * CONTEXTO / 1e9
    necesita = modelo["gb"] + kv_gb + OVERHEAD_GB
    residente = vram_gb >= necesita
    factible = necesita <= vram_gb + ram_gb * FRACCION_RAM_UTIL
    ancho = BW_GPU if residente else BW_RAM
    tok_s = ancho / (modelo["gb"] * modelo["fraccion"])
    if not factible:
        veredicto = "no cabe"
    elif tok_s >= UMBRAL_AGRADABLE:
        veredicto = "recomendable" if residente else "recomendable (desborda a RAM)"
    elif tok_s >= UMBRAL_USABLE:
        veredicto = "lento"
    else:
        veredicto = "inusable para agentes"
    return {
        **modelo,
        "kv_gb": round(kv_gb, 1),
        "necesita_gb": round(necesita, 1),
        "residente": residente,
        "factible": factible,
        "tok_s": round(tok_s, 1),
        "veredicto": veredicto,
    }


def recomendar(hw: Hardware) -> tuple[list[dict], dict | None, list[str]]:
    vram = max((g.vram_gb for g in hw.gpus), default=0.0)
    evaluados = [evaluar(m, vram, hw.ram_gb) for m in CATALOGO]
    buenos = [e for e in evaluados if e["veredicto"].startswith("recomendable")]
    # Igual que Hermes: primero lo que corre entero en GPU; luego la mejor calidad.
    elegido = max(buenos, key=lambda e: (e["residente"], e["calidad"], -e["gb"]), default=None)

    avisos = []
    if not hw.gpus:
        avisos.append(
            "No se detectó GPU NVIDIA (nvidia-smi). Instala el driver o, en WSL, el driver "
            "de Windows con soporte WSL."
        )
    if hw.cuda and hw.sistema == "Linux" and int(hw.cuda.split(".")[0]) < 13:
        avisos.append(
            f"El driver reporta CUDA {hw.cuda}: el runtime local de Hermes en Linux pide un "
            "driver con CUDA 13. Actualiza el driver o usa Ollama como servidor."
        )
    if hw.wsl:
        avisos.append(
            f"WSL2 ve {hw.ram_gb} GB de RAM: por defecto solo recibe una fracción de la del "
            "equipo. Para desbordar modelos MoE a RAM, sube el límite en %UserProfile%\\.wslconfig "
            "(sección [wsl2], memory=56GB) y ejecuta `wsl --shutdown`."
        )
    if elegido and hw.disco_libre_gb < elegido["gb"] + 10:
        avisos.append(
            f"Disco libre {hw.disco_libre_gb} GB: el modelo pesa {elegido['gb']} GB; deja al "
            "menos 10 GB extra."
        )
    version_hermes = hw.software.get("hermes", "no instalado")
    if version_hermes == "no instalado":
        avisos.append("Hermes no está instalado (o no está en el PATH).")
    elif (v := parse_version(version_hermes)) and v < HERMES_MIN:
        avisos.append(
            f"Hermes v{'.'.join(map(str, v))} es anterior a 0.22.5: el plugin "
            "advanced-delegation (delegación del orquestador en los 4 perfiles) se instala pero "
            "no hace nada. Actualiza con `hermes update` antes de instalar los perfiles."
        )
    return evaluados, elegido, avisos


# ------------------------------------------------------------------------ informe


def informe_md(hw: Hardware, evaluados: list[dict], elegido: dict | None, avisos: list[str]) -> str:
    gpus = "; ".join(f"{g.nombre} ({g.vram_gb} GB, driver {g.driver})" for g in hw.gpus)
    lineas = [
        "# Diagnóstico del PC para Hermes",
        "",
        "| Componente | Valor |",
        "|---|---|",
        f"| Sistema | {hw.detalle_sistema}{' — WSL2' if hw.wsl else ''} |",
        f"| CPU | {hw.cpu} ({hw.nucleos} hilos) |",
        f"| RAM | {hw.ram_gb} GB |",
        f"| GPU | {gpus or 'no detectada'} |",
        f"| CUDA (driver) | {hw.cuda or '—'} |",
        f"| Disco libre (repo) | {hw.disco_libre_gb} GB |",
    ]
    lineas += [f"| {k} | {v} |" for k, v in hw.software.items()]
    lineas += [
        "",
        "## Modelos del catálogo local de Hermes con 64K de contexto",
        "",
        "| Modelo | Build GB | +KV 64K | Total GB | Cabe en GPU | tok/s est. | Veredicto |",
        "|---|---|---|---|---|---|---|",
    ]
    for e in evaluados:
        lineas.append(
            f"| {e['nombre']} | {e['gb']} | {e['kv_gb']} | {e['necesita_gb']} | "
            f"{'sí' if e['residente'] else 'no'} | {e['tok_s']} | {e['veredicto']} |"
        )
    lineas += ["", "## Recomendación", ""]
    py = "python" if hw.sistema == "Windows" else "python3"
    if elegido:
        lineas += [
            f"**{elegido['nombre']}** — {elegido['veredicto']}, ~{elegido['tok_s']} tok/s "
            "estimados (fórmula de Hermes; la cifra real depende de tu GPU y de los canales de RAM).",
            "",
            "1. Descárgalo con el runtime de Hermes: `hermes model` → *Local models* → "
            f"`{elegido['nombre'].split(' (')[0]}`.",
            "2. Genera e instala los perfiles con ese mismo modelo para todos:",
            "",
            "```bash",
            f"{py} scripts/instalar_hermes.py --proveedor llamacpp --modelo {elegido['gguf']} "
            "--max-hijos 2 --instalar-plugin",
            "```",
        ]
    else:
        lineas.append("Ningún modelo del catálogo corre a velocidad útil en este equipo.")
    if avisos:
        lineas += ["", "## Avisos", ""] + [f"- {a}" for a in avisos]
    lineas += [
        "",
        "> Estimaciones con las constantes de Hermes (1000 GB/s GPU, 80 GB/s RAM). Un MoE que "
        "desborda suele rendir mejor que esta cota, porque las capas de atención y el KV quedan "
        "en la GPU.",
    ]
    return "\n".join(lineas) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Diagnóstico de hardware y modelo recomendado.")
    ap.add_argument("--out", help="Guarda el informe Markdown en esta ruta")
    ap.add_argument("--json", action="store_true", help="Salida JSON")
    args = ap.parse_args(argv)

    hw = leer_hardware()
    evaluados, elegido, avisos = recomendar(hw)
    if args.json:
        print(
            json.dumps(
                {
                    "hardware": asdict(hw),
                    "modelos": evaluados,
                    "recomendado": elegido["id"] if elegido else None,
                    "avisos": avisos,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    texto = informe_md(hw, evaluados, elegido, avisos)
    if args.out:
        destino = Path(args.out).expanduser()
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(texto, encoding="utf-8")
        print(f"Informe -> {destino}")
    sys.stdout.write(texto)
    return 0


if __name__ == "__main__":
    sys.exit(main())
