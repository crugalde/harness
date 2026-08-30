# Flujo n8n — documentos → Hermes agent → brain md

Pipeline para vaciar carpetas de documentos (cientos o miles de archivos, con subcarpetas)
hacia dos destinos: **Notion** para los papers y **`OneDrive\brain md`** para todo lo que
termina en Markdown. Cada archivo reconocido abre **un chat nuevo de Hermes agent**, que se
cierra al completarse; el siguiente archivo abre el suyo.

```
   PC (Windows)                                  VPS (Docker)
┌───────────────────────────────┐            ┌──────────────────────────┐
│ carpetas seleccionadas        │            │  n8n — plano de control  │
│   └─ recorrido recursivo      │            │                          │
│ hermes_brain (worker)         │  métricas  │  hermes-inventario       │
│   ├─ clasifica PDF / Word     │ ─────────► │  hermes-resultado        │
│   ├─ abre 1 chat por archivo  │            │  hermes-control  ◄──┐    │
│   │    └─ Hermes agent (CLI)  │  órdenes   │  hermes-fin         │    │
│   ├─ cola SQLite reanudable   │ ◄───────── │  hermes-mando ──────┘    │
│   └─ escribe en brain md      │            │  vigilancia (30 min)     │
└───────────────────────────────┘            └──────────────────────────┘
      archivos, rutas y PHI                      solo contadores e IDs opacos
```

**Por qué el trabajo no corre en el VPS:** los archivos, OneDrive y Hermes viven en el PC, y
los resúmenes clínicos son datos de paciente. Mandar rutas o contenido al VPS rompería R8. El
VPS aporta lo que el PC no tiene: panel de estado, historial por lote, aviso cuando el worker
se cuelga, y un mando para pausar o detener un lote largo desde el teléfono.

## Qué hace con cada archivo

| Tipo | Reconocimiento | Acción |
|---|---|---|
| **PDF de revista científica** | título + journal + autor + abstract (o 3 de 4 con DOI) | chat con la skill `analisis-estudio` → publicación en Notion + `.md` en `brain md` |
| **PDF que no es paper** | menos de 2 de esos 4 elementos | se omite y se registra |
| **Word de resumen clínico** | secciones de patología (definición, clínica, diagnóstico, tratamiento…) + vocabulario clínico | chat con la skill `resumen_clinico_md` → `.md` con figuras en `brain md` |
| **Word que no es clínico** | marcadores administrativos, sin estructura clínica | se omite y se registra |
| **Dudoso** (cualquiera de los dos) | puntaje en la zona gris | **cola de revisión**: no detiene el lote; se resuelve al final |

Los umbrales de la zona gris se ajustan en `clasificador:` del YAML del worker.

## Instalación

### 1. En el VPS (n8n)

```bash
# 1. Token compartido con el PC (mismo valor en ambos lados)
python3 -c "import secrets; print(secrets.token_urlsafe(32))"

# 2. Añádelo al entorno del contenedor y reinicia
#    docker-compose.yml →  environment: [ HERMES_TOKEN=<valor>, HERMES_TELEGRAM_CHAT=<opcional> ]
docker compose up -d n8n

# 3. Carpeta de datos dentro del volumen de n8n
docker compose exec n8n mkdir -p /home/node/.n8n/hermes
```

Importa `n8n/flujo_hermes_brain.json` (**Workflows → Import from File**) y **activa** el flujo.
Copia la URL de producción de cualquier webhook: la parte hasta `/webhook` es el `base_url`
que necesita el worker.

> **Estado y persistencia.** Los contadores del flujo viven en *workflow static data*, que
> solo persiste en ejecuciones de producción (flujo activo). En modo prueba se pierden. La
> fuente de verdad del avance es siempre la cola SQLite del PC; n8n es el panel, no el registro.

### 2. En el PC (worker)

```powershell
pip install python-docx pypdf pyyaml requests
copy tools\hermes_brain\config.example.yaml %USERPROFILE%\.config\harness\hermes_brain.yaml
notepad %USERPROFILE%\.config\harness\hermes_brain.yaml     # ajusta lo marcado <-- AJUSTAR
setx HERMES_TOKEN "<el mismo token del VPS>"
```

Lo único que hay que averiguar es la línea de comandos real de Hermes agent. El worker no
asume su sintaxis: se declara en `hermes.comando` con marcadores.

```yaml
hermes:
  comando: ["hermes", "chat", "--new", "--skill", "{skill}", "--attach", "{archivo}",
            "--prompt-file", "{prompt_file}", "--output-json", "{salida_json}"]
```

