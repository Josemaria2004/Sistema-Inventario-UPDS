"""Tests de la interfaz Tkinter (ventanas reales). Necesitan un display:
   Linux sin pantalla:  xvfb-run -a python -m unittest discover -s tests -v
   Windows / macOS / Linux con escritorio: funcionan tal cual.
Si no hay display o tkinter, estos tests se omiten solos."""
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import seguridad
from database import Database
from reportes import ReporteService
from respaldos import RespaldoService
from servicios import AuthService, InventarioService

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, simpledialog, ttk
    _r = tk.Tk(); _r.destroy()
    import ui
    from ui import (App, Categorias, CambiarClave, DialogoCantidad, DialogoModal,
                    DialogoMoverCategoria, FormularioProducto, Historial, Login, Papelera)
    HAY_TK = True
except Exception:                                   # sin tkinter o sin display
    HAY_TK = False


def setUpModule():
    seguridad.ITERACIONES = 1000


def programar(ventana, clase, accion):
    """Espera a que aparezca un diálogo de `clase` dentro de `ventana` y le aplica `accion`."""
    def intento():
        for w in ventana.winfo_children():
            if isinstance(w, clase) and w.winfo_exists():
                accion(w)
                return
        ventana.after(20, intento)
    ventana.after(20, intento)

    def watchdog():                      # si un diálogo se queda abierto, ciérralo: el test falla en vez de colgarse
        for w in ventana.winfo_children():
            if isinstance(w, tk.Toplevel) and w.winfo_exists():
                w.destroy()
    id_wd = ventana.after(4000, watchdog)

    def cancelar(evento):
        if evento.widget is ventana:
            try:
                ventana.after_cancel(id_wd)
            except tk.TclError:
                pass
    ventana.bind("<Destroy>", cancelar, add="+")


