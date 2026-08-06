import os
import re
import subprocess
import plistlib

try:
    from pypdf import PdfReader
except ImportError:
    print("Error: Se requiere la librería 'pypdf'. Instálala ejecutando: pip install pypdf")
    exit(1)

# Diccionario maestro de taxonomía científica
TAXONOMIA = {
    # --- EJE A: SUBDIVISIONES NEUROLÓGICAS ---
    "Neuro_NM_Neuropatia": [r"neuropat\w+", r"neuropathy", r"neuropathies", r"polineuropat\w+",
                            r"polyneuropathy", r"axonopat\w+", r"guillain[- ]barr\w+", r"charcot[- ]marie"],
    "Neuro_NM_Miopatia": [r"miopat\w+", r"myopath\w+", r"distrofia\s+muscular", r"dystrophy", r"miositis",
                          r"myositis", r"rabdomiol\w+", r"rhabdomyolysis"],
    "Neuro_NM_Motoneurona": [r"motoneurona", r"motor\s+neuron", r"SLA", r"ALS",
                             r"esclerosis\s+lateral\s+amiotr\w+", r"amyotrophic\s+lateral\s+sclerosis", r"AME",
                             r"spinal\s+muscular\s+atrophy"],
    "Neuro_NM_UnionNM": [r"uni\w+\s+neuromuscular", r"neuromuscular\s+junction", r"NMJ", r"miastenia",
                         r"myasthenia", r"eaton[- ]lambert", r"botulismo", r"botulism"],
    "Neuro_Cognitivo": [r"cognit\w+", r"alzheimer", r"demencia\w+", r"dementia", r"afasia\w+", r"aphasia",
                        r"deterioro\s+cognit\w+"],

    # --- EJE B: TIPO DE ESTUDIO ---
    "Tipo_Metaanalisis": [r"metaan\w+lisis", r"meta[- ]anal\w+", r"prisma\s+statement"],
    "Tipo_Revision": [r"revisi\w+\s+sistem\w+tica", r"systematic\s+review", r"narrative\s+review", r"overview",
                      r"amstar"],
    "Tipo_Original": [r"original\s+article", r"art\w+culo\s+original", r"clinical\s+trial", r"ensayo\s+cl\w+nico",
                      r"cohort\s+study", r"estudio\s+de\s+cohorte"],

    # --- EJE C: OBJETIVO CLÍNICO ---
    "Obj_Fisiopatologia": [r"fisiopatol\w+", r"pathophysiology", r"pathogenesis", r"patogenia",
                           r"mecanismo\s+molecular", r"molecular\s+mechanism"],
    "Obj_Pronostico": [r"pron\w+stico", r"prognosis", r"prognostic", r"survival", r"supervivencia", r"mortalidad",
                       r"outcomes", r"evoluci\w+n"],
    "Obj_Epidemiologia": [r"epidemiol\w+", r"incidence", r"incidencia", r"prevalence", r"prevalencia",
                          r"burden\s+of\s+disease"],
    "Obj_Clinica": [r"manifestaciones\s+cl\w+nicas", r"clinical\s+features", r"case\s+report", r"caso\s+cl\w+nico",
                    r"phenotype", r"fenotipo", r"presentation"],
    "Obj_Tratamiento": [r"tratamiento", r"treatment", r"therap\w+", r"terap\w+utica", r"efficacy", r"eficacia",
                        r"safety", r"seguridad", r"f\w+rmaco"],
    "Obj_Diagnostico": [r"diagn\w+stico", r"diagnosis", r"diagnostic", r"criteria", r"sensitivity", r"sensibilidad",
                        r"especificidad", r"specificity", r"biomarker", r"electrophysiology", r"EMG", r"electromiograf\w+"]
}


def aplicar_tags_macos(ruta_archivo, lista_tags):
    """Escribe las etiquetas directamente en los atributos extendidos nativos de macOS."""
    if not lista_tags:
        return False
    try:
        # Generar plist binario con las etiquetas
        plist_binario = plistlib.dumps(lista_tags, fmt=plistlib.FMT_BINARY)
        # Ejecutar el comando xattr enviando el plist por stdin
        proceso = subprocess.Popen(
            ['xattr', '-w', 'com.apple.metadata:_kMDItemUserTags', '-', ruta_archivo],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        proceso.communicate(input=plist_binario)
        return proceso.returncode == 0
    except Exception as e:
        print(f"Error aplicando tags a {os.path.basename(ruta_archivo)}: {e}")
        return False


def clasificar_paper(ruta_pdf):
    """Extrae texto del PDF y hace match con las expresiones regulares de la taxonomía."""
    tags_detectados = set()
    try:
        lector = PdfReader(ruta_pdf)
        num_paginas = min(len(lector.pages), 4)  # Escanear solo las primeras 4 páginas para precisión estructural
        texto_acumulado = ""
        for i in range(num_paginas):
            texto_pagi = lector.pages[i].extract_text()
            if texto_pagi:
                texto_acumulado += " " + texto_pagi.lower()
        # Evaluar contra el diccionario de expresiones regulares
        for tag, patrones in TAXONOMIA.items():
            for patron in patrones:
                if re.search(patron, texto_acumulado):
                    tags_detectados.add(tag)
                    break  # Pasar al siguiente tag si este ya hizo match
    except Exception as e:
        print(f"No se pudo procesar el archivo {os.path.basename(ruta_pdf)}: {e}")
    return list(tags_detectados)


def procesar_biblioteca(directorio):
    """Recorre el directorio buscando PDFs para clasificarlos en el acto."""
    print(f"Iniciando escaneo de papers en: {directorio}")
    archivos = [os.path.join(directorio, f) for f in os.listdir(directorio) if f.lower().endswith('.pdf')]
    if not archivos:
        print("No se encontraron archivos PDF en la ruta especificada.")
        return
    for ruta in archivos:
        nombre_archivo = os.path.basename(ruta)
        tags = clasificar_paper(ruta)
        if tags:
            exito = aplicar_tags_macos(ruta, tags)
            if exito:
                print(f"[CLASIFICADO] {nombre_archivo} -> Tags: {tags}")
            else:
                print(f"[ERROR METADATOS] No se pudieron guardar los tags en {nombre_archivo}")
        else:
            print(f"[SIN MATCH] {nombre_archivo} no coincide con criterios definidos.")


if __name__ == "__main__":
    # Define la ruta de la carpeta donde descargas o guardas tus papers
    CARPETA_PAPERS = os.path.expanduser("~/Downloads/Papers_Nuevos")
    if not os.path.exists(CARPETA_PAPERS):
        os.makedirs(CARPETA_PAPERS)
        print(f"Creada la carpeta: {CARPETA_PAPERS}. Coloca tus PDFs ahí y vuelve a ejecutar.")
    else:
        procesar_biblioteca(CARPETA_PAPERS)
