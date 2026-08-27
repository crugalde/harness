---
tipo: sintesis
titulo: Preguntas abiertas y contradicciones del wiki
aliases: [preguntas abiertas, controversias]
tags: [wiki/meta, razonamiento-clinico]
estado: en-progreso
confianza: alta
fuentes: ["[[2026-08-06 Tolosa-Hunt sintesis clinica]]", "[[2026-06-12 DAPT en ACV isquemico]]", "[[2021 Guia EAN-PNS CIDP]]", "[[2020 Epidemiologia CIDP Santiago]]"]
actualizado: 2026-08-27
---

# Preguntas abiertas y contradicciones

Lo que el wiki **no** resuelve, con la fuente que lo dejó abierto. Esta página es el destino de
toda tensión que no se pueda cerrar durante un ingest (ver `AGENTS.md` §4, punto 6). Es también la
lista de trabajo: cada ítem nombra qué fuente lo cerraría.

---

## Tolosa-Hunt

### 1. Un criterio que la técnica no puede cumplir

La ICHD-3 exige inflamación **granulomatosa** demostrada por RM o biopsia, pero la RM detecta
tejido anómalo, no granulomas ([[Criterios ICHD-3 13.8]]). Definición internamente inconsistente,
y raíz de la especificidad ~50%. **Sin resolver**: varios autores piden abandonar el epónimo.

### 2. El THS «benigno»: un subgrupo expulsado por definición

Un porcentaje de pacientes con THS clínicamente evidente tiene **imagen normal**. En una revisión
retrospectiva de casos 1998–2002, el **48%** de los que cumplían ICHD-2 tenían neuroimagen normal;
otras series dan entre **18,18% y 57%** (ref [1]). Con ICHD-3 **esos pacientes ya no son THS**
salvo biopsia.

¿Son THS con imagen insuficiente, o son otra cosa? Argumentos de limitación técnica: lesiones
<1 mm no las ve una RM de 3 T (resolución 1,0–2,0 mm con contraste); hay **retardo radiológico**
(repetir la RM en días o semanas); protocolos avanzados (dinámica de alta resolución, CISS, SPIR,
3D-FIESTA) muestran lesiones que la RM convencional pierde. **Sin resolver.**

### 3. La recurrencia está mal medida

Recurrencia agrupada **23%** (IC 95% 17–32%, I² = 59,9%) en 456 pacientes, pero las tasas
individuales van de **<10% a >60%** y la heterogeneidad no se explicó (ref [3]).

La causa es metodológica: **de 17 estudios, 9 no dieron ninguna definición operativa de
recurrencia**; 4 la definieron clínicamente, 3 como recaída al bajar esteroides, y **solo 1**
documentó correlación radiológica. Casos extremos: Akpinar 71% (pero 3 de 5 recaídas fueron
reclasificadas como mal diagnosticadas), Podgorac 62%, Ata 9%.

Factores asociados a recaída: compromiso de pares **II, IV y VI** (p<0,05); **no** se asociaron
edad, sexo, duración del seguimiento ni anomalías en RM. Los autores advierten sesgo ecológico
(análisis a nivel de estudio, no de paciente).

Dato práctico: seguimientos **≥2 años** dieron recurrencias más altas y menos heterogeneidad
(I² = 42,5%) → **los seguimientos cortos subestiman la recurrencia**. Hay recaídas descritas hasta
**13 años** después.

**Qué la cerraría:** una definición operativa estandarizada de recurrencia. Es el requisito previo
a cualquier otra comparación.

### 4. El tratamiento no tiene ningún ensayo

Sin consenso ni guía. No hay datos concluyentes de que los esteroides reduzcan el grado o la
duración de la oftalmoplejía; Inzitari reportó que no acortaban significativamente la paresia.
Resolución completa entre **61% y 95%** según serie. Vía, dosis óptima, duración y poblaciones
especiales (niños, embarazo): **sin definir**.

**Ahorradores de esteroides — evidencia contradictoria** (ref [3]):

| Estudio | Hallazgo |
|---|---|
| Arthur et al. | Recaída **20% vs 53,8%** con inmunosupresor adyuvante (p<0,034) |
| Kim et al. (n=91) | **Sin diferencia** significativa |

Solo 2 de 17 estudios reportaron uso de ahorradores → no se pudieron meter en la meta-regresión.

### 5. Biomarcadores: promesa sin datos

VHS y PCR chocan entre estudios: Arthur encontró elevación en 34% (con 41% de recurrencia); Hung
reportó marcadores normales y 8% de recurrencia. El meta-análisis los señala como línea a
investigar, **no como herramienta actual**.

### 6. Verificación pendiente en el propio wiki

- **Criterios ICHD-3 no verificados contra el documento original** (403 a la consulta
  automatizada). Todo [[Criterios ICHD-3 13.8]] depende de las tablas de dos revisiones.
- **14 de 23 fuentes tras paywall** sin recuperar; los DOIs están listos para `uc_library_fetcher`
  en `projects/tolosa-hunt/fuentes/resumen_busqueda.md`.
- Sesgo de origen: ~77% de los pacientes del meta-análisis son asiáticos.

---

## DAPT en ACV

### 7. Los ensayos están resumidos, no leídos