@unittest.skipUnless(HAY_TK, "tkinter/display no disponible")
class BaseUI(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.auth = AuthService(self.db)
        self.inv = InventarioService(self.db)
        self.rep = ReporteService(self.inv)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.resp = RespaldoService(self.db, carpeta=os.path.join(self._tmp.name, "respaldos"))
        self.msgs = {"error": [], "info": [], "warning": []}
        self.askyesno = mock.Mock(return_value=True)
        for nombre, clave in [("showerror", "error"), ("showinfo", "info"),
                              ("showwarning", "warning")]:
            p = mock.patch.object(messagebox, nombre,
                                  side_effect=lambda t, m, _c=clave, **k: self.msgs[_c].append(m))
            p.start(); self.addCleanup(p.stop)
        p = mock.patch.object(messagebox, "askyesno", self.askyesno)
        p.start(); self.addCleanup(p.stop)
        self.app = App(self.auth, self.inv, self.rep, self.resp, usuario="tester", mostrar_avisos=False)
        self.addCleanup(self._cerrar)
        self.app.update()

    def _cerrar(self):
        try:
            self.app.destroy()
        except tk.TclError:
            pass
        self.db.cerrar()

    def filas(self):
        return [self.app.tabla.item(i, "values") for i in self.app.tabla.get_children()]

    def seleccionar(self, id_prod):
        self.app.tabla.selection_set(str(id_prod))


class TestCrud(BaseUI):
    def test_ventana_inicia_vacia(self):
        self.assertEqual(self.filas(), [])
        self.assertIn("0.00", self.app.lbl_total.cget("text"))
        self.assertIn("tester", self.app.title())

    def _todos_los_botones(self, w):
        encontrados = []
        for h in w.winfo_children():
            if isinstance(h, ttk.Button):
                encontrados.append(h)
            encontrados += self._todos_los_botones(h)
        return encontrados

    def test_todos_los_botones_son_visibles_incluso_con_la_ventana_minima(self):
        """Regresión: antes 'Categorías' y 'Exportar reporte' quedaban cortados."""
        ancho, alto = self.app.minsize()                 # el tamaño mínimo permitido
        self.app.geometry(f"{ancho}x{alto}")
        self.app.update()
        botones = self._todos_los_botones(self.app)
        self.assertEqual(len(botones), 13)   # 6 de acción + 6 del panel lateral + cambiar clave
        self.assertEqual(len(self.app.botones), 13)
        izq, abajo = self.app.winfo_rootx(), self.app.winfo_rooty() + self.app.winfo_height()
        der = izq + self.app.winfo_width()
        for b in botones:
            with self.subTest(boton=b.cget("text")):
                self.assertGreater(b.winfo_width(), 40)
                self.assertTrue(b.winfo_viewable())
                self.assertGreaterEqual(b.winfo_rootx(), izq)
                self.assertLessEqual(b.winfo_rootx() + b.winfo_width(), der)
                self.assertLessEqual(b.winfo_rooty() + b.winfo_height(), abajo)

    def test_ninguna_columna_de_la_tabla_queda_cortada(self):
        """Regresión: la columna 'Valor' quedaba fuera de la tabla."""
        for ancho, alto in [self.app.minsize(), (1120, 700)]:
            self.app.geometry(f"{ancho}x{alto}")
            self.app.update()
            suma = sum(int(self.app.tabla.column(c, "width"))
                       for c in self.app.tabla["columns"])
            self.assertLessEqual(suma, self.app.tabla.winfo_width() + 1,
                                 f"columnas ({suma}px) no caben en la tabla "
                                 f"({self.app.tabla.winfo_width()}px) a {ancho}x{alto}")

    def test_botones_de_acciones_con_ancho_natural(self):
        """Regresión: ttk reserva 11 caracteres por botón y apretaba el buscador."""
        self.app.update()
        self.assertGreater(self.app.entrada_busqueda.winfo_width(), 200)

    def test_tarjetas_de_resumen_se_actualizan(self):
        self.assertEqual(self.app.lbl_productos.cget("text"), "0")
        self.assertEqual(self.app.lbl_alertas.cget("text"), "0")
        self.inv.crear_producto("A", "", 10.0, 2)        # stock bajo
        self.inv.crear_producto("B", "", 5.0, 20)
        self.app.cargar_tabla()
        self.assertEqual(self.app.lbl_productos.cget("text"), "2")
        self.assertEqual(self.app.lbl_alertas.cget("text"), "1")
        self.assertIn("120.00", self.app.lbl_total.cget("text"))     # 10*2 + 5*20
        # la búsqueda filtra la tabla pero NO los totales del inventario
        self.app.entrada_busqueda.insert(0, "zzz")
        self.app.cargar_tabla()
        self.assertEqual(self.filas(), [])
        self.assertEqual(self.app.lbl_productos.cget("text"), "2")

    def test_mensaje_de_tabla_vacia(self):
        self.app.update()
        self.assertTrue(self.app.lbl_vacio.winfo_ismapped())
        self.assertIn("Agregar", self.app.lbl_vacio.cget("text"))
        self.inv.crear_producto("Mouse", "", 5.0, 20)
        self.app.cargar_tabla(); self.app.update()
        self.assertFalse(self.app.lbl_vacio.winfo_ismapped())
        self.app.entrada_busqueda.insert(0, "xyz")
        self.app.cargar_tabla(); self.app.update()
        self.assertTrue(self.app.lbl_vacio.winfo_ismapped())
        self.assertIn("xyz", self.app.lbl_vacio.cget("text"))

    def test_campo_de_busqueda_con_texto_de_ayuda(self):
        c = self.app.entrada_busqueda
        self.assertEqual(c.get(), "")                              # la ayuda no cuenta como texto
        self.assertIn("Buscar", ttk.Entry.get(c))                 # pero se ve en pantalla
        c.insert(0, "mou")
        self.assertEqual(c.get(), "mou")
        c.delete(0, "end")
        self.assertEqual(c.get(), "")
        self.assertIn("Buscar", ttk.Entry.get(c))                 # vuelve la ayuda

    def test_filas_alternadas_y_stock_bajo(self):
        for n in range(4):
            self.inv.crear_producto(f"P{n}", "", 1.0, 50)
        bajo = self.inv.crear_producto("Bajo", "", 1.0, 1)
        self.app.cargar_tabla()
        etiquetas = {i: self.app.tabla.item(i, "tags") for i in self.app.tabla.get_children()}
        self.assertEqual(etiquetas[str(bajo.id)], ("bajo",))
        self.assertIn(("par",), etiquetas.values())

    def test_columna_valor_en_la_tabla(self):
        self.inv.crear_producto("Mouse", "", 2.5, 10)
        self.app.cargar_tabla()
        self.assertEqual(self.filas()[0][6], "25.00")

    def test_agregar_con_coma_decimal(self):
        def llenar(d):
            d.entries["nombre"].insert(0, "Mouse")
            d.entries["descripcion"].insert(0, "óptico")
            d.entries["precio"].delete(0, "end"); d.entries["precio"].insert(0, "12,5")
            d.entries["cantidad"].delete(0, "end"); d.entries["cantidad"].insert(0, "10")
            d._guardar()
        programar(self.app, FormularioProducto, llenar)
        self.app.agregar()
        filas = self.filas()
        self.assertEqual(len(filas), 1)
        self.assertEqual((filas[0][1], filas[0][3], filas[0][4]), ("Mouse", "12.50", "10"))
        self.assertIn("125.00", self.app.lbl_total.cget("text"))
        self.assertEqual(self.msgs["error"], [])

    def test_formulario_invalido_no_se_cierra_y_conserva_lo_escrito(self):
        estado = {}
        def llenar(d):
            d.entries["nombre"].insert(0, "Cosa")
            d.entries["precio"].delete(0, "end"); d.entries["precio"].insert(0, "nan")
            d._guardar()
            estado["abierto"] = bool(d.winfo_exists())
            estado["nombre"] = d.entries["nombre"].get()
            d.entries["precio"].delete(0, "end"); d.entries["precio"].insert(0, "abc")
            d._guardar()
            d.entries["precio"].delete(0, "end"); d.entries["precio"].insert(0, "-3")
            d._guardar()
            d.destroy()
        programar(self.app, FormularioProducto, llenar)
        self.app.agregar()
        self.assertTrue(estado["abierto"])
        self.assertEqual(estado["nombre"], "Cosa")
        self.assertEqual(len(self.msgs["error"]), 3)
        self.assertEqual(self.filas(), [])

    def test_formulario_nombre_vacio(self):
        def llenar(d):
            d._guardar(); d.destroy()
        programar(self.app, FormularioProducto, llenar)
        self.app.agregar()
        self.assertIn("nombre", self.msgs["error"][0].lower())

    def test_editar_no_permite_tocar_cantidad(self):
        p = self.inv.crear_producto("Mouse", "", 5.0, 7)
        self.app.cargar_tabla(); self.seleccionar(p.id)
        visto = {}
        def editar(d):
            visto["estado"] = str(d.entries["cantidad"].cget("state"))
            visto["valor"] = d.entries["cantidad"].get()
            d.entries["nombre"].delete(0, "end"); d.entries["nombre"].insert(0, "Mouse Pro")
            d.entries["precio"].delete(0, "end"); d.entries["precio"].insert(0, "9.99")
            d._guardar()
        programar(self.app, FormularioProducto, editar)
        self.app.editar()
        self.assertEqual(visto, {"estado": "disabled", "valor": "7"})
        q = self.inv.obtener_producto(p.id)
        self.assertEqual((q.nombre, q.precio, q.cantidad), ("Mouse Pro", 9.99, 7))
        self.assertEqual(self.filas()[0][1], "Mouse Pro")

    def test_editar_y_ajustar_sin_seleccion_avisan(self):
        self.app.editar(); self.app.eliminar(); self.app.ajustar_stock("entrada")
        self.assertEqual(len(self.msgs["warning"]), 3)

    def test_eliminar_confirmado_y_cancelado(self):
        p = self.inv.crear_producto("Mouse", "", 5.0, 7)
        self.app.cargar_tabla(); self.seleccionar(p.id)
        self.askyesno.return_value = False
        self.app.eliminar()
        self.assertEqual(len(self.filas()), 1)
        self.askyesno.return_value = True
        self.app.eliminar()
        self.assertEqual(self.filas(), [])
        self.assertEqual(len(self.inv.listar_movimientos()), 1)     # el historial se conserva

    def test_busqueda_en_vivo(self):
        self.inv.crear_producto("Teclado", "", 5.0, 7)
        self.inv.crear_producto("Mouse", "", 5.0, 7)
        self.app.cargar_tabla()
        self.assertEqual(len(self.filas()), 2)
        self.app.entrada_busqueda.insert(0, "tecl")
        self.app.cargar_tabla()
        self.assertEqual([f[1] for f in self.filas()], ["Teclado"])

    def test_nombre_numerico_no_se_corrompe(self):
        p = self.inv.crear_producto("007", "", 5.0, 7)           # Treeview lo convertiría en 7
        self.app.cargar_tabla(); self.seleccionar(p.id)
        self.app.eliminar()
        self.assertIn("'007'", self.askyesno.call_args[0][1])

    def test_fila_con_stock_bajo_resaltada(self):
        a = self.inv.crear_producto("Poco", "", 1.0, 2)
        b = self.inv.crear_producto("Mucho", "", 1.0, 50)
        self.app.cargar_tabla()
        self.assertIn("bajo", self.app.tabla.item(str(a.id), "tags"))
        self.assertNotIn("bajo", self.app.tabla.item(str(b.id), "tags"))

    def test_seleccion_se_conserva_al_refrescar(self):
        p = self.inv.crear_producto("Mouse", "", 5.0, 7)
        self.app.cargar_tabla(); self.seleccionar(p.id)
        self.app.cargar_tabla()
        self.assertEqual(self.app.tabla.selection(), (str(p.id),))


class TestStockUI(BaseUI):
    def setUp(self):
        super().setUp()
        self.p = self.inv.crear_producto("Mouse", "", 5.0, 10)
        self.app.cargar_tabla(); self.seleccionar(self.p.id)

    def _cantidad(self, texto):
        def f(d):
            d.ent.insert(0, texto); d._ok()
        return f

    def test_salida_ok(self):
        programar(self.app, DialogoCantidad, self._cantidad("3"))
        self.app.ajustar_stock("salida")
        self.assertEqual(self.inv.obtener_producto(self.p.id).cantidad, 7)
        self.assertEqual(self.filas()[0][4], "7")
        self.assertIn("7", self.msgs["info"][0])

    def test_entrada_ok(self):
        programar(self.app, DialogoCantidad, self._cantidad("5"))
        self.app.ajustar_stock("entrada")
        self.assertEqual(self.filas()[0][4], "15")

    def test_salida_con_stock_insuficiente(self):
        programar(self.app, DialogoCantidad, self._cantidad("99"))
        self.app.ajustar_stock("salida")
        self.assertIn("Stock insuficiente", self.msgs["error"][0])
        self.assertEqual(self.inv.obtener_producto(self.p.id).cantidad, 10)

    def test_dialogo_rechaza_texto_cero_y_negativos(self):
        estado = {}
        def f(d):
            for malo in ["abc", "0", "-2", "1.5", ""]:
                d.ent.delete(0, "end"); d.ent.insert(0, malo); d._ok()
            estado["abierto"] = bool(d.winfo_exists())
            d.ent.delete(0, "end"); d.ent.insert(0, "2"); d._ok()
        programar(self.app, DialogoCantidad, f)
        self.app.ajustar_stock("entrada")
        self.assertTrue(estado["abierto"])
        self.assertEqual(len(self.msgs["error"]), 5)
        self.assertEqual(self.filas()[0][4], "12")

    def test_cancelar_dialogo_no_cambia_nada(self):
        programar(self.app, DialogoCantidad, lambda d: d.destroy())
        self.app.ajustar_stock("salida")
        self.assertEqual(self.filas()[0][4], "10")
        self.assertEqual(self.msgs["info"], [])


class TestLoginUI(BaseUI):
    def _login(self, auth, script):
        """Crea una App SIN usuario (pide login) ejecutando `script` sobre el diálogo."""
        original = DialogoModal.mostrar
        def con_script(dlg):
            dlg.after(50, lambda: script(dlg))
            return original(dlg)
        with mock.patch.object(DialogoModal, "mostrar", con_script):
            return App(auth, self.inv, self.rep, self.resp, mostrar_avisos=False)

    def test_login_correcto_abre_la_app_con_el_usuario(self):
        """Regresión del bug de main.py:12: el usuario debe estar disponible tras el login."""
        def script(d):
            d.ent_usuario.insert(0, "admin"); d.ent_clave.insert(0, "admin123"); d._entrar()
        app = self._login(self.auth, script)
        try:
            self.assertTrue(app.autenticado)
            self.assertEqual(app.usuario, "admin")
            self.assertIn("admin", app.title())
            self.assertTrue(app.winfo_viewable() or app.state() == "normal")
        finally:
            app.destroy()

    def test_login_incorrecto_y_luego_correcto(self):
        def script(d):
            d.ent_usuario.insert(0, "admin"); d.ent_clave.insert(0, "mala"); d._entrar()
            self.assertTrue(d.winfo_exists())
            self.assertEqual(d.ent_clave.get(), "")               # limpia la clave
            d.ent_clave.insert(0, "admin123"); d._entrar()
        app = self._login(self.auth, script)
        try:
            self.assertTrue(app.autenticado)
            self.assertEqual(len(self.msgs["error"]), 1)
            self.assertIn("incorrectos", self.msgs["error"][0])
        finally:
            app.destroy()

    def test_cerrar_login_no_abre_la_app(self):
        app = self._login(self.auth, lambda d: d.destroy())
        self.assertFalse(app.autenticado)

    def test_bloqueo_por_intentos_se_muestra(self):
        auth = AuthService(self.db, max_intentos=2, bloqueo_seg=60)
        def script(d):
            d.ent_usuario.insert(0, "admin")
            for _ in range(3):
                d.ent_clave.delete(0, "end"); d.ent_clave.insert(0, "mala"); d._entrar()
            d.destroy()
        app = self._login(auth, script)
        self.assertFalse(app.autenticado)
        self.assertTrue(any("Espera" in m for m in self.msgs["error"]))

    def test_login_no_muestra_la_clave_por_defecto(self):
        def script(d):
            textos = []
            def recorrer(w):
                for h in w.winfo_children():
                    try:
                        textos.append(str(h.cget("text")))
                    except tk.TclError:
                        pass
                    recorrer(h)
            recorrer(d)
            self.assertFalse(any("admin123" in t for t in textos), textos)
            d.destroy()
        self._login(self.auth, script)


class TestCategoriasUI(BaseUI):
    def setUp(self):
        super().setUp()
        self.win = Categorias(self.app, self.inv, al_cambiar=self.app.cargar_tabla)
        self.addCleanup(lambda: self.win.winfo_exists() and self.win.destroy())

    def arbol(self, padre=""):
        """Árbol del Treeview como [(nombre, [hijos...])] (recursivo)."""
        return [(self.win.arbol.item(i, "text"), self.arbol(i))
                for i in self.win.arbol.get_children(padre)]

    def seleccionar_cat(self, id_cat):
        self.win.arbol.selection_set(str(id_cat))
        self.win.update()

    def test_agregar_duplicada_renombrar_eliminar(self):
        self.win.ent.insert(0, "Bebidas"); self.win._agregar()
        self.assertEqual(self.arbol(), [("Bebidas", [])])
        self.win.ent.insert(0, "bebidas"); self.win._agregar()
        self.assertIn("ya existe", self.msgs["error"][-1])

        id_beb = self.inv.listar_categorias()[0].id
        p = self.inv.crear_producto("Cola", "", 1.0, 5, id_beb)
        self.app.cargar_tabla()
        self.seleccionar_cat(id_beb)
        with mock.patch.object(simpledialog, "askstring", return_value="Licores"):
            self.win._renombrar()
        self.assertEqual(self.arbol(), [("Licores", [])])
        self.assertEqual(self.filas()[0][5], "Licores")        # la tabla principal se refresca

        self.win._eliminar()                                   # en uso -> se rechaza
        self.assertIn("usan esta categoría", self.msgs["error"][-1])
        self.inv.eliminar_producto(p.id)
        self.win._eliminar()
        self.assertEqual(self.arbol(), [])

    def test_sin_seleccion_avisa(self):
        self.win._renombrar(); self.win._eliminar(); self.win._mover()
        self.assertEqual(len(self.msgs["warning"]), 3)

    def test_subcategorias_en_el_arbol_con_totales_recursivos(self):
        self.win.ent.insert(0, "Electrónica"); self.win._agregar()
        elec = self.win._id_seleccionado()                       # tras agregar queda seleccionada
        self.win.update()
        self.assertEqual(self.win.combo_padre.get(), "Electrónica")   # propone crear dentro de ella
        self.win.ent.insert(0, "Audio"); self.win._agregar()
        self.assertEqual(self.arbol(), [("Electrónica", [("Audio", [])])])
        audio = self.win._id_seleccionado()
        self.inv.crear_producto("Radio", "", 10.0, 3, elec)          # 30
        self.inv.crear_producto("Parlante", "", 20.0, 2, audio)      # 40
        self.app.cargar_tabla(); self.win._cargar()
        self.assertEqual(self.win.arbol.item(str(audio), "values"), ("1", "40.00"))
        self.assertEqual(self.win.arbol.item(str(elec), "values"), ("2", "70.00"))   # suma la hija
        self.assertEqual(sorted(f[5] for f in self.filas()),
                         ["Electrónica", "Electrónica > Audio"])      # ruta completa en la tabla

    def test_agregar_como_categoria_principal(self):
        c = self.inv.agregar_categoria("Padre")
        self.win._cargar(seleccionar=c.id)
        self.win.update()
        self.win.combo_padre.current(0)                              # "(Categoría principal)"
        self.win.ent.insert(0, "Otra raíz"); self.win._agregar()
        self.assertEqual([n for n, _ in self.arbol()], ["Otra raíz", "Padre"])

    def test_mover_categoria_con_dialogo(self):
        a = self.inv.agregar_categoria("A"); b = self.inv.agregar_categoria("B")
        hija = self.inv.agregar_categoria("Hija", a.id)
        self.win._cargar(); self.seleccionar_cat(a.id)
        visto = {}
        def elegir(d):
            visto["opciones"] = list(d.combo.cget("values"))
            d.combo.current(visto["opciones"].index("B")); d._ok()
        programar(self.win, DialogoMoverCategoria, elegir)
        self.win._mover()
        self.assertEqual(visto["opciones"], ["(Categoría principal)", "B"])   # sin A ni su hija
        self.assertEqual(self.arbol(), [("B", [("A", [("Hija", [])])])])

    def test_mover_cancelado_no_cambia_nada(self):
        a = self.inv.agregar_categoria("A"); self.inv.agregar_categoria("B")
        self.win._cargar(); self.seleccionar_cat(a.id)
        programar(self.win, DialogoMoverCategoria, lambda d: d.destroy())
        self.win._mover()
        self.assertEqual(self.arbol(), [("A", []), ("B", [])])

    def test_eliminar_con_subcategorias_se_rechaza(self):
        a = self.inv.agregar_categoria("A"); self.inv.agregar_categoria("H", a.id)
        self.win._cargar(); self.seleccionar_cat(a.id)
        self.win._eliminar()
        self.assertIn("subcategoría", self.msgs["error"][-1])
        self.assertEqual(self.arbol(), [("A", [("H", [])])])

    def test_producto_con_categoria_y_sin_ella_desde_el_formulario(self):
        madre = self.inv.agregar_categoria("Madre")
        self.inv.agregar_categoria("Hija", madre.id)
        def llenar(d):
            self.assertEqual(list(d.combo_cat.cget("values")),
                             ["(Sin categoría)", "Madre", "Madre > Hija"])
            d.entries["nombre"].insert(0, "X")
            d.combo_cat.current(2); d._guardar()
        programar(self.app, FormularioProducto, llenar)
        self.app.agregar()
        self.assertEqual(self.filas()[0][5], "Madre > Hija")
        self.seleccionar(int(self.app.tabla.get_children()[0]))
        def quitar(d):
            self.assertEqual(d.combo_cat.get(), "Madre > Hija")
            d.combo_cat.current(0); d._guardar()
        programar(self.app, FormularioProducto, quitar)
        self.app.editar()
        self.assertEqual(self.filas()[0][5], "—")


class TestRequisitosUI(BaseUI):
    """Ordenar con merge sort, deshacer (pila), papelera, respaldo/restauración, CSV."""

    def nombres(self):
        return [f[1] for f in self.filas()]

    # ---------------- ordenar por columna (merge sort) ----------------
    def test_ordenar_por_columnas(self):
        c = self.inv.agregar_categoria("Zeta")
        self.inv.crear_producto("banana", "", 3.0, 10, c.id)
        self.inv.crear_producto("Apple", "", 9.5, 4)
        self.inv.crear_producto("cherry", "", 1.0, 7)
        self.app.cargar_tabla()
        self.app._ordenar_por("precio")
        self.assertEqual(self.nombres(), ["cherry", "banana", "Apple"])
        self.app._ordenar_por("precio")                              # 2.º clic: descendente
        self.assertEqual(self.nombres(), ["Apple", "banana", "cherry"])
        self.app._ordenar_por("nombre")                              # sin distinguir mayúsculas
        self.assertEqual(self.nombres(), ["Apple", "banana", "cherry"])
        self.app._ordenar_por("nombre")
        self.assertEqual(self.nombres(), ["cherry", "banana", "Apple"])
        self.app._ordenar_por("cantidad")
        self.assertEqual(self.nombres(), ["Apple", "cherry", "banana"])
        self.app._ordenar_por("categoria")                           # '—' (sin categoría) primero
        self.assertEqual(self.nombres()[-1], "banana")
        self.app._ordenar_por("valor")
        self.assertEqual([f[6] for f in self.filas()], ["7.00", "30.00", "38.00"])

    def test_indicador_de_orden_en_el_encabezado(self):
        self.app._ordenar_por("precio")
        self.assertIn("▲", self.app.tabla.heading("precio", "text"))
        self.app._ordenar_por("precio")
        self.assertIn("▼", self.app.tabla.heading("precio", "text"))
        self.app._ordenar_por("nombre")
        self.assertNotIn("▼", self.app.tabla.heading("precio", "text"))
        self.assertIn("▲", self.app.tabla.heading("nombre", "text"))

    def test_orden_se_mantiene_al_buscar_y_al_refrescar(self):
        for n, pr in [("Aa1", 5.0), ("Aa2", 1.0), ("Aa3", 3.0), ("Otro", 0.5)]:
            self.inv.crear_producto(n, "", pr, 10)
        self.app.cargar_tabla()
        self.app._ordenar_por("precio")
        self.app.entrada_busqueda.insert(0, "aa")
        self.app.cargar_tabla()
        self.assertEqual(self.nombres(), ["Aa2", "Aa3", "Aa1"])

    # ---------------- deshacer ----------------
    def test_boton_deshacer_se_habilita_con_operaciones(self):
        p = self.inv.crear_producto("Mouse", "", 5.0, 10)
        self.app.cargar_tabla(); self.app.tabla.selection_set(str(p.id))
        self.assertTrue(self.app.btn_deshacer.instate(["disabled"]))
        programar(self.app, DialogoCantidad, lambda d: (d.ent.insert(0, "4"), d._ok()))
        self.app.ajustar_stock("salida")
        self.assertTrue(self.app.btn_deshacer.instate(["!disabled"]))
        self.assertEqual(self.filas()[0][4], "6")
        self.app.deshacer()
        self.assertEqual(self.filas()[0][4], "10")
        self.assertIn("deshizo", self.msgs["info"][-1])
        self.assertIn("salida de 4", self.askyesno.call_args[0][1])    # pregunta qué va a deshacer
        self.assertTrue(self.app.btn_deshacer.instate(["disabled"]))

    def test_deshacer_cancelado(self):
        p = self.inv.crear_producto("Mouse", "", 5.0, 10)
        self.inv.ajustar_stock(p.id, "entrada", 5)
        self.app.cargar_tabla()
        self.askyesno.return_value = False
        self.app.deshacer()
        self.assertEqual(self.filas()[0][4], "15")

    def test_deshacer_sin_operaciones(self):
        self.app.deshacer()
        self.assertIn("No hay operaciones", self.msgs["info"][-1])

    def test_deshacer_imposible_muestra_el_motivo(self):
        p = self.inv.crear_producto("Mouse", "", 5.0, 10)
        self.inv.ajustar_stock(p.id, "entrada", 5)
        with self.db.transaccion():
            self.inv.productos.ajustar_cantidad(p.id, -14)
        self.app.cargar_tabla()
        self.app.deshacer()
        self.assertIn("stock actual es 1", self.msgs["error"][-1])

    # ---------------- papelera ----------------
    def test_papelera_restaura_productos(self):
        p = self.inv.crear_producto("Mouse", "", 5.0, 10)
        self.app.cargar_tabla(); self.app.tabla.selection_set(str(p.id))
        self.app.eliminar()
        self.assertEqual(self.filas(), [])
        win = Papelera(self.app, self.inv, al_cambiar=self.app.cargar_tabla)
        try:
            win.update()
            self.assertEqual(len(win.tabla.get_children()), 1)
            win._restaurar()                                          # sin selección: avisa
            self.assertEqual(len(self.msgs["warning"]), 1)
            win.tabla.selection_set(str(p.id))
            win._restaurar()
            self.assertEqual(self.nombres(), ["Mouse"])               # vuelve a la tabla principal
            self.assertEqual(win.tabla.get_children(), ())
            win.update()
            self.assertTrue(win.lbl_vacio.winfo_ismapped())
        finally:
            win.destroy()

    def test_boton_abre_la_papelera(self):
        self.app.ventana_papelera()
        hijas = [w for w in self.app.winfo_children() if isinstance(w, Papelera)]
        self.assertEqual(len(hijas), 1)
        hijas[0].destroy()

    # ---------------- respaldo y restauración ----------------
    def test_crear_respaldo_desde_la_interfaz(self):
        self.inv.crear_producto("A", "", 1.0, 3)
        with tempfile.TemporaryDirectory() as d:
            ruta = os.path.join(d, "mi_respaldo.db")
            with mock.patch.object(filedialog, "asksaveasfilename", return_value=ruta):
                self.app.crear_respaldo()
            self.assertEqual(self.resp.inspeccionar(ruta)["productos"], 1)
            self.assertIn("Respaldo creado", self.msgs["info"][-1])
            with mock.patch.object(filedialog, "asksaveasfilename", return_value=""):
                self.app.crear_respaldo()                            # cancelar: no hace nada

    def test_restaurar_respaldo_desde_la_interfaz(self):
        p = self.inv.crear_producto("Original", "", 1.0, 3)
        self.inv.ajustar_stock(p.id, "entrada", 1)                   # llena la pila de deshacer
        with tempfile.TemporaryDirectory() as d:
            ruta = self.resp.crear(os.path.join(d, "r.db"))
            self.inv.eliminar_producto(p.id)
            self.inv.crear_producto("Intruso", "", 1.0, 1)
            self.app.cargar_tabla()
            self.assertEqual(self.nombres(), ["Intruso"])

            with mock.patch.object(filedialog, "askopenfilename", return_value=str(ruta)):
                self.askyesno.return_value = False                   # el usuario se arrepiente
                self.app.restaurar_respaldo()
                self.assertEqual(self.nombres(), ["Intruso"])
                self.assertIn("REEMPLAZARÁN", self.askyesno.call_args[0][1])
                self.askyesno.return_value = True
                self.app.restaurar_respaldo()
            self.assertEqual(self.nombres(), ["Original"])           # datos recuperados
            self.assertFalse(self.inv.puede_deshacer())               # la pila ya no tiene sentido
            self.assertIn("antes_de_restaurar", self.msgs["info"][-1])   # indica dónde quedó lo anterior

    def test_restaurar_archivo_invalido_muestra_error(self):
        self.inv.crear_producto("A", "", 1.0, 3)
        with tempfile.TemporaryDirectory() as d:
            falso = os.path.join(d, "falso.db")
            with open(falso, "w") as f:
                f.write("no soy una base de datos")
            with mock.patch.object(filedialog, "askopenfilename", return_value=falso):
                self.app.restaurar_respaldo()
        self.assertTrue(self.msgs["error"])
        self.app.cargar_tabla()
        self.assertEqual(self.nombres(), ["A"])

    # ---------------- reporte en CSV ----------------
    def test_exportar_reporte_csv_y_tipos_de_archivo(self):
        self.inv.crear_producto("Teclado", "", 50.0, 2)
        with tempfile.TemporaryDirectory() as d:
            ruta = os.path.join(d, "reporte.csv")
            with mock.patch.object(filedialog, "asksaveasfilename",
                                   return_value=ruta) as dialogo:
                self.app.exportar_reporte()
            self.assertIn(("CSV (Excel)", "*.csv"), dialogo.call_args.kwargs["filetypes"])
            with open(ruta, encoding="utf-8-sig") as f:
                contenido = f.read()
            self.assertTrue(contenido.startswith("ID;Producto;"))
            self.assertIn("Teclado", contenido)

    def test_el_panel_lateral_ofrece_la_recuperacion_de_datos(self):
        textos = {b.cget("text") for b in self.app.botones}
        for esperado in ("Productos eliminados", "Crear respaldo", "Restaurar respaldo",
                         "Deshacer", "Historial", "Categorías", "Exportar reporte"):
            self.assertIn(esperado, textos)


class TestOtrasVentanas(BaseUI):
    def test_historial(self):
        p = self.inv.crear_producto("Mouse", "", 5.0, 10)
        self.inv.ajustar_stock(p.id, "salida", 4)
        h = Historial(self.app, self.inv)
        try:
            items = h.tabla.get_children()
            self.assertEqual(len(items), 2)
            self.assertEqual(h.tabla.item(items[0], "values")[2], "salida")   # el más reciente primero
            self.assertIn("salida", h.tabla.item(items[0], "tags"))
        finally:
            h.destroy()

    def test_exportar_reporte(self):
        self.inv.crear_producto("Teclado", "", 50.0, 2)
        with tempfile.TemporaryDirectory() as d:
            ruta = os.path.join(d, "reporte.txt")
            with mock.patch.object(filedialog, "asksaveasfilename", return_value=ruta):
                self.app.exportar_reporte()
            with open(ruta, encoding="utf-8") as f:
                txt = f.read()
            self.assertIn("Teclado", txt); self.assertIn("tester", txt)
            self.assertIn("Reporte guardado", self.msgs["info"][0])
            malo = os.path.join(d, "no_existe", "r.txt")
            with mock.patch.object(filedialog, "asksaveasfilename", return_value=malo):
                self.app.exportar_reporte()
            self.assertIn("No se pudo guardar", self.msgs["error"][0])

    def test_exportar_cancelado(self):
        with mock.patch.object(filedialog, "asksaveasfilename", return_value=""):
            self.app.exportar_reporte()
        self.assertEqual(self.msgs["info"] + self.msgs["error"], [])

    def test_cambiar_clave(self):
        self.app.usuario = "admin"
        def llenar(d):
            for e, v in zip(d.entries, ["admin123", "nueva-clave", "otra-distinta"]):
                e.insert(0, v)
            d._guardar()                                        # no coinciden -> error
            d.entries[2].delete(0, "end"); d.entries[2].insert(0, "nueva-clave")
            d._guardar()
        programar(self.app, CambiarClave, llenar)
        self.app.cambiar_clave()
        self.assertIn("no coinciden", self.msgs["error"][0])
        self.assertTrue(self.auth.login("admin", "nueva-clave"))
        self.assertIn("actualizada", self.msgs["info"][0])

    def test_avisos_iniciales_stock_bajo_y_clave_por_defecto(self):
        self.inv.crear_producto("Pocos", "", 1.0, 2)
        self.askyesno.return_value = False
        self.app.usuario = "admin"
        self.app._avisos_iniciales()
        self.assertIn("Pocos", self.msgs["warning"][0])
        self.assertEqual(self.askyesno.call_count, 1)            # ofrece cambiar la clave
        self.auth.cambiar_clave("admin", "admin123", "otra-clave-1")
        self.app._avisos_iniciales()
        self.assertEqual(self.askyesno.call_count, 1)            # ya no la ofrece

    def test_error_de_base_de_datos_se_muestra(self):
        with mock.patch.object(self.inv, "listar_productos",
                               side_effect=sqlite3.OperationalError("database is locked")):
            self.app.cargar_tabla()
        self.assertIn("database is locked", self.msgs["error"][0])

    def test_error_inesperado_en_callback_se_muestra(self):
        with mock.patch("ui.traceback.print_exception"):
            self.app.report_callback_exception(ValueError, ValueError("boom"), None)
        self.assertIn("boom", self.msgs["error"][0])


if __name__ == "__main__":
    unittest.main()
