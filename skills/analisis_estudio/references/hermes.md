# Correr la skill en la workstation (Hermes)

Los cuatro scripts son CLI de biblioteca estándar: **no dependen del harness ni de Claude**.
Corren con el Python que ya tiene Hermes y se invocan igual desde PowerShell, desde Hermes o
desde una tarea programada. Eso es lo que hace que la skill sirva en los dos runtimes.

## 1. Traer el repo

```powershell
cd $env:USERPROFILE
git clone https://github.com/crugalde/harness.git
cd harness
python -c "import sys; print(sys.version)"    # 3.10+ ; la workstation tiene 3.11.15
```

En Windows el intérprete se llama `python`, no `python3`. En los ejemplos del `SKILL.md` está
como `python3` porque el harness es POSIX; sustitúyelo.

## 2. Credenciales

Van en un `.env` **fuera de iCloud** — si se sincroniza, el token de Notion sale del computador.

```powershell
mkdir $env:USERPROFILE\.config\harness -Force
notepad $env:USERPROFILE\.config\harness\.env
```

```
NOTION_TOKEN=secret_...
ENTREZ_EMAIL=cristian.ugalde@gmail.com
NCBI_API_KEY=...          # opcional: sube el límite de 3 a 10 peticiones/s
UC_USER=...               # solo si usas uc_library_fetcher
UC_PASSWORD=...
```

`tools/env_loader.py` lo carga solo. Si prefieres otra ruta:
`$env:HARNESS_ENV_FILE = "D:\claves\harness.env"`.

El `NOTION_TOKEN` es el de una **integración interna** de Notion, y hay que compartirle
explícitamente la página 📚 Biblioteca de Investigación desde el menú `···` → *Conexiones*. Sin
ese paso el token existe pero la API responde 404 sobre la base, que es un error confuso porque
parece que la base no existiera.

## 3. Correr

```powershell
$env:ENTREZ_EMAIL = "cristian.ugalde@gmail.com"

# Fase A — inventariar la carpeta
python skills\analisis_estudio\scripts\lote_fichas.py "$env:USERPROFILE\iCloudDrive\neuromuscular"

# Fase B — un paper por vez, tras escribir su ficha .md
python skills\analisis_estudio\scripts\publicar_notion.py `
    "$env:USERPROFILE\iCloudDrive\neuromuscular\msa_jtranslmed_2023.md" `
    --metadatos "$env:USERPROFILE\iCloudDrive\neuromuscular\msa_jtranslmed_2023.metadatos.json"
```

El backtick es la continuación de línea en PowerShell, no la barra invertida.

## 4. Que Hermes la use

Hermes necesita dos cosas: **el texto de la skill en su contexto** y **permiso para ejecutar los
scripts**. Cómo se le entrega el primero depende de su cargador de skills, que no está
documentado aquí — si Hermes lee `AGENTS.md` (el harness es agnóstico al runtime, por eso usa ese
estándar), apuntarlo a la raíz del repo basta. Si no, el `SKILL.md` se le pasa como instrucción
de sistema; el archivo está escrito para leerse solo, sin depender del resto del repo.

Lo segundo tiene una consecuencia concreta que conviene tener clara antes de esperar
automatismo:

> **`approvals.mode: manual` en `config.yaml` pide confirmación antes de ejecutar cualquier
> herramienta.** La skill no pregunta *dónde* publicar —eso es lo que se resolvió—, pero Hermes
> sí va a preguntar si te deja correr el comando. Son dos permisos distintos y viven en capas
> distintas: la excepción a Gate 2 del harness no levanta el gate de Hermes.

Si quieres que la publicación no pida nada, hay que cambiarlo en Hermes, no en la skill.
Recomendación: deja `manual` mientras validas las primeras fichas, y solo entonces decide si
preapruebas el comando concreto de `publicar_notion.py` en vez de aflojar el modo entero.

## 5. Detalles de Windows que sí muerden

- **Rutas al PDF.** `archivo_local` se genera con `Path.as_uri()`, que produce
  `file:///C:/Users/...` correctamente escapado. No la escribas a mano: un espacio sin codificar
  deja la columna `Archivo` rota.
- **iCloud descarga bajo demanda.** Un PDF que aparece en el explorador puede ser solo un
  marcador; el lote lo leería vacío y lo daría por *sin DOI*. Antes de una tanda grande, marca la
  carpeta como *Conservar siempre en este dispositivo*.
- **Nombres largos.** Con rutas de más de 260 caracteres Windows falla al abrir el archivo.
  `neuromuscular/` colgando del perfil de usuario está muy por debajo, pero no anides mucho más.
- **El `.md` y el PDF comparten nombre.** Es a propósito: así iCloud los sincroniza juntos y el
  lote sabe reconocer qué ficha ya está escrita.

## 6. Comprobar que está bien instalada

```powershell
python -m pytest tests\test_analisis_estudio.py -q      # 42 pruebas, todas offline
python skills\analisis_estudio\scripts\lote_fichas.py "<carpeta>" --sin-notion --limite 3
```

La segunda no toca Notion y no escribe nada en la nube: solo inventaría tres PDFs y deja el
`LOTE.md`. Es la forma barata de confirmar que la extracción de DOI funciona con **tus** PDFs
antes de lanzar la carpeta entera — que es donde más varía, porque cada editorial arma el PDF a
su manera.
