"""Tests de la lógica (sin interfaz). Ejecutar:  python -m unittest discover -s tests -v"""
import hashlib
import math
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import seguridad
from database import Database, MovimientoRepository
from models import (CuentaBloqueada, ErrorInventario, ErrorValidacion, MAX_CANTIDAD,
                    NoEncontrado, Producto, StockInsuficiente)
from reportes import ReporteService
from servicios import AuthService, InventarioService


def setUpModule():
    seguridad.ITERACIONES = 1000          # hashes rápidos en los tests


class Base(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.inv = InventarioService(self.db)
        self.addCleanup(self.db.cerrar)


# ------------------------------------------------------------ seguridad
class TestSeguridad(unittest.TestCase):
    def test_hash_con_sal_distinto_cada_vez(self):
        self.assertNotEqual(seguridad.hash_clave("abc123"), seguridad.hash_clave("abc123"))

    def test_verificar_correcta_e_incorrecta(self):
        h = seguridad.hash_clave("secreta1")
        self.assertTrue(seguridad.verificar_clave("secreta1", h))
        self.assertFalse(seguridad.verificar_clave("secreta2", h))

    def test_formato_nuevo(self):
        self.assertTrue(seguridad.hash_clave("x").startswith("pbkdf2_sha256$"))

    def test_basura_no_rompe(self):
        for malo in ["", "basura", "pbkdf2_sha256$x$y$z", None, "a$b$c$d"]:
            self.assertFalse(seguridad.verificar_clave("x", malo))

    def test_hash_legacy_se_reconoce_y_pide_actualizar(self):
        legacy = hashlib.sha256(b"admin123").hexdigest()
        self.assertTrue(seguridad.es_hash_legacy(legacy))
        self.assertTrue(seguridad.verificar_clave("admin123", legacy))
        self.assertFalse(seguridad.verificar_clave("otra", legacy))
        self.assertTrue(seguridad.necesita_actualizar(legacy))

    def test_pocas_iteraciones_pide_actualizar(self):
        self.assertTrue(seguridad.necesita_actualizar(seguridad.hash_clave("x", iteraciones=10)))
        self.assertFalse(seguridad.necesita_actualizar(seguridad.hash_clave("x")))


# ------------------------------------------------------------ auth
class TestAuth(Base):
    def setUp(self):
        super().setUp()
        self.t = [0.0]
        self.auth = AuthService(self.db, reloj=lambda: self.t[0],
                                max_intentos=3, bloqueo_seg=30)

    def test_login_admin_por_defecto(self):
        self.assertTrue(self.auth.login("admin", "admin123"))
        self.assertTrue(self.auth.login("  admin  ", "admin123"))   # espacios

    def test_login_incorrecto(self):
        self.assertFalse(self.auth.login("admin", "mala"))
        self.assertFalse(self.auth.login("noexiste", "admin123"))
        self.assertFalse(self.auth.login("", ""))

    def test_bloqueo_tras_intentos_fallidos_y_desbloqueo(self):
        for _ in range(3):
            self.assertFalse(self.auth.login("admin", "mala"))
        with self.assertRaises(CuentaBloqueada):
            self.auth.login("admin", "admin123")        # bloqueado aunque acierte
        self.t[0] = 31
        self.assertTrue(self.auth.login("admin", "admin123"))

    def test_login_correcto_reinicia_contador(self):
        self.auth.login("admin", "mala"); self.auth.login("admin", "mala")
        self.assertTrue(self.auth.login("admin", "admin123"))
        self.auth.login("admin", "mala"); self.auth.login("admin", "mala")
        self.assertTrue(self.auth.login("admin", "admin123"))   # no bloqueó

    def test_cambiar_clave(self):
        self.assertTrue(self.auth.usa_clave_por_defecto("admin"))
        self.auth.cambiar_clave("admin", "admin123", "nueva-clave")
        self.assertFalse(self.auth.login("admin", "admin123"))
        self.assertTrue(self.auth.login("admin", "nueva-clave"))
        self.assertFalse(self.auth.usa_clave_por_defecto("admin"))

    def test_cambiar_clave_validaciones(self):
        with self.assertRaises(ErrorValidacion):
            self.auth.cambiar_clave("admin", "incorrecta", "nueva-clave")
        with self.assertRaises(ErrorValidacion):
            self.auth.cambiar_clave("admin", "admin123", "123")          # corta
        with self.assertRaises(ErrorValidacion):
            self.auth.cambiar_clave("admin", "admin123", "admin123")     # igual

    def test_usuario_admin_no_se_duplica(self):
        AuthService(self.db); AuthService(self.db)
        n = self.db.conn.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0]
        self.assertEqual(n, 1)


