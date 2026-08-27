# Bitácora del wiki

Registro append-only de lo que pasó y cuándo. Formato fijo `## [AAAA-MM-DD] tipo | título`
(ver `AGENTS.md` §6), para que `grep "^## \[" log.md | tail -5` sirva.

Tipos: `ingest` · `query` · `lint` · `refactor`.

## [2026-08-27] ingest | Tolosa-Hunt sintesis clinica (projects/tolosa-hunt/)
- Fuente: síntesis propia de 18 fuentes, 6-ago-2026. Solo 3 refs leídas a texto completo.
- Página de fuente: [[2026-08-06 Tolosa-Hunt sintesis clinica]]
- Creadas — entidades: [[Sindrome de Tolosa-Hunt]], [[Enfermedad relacionada con IgG4]]
- Creadas — conceptos: [[Criterios ICHD-3 13.8]], [[Oftalmoplejia dolorosa]], [[Seno cavernoso]], [[RM de seno cavernoso]], [[Respuesta a corticoides]]
- Creadas — síntesis: [[Diagnostico diferencial de oftalmoplejia dolorosa]], [[Preguntas abiertas]]
- Tensión registrada: los criterios ICHD-3 exigen inflamación granulomatosa por RM, pero la RM no distingue granuloma de otro tejido que capte contraste. Especificidad ~50%. Queda abierta en [[Preguntas abiertas]] §1.
- Límite heredado: 14 de 23 fuentes tras paywall; ICHD-3 original no consultado (HTTP 403).

## [2026-08-27] ingest | Guia DAPT en ACV isquemico (projects/2026-06-12_dapt_acv/)
- Fuente: guía resumen propia con 10 referencias, alineada a GES. 12-jun-2026.
- Página de fuente: [[2026-06-12 DAPT en ACV isquemico]]
- Creadas — conceptos: [[Doble antiagregacion plaquetaria]], [[Seleccion de pacientes para DAPT]]
- Creadas — entidades (esbozos): [[CHANCE]], [[POINT]], [[THALES]], [[INSPIRES]], [[ATAMIS]], [[CHANCE-2]]
- Creada — síntesis: [[Practica clinica en Chile]] (cruza esta fuente con la de Tolosa-Hunt: ambas aportan disponibilidad local)
- Actualizada: [[Preguntas abiertas]] con los puntos 7-9 (ensayos no leídos, MINSAL 2013, tensión guías 2021 vs INSPIRES/ATAMIS).
- Contradicción registrada: la ventana clásica 12-24 h y NIHSS ≤3 de las guías 2021 chocan con INSPIRES (72 h) y ATAMIS (NIHSS mediana 5), ambos posteriores.

## [2026-08-27] lint | Primer lint tras la siembra
- 20 páginas · 0 enlaces rotos · 0 huérfanas · 6 esbozos (los seis ensayos de DAPT).
- Acción propuesta 1: ingerir POINT_trial.pdf, que ya está en el repo, para convertir [[POINT]] en página real.
- Acción propuesta 2: recuperar con uc_library_fetcher los 13 DOIs tras paywall de projects/tolosa-hunt/fuentes/resumen_busqueda.md.
- Acción propuesta 3: verificar criterios ICHD-3 contra el documento oficial (hoy dependen de dos revisiones).
- Acción propuesta 4: buscar guía AHA/ASA 2024 o posterior para cerrar [[Preguntas abiertas]] §9.
- Hueco detectado: [[Enfermedad relacionada con IgG4]] y [[Seno cavernoso]] están escritas solo desde la óptica de Tolosa-Hunt; ambas piden fuente propia.

## [2026-08-27] refactor | Escáner de carpetas (paso 0 del ingest)
- Nuevo `python tools/wiki.py scan --dir <carpeta>`: inventaría PDFs, .docx, .md y .txt con DOI y título, detecta duplicados por hash y archivos de iCloud sin descargar.
- Cruza nombres y DOI contra las páginas de fuentes/ para marcar qué ya entró al wiki.
- Cola inicial generada sobre projects/ del repo: 6 archivos ya ingeridos, 2 pendientes (los _estado.md, que no son fuentes).
- Pendiente: correr el scan sobre icloud/neuromuscular/CIDP en la máquina de Cristian — este contenedor no ve iCloud.

## [2026-08-27] ingest | Guia EAN/PNS CIDP 2021 (Drive)
- Fuente: Van den Bergh et al, J Peripher Nerv Syst 2021;26:242-268, doi:10.1111/jns.12455. PDF en Google Drive, bajado con acceso UC.
- Leída a texto completo (160k caracteres): criterios clínicos, tablas 2-6, recomendaciones de tratamiento.
- Creadas — entidades: [[CIDP]], [[Nodopatias autoinmunes]]
- Creadas — conceptos: [[Variantes de CIDP]], [[Criterios electrodiagnosticos de CIDP]], [[Categorias diagnosticas de CIDP]], [[Tratamiento de la CIDP]]
- Creada — síntesis: [[Diagnostico diferencial de CIDP]]
- Tensión registrada: la guía existe porque el sobrediagnóstico es frecuente incluso con pruebas bien interpretadas, pero no publica la especificidad resultante de los criterios nuevos ([[Preguntas abiertas]] §10).
- Cambio de nomenclatura que rompe comparabilidad: «CIDP atípica» → variantes; tres niveles de certeza → dos; nodopatías autoinmunes fuera de CIDP.

## [2026-08-27] ingest | Epidemiologia de CIDP en Santiago (Cea 2020, Drive)
- Fuente: Cea G et al, J Clin Neurosci 2020, doi:10.1016/j.jocn.2020.02.009. Primera estimación epidemiológica de CIDP en Sudamérica y el Caribe.
- Página de fuente: [[2020 Epidemiologia CIDP Santiago]]
- Actualizadas: [[CIDP]] (tabla de epidemiología con datos chilenos vs referencia internacional), [[Practica clinica en Chile]] (sección CIDP)
- Contradicción registrada: usó criterios EFNS/PNS 2010 (definite/possible), esquema que la guía 2021 eliminó — toda comparación de prevalencia arrastra el cambio de definición ([[Preguntas abiertas]] §11).
- Hueco abierto: la cobertura de IVIg en el sistema público chileno no está en ninguna fuente ingerida y es lo que decide la conducta real.

## [2026-08-27] lint | Tras las dos ingestas de CIDP
- 31 páginas · 0 enlaces rotos · 0 huérfanas · 6 esbozos (los ensayos de DAPT, sin cambio).
- Inventario de Drive en [[Cola de ingesta CIDP]]: 25 archivos, 20 pendientes, 3 duplicados (misma clase en pdf/docx/audio).
- Siguiente sugerido: Continuum «CIDP and Its Variants» y Allen 2017 para contrastar [[Variantes de CIDP]]; Broers 2022 para contrastar la epidemiología.
