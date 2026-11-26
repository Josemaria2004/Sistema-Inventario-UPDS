"""servicios.py - Lógica de negocio. La interfaz solo habla con estas clases.

- AuthService:       login (con bloqueo por intentos), cambio de clave.
- InventarioService: productos, stock, categorías jerárquicas, papelera, deshacer.

(El reporte está en reportes.py y los respaldos en respaldos.py.)

Todas las operaciones que modifican datos van dentro de
`db.transaccion()`: si algo falla se hace rollback y no queda nada a medias.
"""
import sqlite3
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import seguridad
from database import (CategoriaRepository, Database, MovimientoRepository,
                      ProductoRepository, UsuarioRepository)
from estructuras import ArbolCategorias, EstructuraVacia, Pila
from models import (Categoria, CuentaBloqueada, ErrorInventario, ErrorValidacion,
                    MAX_CANTIDAD, MIN_LARGO_CLAVE, Movimiento, NoEncontrado, Producto,
                    STOCK_MINIMO, StockInsuficiente, TIPOS_MOVIMIENTO)

CAPACIDAD_DESHACER = 50


# =====================================================================
class AuthService:
    USUARIO_DEFECTO = "admin"
    CLAVE_DEFECTO = "admin123"

    def __init__(self, db: Database, reloj=time.monotonic,
                 max_intentos=5, bloqueo_seg=30):
        self.db = db
        self.usuarios = UsuarioRepository(db)
        self._reloj = reloj
        self._max_intentos = max_intentos
        self._bloqueo_seg = bloqueo_seg
        self._fallos = {}            # usuario -> [intentos_fallidos, bloqueado_hasta]
        self._hash_falso = seguridad.hash_clave("no-existe")
        self._asegurar_usuario_por_defecto()

    def _asegurar_usuario_por_defecto(self):
        if not self.usuarios.existe(self.USUARIO_DEFECTO):
            with self.db.transaccion():
                self.usuarios.crear(self.USUARIO_DEFECTO,
                                    seguridad.hash_clave(self.CLAVE_DEFECTO))

    def login(self, usuario, clave) -> bool:
        """True si las credenciales son correctas. Lanza CuentaBloqueada si
        hubo demasiados intentos fallidos seguidos."""
        usuario = (usuario or "").strip()
        clave = clave or ""
        llave = usuario.casefold()
        ahora = self._reloj()
        estado = self._fallos.setdefault(llave, [0, 0.0])
        if estado[1] > ahora:
            raise CuentaBloqueada(estado[1] - ahora)

        almacenado = self.usuarios.obtener_hash(usuario)
        # si el usuario no existe se verifica igual contra un hash falso
        # para no revelar (por el tiempo de respuesta) qué usuarios existen
        ok = seguridad.verificar_clave(clave, almacenado or self._hash_falso) \
            and almacenado is not None
        if ok:
            self._fallos.pop(llave, None)
            if seguridad.necesita_actualizar(almacenado):     # migra hashes viejos
                with self.db.transaccion():
                    self.usuarios.actualizar_hash(usuario, seguridad.hash_clave(clave))
            return True

        estado[0] += 1
        if estado[0] >= self._max_intentos:
            estado[0] = 0
            estado[1] = ahora + self._bloqueo_seg
        return False

    def usa_clave_por_defecto(self, usuario) -> bool:
        almacenado = self.usuarios.obtener_hash(usuario)
        return bool(almacenado) and seguridad.verificar_clave(self.CLAVE_DEFECTO, almacenado)

    def cambiar_clave(self, usuario, actual, nueva):
        almacenado = self.usuarios.obtener_hash(usuario)
        if not almacenado or not seguridad.verificar_clave(actual or "", almacenado):
            raise ErrorValidacion("La contraseña actual es incorrecta.")
        if len(nueva or "") < MIN_LARGO_CLAVE:
            raise ErrorValidacion(
                f"La nueva contraseña debe tener al menos {MIN_LARGO_CLAVE} caracteres.")
        if nueva == actual:
            raise ErrorValidacion("La nueva contraseña debe ser distinta de la actual.")
        with self.db.transaccion():
            self.usuarios.actualizar_hash(usuario, seguridad.hash_clave(nueva))


