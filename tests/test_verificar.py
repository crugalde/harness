"""Verificador de entregables: estructura por tipo, citas, Mermaid y PMIDs (HTTP simulado)."""

from __future__ import annotations

import verificar as v

RESUMEN_OK = """---
titulo: "Efgartigimod in generalised myasthenia gravis"
autores: "Howard JF, Bril V, Vu T, et al."
anio: 2021
doi: "10.1016/S1474-4422(21)00159-9"
pmid: "34146511"
tipo_estudio: "ECA fase 3 doble ciego"
fuente: "workspace/papers_locales/howard-2021.pdf"
texto_analizado: "completo"
tags: [resumen, paper]
---

# Efgartigimod in generalised myasthenia gravis

## 1. Resumen estructurado

- **Tipo de estudio:** ECA fase 3, doble ciego, 56 centros.
- **Población:** 167 adultos con MG generalizada.
- **Objetivo:** eficacia y seguridad de efgartigimod.
- **Método:** 10 mg/kg IV semanal x4 vs placebo; desenlace MG-ADL.
- **Resultados:** respondedores MG-ADL 68% vs 30%, OR 4,95 (IC 95% 2,21-11,53) (p. 5).
- **Conclusiones:** bien tolerado y eficaz.

## 2. Aspectos positivos

1. Aleatorización centralizada y cegamiento doble.
2. Desenlace primario preespecificado y clínicamente relevante.

## 3. Aspectos negativos

1. Seguimiento de 26 semanas: insuficiente para seguridad a largo plazo.
2. Población seronegativa con N = 38: subgrupo sin potencia.

## 4. Aporte global al tema

Primer ECA fase 3 positivo de un bloqueador de FcRn en MG generalizada.

## 5. Hallazgos destacados declarados por los autores

- "68% de respondedores MG-ADL en AChR+" (p. 5)

## 6. Trazabilidad y límites del resumen

- Material suplementario no revisado.
"""


def _correr(texto, tipo=None):
    inf, t = v.verificar(texto, tipo, rapido=True, fuentes=None)
    return inf, t


def test_resumen_completo_pasa():
    inf, tipo = _correr(RESUMEN_OK)
    assert tipo == "resumen"
    assert inf.fallos == 0, inf.filas


def test_resumen_con_un_solo_negativo_falla():
    texto = RESUMEN_OK.replace("2. Población seronegativa con N = 38: subgrupo sin potencia.\n", "")
    inf, _ = _correr(texto)
    assert any("negativos" in n and e == v.FALLO for e, n, _ in inf.filas)


def test_resumen_campo_vacio_y_placeholder_fallan():
    texto = RESUMEN_OK.replace(
        "- **Objetivo:** eficacia y seguridad de efgartigimod.", "- **Objetivo:**"
    ).replace("56 centros", "{{centros}}")
    inf, _ = _correr(texto)
    nombres_fallidos = [n for e, n, _ in inf.filas if e == v.FALLO]
    assert "Resumen estructurado con los 6 campos llenos" in nombres_fallidos
    assert "Sin marcadores de plantilla {{...}} sin llenar" in nombres_fallidos


def test_hallazgo_sin_pagina_es_aviso_no_fallo():
    inf, _ = _correr(RESUMEN_OK.replace('AChR+" (p. 5)', 'AChR+"'))
    assert inf.fallos == 0
    assert any(e == v.AVISO and "página" in n for e, n, _ in inf.filas)


ANALISIS_OK = """---
titulo: "Inhibidores de FcRn en MG"
fecha: 2026-11-13
n_estudios: 2
nivel_lectura: "resúmenes"
tags: [analisis, sintesis]
---

# Inhibidores de FcRn en MG

## 1. Resumen ejecutivo

Ambos reducen el MG-ADL frente a placebo [1, 2]; certeza moderada.

## 2. Estudios incluidos

| # | Estudio | Diseño | N |
|---|---|---|---|
| 1 | Howard 2021 | ECA | 167 |
| 2 | Bril 2023 | ECA | 200 |

## 3. Hallazgos convergentes

- Reducción del MG-ADL [1-2].

## 4. Divergencias y heterogeneidad

- Magnitud distinta por esquema de dosis [1, 2].

## 5. Certeza de la evidencia

Moderada por imprecisión [2].

## 6. Esquema integrador

```mermaid
flowchart TD
    A["Howard 2021"] --> C["MG-ADL: mejora"]
    B["Bril 2023"] --> C
```

## 7. Detalles a considerar

- Disponibilidad en Chile no verificada [1].

## 8. Vacíos y próximos pasos

- Comparación directa entre fármacos.

## Referencias

1. Howard JF. Efgartigimod in generalised myasthenia gravis. Lancet Neurol. 2021. PMID: 34146511.
2. Bril V. Rozanolixizumab in generalised myasthenia gravis. Lancet Neurol. 2023. PMID: 37059508.
"""


