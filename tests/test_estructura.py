"""Consistencia entre AGENTS.md, subagentes, comandos, skills, plantillas y perfiles Hermes."""

from __future__ import annotations

import re
from pathlib import Path

import instalar_hermes as ih
import pytest
import verificar as v
import yaml

RAIZ = Path(__file__).resolve().parent.parent
AGENTES = sorted((RAIZ / ".claude" / "agents").glob("*.md"))
SKILLS = sorted((RAIZ / ".claude" / "skills").glob("*/SKILL.md"))
COMANDOS = sorted((RAIZ / ".claude" / "commands").glob("*.md"))
ESPERADOS = {"buscador", "consultor", "resumidor", "integrador"}


def _frontmatter(ruta: Path) -> dict[str, str]:
    m = re.match(r"^---\n(.*?)\n---\n", ruta.read_text(encoding="utf-8"), re.S)
    assert m, f"{ruta} sin frontmatter"
    return yaml.safe_load(m.group(1))


def test_los_cuatro_agentes_existen_y_estan_en_agents_md():
    assert {p.stem for p in AGENTES} == ESPERADOS
    agents_md = (RAIZ / "AGENTS.md").read_text(encoding="utf-8")
    for nombre in ESPERADOS:
        assert f"`{nombre}`" in agents_md


@pytest.mark.parametrize("ruta", AGENTES, ids=lambda p: p.stem)
def test_agente_valido_y_apunta_a_skill_existente(ruta):
    fm = _frontmatter(ruta)
    assert fm["name"] == ruta.stem
    assert len(fm["description"]) > 60 and fm["tools"] and fm["model"] == "inherit"
    skills = re.findall(r"\.claude/skills/([a-z0-9-]+)/", ruta.read_text(encoding="utf-8"))
    assert skills, f"{ruta.name} no referencia ninguna skill"
    for s in skills:
        assert (RAIZ / ".claude" / "skills" / s / "SKILL.md").is_file(), s


@pytest.mark.parametrize("ruta", SKILLS, ids=lambda p: p.parent.name)
def test_skill_valida_para_claude_code_y_hermes(ruta):
    fm = _frontmatter(ruta)
    assert fm["name"] == ruta.parent.name
    assert re.fullmatch(r"[a-z0-9][a-z0-9._-]*", fm["name"])  # regla de nombres de Hermes
    assert fm["description"] and len(fm["description"]) <= 1024
    for script in re.findall(r"scripts/([a-z_]+\.py)", ruta.read_text(encoding="utf-8")):
        assert (RAIZ / "scripts" / script).is_file(), script


@pytest.mark.parametrize("ruta", COMANDOS, ids=lambda p: p.stem)
def test_comando_usa_argumentos_y_agentes_existentes(ruta):
    texto = ruta.read_text(encoding="utf-8")
    assert "$ARGUMENTS" in texto and _frontmatter(ruta)["description"]
    citados = set(re.findall(r"`(buscador|consultor|resumidor|integrador)`", texto))
    assert citados and citados <= ESPERADOS


@pytest.mark.parametrize(
    "tipo,plantilla",
    [
        ("resumen", "resumen-estudio"),
        ("analisis", "analisis-integrado"),
        ("respuesta", "respuesta-cientifica"),
    ],
)
def test_plantilla_coincide_con_verificador(tipo, plantilla):
    texto = (RAIZ / ".claude" / "skills" / plantilla / "plantilla.md").read_text(encoding="utf-8")
    campos, cuerpo = v.frontmatter(texto)
    assert list(v.secciones(cuerpo)) == v.TIPOS[tipo]["secciones"]
    assert set(v.TIPOS[tipo]["frontmatter"]) <= set(campos)
    assert v.inferir_tipo(campos) == tipo
    # La plantilla vacía debe fallar solo por los marcadores sin llenar.
    inf, _ = v.verificar(texto, tipo, rapido=True, fuentes=None)
    assert any(n.startswith("Sin marcadores") and e == v.FALLO for e, n, _ in inf.filas)


