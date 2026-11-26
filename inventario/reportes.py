"""reportes.py - Generación de reportes con POLIMORFISMO.

`Reporte` es una clase base ABSTRACTA (no se puede instanciar). Define el
"contrato" que cumple cada formato (`extension`, `descripcion`, `renderizar`) y
ofrece el método plantilla `guardar()`, común a todos. `ReporteTxt` y
`ReporteCsv` son las clases concretas. Para agregar otro formato (HTML, PDF...)
basta con crear otra subclase.
"""
import csv
import io
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

from models import ErrorInventario, Producto, STOCK_MINIMO


@dataclass
class DatosReporte:
    """Todo lo que necesita un reporte, ya consultado (así los formatos no tocan la BD)."""
    usuario: str
    fecha: datetime
    productos: List[Producto]
    rutas: Dict[int, str]               # id de categoría -> 'Padre > Hija'
    bajos: List[Producto]
    resumen: list                       # List[ResumenCategoria] en preorden

    @property
    def total(self) -> float:
        return sum(p.valor for p in self.productos)


# =====================================================================
class Reporte(ABC):
    """Clase base abstracta de todos los formatos de reporte."""

    @property
    @abstractmethod
    def extension(self) -> str:
        """Extensión del archivo, con punto (p. ej. '.txt')."""

    @property
    @abstractmethod
    def descripcion(self) -> str:
        """Nombre del formato para mostrar en el cuadro 'Guardar como'."""

    @abstractmethod
    def renderizar(self, datos: DatosReporte) -> str:
        """Convierte los datos en el contenido (texto) del archivo."""

    @property
    def codificacion(self) -> str:
        return "utf-8"

    @property
    def salto_de_linea(self):
        return None                     # el sistema operativo decide (CRLF en Windows)

    def guardar(self, ruta, datos: DatosReporte):
        """Método plantilla: renderiza y escribe el archivo (igual para todos los formatos)."""
        contenido = self.renderizar(datos)
        try:
            with open(ruta, "w", encoding=self.codificacion,
                      newline=self.salto_de_linea) as f:
                f.write(contenido)
        except OSError as e:
            raise ErrorInventario(
                f"No se pudo guardar el reporte: {e.strerror or e}") from e


class ReporteTxt(Reporte):
    extension = ".txt"
    descripcion = "Texto"

    def renderizar(self, d: DatosReporte) -> str:
        l = []
        l.append("REPORTE DE INVENTARIO")
        l.append(f"Generado: {d.fecha:%Y-%m-%d %H:%M}  |  Usuario: {d.usuario}")
        l.append("=" * 60)
        l.append("")
        l.append(f"{'Producto':<25}{'Cant.':>6}{'Precio':>10}{'Subtotal':>12}")
        l.append("-" * 60)
        for p in d.productos:
            l.append(f"{p.nombre[:24]:<25}{p.cantidad:>6}{p.precio:>10.2f}{p.valor:>12.2f}")
        l.append("-" * 60)
        l.append(f"{'VALOR TOTAL':<41}{d.total:>12.2f}")
        l.append("")
        if d.resumen:
            l.append("RESUMEN POR CATEGORÍA (incluye subcategorías):")
            for r in d.resumen:
                nombre = ("  " * r.nivel + r.nombre)[:34]
                l.append(f"  {nombre:<34}{r.productos:>4} prod.{r.valor:>12.2f}")
            l.append("")
        if d.bajos:
            l.append(f"PRODUCTOS CON STOCK BAJO (<{STOCK_MINIMO}):")
            for p in d.bajos:
                l.append(f"  - {p.nombre}: {p.cantidad} unidades")
        return "\n".join(l) + "\n"


class ReporteCsv(Reporte):
    """CSV para abrir en Excel/LibreOffice en español: separador ';' y decimales con coma."""
    extension = ".csv"
    descripcion = "CSV (Excel)"

    @property
    def codificacion(self) -> str:
        return "utf-8-sig"              # con BOM: Excel respeta las tildes

    @property
    def salto_de_linea(self):
        return ""                       # el módulo csv ya escribe sus propios \r\n

    @staticmethod
    def _num(x: float) -> str:
        return f"{x:.2f}".replace(".", ",")

    def renderizar(self, d: DatosReporte) -> str:
        salida = io.StringIO()
        w = csv.writer(salida, delimiter=";", lineterminator="\r\n")
        w.writerow(["ID", "Producto", "Descripción", "Categoría", "Precio",
                    "Cantidad", "Subtotal"])
        for p in d.productos:
            w.writerow([p.id, p.nombre, p.descripcion, d.rutas.get(p.id_categoria, ""),
                        self._num(p.precio), p.cantidad, self._num(p.valor)])
        return salida.getvalue()


# =====================================================================
class ReporteService:
    """Reúne los datos del inventario y los entrega al formato elegido."""

    def __init__(self, inventario, formatos: Optional[List[Reporte]] = None):
        self.inventario = inventario
        self.formatos: List[Reporte] = formatos or [ReporteTxt(), ReporteCsv()]

    def formato_para(self, ruta) -> Reporte:
        """Elige el formato por la extensión del archivo (por defecto, el primero)."""
        ext = os.path.splitext(str(ruta))[1].lower()
        for f in self.formatos:
            if f.extension == ext:
                return f
        return self.formatos[0]

    def tipos_de_archivo(self):
        """Lista para el parámetro `filetypes` de 'Guardar como'."""
        return [(f.descripcion, f"*{f.extension}") for f in self.formatos]

    def recopilar(self, usuario, ahora: Optional[datetime] = None) -> DatosReporte:
        inv = self.inventario
        return DatosReporte(usuario=usuario, fecha=ahora or datetime.now(),
                            productos=inv.listar_productos(),
                            rutas=inv.rutas_categorias(),
                            bajos=inv.productos_bajo_stock(),
                            resumen=inv.resumen_categorias())

    def generar(self, usuario, ahora: Optional[datetime] = None,
                formato: Optional[Reporte] = None) -> str:
        return (formato or self.formatos[0]).renderizar(self.recopilar(usuario, ahora))

    def guardar(self, ruta, usuario, ahora: Optional[datetime] = None):
        self.formato_para(ruta).guardar(ruta, self.recopilar(usuario, ahora))
