"""Diagnóstico de PC: parseo de nvidia-smi y recomendación de modelo según VRAM/RAM."""

from __future__ import annotations

import json

import diagnostico_pc as dp


def _hw(vram: float, ram: float, **extra) -> dp.Hardware:
    base = {
        "sistema": "Linux",
        "detalle_sistema": "Linux 6.8 (x86_64)",
        "wsl": False,
        "cpu": "CPU de prueba",
        "nucleos": 16,
        "ram_gb": ram,
        "gpus": [dp.GPU("NVIDIA GeForce RTX 4080", vram, "580.10")] if vram else [],
        "cuda": "13.0",
        "disco_libre_gb": 500.0,
        "software": {"python": "3.12", "hermes": "hermes 0.23.0", "ollama": "no instalado"},
    }
    base.update(extra)
    return dp.Hardware(**base)


def test_parse_nvidia_smi():
    gpus = dp.parse_nvidia_smi("NVIDIA GeForce RTX 4070 Ti SUPER, 16376, 580.10\nbasura\n")
    assert len(gpus) == 1 and gpus[0].vram_gb == 16.0 and gpus[0].driver == "580.10"


def test_16gb_vram_64gb_ram_recomienda_moe_que_desborda():
    evaluados, elegido, avisos = dp.recomendar(_hw(16.0, 64.0))
    por_id = {e["id"]: e for e in evaluados}
    assert elegido["id"] == "qwen3.6-35b-a3b"
    assert elegido["residente"] is False and elegido["tok_s"] >= dp.UMBRAL_AGRADABLE
    assert por_id["qwen3.8-27b"]["veredicto"] == "inusable para agentes"  # ~5 tok/s desbordado
    assert por_id["qwen3.8-flash-next"]["veredicto"] == "no cabe"
    assert avisos == []


def test_24gb_vram_prefiere_denso_residente_de_mayor_calidad():
    _, elegido, _ = dp.recomendar(_hw(24.0, 64.0))
    assert elegido["id"] == "qwen3.8-27b" and elegido["residente"] is True


def test_poca_memoria_no_recomienda_nada():
    _, elegido, _ = dp.recomendar(_hw(8.0, 16.0))
    assert elegido is None


def test_avisos_wsl_cuda_antiguo_y_sin_hermes():
    hw = _hw(16.0, 31.2, wsl=True, cuda="12.4")
    hw.software["hermes"] = "no instalado"
    _, _, avisos = dp.recomendar(hw)
    texto = " ".join(avisos)
    assert ".wslconfig" in texto and "CUDA 12.4" in texto and "Hermes no está instalado" in texto


def test_sin_gpu_avisa():
    _, _, avisos = dp.recomendar(_hw(0.0, 64.0))
    assert any("No se detectó GPU" in a for a in avisos)


def test_informe_incluye_comando_de_instalacion():
    hw = _hw(16.0, 64.0)
    texto = dp.informe_md(hw, *dp.recomendar(hw))
    assert "--proveedor llamacpp --modelo Qwen3.6-35B-A3B-UD-Q4_K_M" in texto
    assert "| GPU | NVIDIA GeForce RTX 4080 (16.0 GB" in texto


def test_main_json_en_este_equipo(capsys):
    assert dp.main(["--json"]) == 0
    datos = json.loads(capsys.readouterr().out)
    assert {"hardware", "modelos", "recomendado", "avisos"} <= set(datos)
    assert datos["hardware"]["ram_gb"] > 0
