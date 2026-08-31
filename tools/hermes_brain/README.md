# hermes_brain — worker local

Recorre carpetas, reconoce qué es cada documento y abre **un chat de Hermes agent por
archivo**, cerrándolo al completarse. Corre en el PC donde están los archivos, OneDrive y
Hermes. La puesta en marcha completa (incluido el flujo n8n del VPS) está en
[`n8n/README.md`](../../n8n/README.md).

## Comandos

```bash
python hermes_brain.py comprobar                    # qué falta para que funcione
python hermes_brain.py detectar                     # encuentra el CLI de Hermes (sin dependencias)
python hermes_brain.py correr --carpeta "C:\ruta"   # escanear + procesar + informe
python hermes_brain.py escanear --lote papers-2026  # solo inventario
python hermes_brain.py procesar --max 50            # procesa lo pendiente (tope opcional)
python hermes_brain.py revisar                      # resuelve los dudosos en bloque
python hermes_brain.py estado                       # contadores del lote
python hermes_brain.py reintentar                   # devuelve los errores a la cola
python hermes_brain.py informe --stdout             # informe Markdown del lote
python hermes_brain.py clasificar "C:\x.pdf"        # prueba el clasificador (no toca Hermes)
python hermes_brain.py probar-hermes "C:\x.pdf"     # valida la configuración del CLI
python hermes_brain.py detectar --puertos           # …y sondea APIs HTTP locales
```

Todos aceptan `--config <ruta>` y `--lote <nombre>`. Sin `--lote`, `escanear` y `correr`
derivan el nombre de la carpeta (`papers-ela-20260831-1135`) y el resto usa el último.

**La carpeta es un argumento de la corrida, no configuración.** Prioridad: `--carpeta`, luego
`carpetas:` del YAML si lo hay, luego se pregunta por consola. Acepta rutas entre comillas.

## Módulos

| Archivo | Responsabilidad |
|---|---|
| `config.py` | carga y valida el YAML (`~/.config/harness/hermes_brain.yaml`) |
| `comprobar.py` | diagnóstico previo: dependencias, carpetas, destino, conversor, Hermes, n8n |
| `detectar.py` | encuentra el CLI de Hermes: procesos, PATH, carpetas, paquetes, registro |
| `inventario.py` | recorrido recursivo, SHA-256, exclusiones, tope de tamaño |
| `clasificador.py` | PDF de revista científica / Word de resumen clínico, con evidencia |
| `hermes.py` | adaptador del CLI: un proceso = un chat; timeout, reintentos, parseo |
| `cola.py` | cola SQLite: estados, deduplicado, reanudación, envíos diferidos |
| `procesador.py` | motor del lote: clasifica, deriva, convierte el Word, contabiliza, obedece órdenes |
| `cliente_n8n.py` | webhooks del VPS; construye los registros **sin PHI** |
| `informe.py` | informe Markdown local (este sí lleva rutas: no sale del PC) |

## Estados de un archivo

```
pendiente → clasificado → en_proceso → hecho
                       ↘             ↘ error → (reintentar) → clasificado
                        ↘ omitido
                        ↘ dudoso → (revisar) → clasificado | omitido
```

`en_proceso` colgado más de una hora (corte del worker) vuelve solo a `clasificado`.

## Un worker por cola

La cola serializa sus escrituras, pero no está pensada para dos procesos compitiendo por los
mismos archivos: al terminar, un worker libera todo lo que quedó `en_proceso`. Para repartir
carga, usa lotes y bases de datos distintas (`--config` con otro `db:`), no dos workers sobre
la misma.

## Tests

```bash
pytest -q tests/test_hermes_brain.py
```

Cubren clasificación (papers, boletas, Word clínico y administrativo, zona gris),
conversión con figuras y de-identificación, cola, inventario recursivo, adaptador de Hermes
(éxito, timeout, salida sin `.md`) y un lote completo extremo a extremo con un CLI falso.
