#!/usr/bin/env python3
"""decompose.py — Pipeline de descomposición HD-sEMG (esqueleto reproducible).

Carga la señal, aplica preprocesamiento y devuelve métricas estándar. La descomposición real
(CKC de Holobar, BSS de Negro/Farina) se conecta en `_decompose_core`; aquí va un marcador de
posición que reporta la estructura de salida con datos sintéticos para validar el flujo.

Reproducibilidad (D1 de signals): reporta fs, filtros, ventana, método y semilla.

Uso:  python tools/decompose.py <senal.npy|csv> --fs 2048 --method ckc --seed 42
      python tools/decompose.py --synthetic --seed 42
"""
from __future__ import annotations
import argparse, json


def _load(path: str):
    import numpy as np  # import perezoso
    if path.endswith(".npy"):
        return np.load(path)
    return np.loadtxt(path, delimiter=",")


def _bandpass(sig, fs, lo=20, hi=500):
    from scipy.signal import butter, filtfilt  # import perezoso
    b, a = butter(4, [lo / (fs / 2), hi / (fs / 2)], btype="band")
    return filtfilt(b, a, sig, axis=0)


def _decompose_core(sig, fs, method, seed):
    """TODO: conectar CKC/BSS real. Placeholder: reporta la estructura de métricas."""
    import numpy as np
    rng = np.random.default_rng(seed)
    n_mus = int(rng.integers(6, 12))
    return {"n_mus_total": n_mus,
            "n_mus_on_target": max(1, n_mus - int(rng.integers(0, 4))),
            "sil_mean": round(float(rng.uniform(0.85, 0.97)), 3),
            "pnr_db_mean": round(float(rng.uniform(20, 35)), 1)}


def decompose(sig, fs=2048, method="ckc", seed=42) -> dict:
    proc = _bandpass(sig, fs)
    metrics = _decompose_core(proc, fs, method, seed)
    return {"params": {"fs": fs, "filtro": "butter band 20-500 Hz", "method": method, "seed": seed},
            "metrics": metrics}


def main():
    ap = argparse.ArgumentParser(description="Descomposición HD-sEMG (esqueleto).")
    ap.add_argument("senal", nargs="?")
    ap.add_argument("--fs", type=int, default=2048)
    ap.add_argument("--method", default="ckc")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--synthetic", action="store_true", help="Genera señal sintética para validar el flujo.")
    args = ap.parse_args()
    try:
        import numpy as np
    except ImportError:
        print("ERROR: instala numpy y scipy (pip install numpy scipy)."); return
    if args.synthetic or not args.senal:
        rng = np.random.default_rng(args.seed)
        sig = rng.standard_normal((args.fs * 2, 16))  # 2 s, 16 canales
    else:
        sig = _load(args.senal)
    print(json.dumps(decompose(sig, args.fs, args.method, args.seed), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
