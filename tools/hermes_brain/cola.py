"""Cola de trabajo en SQLite: inventario, estados y reintentos.

La cola vive en el PC (es quien ve los archivos). n8n recibe solo contadores y registros
anonimizados; si el VPS no responde, el trabajo local sigue y los envíos quedan encolados.
"""
from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

ESQUEMA = """
CREATE TABLE IF NOT EXISTS archivos (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    lote         TEXT    NOT NULL,
    ruta         TEXT    NOT NULL UNIQUE,
    sha256       TEXT,
    ext          TEXT    NOT NULL,
    tamano       INTEGER NOT NULL DEFAULT 0,
    mtime        REAL    NOT NULL DEFAULT 0,
    clasificacion TEXT   NOT NULL DEFAULT 'desconocido',
    score        REAL    NOT NULL DEFAULT 0,
    evidencia    TEXT    NOT NULL DEFAULT '{}',
    estado       TEXT    NOT NULL DEFAULT 'pendiente',
    motivo       TEXT    NOT NULL DEFAULT '',
    intentos     INTEGER NOT NULL DEFAULT 0,
    salida_md    TEXT    NOT NULL DEFAULT '',
    notion_url   TEXT    NOT NULL DEFAULT '',
    error        TEXT    NOT NULL DEFAULT '',
    duracion_s   REAL    NOT NULL DEFAULT 0,
    creado       REAL    NOT NULL,
    actualizado  REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_archivos_estado ON archivos(estado);
CREATE INDEX IF NOT EXISTS ix_archivos_lote   ON archivos(lote);
CREATE INDEX IF NOT EXISTS ix_archivos_sha    ON archivos(sha256);

CREATE TABLE IF NOT EXISTS envios (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    creado    REAL NOT NULL,
    payload   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    clave TEXT PRIMARY KEY,
    valor TEXT NOT NULL
);
"""

ESTADOS_FINALES = ("hecho", "omitido")
ESTADOS = ("pendiente", "clasificado", "en_proceso", "hecho", "omitido", "dudoso", "error")


@dataclass
class Archivo:
    id: int
    lote: str
    ruta: Path
    sha256: str
    ext: str
    tamano: int
    clasificacion: str
    score: float
    evidencia: dict
    estado: str
    motivo: str
    intentos: int
    salida_md: str
    notion_url: str
    error: str

    @classmethod
    def desde_fila(cls, f: sqlite3.Row) -> Archivo:
        try:
            evidencia = json.loads(f["evidencia"])
        except (json.JSONDecodeError, TypeError):
            evidencia = {}
        return cls(
            id=f["id"], lote=f["lote"], ruta=Path(f["ruta"]), sha256=f["sha256"] or "",
            ext=f["ext"], tamano=f["tamano"], clasificacion=f["clasificacion"],
            score=f["score"], evidencia=evidencia, estado=f["estado"], motivo=f["motivo"],
            intentos=f["intentos"], salida_md=f["salida_md"], notion_url=f["notion_url"],
            error=f["error"],
        )

    @property
    def id_opaco(self) -> str:
        """Identificador sin PHI para reportar a n8n (R8): nunca la ruta ni el nombre."""
        return (self.sha256 or f"id{self.id}")[:16]