# =====================================================================
@dataclass
class Operacion:
    """Un movimiento de stock hecho en esta sesión (lo guarda la pila de 'deshacer')."""
    id_producto: int
    nombre: str
    tipo: str
    cantidad: int

    @property
    def tipo_inverso(self):
        return "salida" if self.tipo == "entrada" else "entrada"


@dataclass
class ResumenCategoria:
    id: int
    nombre: str
    ruta: str
    nivel: int
    productos: int        # incluye los de todas sus subcategorías (suma recursiva)
    valor: float          # ídem


class InventarioService:
    def __init__(self, db: Database):
        self.db = db
        self.productos = ProductoRepository(db)
        self.categorias = CategoriaRepository(db)
        self.movimientos = MovimientoRepository(db)
        # pila (estructura dinámica propia) con las últimas operaciones de stock
        self.pila_deshacer = Pila(capacidad=CAPACIDAD_DESHACER)

    # ---------------- productos ----------------
    def _validar_categoria(self, id_categoria):
        if id_categoria is not None and self.categorias.obtener(id_categoria) is None:
            raise ErrorValidacion("La categoría seleccionada no existe.")

    def crear_producto(self, nombre, descripcion, precio, cantidad,
                       id_categoria=None) -> Producto:
        p = Producto(nombre=(nombre or "").strip(), descripcion=(descripcion or "").strip(),
                     precio=precio, cantidad=cantidad, id_categoria=id_categoria)
        errores = p.validar()
        if errores:
            raise ErrorValidacion(errores)
        self._validar_categoria(id_categoria)
        with self.db.transaccion():
            nuevo_id = self.productos.agregar(p)
            if p.cantidad > 0:
                self.movimientos.registrar(nuevo_id, "entrada", p.cantidad)
        return self.productos.obtener(nuevo_id)

    def actualizar_producto(self, id_prod, nombre, descripcion, precio,
                            id_categoria=None) -> Producto:
        """Edita datos del producto. La cantidad NO se edita aquí: solo cambia
        con entradas/salidas, para que el historial siempre cuadre."""
        actual = self.productos.obtener(id_prod)
        if actual is None:
            raise NoEncontrado("Producto no encontrado.")
        p = Producto(id=id_prod, nombre=(nombre or "").strip(),
                     descripcion=(descripcion or "").strip(), precio=precio,
                     cantidad=actual.cantidad, id_categoria=id_categoria)
        errores = p.validar()
        if errores:
            raise ErrorValidacion(errores)
        self._validar_categoria(id_categoria)
        with self.db.transaccion():
            if not self.productos.actualizar(p):
                raise NoEncontrado("Producto no encontrado.")
        return self.productos.obtener(id_prod)

    def eliminar_producto(self, id_prod):
        """Borrado lógico: el producto va a la papelera y se conserva su historial."""
        with self.db.transaccion():
            if not self.productos.archivar(id_prod):
                raise NoEncontrado("Producto no encontrado.")

    def listar_productos(self, texto="") -> List[Producto]:
        return self.productos.listar((texto or "").strip())

    def obtener_producto(self, id_prod) -> Producto:
        p = self.productos.obtener(id_prod)
        if p is None:
            raise NoEncontrado("Producto no encontrado.")
        return p

    # ---------------- papelera (recuperación de productos eliminados) ----------------
    def listar_eliminados(self) -> List[Producto]:
        return self.productos.listar_archivados()

    def restaurar_producto(self, id_prod) -> Producto:
        with self.db.transaccion():
            if not self.productos.restaurar(id_prod):
                raise NoEncontrado("Ese producto no está en la papelera.")
        return self.productos.obtener(id_prod)

    # ---------------- stock ----------------
    def _aplicar_ajuste(self, id_prod, tipo, cantidad) -> Producto:
        """Registra una entrada/salida (atómico). No toca la pila de 'deshacer'."""
        if tipo not in TIPOS_MOVIMIENTO:
            raise ErrorValidacion("Tipo de movimiento inválido.")
        if isinstance(cantidad, bool) or not isinstance(cantidad, int) or cantidad <= 0:
            raise ErrorValidacion("La cantidad debe ser un número entero mayor que 0.")
        if cantidad > MAX_CANTIDAD:
            raise ErrorValidacion(f"La cantidad no puede superar {MAX_CANTIDAD:,}.")
        delta = cantidad if tipo == "entrada" else -cantidad
        with self.db.transaccion():
            if not self.productos.ajustar_cantidad(id_prod, delta):
                prod = self.productos.obtener(id_prod)
                if prod is None:
                    raise NoEncontrado("Producto no encontrado.")
                if tipo == "salida":
                    raise StockInsuficiente(prod.cantidad)
                raise ErrorValidacion(
                    f"La entrada superaría la cantidad máxima ({MAX_CANTIDAD:,}).")
            self.movimientos.registrar(id_prod, tipo, cantidad)
        return self.productos.obtener(id_prod)

    def ajustar_stock(self, id_prod, tipo, cantidad) -> str:
        """Registra una entrada o salida. Devuelve un mensaje de confirmación."""
        prod = self._aplicar_ajuste(id_prod, tipo, cantidad)
        self.pila_deshacer.apilar(Operacion(id_prod, prod.nombre, tipo, cantidad))
        return f"Stock actualizado: {prod.nombre} ahora tiene {prod.cantidad} unidades."

    # ---------------- deshacer (usa la pila) ----------------
    def puede_deshacer(self) -> bool:
        return not self.pila_deshacer.esta_vacia()

    def descripcion_ultima_operacion(self) -> Optional[str]:
        if not self.puede_deshacer():
            return None
        op = self.pila_deshacer.tope()
        return f"{op.tipo} de {op.cantidad} · {op.nombre}"

    def deshacer_ultimo(self) -> str:
        """Revierte la última entrada/salida de esta sesión registrando el movimiento
        contrario (el historial nunca se borra: queda constancia de ambos)."""
        try:
            op = self.pila_deshacer.tope()
        except EstructuraVacia:
            raise ErrorInventario("No hay operaciones para deshacer.") from None
        try:
            prod = self._aplicar_ajuste(op.id_producto, op.tipo_inverso, op.cantidad)
        except NoEncontrado:
            self.pila_deshacer.desapilar()          # ya no se podrá deshacer nunca
            raise ErrorInventario(
                f"No se puede deshacer: «{op.nombre}» ya no está en el inventario "
                "(recupéralo desde la papelera).") from None
        except StockInsuficiente as e:              # la operación sigue en la pila
            raise ErrorInventario(
                f"No se puede deshacer la {op.tipo} de {op.cantidad} unidades de "
                f"«{op.nombre}»: el stock actual es {e.disponible}.") from None
        self.pila_deshacer.desapilar()
        return (f"Se deshizo la {op.tipo} de {op.cantidad} unidades de «{op.nombre}». "
                f"Stock actual: {prod.cantidad}.")

    def limpiar_deshacer(self):
        """Vacía la pila (p. ej. tras restaurar un respaldo: ya no tendría sentido)."""
        self.pila_deshacer.vaciar()

    def listar_movimientos(self) -> List[Movimiento]:
        return self.movimientos.listar()

    def productos_bajo_stock(self, minimo=STOCK_MINIMO) -> List[Producto]:
        return self.productos.bajo_stock(minimo)

    def valor_total(self) -> float:
        return self.productos.valor_total()

    # ---------------- categorías (jerárquicas) ----------------
    def listar_categorias(self) -> List[Categoria]:
        return self.categorias.listar()

    def arbol_categorias(self) -> ArbolCategorias:
        """Construye en memoria el árbol de categorías (nodos creados dinámicamente)."""
        return ArbolCategorias(self.categorias.listar())

    def rutas_categorias(self) -> Dict[int, str]:
        """{id: 'Padre > Hija'} para mostrar la categoría completa."""
        arbol = self.arbol_categorias()
        return {n.id: arbol.ruta(n.id) for n, _ in arbol.recorrer()}

    def categorias_para_seleccion(self, excluir_subarbol_de=None) -> List[Tuple[int, str]]:
        """[(id, ruta)] en preorden, para los combobox. Con `excluir_subarbol_de` se
        omite esa categoría y todas sus descendientes (no pueden ser su propio padre)."""
        arbol = self.arbol_categorias()
        excluidas = arbol.ids_subarbol(excluir_subarbol_de) if excluir_subarbol_de else set()
        return [(n.id, arbol.ruta(n.id)) for n, _ in arbol.recorrer() if n.id not in excluidas]

    def resumen_categorias(self) -> List[ResumenCategoria]:
        """Productos y valor por categoría, SUMANDO RECURSIVAMENTE las subcategorías."""
        arbol = self.arbol_categorias()
        conteo, valor = self.productos.resumen_por_categoria()
        return [ResumenCategoria(n.id, n.nombre, arbol.ruta(n.id), nivel,
                                 int(arbol.total(n.id, conteo)), arbol.total(n.id, valor))
                for n, nivel in arbol.recorrer()]

    def _categoria_valida(self, nombre, id_padre, id_actual=None) -> Categoria:
        cat = Categoria(id_actual, (nombre or "").strip(), id_padre)
        errores = cat.validar()
        if errores:
            raise ErrorValidacion(errores)
        if self.categorias.nombre_en_uso(cat.nombre, excluir_id=id_actual):
            raise ErrorValidacion("Esa categoría ya existe.")
        if id_padre is not None and self.categorias.obtener(id_padre) is None:
            raise ErrorValidacion("La categoría padre no existe.")
        return cat

    def agregar_categoria(self, nombre, id_padre=None) -> Categoria:
        cat = self._categoria_valida(nombre, id_padre)
        try:
            with self.db.transaccion():
                cat.id = self.categorias.agregar(cat.nombre, id_padre)
        except sqlite3.IntegrityError:
            raise ErrorValidacion("Esa categoría ya existe.")
        return cat

    def renombrar_categoria(self, id_cat, nombre) -> Categoria:
        actual = self.categorias.obtener(id_cat)
        if actual is None:
            raise NoEncontrado("Categoría no encontrada.")
        cat = self._categoria_valida(nombre, actual.id_padre, id_actual=id_cat)
        try:
            with self.db.transaccion():
                self.categorias.renombrar(id_cat, cat.nombre)
        except sqlite3.IntegrityError:
            raise ErrorValidacion("Esa categoría ya existe.")
        return cat

    def mover_categoria(self, id_cat, id_padre) -> Categoria:
        """Cambia el padre de una categoría (None = convertirla en raíz)."""
        actual = self.categorias.obtener(id_cat)
        if actual is None:
            raise NoEncontrado("Categoría no encontrada.")
        if id_padre is not None and self.categorias.obtener(id_padre) is None:
            raise ErrorValidacion("La categoría padre no existe.")
        if not self.arbol_categorias().puede_ser_padre(id_cat, id_padre):
            raise ErrorValidacion(
                "No puedes mover una categoría dentro de sí misma "
                "ni de una de sus subcategorías.")
        with self.db.transaccion():
            self.categorias.mover(id_cat, id_padre)
        actual.id_padre = id_padre
        return actual

    def eliminar_categoria(self, id_cat):
        if self.categorias.obtener(id_cat) is None:
            raise NoEncontrado("Categoría no encontrada.")
        hijas = self.categorias.contar_hijas(id_cat)
        if hijas:
            raise ErrorInventario(
                f"No se puede eliminar: tiene {hijas} subcategoría(s). "
                "Muévelas o elimínalas primero.")
        en_uso = self.categorias.contar_productos_activos(id_cat)
        if en_uso:
            raise ErrorInventario(
                f"No se puede eliminar: {en_uso} producto(s) usan esta categoría.")
        with self.db.transaccion():
            self.categorias.eliminar(id_cat)
