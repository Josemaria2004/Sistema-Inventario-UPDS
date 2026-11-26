"""models.py - Entidades del dominio, constantes y excepciones propias."""
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional

# ----------------------------- constantes -----------------------------
STOCK_MINIMO = 5                 # por debajo de esto hay alerta
MAX_PRECIO = 1_000_000_000
MAX_CANTIDAD = 1_000_000_000
MAX_NOMBRE = 100
MAX_DESCRIPCION = 300
MAX_CATEGORIA = 50
MIN_LARGO_CLAVE = 6
TIPOS_MOVIMIENTO = ("entrada", "salida")


# ----------------------------- excepciones ----------------------------
class ErrorInventario(Exception):
    """Base de los errores de negocio: su mensaje es apto para mostrar."""


class ErrorValidacion(ErrorInventario):
    def __init__(self, errores):
        if isinstance(errores, str):
            errores = [errores]
        self.errores = list(errores)
        super().__init__("\n".join(self.errores))


class NoEncontrado(ErrorInventario):
    pass


class StockInsuficiente(ErrorInventario):
    def __init__(self, disponible):
        self.disponible = disponible
        super().__init__(f"Stock insuficiente (hay {disponible}).")


class CuentaBloqueada(ErrorInventario):
    def __init__(self, segundos):
        self.segundos = int(segundos) + 1
        super().__init__(
            f"Demasiados intentos fallidos. Espera {self.segundos} s e inténtalo de nuevo.")


# ------------------------------- entidades ----------------------------
class Entidad(ABC):
    """Clase base ABSTRACTA de las entidades del dominio que se validan antes de guardarse.

    No se puede instanciar (es abstracta): cada entidad concreta está OBLIGADA a
    implementar `validar()`. `es_valida()` es un método plantilla que usa el
    método abstracto implementado por la subclase.
    """

    @abstractmethod
    def validar(self) -> List[str]:
        """Lista de errores. Lista vacía = datos correctos."""

    def es_valida(self) -> bool:
        return not self.validar()


@dataclass
class Categoria(Entidad):
    id: Optional[int]
    nombre: str
    id_padre: Optional[int] = None          # None = categoría raíz; si no, es subcategoría

    def validar(self) -> List[str]:
        errores = []
        if not isinstance(self.nombre, str) or not self.nombre.strip():
            errores.append("El nombre de la categoría no puede estar vacío.")
        elif len(self.nombre.strip()) > MAX_CATEGORIA:
            errores.append(
                f"El nombre de la categoría no puede superar {MAX_CATEGORIA} caracteres.")
        return errores


@dataclass
class Producto(Entidad):
    nombre: str
    descripcion: str
    precio: float
    cantidad: int
    id: Optional[int] = None
    id_categoria: Optional[int] = None
    categoria: Optional[str] = None      # nombre, solo para mostrar

    @classmethod
    def from_row(cls, fila):
        """Crea un Producto desde una fila sqlite3.Row (ver ProductoRepository)."""
        return cls(id=fila["id"], nombre=fila["nombre"],
                   descripcion=fila["descripcion"] or "",
                   precio=fila["precio"], cantidad=fila["cantidad"],
                   id_categoria=fila["id_categoria"], categoria=fila["categoria"])

    @property
    def valor(self):
        return self.precio * self.cantidad

    def bajo_stock(self, minimo=STOCK_MINIMO):
        return self.cantidad < minimo

    def validar(self) -> List[str]:
        """Devuelve la lista de errores. Lista vacía = datos correctos."""
        errores = []
        if not isinstance(self.nombre, str) or not self.nombre.strip():
            errores.append("El nombre no puede estar vacío.")
        elif len(self.nombre.strip()) > MAX_NOMBRE:
            errores.append(f"El nombre no puede superar {MAX_NOMBRE} caracteres.")
        if not isinstance(self.descripcion, str):
            errores.append("La descripción debe ser texto.")
        elif len(self.descripcion) > MAX_DESCRIPCION:
            errores.append(f"La descripción no puede superar {MAX_DESCRIPCION} caracteres.")

        if isinstance(self.precio, bool) or not isinstance(self.precio, (int, float)):
            errores.append("El precio debe ser un número.")
        elif not math.isfinite(self.precio):          # rechaza nan e inf
            errores.append("El precio no es un número válido.")
        elif self.precio < 0:
            errores.append("El precio no puede ser negativo.")
        elif self.precio > MAX_PRECIO:
            errores.append(f"El precio no puede superar {MAX_PRECIO:,}.")

        if isinstance(self.cantidad, bool) or not isinstance(self.cantidad, int):
            errores.append("La cantidad debe ser un número entero.")
        elif self.cantidad < 0:
            errores.append("La cantidad no puede ser negativa.")
        elif self.cantidad > MAX_CANTIDAD:
            errores.append(f"La cantidad no puede superar {MAX_CANTIDAD:,}.")
        return errores


@dataclass
class Movimiento:
    id: int
    producto: str
    tipo: str
    cantidad: int
    fecha: str


@dataclass
class Usuario:
    usuario: str
    clave_hash: str