[[CHANCE]], [[THALES]], [[INSPIRES]], [[ATAMIS]] y [[CHANCE-2]] se escribieron desde el resumen de
[[2026-06-12 DAPT en ACV isquemico]], no desde el paper. [[POINT]] tiene PDF en la carpeta del
proyecto y es el primero que conviene ingerir de verdad. Hasta entonces esas páginas son esbozos y
no deben sostener una afirmación cuantitativa nueva.

### 8. La referencia GES es de 2013

La guía MINSAL citada data de 2013, matizada como «actualizaciones operativas UTAC». Cualquier
afirmación sobre cobertura vigente necesita verificación antes de un documento formal
([[Practica clinica en Chile]]).

### 9. Tensión entre el criterio clásico y la evidencia nueva

La indicación clásica es NIHSS ≤3 y ventana 12–24 h ([[Seleccion de pacientes para DAPT]]), pero
[[INSPIRES]] extiende a 24–72 h y [[ATAMIS]] a NIHSS mediana 5. **Las guías citadas (2021) son
anteriores a ambos ensayos.** Está sin resolver si la práctica local debe moverse o esperar
actualización formal de guía — y es exactamente el tipo de pregunta que conviene llevar a una
fuente nueva (guía AHA/ASA 2024 o posterior).

---

## CIDP

### 10. Criterios que se cumplen sin tener la enfermedad

La [[2021 Guia EAN-PNS CIDP]] declara que el sobrediagnóstico es frecuente y que parte de él
ocurre en **pacientes que cumplen los criterios con pruebas correctamente interpretadas**. La
revisión de 2021 buscó mejorar la especificidad, pero **no publica la especificidad resultante**
de los criterios nuevos. Sin ese número, no se puede saber cuánto se corrigió.

Es la misma forma de problema que el punto 1 de Tolosa-Hunt: criterios sensibles cuya
especificidad es el dato que falta. **Qué lo cerraría:** un estudio de validación prospectivo de
los criterios 2021 contra un patrón independiente.

### 11. El cambio de criterios rompió la comparabilidad de las series

Las categorías pasaron de *definite/probable/possible* (2010) a **CIDP / possible CIDP** (2021)
porque la exactitud de probable y definite no difería ([[Categorias diagnosticas de CIDP]]). Toda
serie anterior —incluida [[2020 Epidemiologia CIDP Santiago]], que usó EFNS/PNS 2010— clasifica
con un esquema que ya no existe. **Sin resolver:** cuánto cambian las cifras de prevalencia al
reclasificar con 2021.

### 12. La guía cierra su búsqueda en julio de 2019

Y el campo que más se movió desde entonces es justamente el que la guía separó de CIDP: las
[[Nodopatias autoinmunes]]. Todo lo que el wiki afirma sobre anticuerpos nodo-paranodales tiene
esa fecha de corte. **Qué lo cerraría:** una revisión reciente dedicada; hay candidatas en
[[Cola de ingesta CIDP]].

### 13. Los esquemas óptimos de tratamiento no se conocen

La guía lo dice tres veces, con esas palabras ([[Tratamiento de la CIDP]]):

- **Corticoides:** «el mejor régimen no se conoce». Los pulsos no mejoran la discapacidad más que
  la vía diaria (certeza moderada), pero darían menos efectos adversos, respuesta más rápida y
  remisiones más frecuentes y prolongadas (certeza baja a muy baja). La evidencia contra placebo
  es de **muy baja certeza**: un ensayo, 28 participantes.
- **IVIg:** «la mejor dosis y esquema de mantención no se conocen» — pese a certeza **alta** de
  eficacia. La práctica (0,4–1 g/kg cada 2–6 semanas) es más flexible que el esquema de los
  ensayos (1 g/kg cada 3 semanas).
- **Cuándo desescalar:** las cifras (revisar cada 6–12 meses los primeros 2–3 años) están
  declaradas como **experiencia clínica**, no como evidencia.

### 14. CIDP y diabetes: sin asociación demostrable con los datos locales

En Santiago, 3 de 15 pacientes tenían diabetes: prevalencia 0,59/100.000 frente a 8/100.000 en el
trabajo de Dyck. Los autores concluyen que **no se puede establecer asociación** — en un país con
la mayor prevalencia de diabetes de Sudamérica (9,4% de adultos). La pregunta sigue abierta y es
localmente relevante: la neuropatía diabética está en el diferencial de la CIDP distal
([[Diagnostico diferencial de CIDP]]).

### 15. Dos entidades sin lugar en la clasificación

- **CISP**: probablemente inmunomediada y responde a inmunoterapia, pero «no hay evidencia
  suficiente para determinar si es desmielinizante o si se relaciona con la CIDP sensitiva», así
  que quedó fuera de la clasificación de variantes.
- **CIDP asociada** a diabetes, MGUS, VIH o neoplasia: «no hay evidencia suficiente» para
  considerarla distinta de la idiopática. Se trata igual porque no se sabe si es distinta.

### 16. La razón hombre:mujer chilena no coincide

1,1:1 en Santiago, frente al predominio masculino algo mayor de la mayoría de las series. Los
autores lo dejan planteado como sesgo de muestra **o** particularidad poblacional, sin poder
distinguir entre ambos.

---

## Enlaces

[[Sindrome de Tolosa-Hunt]] · [[Criterios ICHD-3 13.8]] · [[RM de seno cavernoso]] ·
[[Doble antiagregacion plaquetaria]] · [[Practica clinica en Chile]] · [[CIDP]] ·
[[Categorias diagnosticas de CIDP]] · [[Tratamiento de la CIDP]]
