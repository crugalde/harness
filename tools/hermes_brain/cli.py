"""CLI del worker: escanear → procesar → revisar dudosos → informe.

    python hermes_brain.py correr --lote biblioteca-2026
    python hermes_brain.py revisar
    python hermes_brain.py estado

(o `python -m hermes_brain …` con `tools/` en el PYTHONPATH).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from . import informe as inf
from .clasificador import clasificar
from .cliente_n8n import ClienteN8n
from .cola import Cola
from .config import Config, ErrorConfig, cargar
from .hermes import ejecutar_chat, prompt_pdf, slug
from .inventario import escanear
from .procesador import DetenerLote, Progreso, procesar_lote


def _lote_por_defecto() -> str:
    return datetime.now().strftime("lote-%Y%m%d-%H%M")


def _abrir(args) -> tuple[Config, Cola]:
    cfg = cargar(args.config)
    return cfg, Cola(cfg.db)


def _imprimir_avance(prog: Progreso, total: int) -> None:
    fin = "\n" if prog.procesados == total else "\r"
    print(prog.linea(total).ljust(100), end=fin, flush=True)


# --------------------------------------------------------------------------- comandos
def cmd_escanear(args) -> int:
    cfg, cola = _abrir(args)
    lote = args.lote or _lote_por_defecto()
    carpetas = [Path(c) for c in args.carpeta] if args.carpeta else None
    print(f"Escaneando {'; '.join(str(c) for c in (carpetas or cfg.carpetas))} …")
    res = escanear(cfg, cola, lote, carpetas,
                   progreso=lambda n: print(f"  {n} archivos vistos…", end="\r", flush=True))
    cola.set_meta("ultimo_lote", lote)
    print(f"\nLote `{lote}`: {res.nuevos} nuevos, {res.repetidos} ya conocidos, "
          f"{res.demasiado_grandes} demasiado grandes, {res.ilegibles} ilegibles "
          f"({res.vistos} vistos).")
    ClienteN8n(cfg.n8n, cola).inventario(lote, res.como_dict(), len(carpetas or cfg.carpetas))
    cola.cerrar()
    return 0


def cmd_procesar(args) -> int:
    cfg, cola = _abrir(args)
    lote = args.lote or cola.get_meta("ultimo_lote") or None
    cliente = ClienteN8n(cfg.n8n, cola)
    print(f"Procesando lote `{lote or 'todos'}` (concurrencia {cfg.concurrencia})…")
    try:
        prog = procesar_lote(cfg, cola, lote, args.max, cliente, _imprimir_avance)
    except DetenerLote as exc:
        print(f"\nDetenido: {exc}")
        cola.cerrar()
        return 130
    resumen = cola.resumen(lote)
    cliente.fin(lote or "todos", resumen, cola.resumen_clasificacion(lote),
                resumen.get("dudoso", 0),
                [{"id": a.id_opaco, "error": a.error[:160]} for a in cola.por_estado("error", lote)])
    print(f"\nListo en {prog.segundos/60:.1f} min. {prog.linea(prog.procesados)}")
    if resumen.get("dudoso"):
        print(f"Quedan {resumen['dudoso']} dudosos: resuélvelos con "
              f"`python hermes_brain.py revisar --lote {lote or ''}`.")
    cola.cerrar()
    return 0


def cmd_correr(args) -> int:
    """Escanear + procesar + informe, que es el uso normal sobre una carpeta nueva."""
    args.lote = args.lote or _lote_por_defecto()
    codigo = cmd_escanear(args)
    if codigo:
        return codigo
    codigo = cmd_procesar(args)
    args.salida = args.salida or None
    cmd_informe(args)
    return codigo


def cmd_revisar(args) -> int:
    """Cola de revisión: resuelve al final, en bloque, los archivos dudosos."""
    _cfg, cola = _abrir(args)
    lote = args.lote or None
    dudosos = cola.por_estado("dudoso", lote)
    if not dudosos:
        print("No hay archivos dudosos pendientes.")
        cola.cerrar()
        return 0
    print(f"{len(dudosos)} archivo(s) dudoso(s). Para cada uno: [s] sí, procesar · [n] no, omitir · "
          "[a] abrir · [q] salir\n")
    for i, a in enumerate(dudosos, 1):
        clase_si = "cientifico" if a.ext == ".pdf" else "clinico"
        pregunta = ("¿Es un PDF de revista científica?" if a.ext == ".pdf"
                    else "¿Es un resumen clínico?")
        if args.todos_si or args.todos_no:
            decision = "s" if args.todos_si else "n"
        else:
            print(f"[{i}/{len(dudosos)}] {a.ruta}")
            print(f"      motivo: {a.motivo}")
            if a.evidencia:
                print(f"      señales: {json.dumps(a.evidencia, ensure_ascii=False)[:300]}")
            decision = ""
            while decision not in ("s", "n", "q"):
                decision = input(f"      {pregunta} [s/n/a/q]: ").strip().lower()[:1]
                if decision == "a":
                    _abrir_archivo(a.ruta)
                    decision = ""
        if decision == "q":
            break
        if decision == "s":
            cola.actualizar(a.id, estado="clasificado", clasificacion=clase_si,
                            motivo="confirmado en revisión manual")
        else:
            cola.actualizar(a.id, estado="omitido", clasificacion=f"no_{clase_si}",
                            motivo="descartado en revisión manual")
    pendientes = len(cola.pendientes(lote))
    cola.cerrar()
    print(f"\nRevisión aplicada. {pendientes} archivo(s) esperando proceso.")
    if pendientes and not args.no_procesar:
        return cmd_procesar(args)
    return 0


def _abrir_archivo(ruta: Path) -> None:
    import subprocess
    try:
        if sys.platform == "win32":
            import os
            os.startfile(str(ruta))
        elif sys.platform == "darwin":
            subprocess.run(["open", str(ruta)], check=False)
        else:
            subprocess.run(["xdg-open", str(ruta)], check=False)
    except Exception as exc:   # abrir el visor es una comodidad: si falla, se sigue revisando
        print(f"      no se pudo abrir: {exc}")


def cmd_estado(args) -> int:
    cfg, cola = _abrir(args)
    lote = args.lote or None
    resumen = cola.resumen(lote)
    print(f"Lote: {lote or 'todos'}   DB: {cfg.db}")
    for clave, valor in resumen.items():
        if valor:
            print(f"  {clave:12} {valor}")
    clases = cola.resumen_clasificacion(lote)
    if clases:
        print("  clasificación:", ", ".join(f"{k}={v}" for k, v in clases.items()))
    pend = len(cola.envios_pendientes(limite=1000))
    if pend:
        print(f"  envíos a n8n pendientes: {pend}")
    cola.cerrar()
    return 0


def cmd_reintentar(args) -> int:
    _cfg, cola = _abrir(args)
    n = cola.reencolar(args.lote or None, "error")
    cola.cerrar()
    print(f"{n} archivo(s) con error vuelven a la cola.")
    if n and not args.no_procesar:
        return cmd_procesar(args)
    return 0


def cmd_informe(args) -> int:
    cfg, cola = _abrir(args)
    lote = args.lote or cola.get_meta("ultimo_lote") or None
    destino = Path(args.salida) if getattr(args, "salida", None) else \
        cfg.destino_md / f"_informe-{lote or 'todos'}.md"
    texto = inf.generar(cola, lote, destino)
    print(texto if args.stdout else f"Informe escrito en {destino}")
    cola.cerrar()
    return 0


def cmd_clasificar(args) -> int:
    """Prueba el clasificador sobre un archivo suelto, sin tocar la cola ni Hermes."""
    cfg = cargar(args.config)
    clf = clasificar(Path(args.archivo), cfg.clasificador)
    print(json.dumps({"decision": clf.decision, "score": clf.score, "motivo": clf.motivo,
                      "titulo": clf.titulo, "evidencia": clf.evidencia},
                     ensure_ascii=False, indent=2))
    return 0


def cmd_probar_hermes(args) -> int:
    """Abre un chat de Hermes con un archivo para validar la configuración del CLI."""
    cfg = cargar(args.config)
    ruta = Path(args.archivo)
    nombre = slug(ruta.stem)
    res = ejecutar_chat(cfg.hermes, archivo=ruta, skill=cfg.hermes.skill_pdf,
                        prompt=prompt_pdf(cfg, ruta, "", nombre), destino=cfg.destino_md,
                        adjuntos=cfg.dir_adjuntos, nombre_slug=nombre)
    print(f"ok={res.ok} md={res.md or '-'} notion={res.notion_url or '-'} "
          f"duración={res.duracion_s:.1f}s")
    if res.error:
        print(f"error: {res.error}")
    if res.salida:
        print("--- últimas líneas de Hermes ---")
        print(res.salida[-1500:])
    return 0 if res.ok else 1


# --------------------------------------------------------------------------- parser
def construir_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="hermes_brain",
        description="Worker local: recorre carpetas, reconoce PDFs científicos y resúmenes "
                    "clínicos Word, y los deriva a un chat de Hermes agent por archivo.")
    p.add_argument("--config", help="ruta del YAML (por defecto ~/.config/harness/hermes_brain.yaml)")
    sub = p.add_subparsers(dest="comando", required=True)

    def con_lote(sp):
        sp.add_argument("--lote", help="nombre del lote (por defecto, el último usado)")
        return sp

    e = con_lote(sub.add_parser("escanear", help="inventaría las carpetas configuradas"))
    e.add_argument("--carpeta", action="append", help="carpeta a escanear (repetible)")
    e.set_defaults(func=cmd_escanear)

    pr = con_lote(sub.add_parser("procesar", help="clasifica y deriva a Hermes lo pendiente"))
    pr.add_argument("--max", type=int, help="tope de archivos en esta corrida")
    pr.set_defaults(func=cmd_procesar)

    c = con_lote(sub.add_parser("correr", help="escanear + procesar + informe"))
    c.add_argument("--carpeta", action="append")
    c.add_argument("--max", type=int)
    c.add_argument("--salida", help="ruta del informe .md")
    c.add_argument("--stdout", action="store_true")
    c.set_defaults(func=cmd_correr)

    r = con_lote(sub.add_parser("revisar", help="resuelve la cola de dudosos al final del lote"))
    r.add_argument("--todos-si", action="store_true", help="acepta todos sin preguntar")
    r.add_argument("--todos-no", action="store_true", help="descarta todos sin preguntar")
    r.add_argument("--no-procesar", action="store_true", help="no procesar tras revisar")
    r.add_argument("--max", type=int)
    r.set_defaults(func=cmd_revisar)

    con_lote(sub.add_parser("estado", help="contadores del lote")).set_defaults(func=cmd_estado)

    rt = con_lote(sub.add_parser("reintentar", help="devuelve a la cola los archivos con error"))
    rt.add_argument("--no-procesar", action="store_true")
    rt.add_argument("--max", type=int)
    rt.set_defaults(func=cmd_reintentar)

    i = con_lote(sub.add_parser("informe", help="informe Markdown del lote (queda local)"))
    i.add_argument("--salida", help="ruta del .md")
    i.add_argument("--stdout", action="store_true")
    i.set_defaults(func=cmd_informe)

    cl = sub.add_parser("clasificar", help="prueba el clasificador sobre un archivo")
    cl.add_argument("archivo")
    cl.set_defaults(func=cmd_clasificar)

    ph = sub.add_parser("probar-hermes", help="valida la configuración del CLI de Hermes")
    ph.add_argument("archivo")
    ph.set_defaults(func=cmd_probar_hermes)
    return p


def main(argv: list[str] | None = None) -> int:
    args = construir_parser().parse_args(argv)
    for opcional in ("lote", "max", "salida", "stdout", "no_procesar", "todos_si", "todos_no", "carpeta"):
        if not hasattr(args, opcional):
            setattr(args, opcional, None)
    try:
        return args.func(args)
    except ErrorConfig as exc:
        print(f"Configuración: {exc}", file=sys.stderr)
        return 2
    except FileNotFoundError as exc:
        print(f"No encontrado: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nInterrumpido. El avance quedó guardado; vuelve a correr `procesar`.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
