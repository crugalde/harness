"""hermes_brain — worker local que recorre carpetas, clasifica documentos y los deriva a
Hermes agent (un chat por archivo), reportando el avance al flujo n8n del VPS.

Diseño: el VPS nunca ve rutas locales ni contenido clínico (R8). El worker corre en el PC
donde viven los archivos, OneDrive y Hermes; a n8n solo viajan identificadores opacos,
clasificaciones y contadores.
"""

__version__ = "1.0.0"