# ------------------------------------------------------------ validación
class TestValidacion(Base):
    def test_validar_rechaza_nan_inf_y_extremos(self):
        casos = {
            "nan": Producto("x", "", float("nan"), 1),
            "inf": Producto("x", "", math.inf, 1),
            "-inf": Producto("x", "", -math.inf, 1),
            "negativo": Producto("x", "", -1.0, 1),
            "cantidad neg": Producto("x", "", 1.0, -1),
            "cantidad gigante": Producto("x", "", 1.0, 10 ** 25),
            "nombre vacío": Producto("   ", "", 1.0, 1),
            "nombre largo": Producto("x" * 101, "", 1.0, 1),
            "cantidad float": Producto("x", "", 1.0, 1.5),
            "bool": Producto("x", "", True, True),
        }
        for etiqueta, p in casos.items():
            with self.subTest(etiqueta):
                self.assertTrue(p.validar(), f"{etiqueta} debería ser inválido")

    def test_validar_acepta_correcto(self):
        self.assertEqual(Producto("Mouse", "", 0, 0).validar(), [])
        self.assertEqual(Producto("Mouse", "óptico", 12.5, 3).validar(), [])

    def test_servicio_rechaza_nan_inf_gigante_sin_tocar_la_bd(self):
        for precio, cant in [(float("nan"), 1), (math.inf, 1), (1.0, 10 ** 25)]:
            with self.subTest(precio=precio, cant=cant):
                with self.assertRaises(ErrorValidacion):
                    self.inv.crear_producto("x", "", precio, cant)
        self.assertEqual(self.inv.listar_productos(), [])

    def test_categoria_inexistente(self):
        with self.assertRaises(ErrorValidacion):
            self.inv.crear_producto("x", "", 1.0, 1, id_categoria=999)