def test_instalar_hermes_genera_perfiles_validos(tmp_path):
    perfiles = ih.generar(tmp_path, "modelo-agentes", "modelo-orq", "http://localhost:11434/v1")
    assert [p.nombre for p in perfiles] == ["orquestador", *sorted(ESPERADOS)]
    for p in perfiles:
        d = tmp_path / p.nombre
        cfg = yaml.safe_load((d / "config.yaml").read_text(encoding="utf-8"))
        dist = yaml.safe_load((d / "distribution.yaml").read_text(encoding="utf-8"))
        assert dist["name"] == p.nombre and dist["hermes_requires"] == ">=0.22.5"
        assert cfg["model"]["provider"] == "custom"
        assert cfg["fallback_providers"] == [] and cfg["memory"]["write_approval"] is True
        assert Path(cfg["terminal"]["cwd"]) == RAIZ
        assert cfg["skills"]["external_dirs"] == [str(RAIZ / ".claude" / "skills")]
        assert (d / "SOUL.md").read_text(encoding="utf-8").strip()
    orq = yaml.safe_load((tmp_path / "orquestador" / "config.yaml").read_text(encoding="utf-8"))
    assert orq["model"]["default"] == "modelo-orq"
    assert orq["delegation"]["backend"] == "profile_routes"
    rutas = orq["delegation"]["backends"]["profile_routes"]["profiles"]
    assert {r["name"] for r in rutas} == ESPERADOS and all(r["description"] for r in rutas)
    agente = yaml.safe_load((tmp_path / "buscador" / "config.yaml").read_text(encoding="utf-8"))
    assert agente["model"]["default"] == "modelo-agentes" and "delegation" not in agente


def test_instalar_hermes_solo_generar(tmp_path):
    assert ih.main(["--modelo", "m", "--salida", str(tmp_path / "h"), "--solo-generar"]) == 0
    assert (tmp_path / "h" / "orquestador" / "SOUL.md").is_file()


# Subconjunto de los patrones con que Hermes (tools/threat_patterns.py) BLOQUEA archivos de
# contexto y skills. Si alguno coincide, Hermes descarta el archivo entero.
PATRONES_HERMES = [
    r"ignore\s+(\w+\s+){0,3}(previous|all|above|prior)\s+(\w+\s+){0,3}instructions",
    r"system\s+prompt\s+override",
    r"disregard\s+(\w+\s+){0,3}(your|all|any)\s+(\w+\s+){0,3}(instructions|rules|guidelines)",
    r"do\s+not\s+(\w+\s+){0,3}tell\s+(\w+\s+){0,3}the\s+user",
    r"<!--[^>]{0,512}(?:ignore|override|system|secret|hidden)[^>]{0,512}-->",
    r"you\s+are\s+(\w+\s+){0,3}now\s+(?:a|an|the)\s+",
    r"cat\s+[^\n]{0,2048}(\.env|credentials|\.netrc|\.pgpass|\.npmrc|\.pypirc)",
    r"curl\s+[^\n]{0,2048}\$\{?\w*(?:KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)S?\b",
    r"pull\s+(down\s+)?(?:new\s+)?task(?:ing|s)?\b",
    r"(update|modify|edit|write|change|append|add\s+to)\s+[^\n]{0,2048}(AGENTS\.md|CLAUDE\.md)",
    r"(send|post|upload|transmit)\s+[^\n]{0,2048}\s+(to|at)\s+https?://",
]
INVISIBLES = set("​‌‍⁠⁢⁣⁤﻿‪‫‬‭‮")


@pytest.mark.parametrize(
    "ruta",
    [RAIZ / "AGENTS.md", *AGENTES, *SKILLS],
    ids=lambda p: str(p.relative_to(RAIZ)),
)
def test_contexto_no_dispara_el_escaner_de_hermes(ruta):
    texto = ruta.read_text(encoding="utf-8")
    for patron in PATRONES_HERMES:
        assert not re.search(patron, texto, re.I), f"{ruta.name} coincide con {patron}"
    assert not set(texto) & INVISIBLES


def test_agents_md_cabe_en_contexto_local():
    # Cada carácter del contexto compite con el trabajo en modelos locales de 64K.
    assert len((RAIZ / "AGENTS.md").read_text(encoding="utf-8")) < 14_000


def test_primera_frase_no_corta_palabras():
    assert ih.primera_frase("Corta. Larga") == "Corta."
    largo = ih.primera_frase("palabra " * 60, largo=50)
    assert largo.endswith("palabra…") and len(largo) <= 50
