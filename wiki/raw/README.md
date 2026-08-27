# raw/ — fuentes crudas

Capa **inmutable**. Aquí vive lo que llega de afuera: artículos clipeados con Obsidian Web
Clipper, PDFs de papers, exports de NotebookLM, transcripciones, notas de congreso, imágenes.

Reglas:

- El agente **lee** de aquí y **nunca** escribe, edita ni borra. Todo lo derivado va al wiki.
- Un archivo por fuente, con nombre estable: `AAAA-MM-DD autor-tema.md`. El nombre no cambia
  después de ingerido — las páginas del wiki lo citan.
- Imágenes en `raw/assets/`. En Obsidian: Ajustes → Archivos y enlaces → carpeta de adjuntos
  `wiki/raw/assets`, y el atajo "Descargar adjuntos del archivo actual" deja las imágenes en
  disco tras clipear.
- **Sin PHI.** Si una fuente trae datos de paciente, se de-identifica antes de guardarla aquí.

Los PDFs y notas que ya viven en `projects/` del harness también sirven como fuente: se ingieren
igual, citando su ruta en el repo. No hace falta copiarlos aquí.