# ------------------------------------------------------------ productos
class TestProductos(Base):
    def test_crear_registra_movimiento_de_entrada(self):
        p = self.inv.crear_producto("  Teclado ", " mecánico ", 50.0, 10)
        self.assertEqual((p.nombre, p.descripcion, p.cantidad), ("Teclado", "mecánico", 10))
        movs = self.inv.listar_movimientos()
        self.assertEqual([(m.tipo, m.cantidad) for m in movs], [("entrada", 10)])

    def test_crear_con_cantidad_cero_no_registra_movimiento(self):
        self.inv.crear_producto("Mouse", "", 5.0, 0)
        self.assertEqual(self.inv.listar_movimientos(), [])

    def test_editar_no_cambia_cantidad_y_historial_cuadra(self):
        p = self.inv.crear_producto("Mouse", "", 5.0, 5)
        q = self.inv.actualizar_producto(p.id, "Mouse X", "nuevo", 7.5)
        self.assertEqual((q.nombre, q.precio, q.cantidad), ("Mouse X", 7.5, 5))
        self.assertEqual(sum(m.cantidad for m in self.inv.listar_movimientos()), 5)

    def test_editar_inexistente_o_invalido(self):
        with self.assertRaises(NoEncontrado):
            self.inv.actualizar_producto(999, "x", "", 1.0)
        p = self.inv.crear_producto("Mouse", "", 5.0, 5)
        with self.assertRaises(ErrorValidacion):
            self.inv.actualizar_producto(p.id, "", "", 1.0)
        with self.assertRaises(ErrorValidacion):
            self.inv.actualizar_producto(p.id, "ok", "", float("nan"))

    def test_eliminar_es_logico_y_conserva_historial(self):
        p = self.inv.crear_producto("Mouse", "", 5.0, 5)
        self.inv.ajustar_stock(p.id, "salida", 2)
        self.inv.eliminar_producto(p.id)
        self.assertEqual(self.inv.listar_productos(), [])
        self.assertEqual(len(self.inv.listar_movimientos()), 2)       # historial intacto
        self.assertEqual(self.inv.valor_total(), 0)                    # ya no cuenta
        with self.assertRaises(NoEncontrado):
            self.inv.eliminar_producto(p.id)                            # ya no existe
        with self.assertRaises(NoEncontrado):
            self.inv.ajustar_stock(p.id, "entrada", 1)

    def test_busqueda_por_nombre_descripcion_y_categoria(self):
        c = self.inv.agregar_categoria("Oficina")
        self.inv.crear_producto("Silla", "ergonómica", 100.0, 5, c.id)
        self.inv.crear_producto("Mesa", "madera", 200.0, 5)
        self.assertEqual([p.nombre for p in self.inv.listar_productos("sil")], ["Silla"])
        self.assertEqual([p.nombre for p in self.inv.listar_productos("MADERA")], ["Mesa"])
        self.assertEqual([p.nombre for p in self.inv.listar_productos("oficina")], ["Silla"])
        self.assertEqual(self.inv.listar_productos("zzz"), [])

    def test_busqueda_con_comodines_es_literal(self):
        self.inv.crear_producto("100% algodón", "", 1.0, 10)
        self.inv.crear_producto("Otro", "", 1.0, 10)
        self.inv.crear_producto("a_b", "", 1.0, 10)
        self.assertEqual(len(self.inv.listar_productos("%")), 1)
        self.assertEqual([p.nombre for p in self.inv.listar_productos("_")], ["a_b"])

    def test_busqueda_resistente_a_sql_injection(self):
        self.inv.crear_producto("Mouse", "", 1.0, 10)
        self.assertEqual(self.inv.listar_productos("'; DROP TABLE productos; --"), [])
        self.assertEqual(len(self.inv.listar_productos()), 1)

    def test_valor_total(self):
        self.inv.crear_producto("A", "", 10.0, 3)
        self.inv.crear_producto("B", "", 2.5, 4)
        self.assertAlmostEqual(self.inv.valor_total(), 40.0)

    def test_bajo_stock(self):
        self.inv.crear_producto("Poco", "", 1.0, 4)
        self.inv.crear_producto("Justo", "", 1.0, 5)
        self.inv.crear_producto("Cero", "", 1.0, 0)
        self.assertEqual({p.nombre for p in self.inv.productos_bajo_stock()}, {"Poco", "Cero"})


