"""Tests de los requisitos de la materia: recursividad, memoria dinámica (estructuras
enlazadas), clases base abstractas y recuperación de datos (respaldo / papelera)."""
import csv
import io
import os
import random
import sqlite3
import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import algoritmos
from algoritmos import merge_sort
from database import (CategoriaRepository, Database, MovimientoRepository,
                      ProductoRepository, RepositorioBase, UsuarioRepository)
from estructuras import ArbolCategorias, EstructuraVacia, ListaEnlazada, Pila
from models import (Categoria, Entidad, ErrorInventario, ErrorValidacion, NoEncontrado,
                    Producto)
from reportes import DatosReporte, Reporte, ReporteCsv, ReporteService, ReporteTxt
from respaldos import RespaldoService
from servicios import AuthService, InventarioService


class Base(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.inv = InventarioService(self.db)
        self.addCleanup(self.db.cerrar)


# =====================================================================
#  MEMORIA DINÁMICA: lista enlazada y pila
# =====================================================================
class TestListaEnlazada(unittest.TestCase):
    def test_vacia(self):
        l = ListaEnlazada()
        self.assertEqual((len(l), l.esta_vacia(), list(l)), (0, True, []))
        for operacion in (l.primero, l.eliminar_primero, l.eliminar_ultimo):
            with self.assertRaises(EstructuraVacia):
                operacion()

    def test_agregar_y_eliminar(self):
        l = ListaEnlazada()
        for x in (1, 2, 3):
            l.agregar_al_final(x)
        l.agregar_al_inicio(0)
        self.assertEqual(l.a_lista(), [0, 1, 2, 3])
        self.assertEqual(l.eliminar_primero(), 0)
        self.assertEqual(l.eliminar_ultimo(), 3)
        self.assertEqual(l.a_lista(), [1, 2])
        l.agregar_al_final(9)                       # la cola debe seguir bien enlazada
        self.assertEqual(l.a_lista(), [1, 2, 9])

    def test_un_solo_elemento_y_volver_a_llenar(self):
        l = ListaEnlazada()
        l.agregar_al_final("a")
        self.assertEqual(l.eliminar_ultimo(), "a")
        self.assertTrue(l.esta_vacia())
        l.agregar_al_inicio("b"); l.agregar_al_final("c")
        self.assertEqual(l.a_lista(), ["b", "c"])

    def test_buscar_y_vaciar(self):
        l = ListaEnlazada()
        for x in (5, 8, 12):
            l.agregar_al_final(x)
        self.assertEqual(l.buscar(lambda v: v > 6), 8)
        self.assertIsNone(l.buscar(lambda v: v > 100))
        l.vaciar()
        self.assertEqual((len(l), l.a_lista()), (0, []))

    def test_equivale_a_una_lista_de_python_con_operaciones_aleatorias(self):
        rnd = random.Random(7)
        l, ref = ListaEnlazada(), []
        for _ in range(2000):
            op = rnd.choice(["fin", "ini", "pri", "ult"])
            if op == "fin":
                v = rnd.randint(0, 99); l.agregar_al_final(v); ref.append(v)
            elif op == "ini":
                v = rnd.randint(0, 99); l.agregar_al_inicio(v); ref.insert(0, v)
            elif ref and op == "pri":
                self.assertEqual(l.eliminar_primero(), ref.pop(0))
            elif ref and op == "ult":
                self.assertEqual(l.eliminar_ultimo(), ref.pop())
            self.assertEqual(len(l), len(ref))
        self.assertEqual(l.a_lista(), ref)


class TestPila(unittest.TestCase):
    def test_lifo(self):
        p = Pila()
        for x in "abc":
            p.apilar(x)
        self.assertEqual(p.tope(), "c")
        self.assertEqual(len(p), 3)                # tope() no saca nada
        self.assertEqual([p.desapilar() for _ in range(3)], ["c", "b", "a"])
        self.assertTrue(p.esta_vacia())

    def test_pila_vacia(self):
        p = Pila()
        with self.assertRaises(EstructuraVacia):
            p.desapilar()
        with self.assertRaises(EstructuraVacia):
            p.tope()

    def test_capacidad_descarta_lo_mas_antiguo(self):
        p = Pila(capacidad=3)
        for x in range(1, 6):
            p.apilar(x)
        self.assertEqual(list(p), [5, 4, 3])        # del tope al fondo
        self.assertEqual(len(p), 3)

    def test_capacidad_invalida_y_vaciar(self):
        with self.assertRaises(ValueError):
            Pila(capacidad=0)
        p = Pila(); p.apilar(1); p.vaciar()
        self.assertTrue(p.esta_vacia())


# =====================================================================
#  RECURSIVIDAD: árbol de categorías y merge sort
# =====================================================================
def categorias_ejemplo():
    return [Categoria(1, "Electrónica"), Categoria(2, "Audio", 1),
            Categoria(3, "Auriculares", 2), Categoria(4, "Oficina"),
            Categoria(5, "Muebles", 4), Categoria(6, "Cables", 1)]


class TestArbolCategorias(unittest.TestCase):
    def setUp(self):
        self.a = ArbolCategorias(categorias_ejemplo())

    def test_recorrido_preorden_ordenado(self):
        self.assertEqual([(n.nombre, nivel) for n, nivel in self.a.recorrer()],
                         [("Electrónica", 0), ("Audio", 1), ("Auriculares", 2),
                          ("Cables", 1), ("Oficina", 0), ("Muebles", 1)])

    def test_ruta_y_nivel(self):
        self.assertEqual(self.a.ruta(3), "Electrónica > Audio > Auriculares")
        self.assertEqual(self.a.ruta(1), "Electrónica")
        self.assertEqual(self.a.ruta(3, " / "), "Electrónica / Audio / Auriculares")
        self.assertEqual(self.a.ruta(999), "")
        self.assertEqual([self.a.nivel(i) for i in (1, 2, 3, 999)], [0, 1, 2, 0])

    def test_ids_del_subarbol(self):
        self.assertEqual(self.a.ids_subarbol(1), {1, 2, 3, 6})
        self.assertEqual(self.a.ids_subarbol(2), {2, 3})
        self.assertEqual(self.a.ids_subarbol(3), {3})
        self.assertEqual(self.a.ids_subarbol(999), set())

    def test_altura(self):
        self.assertEqual(self.a.altura(), 3)
        self.assertEqual(ArbolCategorias([]).altura(), 0)
        self.assertEqual(ArbolCategorias([Categoria(1, "x")]).altura(), 1)

    def test_total_recursivo(self):
        directo = {3: 5, 2: 1, 6: 10, 4: 100}
        self.assertEqual(self.a.total(1, directo), 16)      # 0 + (1 + 5) + 10
        self.assertEqual(self.a.total(2, directo), 6)
        self.assertEqual(self.a.total(4, directo), 100)
        self.assertEqual(self.a.total(5, directo), 0)
        self.assertEqual(self.a.total(999, directo), 0)

    def test_puede_ser_padre_evita_ciclos(self):
        self.assertFalse(self.a.puede_ser_padre(1, 1))      # dentro de sí misma
        self.assertFalse(self.a.puede_ser_padre(1, 3))      # dentro de su nieta
        self.assertFalse(self.a.puede_ser_padre(2, 3))
        self.assertTrue(self.a.puede_ser_padre(2, 1))
        self.assertTrue(self.a.puede_ser_padre(3, 4))
        self.assertTrue(self.a.puede_ser_padre(3, None))

    def test_padre_inexistente_o_propio_se_trata_como_raiz(self):
        a = ArbolCategorias([Categoria(1, "A", 99), Categoria(2, "B", 2)])
        self.assertEqual([n.nombre for n in a.raices], ["A", "B"])

    def test_ciclos_en_datos_danados_no_provocan_recursion_infinita(self):
        for cats in ([Categoria(1, "A", 2), Categoria(2, "B", 1)],
                     [Categoria(1, "A", 3), Categoria(2, "B", 1), Categoria(3, "C", 2),
                      Categoria(4, "D")]):
            a = ArbolCategorias(cats)
            visitados = [n.id for n, _ in a.recorrer()]
            self.assertEqual(sorted(visitados), sorted(c.id for c in cats))
            for c in cats:
                a.ruta(c.id); a.ids_subarbol(c.id)           # no deben colgarse

    def test_arbol_profundo(self):
        cats = [Categoria(1, "n1")] + [Categoria(i, f"n{i}", i - 1) for i in range(2, 201)]
        a = ArbolCategorias(cats)
        self.assertEqual(a.altura(), 200)
        self.assertEqual(a.ruta(200).count(" > "), 199)
        self.assertEqual(len(a.ids_subarbol(1)), 200)


class TestMergeSort(unittest.TestCase):
    def test_igual_que_sorted_con_listas_aleatorias(self):
        rnd = random.Random(11)
        for _ in range(300):
            datos = [rnd.randint(-20, 20) for _ in range(rnd.randint(0, 60))]
            self.assertEqual(merge_sort(datos), sorted(datos))
            self.assertEqual(merge_sort(datos, reverso=True), sorted(datos, reverse=True))

    def test_es_estable_en_ambos_sentidos(self):
        rnd = random.Random(3)
        datos = [(rnd.randint(0, 4), i) for i in range(200)]
        self.assertEqual(merge_sort(datos, clave=lambda t: t[0]),
                         sorted(datos, key=lambda t: t[0]))
        self.assertEqual(merge_sort(datos, clave=lambda t: t[0], reverso=True),
                         sorted(datos, key=lambda t: t[0], reverse=True))

    def test_casos_borde_y_no_modifica_el_original(self):
        self.assertEqual(merge_sort([]), [])
        self.assertEqual(merge_sort([7]), [7])
        original = [3, 1, 2]
        resultado = merge_sort(original)
        self.assertEqual(original, [3, 1, 2])
        self.assertIsNot(resultado, original)
        self.assertEqual(merge_sort((3, 1, 2)), [1, 2, 3])
        self.assertEqual(merge_sort(["b", "A", "c"], clave=str.casefold), ["A", "b", "c"])

    def test_lista_grande(self):
        rnd = random.Random(5)
        datos = [rnd.random() for _ in range(5000)]
        self.assertEqual(merge_sort(datos), sorted(datos))

    def test_es_realmente_recursivo(self):
        """Con 8 elementos: 1 + 2 + 4 + 8 = 15 llamadas (divide y vencerás)."""
        with mock.patch.object(algoritmos, "merge_sort",
                               wraps=algoritmos.merge_sort) as espia:
            algoritmos.merge_sort([5, 3, 8, 1, 9, 2, 7, 4])
        self.assertEqual(espia.call_count, 15)


# =====================================================================
#  CLASES BASE ABSTRACTAS
# =====================================================================
class TestClasesAbstractas(Base):
    def test_las_bases_no_se_pueden_instanciar(self):
        for clase, args in [(Entidad, ()), (RepositorioBase, (self.db,)), (Reporte, ())]:
            with self.subTest(clase=clase.__name__):
                with self.assertRaises(TypeError):
                    clase(*args)

    def test_subclase_incompleta_no_se_puede_instanciar(self):
        class SinRenderizar(Reporte):
            extension = ".x"
            descripcion = "X"
        class EntidadSinValidar(Entidad):
            pass
        class RepoSinObtener(RepositorioBase):
            def listar(self):
                return []
        for clase, args in [(SinRenderizar, ()), (EntidadSinValidar, ()),
                            (RepoSinObtener, (self.db,))]:
            with self.subTest(clase=clase.__name__):
                with self.assertRaises(TypeError):
                    clase(*args)

    def test_las_entidades_heredan_de_entidad(self):
        for e in (Producto("a", "", 1.0, 1), Categoria(None, "x")):
            self.assertIsInstance(e, Entidad)
            self.assertTrue(e.es_valida())
        self.assertFalse(Producto("", "", 1.0, 1).es_valida())
        self.assertFalse(Categoria(None, "  ").es_valida())

    def test_todos_los_repositorios_cumplen_el_contrato(self):
        for repo in (UsuarioRepository(self.db), CategoriaRepository(self.db),
                     ProductoRepository(self.db), MovimientoRepository(self.db)):
            with self.subTest(repo=type(repo).__name__):
                self.assertIsInstance(repo, RepositorioBase)
                self.assertIsInstance(repo.listar(), list)
                self.assertIsNone(repo.obtener("no-existe" if isinstance(
                    repo, UsuarioRepository) else 999))

    def test_polimorfismo_de_reportes(self):
        self.inv.crear_producto("Teclado", "", 50.0, 2)
        servicio = ReporteService(self.inv)
        datos = servicio.recopilar("ana", datetime(2026, 1, 1))
        for formato in servicio.formatos:
            self.assertIsInstance(formato, Reporte)
            self.assertIsInstance(formato.renderizar(datos), str)
            self.assertTrue(formato.extension.startswith("."))

    def test_se_puede_agregar_un_formato_nuevo_sin_tocar_el_servicio(self):
        class ReporteMarkdown(Reporte):
            extension = ".md"
            descripcion = "Markdown"
            def renderizar(self, d: DatosReporte) -> str:
                return "# Inventario\n" + "\n".join(f"- {p.nombre}" for p in d.productos)
        self.inv.crear_producto("Mouse", "", 5.0, 9)
        servicio = ReporteService(self.inv, formatos=[ReporteTxt(), ReporteMarkdown()])
        self.assertIn(("Markdown", "*.md"), servicio.tipos_de_archivo())
        with tempfile.TemporaryDirectory() as d:
            ruta = os.path.join(d, "r.md")
            servicio.guardar(ruta, "ana")
            with open(ruta, encoding="utf-8") as f:
                self.assertEqual(f.read(), "# Inventario\n- Mouse")


# =====================================================================
#  CATEGORÍAS JERÁRQUICAS (servicio)
# =====================================================================
class TestCategoriasJerarquicas(Base):
    def setUp(self):
        super().setUp()
        self.elec = self.inv.agregar_categoria("Electrónica")
        self.audio = self.inv.agregar_categoria("Audio", self.elec.id)
        self.auri = self.inv.agregar_categoria("Auriculares", self.audio.id)
        self.ofi = self.inv.agregar_categoria("Oficina")

    def test_subcategorias_y_rutas(self):
        self.assertEqual(self.audio.id_padre, self.elec.id)
        self.assertEqual(self.inv.rutas_categorias()[self.auri.id],
                         "Electrónica > Audio > Auriculares")
        self.assertEqual([r for _, r in self.inv.categorias_para_seleccion()],
                         ["Electrónica", "Electrónica > Audio",
                          "Electrónica > Audio > Auriculares", "Oficina"])

    def test_seleccion_excluyendo_el_subarbol(self):
        rutas = [r for _, r in self.inv.categorias_para_seleccion(self.audio.id)]
        self.assertEqual(rutas, ["Electrónica", "Oficina"])

    def test_padre_inexistente_y_nombres_repetidos(self):
        with self.assertRaises(ErrorValidacion):
            self.inv.agregar_categoria("X", id_padre=999)
        with self.assertRaises(ErrorValidacion):
            self.inv.agregar_categoria("audio", self.ofi.id)      # nombre único global

    def test_mover(self):
        self.inv.mover_categoria(self.audio.id, self.ofi.id)
        self.assertEqual(self.inv.rutas_categorias()[self.auri.id],
                         "Oficina > Audio > Auriculares")
        self.inv.mover_categoria(self.audio.id, None)             # volver a raíz
        self.assertEqual(self.inv.rutas_categorias()[self.audio.id], "Audio")

    def test_mover_no_puede_crear_ciclos(self):
        for hijo, padre in [(self.elec.id, self.elec.id), (self.elec.id, self.auri.id),
                            (self.audio.id, self.auri.id)]:
            with self.subTest(mover=hijo, dentro_de=padre):
                with self.assertRaises(ErrorValidacion):
                    self.inv.mover_categoria(hijo, padre)
        self.assertEqual(self.inv.rutas_categorias()[self.auri.id],
                         "Electrónica > Audio > Auriculares")      # nada cambió

    def test_mover_errores(self):
        with self.assertRaises(NoEncontrado):
            self.inv.mover_categoria(999, None)
        with self.assertRaises(ErrorValidacion):
            self.inv.mover_categoria(self.audio.id, 999)

    def test_renombrar_conserva_el_padre(self):
        self.inv.renombrar_categoria(self.audio.id, "Sonido")
        self.assertEqual(self.inv.rutas_categorias()[self.auri.id],
                         "Electrónica > Sonido > Auriculares")

    def test_eliminar_con_hijas_se_rechaza_y_hoja_se_elimina(self):
        with self.assertRaises(ErrorInventario) as cm:
            self.inv.eliminar_categoria(self.audio.id)
        self.assertIn("subcategoría", str(cm.exception))
        self.inv.eliminar_categoria(self.auri.id)
        self.inv.eliminar_categoria(self.audio.id)                # ahora es hoja
        self.assertEqual([c.nombre for c in self.inv.listar_categorias()],
                         ["Electrónica", "Oficina"])

    def test_resumen_suma_recursivamente_las_subcategorias(self):
        self.inv.crear_producto("Radio", "", 10.0, 3, self.elec.id)      # 30
        self.inv.crear_producto("Parlante", "", 20.0, 2, self.audio.id)  # 40
        self.inv.crear_producto("Airpods", "", 100.0, 1, self.auri.id)   # 100
        self.inv.crear_producto("Silla", "", 50.0, 2, self.ofi.id)       # 100
        r = {x.nombre: x for x in self.inv.resumen_categorias()}
        self.assertEqual((r["Auriculares"].productos, r["Auriculares"].valor), (1, 100))
        self.assertEqual((r["Audio"].productos, r["Audio"].valor), (2, 140))
        self.assertEqual((r["Electrónica"].productos, r["Electrónica"].valor), (3, 170))
        self.assertEqual((r["Oficina"].productos, r["Oficina"].valor), (1, 100))
        self.assertEqual([x.nivel for x in self.inv.resumen_categorias()], [0, 1, 2, 0])

    def test_los_productos_eliminados_no_cuentan_en_el_resumen(self):
        p = self.inv.crear_producto("Radio", "", 10.0, 3, self.elec.id)
        self.inv.eliminar_producto(p.id)
        r = {x.nombre: x for x in self.inv.resumen_categorias()}
        self.assertEqual((r["Electrónica"].productos, r["Electrónica"].valor), (0, 0))


# =====================================================================
#  DESHACER (usa la pila)
# =====================================================================
class TestDeshacer(Base):
    def setUp(self):
        super().setUp()
        self.p = self.inv.crear_producto("Mouse", "", 5.0, 10)

    def stock(self):
        return self.inv.obtener_producto(self.p.id).cantidad

    def test_sin_operaciones(self):
        self.assertFalse(self.inv.puede_deshacer())
        self.assertIsNone(self.inv.descripcion_ultima_operacion())
        with self.assertRaises(ErrorInventario):
            self.inv.deshacer_ultimo()

    def test_crear_producto_no_se_puede_deshacer(self):
        self.assertFalse(self.inv.puede_deshacer())

    def test_deshacer_entrada_y_salida(self):
        self.inv.ajustar_stock(self.p.id, "entrada", 5)
        self.assertEqual(self.inv.descripcion_ultima_operacion(), "entrada de 5 · Mouse")
        msg = self.inv.deshacer_ultimo()
        self.assertEqual(self.stock(), 10)
        self.assertIn("Se deshizo la entrada de 5", msg)
        self.inv.ajustar_stock(self.p.id, "salida", 4)
        self.inv.deshacer_ultimo()
        self.assertEqual(self.stock(), 10)
        self.assertFalse(self.inv.puede_deshacer())

    def test_el_historial_conserva_ambos_movimientos(self):
        self.inv.ajustar_stock(self.p.id, "salida", 3)
        self.inv.deshacer_ultimo()
        self.assertEqual([(m.tipo, m.cantidad) for m in self.inv.listar_movimientos()],
                         [("entrada", 3), ("salida", 3), ("entrada", 10)])

    def test_orden_lifo(self):
        self.inv.ajustar_stock(self.p.id, "entrada", 1)
        self.inv.ajustar_stock(self.p.id, "salida", 2)
        self.inv.ajustar_stock(self.p.id, "entrada", 4)           # stock 13
        self.inv.deshacer_ultimo(); self.assertEqual(self.stock(), 9)
        self.inv.deshacer_ultimo(); self.assertEqual(self.stock(), 11)
        self.inv.deshacer_ultimo(); self.assertEqual(self.stock(), 10)

    def test_operaciones_fallidas_no_se_apilan(self):
        with self.assertRaises(ErrorInventario):
            self.inv.ajustar_stock(self.p.id, "salida", 99)
        self.assertFalse(self.inv.puede_deshacer())

    def test_no_se_puede_deshacer_si_falta_stock_y_la_operacion_se_conserva(self):
        self.inv.ajustar_stock(self.p.id, "entrada", 5)                 # stock 15
        with self.db.transaccion():
            self.inv.productos.ajustar_cantidad(self.p.id, -14)         # stock 1 (por fuera)
        movs = len(self.inv.listar_movimientos())
        with self.assertRaises(ErrorInventario) as cm:
            self.inv.deshacer_ultimo()
        self.assertIn("stock actual es 1", str(cm.exception))
        self.assertTrue(self.inv.puede_deshacer())
        self.assertEqual(len(self.inv.listar_movimientos()), movs)

    def test_producto_eliminado(self):
        self.inv.ajustar_stock(self.p.id, "entrada", 5)
        self.inv.eliminar_producto(self.p.id)
        with self.assertRaises(ErrorInventario) as cm:
            self.inv.deshacer_ultimo()
        self.assertIn("papelera", str(cm.exception))
        self.assertFalse(self.inv.puede_deshacer())                      # ya no se acumula

    def test_limpiar_y_capacidad(self):
        for _ in range(60):
            self.inv.ajustar_stock(self.p.id, "entrada", 1)
        self.assertEqual(len(self.inv.pila_deshacer), 50)
        self.inv.limpiar_deshacer()
        self.assertFalse(self.inv.puede_deshacer())


# =====================================================================
#  PAPELERA (recuperar productos eliminados)
# =====================================================================
class TestPapelera(Base):
    def test_eliminar_listar_y_restaurar(self):
        c = self.inv.agregar_categoria("Cat")
        p = self.inv.crear_producto("Mouse", "óptico", 5.0, 7, c.id)
        self.inv.ajustar_stock(p.id, "salida", 2)
        self.inv.eliminar_producto(p.id)
        self.assertEqual(self.inv.listar_productos(), [])
        self.assertEqual([x.nombre for x in self.inv.listar_eliminados()], ["Mouse"])
        r = self.inv.restaurar_producto(p.id)
        self.assertEqual((r.nombre, r.cantidad, r.categoria), ("Mouse", 5, "Cat"))
        self.assertEqual([x.nombre for x in self.inv.listar_productos()], ["Mouse"])
        self.assertEqual(self.inv.listar_eliminados(), [])
        self.assertEqual(len(self.inv.listar_movimientos()), 2)         # historial intacto
        self.assertAlmostEqual(self.inv.valor_total(), 25.0)

    def test_restaurar_errores(self):
        p = self.inv.crear_producto("Mouse", "", 5.0, 1)
        with self.assertRaises(NoEncontrado):
            self.inv.restaurar_producto(999)
        with self.assertRaises(NoEncontrado):
            self.inv.restaurar_producto(p.id)                           # no está eliminado

    def test_restaurar_tras_borrar_su_categoria(self):
        c = self.inv.agregar_categoria("Temp")
        p = self.inv.crear_producto("X", "", 1.0, 1, c.id)
        self.inv.eliminar_producto(p.id)
        self.inv.eliminar_categoria(c.id)
        r = self.inv.restaurar_producto(p.id)
        self.assertIsNone(r.id_categoria)


# =====================================================================
#  REPORTES (TXT y CSV)
# =====================================================================
class TestReportesFormatos(Base):
    def setUp(self):
        super().setUp()
        self.elec = self.inv.agregar_categoria("Electrónica")
        self.audio = self.inv.agregar_categoria("Audio", self.elec.id)
        self.inv.crear_producto("Teclado", "mecánico; rojo", 50.0, 2, self.elec.id)
        self.inv.crear_producto("Parlante", "", 19.5, 10, self.audio.id)
        self.rep = ReporteService(self.inv)
        self.fecha = datetime(2026, 1, 2, 3, 4)

    def test_txt_incluye_resumen_por_categoria_con_sangria(self):
        txt = self.rep.generar("ana", self.fecha)
        self.assertIn("RESUMEN POR CATEGORÍA", txt)
        self.assertIn("  Electrónica", txt)
        self.assertIn("    Audio", txt)                 # subcategoría con sangría
        self.assertIn("295.00", txt)                    # 2*50 + 10*19.5 (Electrónica incl. Audio)

    def test_txt_sin_categorias_no_tiene_esa_seccion(self):
        db = Database(":memory:"); self.addCleanup(db.cerrar)
        inv = InventarioService(db); inv.crear_producto("X", "", 1.0, 9)
        self.assertNotIn("RESUMEN POR CATEGORÍA", ReporteService(inv).generar("ana"))

    def test_csv_contenido(self):
        texto = ReporteService(self.inv).formatos[1].renderizar(
            self.rep.recopilar("ana", self.fecha))
        filas = list(csv.reader(io.StringIO(texto), delimiter=";"))
        self.assertEqual(filas[0], ["ID", "Producto", "Descripción", "Categoría", "Precio",
                                    "Cantidad", "Subtotal"])
        datos = {f[1]: f for f in filas[1:]}
        self.assertEqual(datos["Parlante"][3:], ["Electrónica > Audio", "19,50", "10", "195,00"])
        self.assertEqual(datos["Teclado"][2], "mecánico; rojo")         # el ';' queda entrecomillado

    def test_guardar_elige_formato_por_extension(self):
        with tempfile.TemporaryDirectory() as d:
            ruta_csv, ruta_txt, ruta_otra = (os.path.join(d, n) for n in
                                             ("a.csv", "b.txt", "c.CSV"))
            self.rep.guardar(ruta_csv, "ana"); self.rep.guardar(ruta_txt, "ana")
            self.rep.guardar(ruta_otra, "ana")
            with open(ruta_csv, "rb") as f:
                crudo = f.read()
            self.assertTrue(crudo.startswith(b"\xef\xbb\xbf"))           # BOM para Excel
            self.assertIn("Categoría".encode("utf-8"), crudo)
            with open(ruta_txt, encoding="utf-8") as f:
                self.assertIn("REPORTE DE INVENTARIO", f.read())
            self.assertIsInstance(self.rep.formato_para(ruta_otra), ReporteCsv)   # mayúsculas
            self.assertIsInstance(self.rep.formato_para("x.xyz"), ReporteTxt)     # por defecto

    def test_tipos_de_archivo_para_el_dialogo(self):
        self.assertEqual(self.rep.tipos_de_archivo(),
                         [("Texto", "*.txt"), ("CSV (Excel)", "*.csv")])

    def test_error_al_guardar_csv(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ErrorInventario):
                self.rep.guardar(os.path.join(d, "no_existe", "r.csv"), "ana")


# =====================================================================
#  RESPALDO Y RESTAURACIÓN
# =====================================================================
ESQUEMA_V1 = """
    CREATE TABLE usuarios(id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario TEXT NOT NULL UNIQUE, clave_hash TEXT NOT NULL);
    CREATE TABLE categorias(id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT NOT NULL UNIQUE);
    CREATE TABLE productos(id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT NOT NULL,
        descripcion TEXT, precio REAL NOT NULL CHECK(precio >= 0),
        cantidad INTEGER NOT NULL CHECK(cantidad >= 0), id_categoria INTEGER,
        FOREIGN KEY(id_categoria) REFERENCES categorias(id));
    CREATE TABLE movimientos(id INTEGER PRIMARY KEY AUTOINCREMENT, id_producto INTEGER NOT NULL,
        tipo TEXT NOT NULL CHECK(tipo IN ('entrada','salida')), cantidad INTEGER NOT NULL,
        fecha TEXT NOT NULL, FOREIGN KEY(id_producto) REFERENCES productos(id));
"""


class TestRespaldos(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.db = Database(self.dir / "inv.db")
        self.addCleanup(lambda: self._cerrar())
        self.inv = InventarioService(self.db)
        self.resp = RespaldoService(self.db, carpeta=self.dir / "respaldos")

    def _cerrar(self):
        try:
            self.db.cerrar()
        except sqlite3.Error:
            pass

    def nombres(self):
        return [p.nombre for p in self.inv.listar_productos()]

    def test_crear_respaldo_es_una_base_valida(self):
        self.inv.crear_producto("A", "", 1.0, 3)
        ruta = self.resp.crear(self.dir / "copia.db")
        self.assertTrue(ruta.is_file())
        self.assertEqual(self.resp.inspeccionar(ruta),
                         {"productos": 1, "categorias": 0, "movimientos": 1})

    def test_restaurar_recupera_el_estado_del_respaldo(self):
        a = self.inv.crear_producto("A", "", 10.0, 5)
        self.inv.crear_producto("B", "", 2.0, 8)
        copia = self.resp.crear(self.dir / "copia.db")
        # "desastre": se borra A, se agrega C y se mueve stock
        self.inv.eliminar_producto(a.id)
        self.inv.crear_producto("C", "", 1.0, 1)
        self.inv.ajustar_stock(self.inv.listar_productos("B")[0].id, "salida", 8)
        self.assertEqual(self.nombres(), ["B", "C"])

        r = self.resp.restaurar(copia)
        self.assertEqual(self.nombres(), ["A", "B"])
        self.assertEqual({p.nombre: p.cantidad for p in self.inv.listar_productos()},
                         {"A": 5, "B": 8})
        self.assertEqual(len(self.inv.listar_movimientos()), 2)
        self.assertEqual((r.productos, r.movimientos), (2, 2))

    def test_restaurar_guarda_copia_de_seguridad_de_lo_que_habia(self):
        self.inv.crear_producto("A", "", 1.0, 1)
        copia = self.resp.crear(self.dir / "copia.db")
        self.inv.crear_producto("Nuevo", "", 1.0, 1)
        r = self.resp.restaurar(copia)
        self.assertTrue(r.copia_de_seguridad.is_file())
        self.assertEqual(self.resp.inspeccionar(r.copia_de_seguridad)["productos"], 2)
        self.resp.restaurar(r.copia_de_seguridad)                # incluso se puede "deshacer"
        self.assertEqual(self.nombres(), ["A", "Nuevo"])

    def test_la_base_sigue_funcionando_tras_restaurar(self):
        copia = self.resp.crear(self.dir / "vacia.db")
        self.inv.crear_producto("X", "", 1.0, 1)
        self.resp.restaurar(copia)
        p = self.inv.crear_producto("Y", "", 3.0, 4)
        self.inv.ajustar_stock(p.id, "salida", 1)
        self.inv.eliminar_producto(p.id)
        self.assertEqual(self.db.conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)

    def test_archivos_invalidos_se_rechazan_sin_tocar_los_datos(self):
        self.inv.crear_producto("A", "", 1.0, 1)
        texto = self.dir / "texto.db"; texto.write_text("esto no es sqlite")
        vacia = self.dir / "vacia_sqlite.db"
        con = sqlite3.connect(vacia); con.execute("CREATE TABLE otra(x)"); con.commit(); con.close()
        incompleta = self.dir / "incompleta.db"
        con = sqlite3.connect(incompleta)
        con.executescript("CREATE TABLE usuarios(a); CREATE TABLE categorias(a);"
                          "CREATE TABLE productos(a); CREATE TABLE movimientos(a);")
        con.close()
        buena = self.resp.crear(self.dir / "buena.db")
        danada = self.dir / "danada.db"
        datos = bytearray(buena.read_bytes()); datos[100:4096] = b"\xff" * (4096 - 100)
        danada.write_bytes(bytes(datos))
        for ruta in (self.dir / "noexiste.db", self.dir, texto, vacia, incompleta, danada):
            with self.subTest(archivo=ruta.name):
                with self.assertRaises(ErrorInventario):
                    self.resp.restaurar(ruta)
        self.assertEqual(self.nombres(), ["A"])                  # nada cambió

    def test_restaurar_un_respaldo_de_la_version_antigua(self):
        viejo = self.dir / "v1.db"
        con = sqlite3.connect(viejo); con.executescript(ESQUEMA_V1)
        con.execute("INSERT INTO productos(nombre, descripcion, precio, cantidad)"
                    " VALUES ('Viejo', '', 2.0, 6)")
        con.commit(); con.close()
        self.resp.restaurar(viejo)
        self.assertEqual(self.nombres(), ["Viejo"])               # columna 'activo' añadida
        self.inv.agregar_categoria("Hija", self.inv.agregar_categoria("Madre").id)  # 'id_padre' añadida
        self.inv.eliminar_producto(self.inv.listar_productos()[0].id)
        self.assertEqual(self.nombres(), [])

    def test_respaldo_automatico_uno_por_dia_y_poda(self):
        d1 = self.resp.respaldo_automatico(hoy=date(2026, 1, 1))
        self.assertTrue(d1.is_file())
        self.assertIsNone(self.resp.respaldo_automatico(hoy=date(2026, 1, 1)))   # ya existe
        for dia in range(2, 12):
            self.resp.respaldo_automatico(hoy=date(2026, 1, dia), max_copias=7)
        autos = sorted(p.name for p in (self.dir / "respaldos").glob("auto_*.db"))
        self.assertEqual(len(autos), 7)
        self.assertEqual(autos[0], "auto_20260105.db")            # las más antiguas se borraron
        self.assertEqual(autos[-1], "auto_20260111.db")

    def test_no_se_puede_sobrescribir_la_base_en_uso(self):
        with self.assertRaises(ErrorInventario):
            self.resp.crear(self.dir / "inv.db")
        self.inv.crear_producto("A", "", 1.0, 1)                  # la base sigue intacta
        self.assertEqual(self.nombres(), ["A"])

    def test_crear_respaldo_en_carpeta_nueva_y_en_ruta_imposible(self):
        ruta = self.resp.crear(self.dir / "a" / "b" / "c.db")
        self.assertTrue(ruta.is_file())
        archivo = self.dir / "archivo.txt"; archivo.write_text("x")
        with self.assertRaises(ErrorInventario):
            self.resp.crear(archivo / "dentro.db")               # 'archivo.txt' no es carpeta

    def test_respaldo_y_restauracion_con_base_en_memoria(self):
        db = Database(":memory:"); self.addCleanup(db.cerrar)
        inv = InventarioService(db)
        resp = RespaldoService(db, carpeta=self.dir / "mem")
        inv.crear_producto("M", "", 1.0, 2)
        copia = resp.crear(self.dir / "mem.db")
        inv.crear_producto("N", "", 1.0, 2)
        resp.restaurar(copia)
        self.assertEqual([p.nombre for p in inv.listar_productos()], ["M"])


if __name__ == "__main__":
    unittest.main()
