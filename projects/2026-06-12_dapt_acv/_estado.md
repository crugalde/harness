# Estado del Proyecto: DAPT en ACV & Automatización UC Library

## Objetivo
1. Realizar una revisión clínica de Doble Antiagregación Plaquetaria (DAPT) en ACV isquémico (Agudo vs. Crónico).
2. Generar una presentación en formato PPTX usando plantilla institucional UC.
3. Crear un Skill de automatización (`uc_library_fetcher`) que inicie sesión mediante el proxy CAS UC y descargue PDFs con barrera de pago de forma híbrida.

## Decisiones Tomadas
- Se concretó el análisis clínico detallado (`analisis_dapt_agudo_cronico.md`).
- Se refactorizó el script de descarga (`fetch_uc_paper.py`) para operar en modo Híbrido: el script se loguea solo y si la heurística falla, te deja el navegador visible por 2 minutos para que bajes el PDF a mano.
- Se configuró con éxito el archivo `.env` local para inyección segura de claves UC sin que queden expuestas en chat.
- Se aplicó un parche para resolver DOIs y burlar el bloqueo (Error 403) de `doi.org`.

## Pendientes
- **Problema de Enrutamiento EZproxy:** A pesar de tener el login exitoso, el paso de `ezproxy.puc.cl/login?url=...` nos sigue botando al menú general de bases de datos. Esto significa que la Biblioteca UC tiene reglas específicas para llegar a ciertas revistas o no permite links de redirección directos universales.
- Completar la descarga y análisis de los ensayos MATCH y POINT.
- Construir y ensamblar el archivo final de PowerPoint.

## Siguiente Acción (Próxima Sesión)
1. **Depuración Manual Guiada:** El agente deberá pedirte mañana que entres *tú mismo* a la página de la biblioteca de la UC, busques The Lancet o NEJM, y le pegues la "URL exacta" que aparece arriba (la que ya tiene el proxy inyectado por la U). Así veremos qué formato usa realmente el EZproxy de la Católica para Elsevier/NEJM y lo clonaremos en el código.
2. Finalizar la generación del PPTX.