# ------------------------------------------------------------ stock
class TestStock(Base):
    def setUp(self):
        super().setUp()
        self.p = self.inv.crear_producto("Mouse", "", 5.0, 10)

    def test_entrada_y_salida(self):
        msg = self.inv.ajustar_stock(self.p.id, "entrada", 5)
        self.assertIn("15", msg)
        self.inv.ajustar_stock(self.p.id, "salida", 3)
        self.assertEqual(self.inv.obtener_producto(self.p.id).cantidad, 12)
        self.assertEqual([m.tipo for m in self.inv.listar_movimientos()],
                         ["salida", "entrada", "entrada"])             # más reciente primero

    def test_salida_exacta_deja_cero(self):
        self.inv.ajustar_stock(self.p.id, "salida", 10)
        self.assertEqual(self.inv.obtener_producto(self.p.id).cantidad, 0)

    def test_stock_insuficiente(self):
        with self.assertRaises(StockInsuficiente) as cm:
            self.inv.ajustar_stock(self.p.id, "salida", 11)
        self.assertEqual(cm.exception.disponible, 10)
        self.assertEqual(self.inv.obtener_producto(self.p.id).cantidad, 10)
        self.assertEqual(len(self.inv.listar_movimientos()), 1)        # no registró nada

    def test_cantidades_invalidas(self):
        for cant in [0, -3, 1.5, "5", True, None, MAX_CANTIDAD + 1]:
            with self.subTest(cant=cant):
                with self.assertRaises(ErrorValidacion):
                    self.inv.ajustar_stock(self.p.id, "entrada", cant)

    def test_tipo_invalido_y_producto_inexistente(self):
        with self.assertRaises(ErrorValidacion):
            self.inv.ajustar_stock(self.p.id, "robo", 1)
        with self.assertRaises(NoEncontrado):
            self.inv.ajustar_stock(999, "entrada", 1)

    def test_entrada_que_supera_el_maximo(self):
        with self.assertRaises(ErrorValidacion):
            self.inv.ajustar_stock(self.p.id, "entrada", MAX_CANTIDAD)
        self.assertEqual(self.inv.obtener_producto(self.p.id).cantidad, 10)

    def test_atomicidad_si_falla_el_movimiento_se_revierte_el_stock(self):
        with mock.patch.object(MovimientoRepository, "registrar",
                               side_effect=sqlite3.OperationalError("disco lleno")):
            with self.assertRaises(sqlite3.OperationalError):
                self.inv.ajustar_stock(self.p.id, "salida", 4)
        self.assertEqual(self.inv.obtener_producto(self.p.id).cantidad, 10)

    def test_atomicidad_al_crear_producto(self):
        with mock.patch.object(MovimientoRepository, "registrar",
                               side_effect=sqlite3.OperationalError("disco lleno")):
            with self.assertRaises(sqlite3.OperationalError):
                self.inv.crear_producto("Fantasma", "", 1.0, 5)
        self.assertEqual([p.nombre for p in self.inv.listar_productos()], ["Mouse"])


# ------------------------------------------------------------ categorías
class TestCategorias(Base):
    def test_agregar_y_listar_ordenado(self):
        self.inv.agregar_categoria("Zapatos"); self.inv.agregar_categoria("Bebidas")
        self.assertEqual([c.nombre for c in self.inv.listar_categorias()], ["Bebidas", "Zapatos"])

    def test_duplicadas_sin_importar_mayusculas_ni_tildes(self):
        self.inv.agregar_categoria("Electrónica")
        for dup in ["electrónica", "ELECTRÓNICA", "  Electrónica  "]:
            with self.assertRaises(ErrorValidacion):
                self.inv.agregar_categoria(dup)

    def test_nombre_vacio_o_largo(self):
        for malo in ["", "   ", None, "x" * 51]:
            with self.assertRaises(ErrorValidacion):
                self.inv.agregar_categoria(malo)

    def test_renombrar(self):
        a = self.inv.agregar_categoria("Uno"); self.inv.agregar_categoria("Dos")
        self.assertEqual(self.inv.renombrar_categoria(a.id, "Uno bis").nombre, "Uno bis")
        self.inv.renombrar_categoria(a.id, "uno BIS")          # mismo nombre (otra caja): permitido
        with self.assertRaises(ErrorValidacion):
            self.inv.renombrar_categoria(a.id, "dos")           # choca con otra
        with self.assertRaises(NoEncontrado):
            self.inv.renombrar_categoria(999, "x")

    def test_eliminar_sin_uso(self):
        c = self.inv.agregar_categoria("Temporal")
        self.inv.eliminar_categoria(c.id)
        self.assertEqual(self.inv.listar_categorias(), [])

    def test_eliminar_en_uso_se_rechaza(self):
        c = self.inv.agregar_categoria("Usada")
        self.inv.crear_producto("X", "", 1.0, 1, c.id)
        with self.assertRaises(ErrorInventario):
            self.inv.eliminar_categoria(c.id)
        self.assertEqual(len(self.inv.listar_categorias()), 1)

    def test_eliminar_categoria_con_producto_archivado(self):
        c = self.inv.agregar_categoria("Vieja")
        p = self.inv.crear_producto("X", "", 1.0, 1, c.id)
        self.inv.eliminar_producto(p.id)
        self.inv.eliminar_categoria(c.id)           # no debe fallar por la clave foránea
        self.assertEqual(self.inv.listar_categorias(), [])

    def test_quitar_categoria_de_un_producto(self):
        c = self.inv.agregar_categoria("Cat")
        p = self.inv.crear_producto("X", "", 1.0, 1, c.id)
        q = self.inv.actualizar_producto(p.id, "X", "", 1.0, None)
        self.assertIsNone(q.id_categoria)


