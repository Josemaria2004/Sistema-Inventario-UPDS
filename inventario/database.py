"""database.py - Conexión SQLite y repositorios (una clase por entidad).

Los repositorios SOLO ejecutan SQL: no hacen commit ni validan reglas de
negocio. Las transacciones las controla la capa de servicios con
`Database.transaccion()`, así cada operación es atómica (todo o nada).

`RepositorioBase` es una clase abstracta: obliga a todos los repositorios a
ofrecer `listar()` y `obtener()`.
"""
import sqlite3
import sys
from abc import ABC, abstractmethod
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from models import (Categoria, MAX_CANTIDAD, Movimiento, Producto, STOCK_MINIMO, Usuario)

if getattr(sys, "frozen", False):
    RUTA_POR_DEFECTO = Path(sys.executable).resolve().parent / "inventario.db"
else:
    RUTA_POR_DEFECTO = Path(__file__).resolve().parent / "inventario.db"

# Tablas obligatorias para validar respaldos del sistema.
TABLAS_REQUERIDAS = ("usuarios", "categorias", "productos", "movimientos")


class Database:
    """Maneja la conexión, el esquema y las transacciones."""

    def __init__(self, ruta=None):
        self.ruta = str(ruta or RUTA_POR_DEFECTO)           # ':memory:' en los tests
        self.conn = sqlite3.connect(self.ruta)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._crear_tablas()
        self.migrar()

    def _crear_tablas(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS usuarios(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario TEXT NOT NULL UNIQUE,
                clave_hash TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS categorias(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL UNIQUE,
                id_padre INTEGER REFERENCES categorias(id)
            );
            CREATE TABLE IF NOT EXISTS productos(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL,
                descripcion TEXT,
                precio REAL NOT NULL CHECK(precio >= 0),
                cantidad INTEGER NOT NULL CHECK(cantidad >= 0),
                id_categoria INTEGER,
                activo INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY(id_categoria) REFERENCES categorias(id)
            );
            CREATE TABLE IF NOT EXISTS movimientos(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                id_producto INTEGER NOT NULL,
                tipo TEXT NOT NULL CHECK(tipo IN ('entrada','salida')),
                cantidad INTEGER NOT NULL CHECK(cantidad > 0),
                fecha TEXT NOT NULL,
                FOREIGN KEY(id_producto) REFERENCES productos(id)
            );
        """)
        self.conn.commit()

    def migrar(self):
        """Actualiza bases de datos creadas con versiones anteriores (o restauradas
        desde un respaldo antiguo): añade las columnas que falten."""
        cols_prod = {f["name"] for f in self.conn.execute("PRAGMA table_info(productos)")}
        if "activo" not in cols_prod:
            self.conn.execute(
                "ALTER TABLE productos ADD COLUMN activo INTEGER NOT NULL DEFAULT 1")
        cols_cat = {f["name"] for f in self.conn.execute("PRAGMA table_info(categorias)")}
        if "id_padre" not in cols_cat:
            self.conn.execute(
                "ALTER TABLE categorias ADD COLUMN id_padre INTEGER REFERENCES categorias(id)")
        self.conn.commit()

    @contextmanager
    def transaccion(self):
        """Commit si todo sale bien; rollback ante cualquier excepción."""
        try:
            yield self.conn
            self.conn.commit()
        except BaseException:
            self.conn.rollback()
            raise

    def cerrar(self):
        self.conn.close()


# =====================================================================
class RepositorioBase(ABC):
    """Clase base ABSTRACTA de todos los repositorios.

    Guarda la conexión y OBLIGA a las subclases a implementar `listar()` y
    `obtener()`. No se puede instanciar directamente.
    """

    def __init__(self, db: Database):
        self.db = db
        self.conn = db.conn

    @abstractmethod
    def listar(self):
        """Todos los registros de la entidad."""

    @abstractmethod
    def obtener(self, identificador):
        """Un registro por su identificador (o None si no existe)."""


# =====================================================================
class UsuarioRepository(RepositorioBase):
    def listar(self) -> List[Usuario]:
        return [Usuario(f["usuario"], f["clave_hash"]) for f in self.conn.execute(
            "SELECT usuario, clave_hash FROM usuarios ORDER BY usuario")]

    def obtener(self, usuario) -> Optional[Usuario]:
        f = self.conn.execute("SELECT usuario, clave_hash FROM usuarios WHERE usuario=?",
                              (usuario,)).fetchone()
        return Usuario(f["usuario"], f["clave_hash"]) if f else None

    def obtener_hash(self, usuario) -> Optional[str]:
        u = self.obtener(usuario)
        return u.clave_hash if u else None

    def existe(self, usuario) -> bool:
        return self.obtener(usuario) is not None

    def crear(self, usuario, clave_hash):
        self.conn.execute("INSERT INTO usuarios(usuario, clave_hash) VALUES (?,?)",
                          (usuario, clave_hash))

    def actualizar_hash(self, usuario, clave_hash):
        self.conn.execute("UPDATE usuarios SET clave_hash=? WHERE usuario=?",
                          (clave_hash, usuario))


# =====================================================================
class CategoriaRepository(RepositorioBase):
    @staticmethod
    def _desde_fila(f) -> Categoria:
        return Categoria(f["id"], f["nombre"], f["id_padre"])

    def listar(self) -> List[Categoria]:
        filas = self.conn.execute(
            "SELECT id, nombre, id_padre FROM categorias ORDER BY nombre").fetchall()
        return [self._desde_fila(f) for f in filas]

    def obtener(self, id_cat) -> Optional[Categoria]:
        f = self.conn.execute("SELECT id, nombre, id_padre FROM categorias WHERE id=?",
                              (id_cat,)).fetchone()
        return self._desde_fila(f) if f else None

    def nombre_en_uso(self, nombre, excluir_id=None) -> bool:
        """Compara sin distinguir mayúsculas/minúsculas (también con tildes y ñ)."""
        buscado = nombre.strip().casefold()
        return any(c.nombre.casefold() == buscado and c.id != excluir_id
                   for c in self.listar())

    def agregar(self, nombre, id_padre=None) -> int:
        return self.conn.execute(
            "INSERT INTO categorias(nombre, id_padre) VALUES (?,?)",
            (nombre, id_padre)).lastrowid

    def renombrar(self, id_cat, nombre):
        self.conn.execute("UPDATE categorias SET nombre=? WHERE id=?", (nombre, id_cat))

    def mover(self, id_cat, id_padre):
        self.conn.execute("UPDATE categorias SET id_padre=? WHERE id=?", (id_padre, id_cat))

    def contar_hijas(self, id_cat) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM categorias WHERE id_padre=?", (id_cat,)).fetchone()[0]

    def contar_productos_activos(self, id_cat) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM productos WHERE id_categoria=? AND activo=1",
            (id_cat,)).fetchone()[0]

    def eliminar(self, id_cat):
        # los productos archivados dejan de apuntar a la categoría borrada
        self.conn.execute(
            "UPDATE productos SET id_categoria=NULL WHERE id_categoria=?", (id_cat,))
        self.conn.execute("DELETE FROM categorias WHERE id=?", (id_cat,))


# =====================================================================
def _patron_like(texto):
    """Escapa % y _ para que se busquen como texto literal."""
    esc = texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{esc}%"


class ProductoRepository(RepositorioBase):
    _SELECT = ("SELECT p.id, p.nombre, p.descripcion, p.precio, p.cantidad,"
               " p.id_categoria, c.nombre AS categoria"
               " FROM productos p LEFT JOIN categorias c ON p.id_categoria = c.id")

    def agregar(self, p: Producto) -> int:
        return self.conn.execute(
            "INSERT INTO productos(nombre, descripcion, precio, cantidad, id_categoria)"
            " VALUES (?,?,?,?,?)",
            (p.nombre, p.descripcion, p.precio, p.cantidad, p.id_categoria)).lastrowid

    def listar(self, texto="") -> List[Producto]:
        if texto:
            like = _patron_like(texto)
            filas = self.conn.execute(
                self._SELECT + " WHERE p.activo=1 AND (p.nombre LIKE ? ESCAPE '\\'"
                " OR p.descripcion LIKE ? ESCAPE '\\' OR c.nombre LIKE ? ESCAPE '\\')"
                " ORDER BY p.nombre", (like, like, like)).fetchall()
        else:
            filas = self.conn.execute(
                self._SELECT + " WHERE p.activo=1 ORDER BY p.nombre").fetchall()
        return [Producto.from_row(f) for f in filas]

    def obtener(self, id_prod) -> Optional[Producto]:
        f = self.conn.execute(
            self._SELECT + " WHERE p.id=? AND p.activo=1", (id_prod,)).fetchone()
        return Producto.from_row(f) if f else None

    def listar_archivados(self) -> List[Producto]:
        """Productos 'eliminados' (borrado lógico): la papelera."""
        filas = self.conn.execute(
            self._SELECT + " WHERE p.activo=0 ORDER BY p.nombre").fetchall()
        return [Producto.from_row(f) for f in filas]

    def actualizar(self, p: Producto) -> bool:
        """Edita los datos del producto. NO toca la cantidad (solo los movimientos)."""
        cur = self.conn.execute(
            "UPDATE productos SET nombre=?, descripcion=?, precio=?, id_categoria=?"
            " WHERE id=? AND activo=1",
            (p.nombre, p.descripcion, p.precio, p.id_categoria, p.id))
        return cur.rowcount == 1

    def archivar(self, id_prod) -> bool:
        """Borrado lógico: el producto desaparece de la lista pero su historial queda."""
        cur = self.conn.execute(
            "UPDATE productos SET activo=0 WHERE id=? AND activo=1", (id_prod,))
        return cur.rowcount == 1

    def restaurar(self, id_prod) -> bool:
        """Saca un producto de la papelera."""
        cur = self.conn.execute(
            "UPDATE productos SET activo=1 WHERE id=? AND activo=0", (id_prod,))
        return cur.rowcount == 1

    def ajustar_cantidad(self, id_prod, delta) -> bool:
        """Suma `delta` (puede ser negativo) de forma atómica.

        Devuelve False si el producto no existe o si el resultado quedaría
        fuera de 0..MAX_CANTIDAD (la condición va en el propio UPDATE, así no
        hay carrera entre 'comprobar' y 'actualizar').
        """
        cur = self.conn.execute(
            "UPDATE productos SET cantidad = cantidad + ?"
            " WHERE id=? AND activo=1 AND cantidad + ? >= 0 AND cantidad + ? <= ?",
            (delta, id_prod, delta, delta, MAX_CANTIDAD))
        return cur.rowcount == 1

    def valor_total(self) -> float:
        return self.conn.execute(
            "SELECT COALESCE(SUM(precio * cantidad), 0) FROM productos WHERE activo=1"
        ).fetchone()[0]

    def bajo_stock(self, minimo=STOCK_MINIMO) -> List[Producto]:
        filas = self.conn.execute(
            self._SELECT + " WHERE p.activo=1 AND p.cantidad < ? ORDER BY p.nombre",
            (minimo,)).fetchall()
        return [Producto.from_row(f) for f in filas]

    def resumen_por_categoria(self) -> Tuple[Dict[int, int], Dict[int, float]]:
        """({id_categoria: nº de productos}, {id_categoria: valor}) SOLO directos
        (sin subcategorías: eso lo suma el árbol, recursivamente)."""
        conteo: Dict[int, int] = {}
        valor: Dict[int, float] = {}
        for f in self.conn.execute(
                "SELECT id_categoria, COUNT(*) AS n, SUM(precio * cantidad) AS v"
                " FROM productos WHERE activo=1 AND id_categoria IS NOT NULL"
                " GROUP BY id_categoria"):
            conteo[f["id_categoria"]] = f["n"]
            valor[f["id_categoria"]] = f["v"] or 0.0
        return conteo, valor


# =====================================================================
class MovimientoRepository(RepositorioBase):
    _SELECT = ("SELECT m.id, p.nombre, m.tipo, m.cantidad, m.fecha"
               " FROM movimientos m JOIN productos p ON m.id_producto = p.id")

    def registrar(self, id_producto, tipo, cantidad, fecha=None):
        fecha = fecha or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.conn.execute(
            "INSERT INTO movimientos(id_producto, tipo, cantidad, fecha) VALUES (?,?,?,?)",
            (id_producto, tipo, cantidad, fecha))

    @staticmethod
    def _desde_fila(f) -> Movimiento:
        return Movimiento(f["id"], f["nombre"], f["tipo"], f["cantidad"], f["fecha"])

    def listar(self) -> List[Movimiento]:
        filas = self.conn.execute(self._SELECT + " ORDER BY m.id DESC").fetchall()
        return [self._desde_fila(f) for f in filas]

    def obtener(self, id_mov) -> Optional[Movimiento]:
        f = self.conn.execute(self._SELECT + " WHERE m.id=?", (id_mov,)).fetchone()
        return self._desde_fila(f) if f else None
