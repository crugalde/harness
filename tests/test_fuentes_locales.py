"""Fuentes locales: carpeta, Obsidian (lectura y guardado) y Zotero (HTTP simulado)."""

from __future__ import annotations

import fuentes_locales as fl
import pytest


def test_terminos_respeta_frases_y_acentos():
    assert fl.terminos('"fibra fina" Neuropatía x') == ["fibra fina", "neuropatia"]


def test_puntuar_and_or():
    texto = "La neuropatía de fibra fina es frecuente. Fibra fina otra vez."
    assert fl.puntuar(texto, ["fibra fina", "neuropatia"])[0] == 3
    assert fl.puntuar(texto, ["fibra fina", "ausente"])[0] == 0
    assert fl.puntuar(texto, ["fibra fina", "ausente"], todos=False)[0] == 2


def test_buscar_carpeta_con_pagina(tmp_path, monkeypatch):
    monkeypatch.setattr(fl, "CACHE", tmp_path / ".cache")
    carpeta = tmp_path / "papers"
    (carpeta / "oculta").mkdir(parents=True)
    (carpeta / "a.md").write_text(
        "[p. 1]\nIntro\n[p. 3]\nEl MG-ADL bajó 2 puntos.", encoding="utf-8"
    )
    (carpeta / "b.txt").write_text("Sin relación.", encoding="utf-8")
    (carpeta / ".privado.md").write_text("MG-ADL", encoding="utf-8")
    res = fl.buscar_carpeta(carpeta, "MG-ADL")
    assert len(res) == 1 and res[0]["archivo"].endswith("a.md")
    assert res[0]["pagina"] == "3"
    # Segunda búsqueda usa la caché.
    assert any((tmp_path / ".cache").iterdir())
    assert fl.buscar_carpeta(carpeta, "MG-ADL")[0]["pagina"] == "3"


def test_buscar_carpeta_inexistente(tmp_path):
    with pytest.raises(RuntimeError):
        fl.buscar_carpeta(tmp_path / "no", "x")


def test_obsidian_busca_y_omite_carpetas_ocultas(tmp_path):
    (tmp_path / ".obsidian").mkdir()
    (tmp_path / ".obsidian" / "x.md").write_text("miastenia", encoding="utf-8")
    (tmp_path / "Miastenia gravis.md").write_text("Notas sobre FcRn.", encoding="utf-8")
    res = fl.buscar_obsidian(tmp_path, "miastenia")
    assert [r["wikilink"] for r in res] == ["[[Miastenia gravis]]"]


def test_guardar_obsidian_no_sobrescribe_sin_flag(tmp_path):
    vault, archivo = tmp_path / "vault", tmp_path / "resumen.md"
    vault.mkdir()
    archivo.write_text("v1", encoding="utf-8")
    destino = fl.guardar_obsidian(archivo, vault, "Resumenes")
    assert destino.read_text(encoding="utf-8") == "v1"
    archivo.write_text("v2", encoding="utf-8")
    with pytest.raises(FileExistsError):
        fl.guardar_obsidian(archivo, vault, "Resumenes")
    fl.guardar_obsidian(archivo, vault, "Resumenes", sobrescribir=True)
    assert destino.read_text(encoding="utf-8") == "v2"
    with pytest.raises(RuntimeError, match="dentro de la bóveda"):
        fl.guardar_obsidian(archivo, vault, "../fuera")


def test_cli_guardar_obsidian_devuelve_2_si_existe(tmp_path, monkeypatch):
    vault = tmp_path / "v"
    (vault / "R").mkdir(parents=True)
    (vault / "R" / "n.md").write_text("x", encoding="utf-8")
    (tmp_path / "n.md").write_text("y", encoding="utf-8")
    monkeypatch.setenv("OBSIDIAN_VAULT", str(vault))
    assert fl.main(["guardar-obsidian", str(tmp_path / "n.md"), "--subcarpeta", "R"]) == 2


ITEM = {
    "key": "ABCD1234",
    "data": {
        "title": "Efgartigimod ADAPT",
        "creators": [
            {"creatorType": "author", "lastName": "Howard"},
            {"creatorType": "editor", "lastName": "Ed"},
        ],
        "date": "2021-07-01",
        "DOI": "10.1016/X",
        "publicationTitle": "Lancet Neurol",
        "tags": [{"tag": "MG"}],
    },
}
ADJUNTO = {
    "key": "ATT9",
    "data": {
        "itemType": "attachment",
        "contentType": "application/pdf",
        "linkMode": "imported_file",
        "filename": "howard.pdf",
    },
}


def test_parse_zotero_item_y_ruta_adjunto(monkeypatch, tmp_path):
    reg = fl.parse_zotero_item(ITEM)
    assert reg["autores"] == ["Howard"] and reg["anio"] == "2021" and reg["doi"] == "10.1016/x"
    monkeypatch.setenv("ZOTERO_DATA_DIR", str(tmp_path))
    assert fl._ruta_adjunto(ADJUNTO) == str(tmp_path / "storage" / "ATT9" / "howard.pdf")


def test_buscar_zotero_local_simulado(monkeypatch, tmp_path):
    monkeypatch.setenv("ZOTERO_DATA_DIR", str(tmp_path))

    def http_falso(url, params=None, **_):
        if url.endswith("/children"):
            return [ADJUNTO]
        return [ITEM]

    monkeypatch.setattr(fl, "http_get", http_falso)
    res, modo = fl.buscar_zotero("efgartigimod")
    assert modo == "local" and res[0]["pdfs"][0].endswith("howard.pdf")


def test_zotero_sin_api_ni_credenciales(monkeypatch):
    monkeypatch.setattr(fl, "http_get", lambda *a, **k: None)
    monkeypatch.delenv("ZOTERO_USER_ID", raising=False)
    monkeypatch.delenv("ZOTERO_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="Zotero no responde"):
        fl.buscar_zotero("x")