def test_analisis_completo_pasa():
    inf, tipo = _correr(ANALISIS_OK)
    assert tipo == "analisis" and inf.fallos == 0, inf.filas


def test_analisis_cita_huerfana_y_mermaid_sin_comillas_fallan():
    texto = ANALISIS_OK.replace("[1, 2]; certeza", "[1, 3]; certeza").replace(
        'C["MG-ADL: mejora"]', "C[MG-ADL: mejora]"
    )
    inf, _ = _correr(texto)
    fallidos = [n for e, n, _ in inf.filas if e == v.FALLO]
    assert "Toda cita [n] tiene su referencia" in fallidos
    assert any(n.startswith("Sintaxis Mermaid") for n in fallidos)


def test_analisis_sin_esquema_ni_tabla_falla():
    texto = ANALISIS_OK.replace("| 2 | Bril 2023 | ECA | 200 |\n", "")
    texto = texto.split("```mermaid")[0] + "Sin diagrama.\n\n## 7." + texto.split("## 7.")[1]
    inf, _ = _correr(texto)
    fallidos = [n for e, n, _ in inf.filas if e == v.FALLO]
    assert "Tabla de estudios con al menos 2 filas" in fallidos
    assert "Esquema integrador en Mermaid" in fallidos


RESPUESTA = """---
pregunta: "¿Efgartigimod reduce el MG-ADL?"
fecha: 2026-11-13
fuentes_consultadas: "pubmed"
certeza: "moderada"
tags: [respuesta]
---

# ¿Efgartigimod reduce el MG-ADL?

## 1. Respuesta

Sí, en MG generalizada AChR+ [1].

## 2. Evidencia que la sustenta

- ECA, N = 167 [1].

## 3. Certeza y por qué

Moderada: un solo ECA.

## 4. Lo que no se encontró o queda abierto

- Datos a largo plazo.

## Referencias

1. Howard JF. Efgartigimod in generalised myasthenia gravis. Lancet Neurol. 2021. PMID: 34146511.
"""


def test_respuesta_y_certeza_invalida():
    inf, _ = _correr(RESPUESTA)
    assert inf.fallos == 0, inf.filas
    inf, _ = _correr(RESPUESTA.replace('certeza: "moderada"', 'certeza: "bastante"'))
    assert any(n == "Certeza en escala válida" and e == v.FALLO for e, n, _ in inf.filas)


def test_tipo_desconocido_falla():
    inf, tipo = _correr("# Sin frontmatter\n")
    assert tipo == "desconocido" and inf.fallos == 1


def _esummary(titulos):
    def falso(url, params=None, **_):
        ids = params["id"].split(",")
        res = {"uids": ids}
        for i in ids:
            res[i] = (
                {"title": titulos[i]} if i in titulos else {"error": "cannot get document summary"}
            )
        return {"result": res}

    return falso


def test_pmids_existentes_y_coincidentes(monkeypatch):
    monkeypatch.setattr(
        v,
        "http_get",
        _esummary(
            {
                "34146511": "Safety, efficacy of efgartigimod in generalised myasthenia gravis",
                "37059508": "Rozanolixizumab in generalised myasthenia gravis",
            }
        ),
    )
    inf, _ = v.verificar(ANALISIS_OK, None, rapido=False, fuentes=None)
    assert inf.fallos == 0, inf.filas


def test_pmid_inexistente_y_titulo_discordante(monkeypatch):
    monkeypatch.setattr(
        v, "http_get", _esummary({"37059508": "Cardiac surgery outcomes in adults"})
    )
    inf, _ = v.verificar(ANALISIS_OK, None, rapido=False, fuentes=None)
    fallidos = {n: d for e, n, d in inf.filas if e == v.FALLO}
    assert "34146511" in fallidos["Los 2 PMIDs existen en PubMed"]
    assert "37059508" in fallidos["Título citado coincide con el de PubMed"]


def test_cli_codigo_de_salida(tmp_path):
    bueno, malo = tmp_path / "ok.md", tmp_path / "mal.md"
    bueno.write_text(RESUMEN_OK, encoding="utf-8")
    malo.write_text(
        RESUMEN_OK.replace("## 4. Aporte global al tema", "## 4. Otra"), encoding="utf-8"
    )
    assert v.main([str(bueno), "--rapido"]) == 0
    assert v.main([str(malo), "--rapido"]) == 1