# ------------------------------------------------------------ reporte
class TestReporte(Base):
    def setUp(self):
        super().setUp()
        self.inv.crear_producto("Teclado", "", 50.0, 2)
        self.inv.crear_producto("Monitor", "", 100.0, 10)
        self.rep = ReporteService(self.inv)

    def test_contenido(self):
        txt = self.rep.generar("ana", ahora=datetime(2026, 1, 2, 3, 4))
        self.assertIn("REPORTE DE INVENTARIO", txt)
        self.assertIn("2026-01-02 03:04", txt)
        self.assertIn("Usuario: ana", txt)
        self.assertIn("Teclado", txt)
        self.assertIn("1100.00", txt)                       # 2*50 + 10*100
        self.assertIn("STOCK BAJO", txt)
        self.assertIn("- Teclado: 2 unidades", txt)
        self.assertNotIn("- Monitor", txt)

    def test_guardar_archivo_y_error_de_ruta(self):
        with tempfile.TemporaryDirectory() as d:
            ruta = os.path.join(d, "r.txt")
            self.rep.guardar(ruta, "ana")
            with open(ruta, encoding="utf-8") as f:
                self.assertIn("VALOR TOTAL", f.read())
            with self.assertRaises(ErrorInventario):
                self.rep.guardar(os.path.join(d, "no_existe", "r.txt"), "ana")


# ------------------------------------------------------------ migración
class TestMigracion(unittest.TestCase):
    def test_bd_de_la_version_anterior(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)   # se registra primero: se ejecuta DESPUÉS de cerrar la BD
        ruta = os.path.join(d, "viejo.db")
        con = sqlite3.connect(ruta)
        con.executescript("""
            CREATE TABLE usuarios(id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario TEXT NOT NULL UNIQUE, clave_hash TEXT NOT NULL);
            CREATE TABLE categorias(id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL UNIQUE);
            CREATE TABLE productos(id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT NOT NULL,
                descripcion TEXT, precio REAL NOT NULL CHECK(precio >= 0),
                cantidad INTEGER NOT NULL CHECK(cantidad >= 0), id_categoria INTEGER,
                FOREIGN KEY(id_categoria) REFERENCES categorias(id));
            CREATE TABLE movimientos(id INTEGER PRIMARY KEY AUTOINCREMENT,
                id_producto INTEGER NOT NULL,
                tipo TEXT NOT NULL CHECK(tipo IN ('entrada','salida')),
                cantidad INTEGER NOT NULL, fecha TEXT NOT NULL,
                FOREIGN KEY(id_producto) REFERENCES productos(id));
        """)
        con.execute("INSERT INTO usuarios(usuario, clave_hash) VALUES ('admin', ?)",
                    (hashlib.sha256(b"admin123").hexdigest(),))
        con.execute("INSERT INTO productos(nombre, descripcion, precio, cantidad)"
                    " VALUES ('Viejo', 'x', 3.0, 7)")
        con.execute("INSERT INTO movimientos(id_producto, tipo, cantidad, fecha)"
                    " VALUES (1, 'entrada', 7, '2025-01-01 00:00:00')")
        con.commit(); con.close()

        db = Database(ruta)
        self.addCleanup(db.cerrar)
        inv = InventarioService(db)
        self.assertEqual([p.nombre for p in inv.listar_productos()], ["Viejo"])
        self.assertEqual(len(inv.listar_movimientos()), 1)
        inv.ajustar_stock(1, "salida", 2)
        inv.eliminar_producto(1)                             # columna 'activo' migrada

        auth = AuthService(db)
        self.assertTrue(auth.login("admin", "admin123"))     # hash legacy aceptado
        nuevo = db.conn.execute("SELECT clave_hash FROM usuarios").fetchone()[0]
        self.assertTrue(nuevo.startswith("pbkdf2_sha256$"))  # y migrado
        self.assertTrue(auth.login("admin", "admin123"))


if __name__ == "__main__":
    unittest.main()