Verifícalo con un archivo antes de lanzar un lote de miles:

```powershell
python hermes_brain.py probar-hermes "C:\ruta\a\un_paper.pdf"
```

Si tu CLI no sabe escribir `{salida_json}`, no pasa nada: el worker también acepta una línea
JSON en stdout (`{"md": "...", "notion_url": "..."}`) y, en último término, detecta el `.md`
recién aparecido en `brain md`.

### 3. Correr un lote

```powershell
python hermes_brain.py correr --carpeta "C:\Users\Usuario\OneDrive\Papers"
python hermes_brain.py revisar          # al terminar: resuelve los dudosos en bloque
```

## Endpoints del flujo

| Webhook | Método | Quién llama | Para qué |
|---|---|---|---|
| `hermes-inventario` | POST | worker | abre el lote y guarda el conteo del recorrido |
| `hermes-resultado` | POST | worker | registros anónimos por tandas de 25 |
| `hermes-control` | POST | worker | latido cada 10 archivos + recoge órdenes |
| `hermes-fin` | POST | worker | cierra el lote, escribe el informe y avisa |
| `hermes-mando` | GET | tú | `?token=…&accion=pausa\|seguir\|detener` |

Pausar un lote desde el teléfono:

```
https://n8n.tudominio.cl/webhook/hermes-mando?token=TOKEN&accion=pausa
```

El worker obedece **entre archivos**, nunca a mitad de un chat de Hermes.

## Qué sale del PC y qué no

Lo que viaja al VPS por cada archivo:

```json
{"id": "a3f9c1e07b4d2856", "ext": ".pdf", "kb": 812, "clasificacion": "cientifico",
 "estado": "hecho", "score": 8.5, "duracion_s": 96.4, "md": true, "notion": true}
```

`id` es el SHA-256 truncado del archivo. **No** viajan rutas, nombres de archivo, títulos ni
contenido — el nombre de archivo también es PHI (R8). `n8n.enviar_nombres: true` existe para
depurar carpetas sin datos clínicos; no lo actives sobre resúmenes de pacientes.

## Operación con miles de archivos

- **Reanudable.** La cola SQLite guarda el estado archivo por archivo. Ctrl+C, corte de luz o
  reinicio: `python hermes_brain.py procesar` retoma donde iba, sin repetir chats.
- **Sin duplicados.** El deduplicado es por SHA-256: el mismo paper en dos carpetas se procesa
  una vez.
- **Los dudosos no bloquean.** Se acumulan y se resuelven al final con `revisar` (que muestra
  el motivo y permite abrir el documento). Preguntar archivo por archivo detendría el lote
  durante horas.
- **Un chat a la vez** (`concurrencia: 1`) si el modelo corre local. Súbelo solo si Hermes
  atiende varias sesiones sin degradarse.
- **Ritmo esperado.** El cuello de botella es Hermes, no el recorrido: el inventario de 5.000
  archivos toma minutos; los chats, lo que tarde el modelo por documento.
- **Si el worker se cae**, el nodo *Cada 30 minutos* lo nota (45 min sin latido) y avisa.

## Verificación del flujo sin n8n

```bash
node n8n/simular_flujo.js
```

Ejecuta el JavaScript de los nodos Code contra payloads de ejemplo y comprueba contadores,
mando, informe y vigilancia. Úsalo tras editar cualquier nodo Code antes de reimportar.

## Problemas frecuentes

| Síntoma | Causa habitual |
|---|---|
| `Falta HERMES_TOKEN en el entorno de n8n` | la variable no llegó al contenedor: revisa `docker compose exec n8n env \| grep HERMES` |
| El worker registra todo pero n8n no muestra nada | el flujo está inactivo: los webhooks de producción solo responden con el flujo activo |
| `404` en los webhooks | estás usando la URL `/webhook-test/…`, que solo vive mientras escuchas desde el editor |
| Todos los PDF salen `dudoso` | son escaneos sin capa de texto: necesitan OCR antes del pipeline |
| Muchos Word clínicos salen `no_clinico` | usan negrita en vez de estilos de título: baja `docx_umbral_si` a 3.0 |
| Hermes termina sin `.md` | la skill no escribió en `destino_md`; revisa la salida con `probar-hermes` |
| Los envíos quedan pendientes | el VPS no respondió: se reintentan solos en la siguiente corrida (`estado` los muestra) |