class Cola:
    """Acceso a la cola SQLite. Todas las escrituras son atómicas por transacción."""

    def __init__(self, ruta_db: Path):
        self.ruta_db = Path(ruta_db)
        self.ruta_db.parent.mkdir(parents=True, exist_ok=True)
        self.cx = sqlite3.connect(str(self.ruta_db), timeout=30, isolation_level=None,
                                  check_same_thread=False)  # escrituras serializadas por BEGIN IMMEDIATE
        self.cx.row_factory = sqlite3.Row
        self.cx.execute("PRAGMA journal_mode=WAL")
        self.cx.execute("PRAGMA busy_timeout=30000")
        self.cx.executescript(ESQUEMA)

    def cerrar(self) -> None:
        self.cx.close()

    def __enter__(self) -> Cola:
        return self

    def __exit__(self, *_exc) -> None:
        self.cerrar()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        self.cx.execute("BEGIN IMMEDIATE")
        try:
            yield self.cx
        except Exception:      # cualquier fallo del bloque deshace la transacción y se propaga
            self.cx.execute("ROLLBACK")
            raise
        else:
            self.cx.execute("COMMIT")

    # ------------------------------------------------------------------ inventario
    def registrar(self, lote: str, ruta: Path, ext: str, tamano: int, mtime: float,
                  sha256: str = "") -> bool:
        """Inserta un archivo nuevo. Devuelve True si se insertó, False si ya estaba."""
        ahora = time.time()
        with self._tx() as cx:
            cur = cx.execute(
                "INSERT OR IGNORE INTO archivos (lote, ruta, sha256, ext, tamano, mtime, creado, actualizado)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (lote, str(ruta), sha256, ext, tamano, mtime, ahora, ahora),
            )
            if cur.rowcount == 0:
                # Ya conocido: si cambió en disco, vuelve a la cola.
                cx.execute(
                    "UPDATE archivos SET estado='pendiente', clasificacion='desconocido', intentos=0,"
                    " error='', motivo='', sha256=?, tamano=?, mtime=?, actualizado=?"
                    " WHERE ruta=? AND (mtime != ? OR tamano != ?)",
                    (sha256, tamano, mtime, ahora, str(ruta), mtime, tamano),
                )
                return False
        return True

    def marcar_duplicados(self) -> int:
        """Omite archivos cuyo sha256 ya fue procesado con éxito en otra ruta."""
        ahora = time.time()
        with self._tx() as cx:
            cur = cx.execute(
                "UPDATE archivos SET estado='omitido', motivo='duplicado', actualizado=?"
                " WHERE estado IN ('pendiente','clasificado') AND sha256 != '' AND sha256 IN"
                " (SELECT sha256 FROM archivos WHERE estado='hecho' AND sha256 != '')",
                (ahora,),
            )
            return cur.rowcount

    # ------------------------------------------------------------------ lectura
    def pendientes(self, lote: str | None = None, limite: int | None = None,
                   estados: tuple[str, ...] = ("pendiente", "clasificado")) -> list[Archivo]:
        sql = f"SELECT * FROM archivos WHERE estado IN ({','.join('?' * len(estados))})"
        params: list = list(estados)
        if lote:
            sql += " AND lote = ?"
            params.append(lote)
        sql += " ORDER BY id"
        if limite:
            sql += " LIMIT ?"
            params.append(limite)
        return [Archivo.desde_fila(f) for f in self.cx.execute(sql, params)]

    def por_estado(self, estado: str, lote: str | None = None) -> list[Archivo]:
        sql = "SELECT * FROM archivos WHERE estado = ?"
        params: list = [estado]
        if lote:
            sql += " AND lote = ?"
            params.append(lote)
        return [Archivo.desde_fila(f) for f in self.cx.execute(sql + " ORDER BY id", params)]

    def obtener(self, id_archivo: int) -> Archivo | None:
        fila = self.cx.execute("SELECT * FROM archivos WHERE id = ?", (id_archivo,)).fetchone()
        return Archivo.desde_fila(fila) if fila else None

    def resumen(self, lote: str | None = None) -> dict[str, int]:
        sql = "SELECT estado, COUNT(*) n FROM archivos"
        params: list = []
        if lote:
            sql += " WHERE lote = ?"
            params.append(lote)
        sql += " GROUP BY estado"
        conteo = {e: 0 for e in ESTADOS}
        for fila in self.cx.execute(sql, params):
            conteo[fila["estado"]] = fila["n"]
        conteo["total"] = sum(conteo[e] for e in ESTADOS)
        return conteo

    def resumen_clasificacion(self, lote: str | None = None) -> dict[str, int]:
        sql = "SELECT clasificacion, COUNT(*) n FROM archivos"
        params: list = []
        if lote:
            sql += " WHERE lote = ?"
            params.append(lote)
        return {f["clasificacion"]: f["n"] for f in self.cx.execute(sql + " GROUP BY clasificacion", params)}

    def lotes(self) -> list[str]:
        return [f["lote"] for f in self.cx.execute("SELECT DISTINCT lote FROM archivos ORDER BY lote")]

    # ------------------------------------------------------------------ escritura
    def actualizar(self, id_archivo: int, **campos) -> None:
        if not campos:
            return
        if "evidencia" in campos and not isinstance(campos["evidencia"], str):
            campos["evidencia"] = json.dumps(campos["evidencia"], ensure_ascii=False)
        campos["actualizado"] = time.time()
        set_sql = ", ".join(f"{k} = ?" for k in campos)
        with self._tx() as cx:
            cx.execute(f"UPDATE archivos SET {set_sql} WHERE id = ?",
                       (*campos.values(), id_archivo))

    def tomar(self, id_archivo: int) -> bool:
        """Marca `en_proceso` solo si nadie más lo tomó. Devuelve True si lo tomó este worker."""
        with self._tx() as cx:
            cur = cx.execute(
                "UPDATE archivos SET estado='en_proceso', intentos=intentos+1, actualizado=?"
                " WHERE id=? AND estado IN ('pendiente','clasificado')",
                (time.time(), id_archivo),
            )
            return cur.rowcount == 1

    def liberar_colgados(self, segundos: int = 3600) -> int:
        """Devuelve a la cola lo que quedó `en_proceso` tras un corte del worker."""
        limite = time.time() - segundos
        with self._tx() as cx:
            cur = cx.execute(
                "UPDATE archivos SET estado='clasificado', actualizado=?"
                " WHERE estado='en_proceso' AND actualizado < ?", (time.time(), limite))
            return cur.rowcount

    def reencolar(self, lote: str | None = None, estado_origen: str = "error") -> int:
        sql = "UPDATE archivos SET estado='clasificado', error='', actualizado=? WHERE estado=?"
        params: list = [time.time(), estado_origen]
        if lote:
            sql += " AND lote=?"
            params.append(lote)
        with self._tx() as cx:
            return cx.execute(sql, params).rowcount

    # ------------------------------------------------------------------ envíos a n8n
    def encolar_envio(self, payload: dict) -> None:
        with self._tx() as cx:
            cx.execute("INSERT INTO envios (creado, payload) VALUES (?,?)",
                       (time.time(), json.dumps(payload, ensure_ascii=False)))

    def envios_pendientes(self, limite: int = 100) -> list[tuple[int, dict]]:
        filas = self.cx.execute("SELECT id, payload FROM envios ORDER BY id LIMIT ?", (limite,))
        return [(f["id"], json.loads(f["payload"])) for f in filas]

    def borrar_envios(self, ids: list[int]) -> None:
        if not ids:
            return
        with self._tx() as cx:
            cx.executemany("DELETE FROM envios WHERE id = ?", [(i,) for i in ids])

    # ------------------------------------------------------------------ meta
    def set_meta(self, clave: str, valor: str) -> None:
        with self._tx() as cx:
            cx.execute("INSERT INTO meta (clave, valor) VALUES (?,?)"
                       " ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor", (clave, str(valor)))

    def get_meta(self, clave: str, defecto: str = "") -> str:
        fila = self.cx.execute("SELECT valor FROM meta WHERE clave = ?", (clave,)).fetchone()
        return fila["valor"] if fila else defecto
