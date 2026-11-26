"""respaldos.py - Recuperación de datos: respaldo, restauración y respaldo automático.

Se usa la API de respaldo de SQLite (`Connection.backup`), que copia la base de
forma consistente aunque esté abierta. Antes de restaurar se valida el archivo y
se guarda una copia de seguridad de los datos actuales, así incluso una
restauración equivocada se puede deshacer.
"""
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from database import Database, TABLAS_REQUERIDAS
from models import ErrorInventario

COLUMNAS_MINIMAS = {"productos": {"nombre", "precio", "cantidad"},
                    "movimientos": {"id_producto", "tipo", "cantidad", "fecha"}}


@dataclass
class ResultadoRestauracion:
    productos: int
    categorias: int
    movimientos: int
    copia_de_seguridad: Path        # copia de los datos que había ANTES de restaurar


class RespaldoService:
    def __init__(self, db: Database, carpeta=None):
        self.db = db
        if carpeta:
            self.carpeta = Path(carpeta)
        elif db.ruta == ":memory:":
            self.carpeta = Path(tempfile.gettempdir()) / "inventario_respaldos"
        else:
            self.carpeta = Path(db.ruta).resolve().parent / "respaldos"

    # ---------------- crear ----------------
    def crear(self, ruta_destino) -> Path:
        """Guarda una copia completa de la base de datos en `ruta_destino`."""
        destino = Path(ruta_destino)
        if destino.exists() and destino.resolve() == Path(self.db.ruta).resolve():
            raise ErrorInventario("El respaldo no puede sobrescribir la base de datos en uso.")
        try:
            destino.parent.mkdir(parents=True, exist_ok=True)
            self.db.conn.commit()
            copia = sqlite3.connect(str(destino))
            try:
                self.db.conn.backup(copia)
            finally:
                copia.close()
        except (sqlite3.Error, OSError) as e:
            raise ErrorInventario(f"No se pudo crear el respaldo: {e}") from e
        return destino

    def _copia_con_marca(self, prefijo) -> Path:
        base = f"{prefijo}_{datetime.now():%Y%m%d_%H%M%S}"
        destino, n = self.carpeta / f"{base}.db", 1
        while destino.exists():
            destino = self.carpeta / f"{base}_{n}.db"
            n += 1
        return self.crear(destino)

    def respaldo_automatico(self, hoy: Optional[date] = None, max_copias=7) -> Optional[Path]:
        """Una copia por día (auto_AAAAMMDD.db); conserva solo las últimas `max_copias`.
        Devuelve la ruta creada, o None si ya existía la de hoy."""
        hoy = hoy or date.today()
        destino = self.carpeta / f"auto_{hoy:%Y%m%d}.db"
        if destino.exists():
            return None
        self.crear(destino)
        for viejo in sorted(self.carpeta.glob("auto_*.db"))[:-max_copias]:
            try:
                viejo.unlink()
            except OSError:
                pass
        return destino

    # ---------------- validar y restaurar ----------------
    def inspeccionar(self, ruta) -> dict:
        """Comprueba que `ruta` sea un respaldo válido de este programa.
        Devuelve {'productos': n, 'categorias': n, 'movimientos': n} o lanza ErrorInventario."""
        archivo = Path(ruta)
        if not archivo.is_file():
            raise ErrorInventario("El archivo no existe.")
        try:
            con = sqlite3.connect(f"{archivo.resolve().as_uri()}?mode=ro", uri=True)
        except sqlite3.Error as e:
            raise ErrorInventario(f"No se pudo abrir el archivo: {e}") from e
        try:
            if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ErrorInventario("El archivo de respaldo está dañado.")
            tablas = {f[0] for f in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            faltan = [t for t in TABLAS_REQUERIDAS if t not in tablas]
            if faltan:
                raise ErrorInventario(
                    "El archivo no es un respaldo de este programa "
                    f"(faltan las tablas: {', '.join(faltan)}).")
            for tabla, requeridas in COLUMNAS_MINIMAS.items():
                columnas = {f[1] for f in con.execute(f"PRAGMA table_info({tabla})")}
                if not requeridas <= columnas:
                    raise ErrorInventario(
                        f"El respaldo es de una versión incompatible (tabla '{tabla}').")
            return {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                    for t in ("productos", "categorias", "movimientos")}
        except sqlite3.DatabaseError as e:
            raise ErrorInventario(f"El archivo no es una base de datos válida ({e}).") from e
        finally:
            con.close()

    def restaurar(self, ruta) -> ResultadoRestauracion:
        """REEMPLAZA todos los datos actuales por los del respaldo."""
        info = self.inspeccionar(ruta)                       # 1) validar primero
        copia = self._copia_con_marca("antes_de_restaurar")  # 2) red de seguridad
        try:
            self.db.conn.commit()
            origen = sqlite3.connect(f"{Path(ruta).resolve().as_uri()}?mode=ro", uri=True)
            try:
                origen.backup(self.db.conn)                  # 3) copiar el respaldo
            finally:
                origen.close()
            self.db.migrar()                                 # respaldos de versiones antiguas
            self.db.conn.execute("PRAGMA foreign_keys = ON")
        except (sqlite3.Error, OSError) as e:
            raise ErrorInventario(
                f"No se pudo restaurar el respaldo: {e}\n"
                f"Tus datos anteriores están en: {copia}") from e
        return ResultadoRestauracion(info["productos"], info["categorias"],
                                     info["movimientos"], copia)
