#!/usr/bin/env python3
"""read_emg.py — Lectura local y de-identificación de estudios EMG.

Procesa archivos LOCALES (sin red) y devuelve contenido anonimizado (R8). Para texto/CSV
funciona directo; para formatos propietarios binarios (Cadwell Sierra Summit .sd) deja el
gancho al parser OLE/binario.

Uso:  python tools/read_emg.py <ruta> [--out salida.txt]
"""
from __future__ import annotations
import argparse, re
from pathlib import Path

# Patrones de identificadores chilenos / comunes a redactar
PATTERNS = [
    (re.compile(r"\b\d{1,2}\.\d{3}\.\d{3}-[\dkK]\b"), "[RUT]"),          # RUT chileno
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"), "[EMAIL]"),
    (re.compile(r"\b\d{2}/\d{2}/\d{4}\b"), "[FECHA]"),
    (re.compile(r"(?i)\b(nombre|paciente|rut)\s*:\s*.+"), r"\1: [REDACTADO]"),
]


def deidentify(text: str) -> str:
    for pat, repl in PATTERNS:
        text = pat.sub(repl, text)
    return text


def read_emg(path: str) -> str:
    p = Path(path)
    if not p.exists():
        return f"ERROR: no existe {path}"
    if p.suffix.lower() == ".sd":
        return ("ERROR: .sd es binario propietario (Cadwell). Conecta aquí el parser OLE/binario "
                "para extraer NCV/EMG antes de de-identificar.")
    try:
        raw = p.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"ERROR leyendo {path}: {e}"
    return deidentify(raw)


def main():
    ap = argparse.ArgumentParser(description="Lee y de-identifica un estudio EMG local.")
    ap.add_argument("ruta")
    ap.add_argument("--out", help="Guardar resultado anonimizado en esta ruta.")
    args = ap.parse_args()
    result = read_emg(args.ruta)
    if args.out:
        Path(args.out).write_text(result, encoding="utf-8")
        print(f"Anonimizado -> {args.out}")
    else:
        print(result)


if __name__ == "__main__":
    main()
