"""ui.py - Interfaz gráfica (Tkinter + ttk).

Solo muestra datos y recoge entradas: toda la lógica de negocio vive en
servicios.py. Los errores de negocio (ErrorInventario) y de base de datos
(sqlite3.Error) se muestran al usuario en un cuadro de diálogo.
El aspecto (colores, fuentes, estilos) está centralizado en tema.py.
"""
import functools
import sqlite3
import tkinter as tk
import traceback
from datetime import datetime
from tkinter import filedialog, messagebox, simpledialog, ttk

import tema
from algoritmos import merge_sort
from models import ErrorInventario, ErrorValidacion, Producto, STOCK_MINIMO
from tema import px

SIN_CATEGORIA = "(Sin categoría)"
CATEGORIA_RAIZ = "(Categoría principal)"
MARCADOR_BUSQUEDA = "Buscar productos…"


def manejar_errores(metodo):
    """Decorador para handlers de la UI: muestra los errores en vez de perderlos."""
    @functools.wraps(metodo)
    def envoltura(self, *args, **kwargs):
        try:
            return metodo(self, *args, **kwargs)
        except ErrorInventario as e:
            messagebox.showerror("Error", str(e), parent=self)
        except sqlite3.Error as e:
            messagebox.showerror("Error de base de datos",
                                 f"No se pudo completar la operación.\n\n{e}", parent=self)
        return None
    return envoltura


def numero_desde_texto(texto):
    """Convierte '12,50' o '12.50' a float (acepta coma decimal)."""
    texto = texto.strip()
    if "," in texto and "." not in texto:
        texto = texto.replace(",", ".")
    return float(texto)


# =====================================================================
#  COMPONENTES REUTILIZABLES
# =====================================================================
class CampoBusqueda(ttk.Entry):
    """Entry con texto de ayuda (placeholder). `get()` devuelve "" mientras se ve la ayuda."""

    def __init__(self, padre, marcador, **kw):
        super().__init__(padre, **kw)
        self._marcador = marcador
        self._mostrando = False
        self.bind("<FocusIn>", lambda e: self._quitar_marcador(), add="+")
        self.bind("<FocusOut>", lambda e: self._poner_marcador(), add="+")
        self._poner_marcador()

    def _poner_marcador(self):
        if not super().get():
            self._mostrando = True
            super().insert(0, self._marcador)
            self.configure(foreground=tema.TEXTO_SUAVE)

    def _quitar_marcador(self):
        if self._mostrando:
            super().delete(0, "end")
            self._mostrando = False
            self.configure(foreground=tema.TEXTO)

    def get(self):
        return "" if self._mostrando else super().get()

    def insert(self, indice, texto):
        self._quitar_marcador()
        super().insert(indice, texto)

    def delete(self, primero, ultimo=None):
        self._quitar_marcador()
        super().delete(primero, ultimo)
        if self.focus_get() is not self:
            self._poner_marcador()


class TarjetaDato(tk.Frame):
    """Tarjeta con una franja de color, un título y un número grande."""

    def __init__(self, padre, titulo, color):
        super().__init__(padre, background=tema.TARJETA,
                         highlightbackground=tema.BORDE, highlightthickness=1)
        tk.Frame(self, background=color, width=px(5)).pack(side="left", fill="y")
        cuerpo = tk.Frame(self, background=tema.TARJETA)
        cuerpo.pack(side="left", fill="both", expand=True, padx=px(16), pady=px(12))
        ttk.Label(cuerpo, text=titulo, style="TituloTarjeta.TLabel").pack(anchor="w")
        self.valor = ttk.Label(cuerpo, text="—", style="ValorTarjeta.TLabel")
        self.valor.pack(anchor="w")

    def poner(self, texto, color=None):
        self.valor.configure(text=texto, foreground=color or tema.TEXTO)


def tabla_con_scroll(padre, columnas, **kw):
    """Treeview + scrollbar dentro de una tarjeta blanca. Devuelve (tarjeta, treeview)."""
    tarjeta = tk.Frame(padre, background=tema.TARJETA,
                       highlightbackground=tema.BORDE, highlightthickness=1)
    tabla = ttk.Treeview(tarjeta, columns=columnas, show="headings", **kw)
    scroll = ttk.Scrollbar(tarjeta, orient="vertical", command=tabla.yview)
    tabla.configure(yscrollcommand=scroll.set)
    tabla.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")
    return tarjeta, tabla


# =====================================================================
#  CLASE BASE DE LOS DIÁLOGOS MODALES
# =====================================================================
class DialogoModal(tk.Toplevel):
    """Ventana modal: bloquea la ventana padre hasta que se cierra.

    Uso:  resultado = MiDialogo(padre, ...).mostrar()
    Los widgets del diálogo se agregan dentro de `self.cuerpo`.
    """

    def __init__(self, padre, titulo, ligado_al_padre=True):
        super().__init__(padre)
        self.padre = padre
        self.title(titulo)
        self.configure(background=tema.FONDO)
        self.resizable(False, False)
        self.resultado = None
        self.cuerpo = ttk.Frame(self, padding=px(24))
        self.cuerpo.pack(fill="both", expand=True)
        if ligado_al_padre:
            self.transient(padre)
        self.bind("<Escape>", lambda e: self.destroy())

    def _centrar(self):
        self.update_idletasks()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        if self.padre.winfo_viewable():
            x = self.padre.winfo_rootx() + (self.padre.winfo_width() - w) // 2
            y = self.padre.winfo_rooty() + (self.padre.winfo_height() - h) // 2
        else:
            x = (self.winfo_screenwidth() - w) // 2
            y = (self.winfo_screenheight() - h) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")

    def mostrar(self):
        self._centrar()
        self.wait_visibility()
        self.grab_set()
        self.focus_force()
        self.wait_window(self)
        return self.resultado

    def _fila_botones(self, fila, texto_ok, comando_ok, columnas=1, estilo_ok="Primario"):
        """Botones 'Cancelar' y OK alineados a la derecha."""
        marco = ttk.Frame(self.cuerpo)
        marco.grid(row=fila, column=0, columnspan=columnas, sticky="e", pady=(px(18), 0))
        ttk.Button(marco, text="Cancelar", style="Secundario.TButton",
                   command=self.destroy).pack(side="left", padx=(0, px(8)))
        ttk.Button(marco, text=texto_ok, style=f"{estilo_ok}.TButton",
                   command=comando_ok).pack(side="left")


# =====================================================================
#  LOGIN
# =====================================================================
class Login(DialogoModal):
    """Devuelve el nombre de usuario si el login fue correcto, o None."""

    def __init__(self, padre, auth):
        super().__init__(padre, "Inventario - Iniciar sesión", ligado_al_padre=False)
        self.auth = auth
        self.cuerpo.configure(padding=0)

        banda = tk.Frame(self.cuerpo, background=tema.LATERAL)
        banda.pack(fill="x")
        ttk.Label(banda, text="Sistema de Inventario", style="Banda.TLabel"
                  ).pack(anchor="w", padx=px(28), pady=(px(26), 0))
        ttk.Label(banda, text="Inicia sesión para continuar", style="BandaSuave.TLabel"
                  ).pack(anchor="w", padx=px(28), pady=(px(2), px(24)))

        formulario = ttk.Frame(self.cuerpo, padding=(px(28), px(22), px(28), px(26)))
        formulario.pack(fill="both")
        ttk.Label(formulario, text="Usuario", style="Etiqueta.TLabel").pack(anchor="w")
        self.ent_usuario = ttk.Entry(formulario, width=32)
        self.ent_usuario.pack(fill="x", pady=(px(3), px(14)))
        ttk.Label(formulario, text="Contraseña", style="Etiqueta.TLabel").pack(anchor="w")
        self.ent_clave = ttk.Entry(formulario, width=32, show="•")
        self.ent_clave.pack(fill="x", pady=(px(3), px(22)))
        ttk.Button(formulario, text="Iniciar sesión", style="Primario.TButton",
                   command=self._entrar).pack(fill="x")
        for e in (self.ent_usuario, self.ent_clave):
            e.bind("<Return>", lambda ev: self._entrar())
        self.ent_usuario.focus_set()

    def _entrar(self):
        usuario = self.ent_usuario.get().strip()
        try:
            ok = self.auth.login(usuario, self.ent_clave.get())
        except ErrorInventario as e:                    # cuenta bloqueada
            messagebox.showerror("Acceso bloqueado", str(e), parent=self)
            self.ent_clave.delete(0, "end")
            return
        except sqlite3.Error as e:
            messagebox.showerror("Error de base de datos", str(e), parent=self)
            return
        if ok:
            self.resultado = usuario          # se guarda ANTES de destruir la ventana
            self.destroy()
        else:
            messagebox.showerror("Error", "Usuario o contraseña incorrectos.", parent=self)
            self.ent_clave.delete(0, "end")
            self.ent_clave.focus_set()


# =====================================================================
#  VENTANA PRINCIPAL
# =====================================================================
class App(tk.Tk):
    def __init__(self, auth, inventario, reportes, respaldos, usuario=None,
                 mostrar_avisos=True):
        super().__init__()
        tema.aplicar_tema(self)
        self.auth = auth
        self.inventario = inventario
        self.reportes = reportes
        self.respaldos = respaldos
        self.usuario = None
        self.autenticado = False
        self.botones = []
        self._orden = None                       # None o (columna, descendente)
        self._titulos = {}
        self.title("Sistema de Inventario")
        ancho = min(px(1120), self.winfo_screenwidth() - 60)
        alto = min(px(700), self.winfo_screenheight() - 100)
        self.geometry(f"{ancho}x{alto}")
        self.minsize(min(px(1000), ancho), min(px(640), alto))

        if usuario is None:                       # login dentro de la misma ventana raíz
            self.withdraw()
            usuario = Login(self, self.auth).mostrar()
            if not usuario:
                self.destroy()
                return
            self.deiconify()
        self.usuario = usuario
        self.autenticado = True
        self.title(f"Sistema de Inventario - {usuario}")

        self._construir_widgets()
        self.cargar_tabla()
        self.bind("<Control-n>", lambda e: self.agregar())
        if mostrar_avisos:
            self.after(150, self._avisos_iniciales)

    def report_callback_exception(self, exc, val, tb):
        """Red de seguridad: un error inesperado se muestra en vez de perderse en consola."""
        traceback.print_exception(exc, val, tb)
        try:
            messagebox.showerror("Error inesperado",
                                 f"Ocurrió un error inesperado:\n{val}", parent=self)
        except tk.TclError:
            pass

    # ---------- construcción de la interfaz ----------
    def _boton(self, padre, texto, comando, estilo):
        b = ttk.Button(padre, text=texto, command=comando, style=f"{estilo}.TButton",
                       cursor="hand2")
        self.botones.append(b)
        return b

    def _construir_widgets(self):
        self._construir_lateral()
        contenido = ttk.Frame(self, padding=(px(26), px(22), px(26), px(22)))
        contenido.pack(side="left", fill="both", expand=True)

        # --- cabecera
        cab = ttk.Frame(contenido)
        cab.pack(fill="x")
        ttk.Label(cab, text="Productos", style="Titulo.TLabel").pack(anchor="w")
        ttk.Label(cab, text="Administra el stock, los precios y las categorías.",
                  style="Suave.TLabel").pack(anchor="w")

        # --- tarjetas de resumen
        tarjetas = ttk.Frame(contenido)
        tarjetas.pack(fill="x", pady=(px(16), px(16)))
        self.card_total = TarjetaDato(tarjetas, "VALOR TOTAL DEL INVENTARIO", tema.PRIMARIO)
        self.card_productos = TarjetaDato(tarjetas, "PRODUCTOS", tema.EXITO)
        self.card_alertas = TarjetaDato(tarjetas, f"STOCK BAJO (menos de {STOCK_MINIMO})",
                                        tema.PELIGRO)
        for i, c in enumerate((self.card_total, self.card_productos, self.card_alertas)):
            tarjetas.columnconfigure(i, weight=1, uniform="tarjetas")
            c.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else px(14), 0))
        self.lbl_total = self.card_total.valor            # (los tests leen estos textos)
        self.lbl_productos = self.card_productos.valor
        self.lbl_alertas = self.card_alertas.valor

        # --- barra de búsqueda y acciones
        barra = ttk.Frame(contenido)
        barra.pack(fill="x", pady=(0, px(12)))
        # los botones se empaquetan primero (a la derecha) para que SIEMPRE tengan sitio;
        # el buscador ocupa lo que sobra y se encoge si la ventana es estrecha
        for texto, cmd, estilo in reversed([
                ("+ Agregar", self.agregar, "Primario"),
                ("Editar", self.editar, "Secundario"),
                ("Eliminar", self.eliminar, "Peligro"),
                ("Entrada", lambda: self.ajustar_stock("entrada"), "Exito"),
                ("Salida", lambda: self.ajustar_stock("salida"), "Aviso"),
                ("Deshacer", self.deshacer, "Secundario")]):
            b = self._boton(barra, texto, cmd, estilo)
            b.pack(side="right", padx=(px(6), 0))
            if texto == "Deshacer":
                self.btn_deshacer = b
        self.botones.reverse()                      # orden visual: Agregar ... Deshacer
        self.entrada_busqueda = CampoBusqueda(barra, MARCADOR_BUSQUEDA, width=10)
        self.entrada_busqueda.pack(side="left", fill="x", expand=True, padx=(0, px(8)))
        self.entrada_busqueda.bind("<KeyRelease>", lambda e: self.cargar_tabla())

        # --- tabla
        columnas = ("id", "nombre", "descripcion", "precio", "cantidad", "categoria", "valor")
        marco, self.tabla = tabla_con_scroll(contenido, columnas, selectmode="browse")
        marco.pack(fill="both", expand=True)
        # anchos pensados para que SUMEN menos que el ancho mínimo de la ventana;
        # 'nombre' y 'descripción' absorben el espacio sobrante cuando la ventana es más ancha
        for c, t, w, anc, estira in [("id", "ID", 44, "center", False),
                                     ("nombre", "Nombre", 140, "w", True),
                                     ("descripcion", "Descripción", 120, "w", True),
                                     ("precio", "Precio", 80, "e", False),
                                     ("cantidad", "Cant.", 60, "center", False),
                                     ("categoria", "Categoría", 190, "w", True),
                                     ("valor", "Valor", 90, "e", False)]:
            self._titulos[c] = t
            self.tabla.heading(c, text=t, anchor="center" if anc != "w" else "w",
                               command=lambda col=c: self._ordenar_por(col))
            self.tabla.column(c, width=px(w), anchor=anc, stretch=estira, minwidth=px(40))
        self.tabla.tag_configure("par", background=tema.FILA_PAR)
        self.tabla.tag_configure("bajo", background=tema.FILA_BAJA, foreground=tema.TEXTO_BAJO)
        self.tabla.bind("<Double-1>", lambda e: self.editar())
        self.tabla.bind("<Return>", lambda e: self.editar())
        self.tabla.bind("<Delete>", lambda e: self.eliminar())
        self.lbl_vacio = ttk.Label(marco, text="", style="Vacio.TLabel", justify="center")

    def _construir_lateral(self):
        lateral = tk.Frame(self, background=tema.LATERAL, width=px(224))
        lateral.pack(side="left", fill="y")
        lateral.pack_propagate(False)
        ttk.Label(lateral, text="Inventario", style="LateralTitulo.TLabel"
                  ).pack(anchor="w", padx=px(22), pady=(px(28), 0))
        ttk.Label(lateral, text="Programación III", style="LateralSuave.TLabel"
                  ).pack(anchor="w", padx=px(22), pady=(0, px(28)))
        ttk.Label(lateral, text="HERRAMIENTAS", style="LateralSuave.TLabel"
                  ).pack(anchor="w", padx=px(22), pady=(0, px(6)))
        for texto, cmd in [("Historial", self.ver_historial),
                           ("Categorías", self.ventana_categorias),
                           ("Exportar reporte", self.exportar_reporte)]:
            self._boton(lateral, texto, cmd, "Lateral").pack(fill="x")
        ttk.Label(lateral, text="RECUPERACIÓN DE DATOS", style="LateralSuave.TLabel"
                  ).pack(anchor="w", padx=px(22), pady=(px(22), px(6)))
        for texto, cmd in [("Productos eliminados", self.ventana_papelera),
                           ("Crear respaldo", self.crear_respaldo),
                           ("Restaurar respaldo", self.restaurar_respaldo)]:
            self._boton(lateral, texto, cmd, "Lateral").pack(fill="x")

        pie = tk.Frame(lateral, background=tema.LATERAL)
        pie.pack(side="bottom", fill="x", pady=(0, px(14)))
        ttk.Label(pie, text="SESIÓN", style="LateralSuave.TLabel"
                  ).pack(anchor="w", padx=px(22))
        ttk.Label(pie, text=self.usuario, style="Lateral.TLabel"
                  ).pack(anchor="w", padx=px(22), pady=(0, px(8)))
        self._boton(pie, "Cambiar clave", self.cambiar_clave, "Lateral").pack(fill="x")

    # ---------- avisos al iniciar ----------
    def _avisos_iniciales(self):
        self._mostrar_alertas_stock()
        if self.auth.usa_clave_por_defecto(self.usuario):
            if messagebox.askyesno(
                    "Seguridad",
                    "Todavía usas la contraseña por defecto.\n¿Quieres cambiarla ahora?",
                    parent=self):
                self.cambiar_clave()

    def _mostrar_alertas_stock(self):
        bajos = self.inventario.productos_bajo_stock()
        if bajos:
            lista = "\n".join(f"- {p.nombre}: quedan {p.cantidad}" for p in bajos)
            messagebox.showwarning(
                "Stock bajo", f"Productos con menos de {STOCK_MINIMO} unidades:\n{lista}",
                parent=self)

    # ---------- tabla ----------
    def _ordenar_por(self, columna):
        """Clic en un encabezado: ordena por esa columna (otro clic invierte el orden)."""
        if self._orden and self._orden[0] == columna:
            self._orden = (columna, not self._orden[1])
        else:
            self._orden = (columna, False)
        self.cargar_tabla()

    def _actualizar_encabezados(self):
        for col, titulo in self._titulos.items():
            marca = ""
            if self._orden and self._orden[0] == col:
                marca = "  ▼" if self._orden[1] else "  ▲"
            self.tabla.heading(col, text=titulo + marca)

    @manejar_errores
    def cargar_tabla(self):
        texto = self.entrada_busqueda.get().strip()
        seleccionado = self.tabla.selection()
        productos = self.inventario.listar_productos(texto)
        todos = self.inventario.listar_productos() if texto else productos
        rutas = self.inventario.rutas_categorias()

        if self._orden:                      # ordenamiento recursivo (merge sort)
            claves = {"id": lambda p: p.id,
                      "nombre": lambda p: p.nombre.casefold(),
                      "descripcion": lambda p: p.descripcion.casefold(),
                      "precio": lambda p: p.precio,
                      "cantidad": lambda p: p.cantidad,
                      "categoria": lambda p: rutas.get(p.id_categoria, "").casefold(),
                      "valor": lambda p: p.valor}
            columna, descendente = self._orden
            productos = merge_sort(productos, clave=claves[columna], reverso=descendente)
        self._actualizar_encabezados()

        self.tabla.delete(*self.tabla.get_children())
        for n, p in enumerate(productos):
            etiqueta = "bajo" if p.bajo_stock() else ("par" if n % 2 else "")
            self.tabla.insert(
                "", "end", iid=str(p.id), tags=(etiqueta,) if etiqueta else (),
                values=(p.id, p.nombre, p.descripcion, f"{p.precio:,.2f}", p.cantidad,
                        rutas.get(p.id_categoria, "—"), f"{p.valor:,.2f}"))
        if seleccionado and self.tabla.exists(seleccionado[0]):
            self.tabla.selection_set(seleccionado[0])

        bajos = len(self.inventario.productos_bajo_stock())
        self.card_total.poner(f"${self.inventario.valor_total():,.2f}")
        self.card_productos.poner(str(len(todos)))
        self.card_alertas.poner(str(bajos), tema.PELIGRO if bajos else tema.EXITO)
        self.btn_deshacer.state(["!disabled"] if self.inventario.puede_deshacer()
                                else ["disabled"])

        if productos:
            self.lbl_vacio.place_forget()
        else:
            self.lbl_vacio.configure(
                text=(f"Sin resultados para “{texto}”." if texto else
                      "Todavía no hay productos.\nPulsa  + Agregar  para crear el primero."))
            self.lbl_vacio.place(relx=0.5, rely=0.4, anchor="center")

    def _id_seleccionado(self):
        sel = self.tabla.selection()
        if not sel:
            messagebox.showwarning("Atención", "Selecciona un producto de la tabla.",
                                   parent=self)
            return None
        return int(sel[0])              # el iid de la fila ES el id del producto

    # ---------- CRUD ----------
    @manejar_errores
    def agregar(self):
        FormularioProducto(
            self, self.inventario.categorias_para_seleccion(),
            lambda d: self.inventario.crear_producto(
                d["nombre"], d["descripcion"], d["precio"], d["cantidad"], d["id_categoria"])
        ).mostrar()
        self.cargar_tabla()

    @manejar_errores
    def editar(self):
        id_prod = self._id_seleccionado()
        if id_prod is None:
            return
        prod = self.inventario.obtener_producto(id_prod)
        FormularioProducto(
            self, self.inventario.categorias_para_seleccion(),
            lambda d: self.inventario.actualizar_producto(
                id_prod, d["nombre"], d["descripcion"], d["precio"], d["id_categoria"]),
            producto=prod).mostrar()
        self.cargar_tabla()

    @manejar_errores
    def eliminar(self):
        id_prod = self._id_seleccionado()
        if id_prod is None:
            return
        prod = self.inventario.obtener_producto(id_prod)
        if messagebox.askyesno(
                "Confirmar",
                f"¿Eliminar '{prod.nombre}'?\nSu historial de movimientos se conserva.",
                parent=self):
            self.inventario.eliminar_producto(id_prod)
            self.cargar_tabla()

    # ---------- entrada / salida de stock ----------
    @manejar_errores
    def ajustar_stock(self, tipo):
        id_prod = self._id_seleccionado()
        if id_prod is None:
            return
        prod = self.inventario.obtener_producto(id_prod)
        cant = DialogoCantidad(self, tipo, prod.nombre, prod.cantidad).mostrar()
        if cant:
            try:
                msg = self.inventario.ajustar_stock(id_prod, tipo, cant)
            finally:
                self.cargar_tabla()
            messagebox.showinfo("Movimiento", msg, parent=self)

    @manejar_errores
    def deshacer(self):
        descripcion = self.inventario.descripcion_ultima_operacion()
        if descripcion is None:
            messagebox.showinfo("Deshacer", "No hay operaciones para deshacer.", parent=self)
            return
        if not messagebox.askyesno(
                "Deshacer", f"¿Deshacer la última operación?\n\n{descripcion}\n\n"
                "Se registrará el movimiento contrario en el historial.", parent=self):
            return
        try:
            msg = self.inventario.deshacer_ultimo()
        finally:
            self.cargar_tabla()
        messagebox.showinfo("Deshacer", msg, parent=self)

    # ---------- ventanas auxiliares ----------
    def ver_historial(self):
        Historial(self, self.inventario)

    def ventana_categorias(self):
        Categorias(self, self.inventario, al_cambiar=self.cargar_tabla)

    def ventana_papelera(self):
        Papelera(self, self.inventario, al_cambiar=self.cargar_tabla)

    # ---------- recuperación de datos ----------
    @manejar_errores
    def crear_respaldo(self):
        ruta = filedialog.asksaveasfilename(
            parent=self, defaultextension=".db",
            initialfile=f"inventario_respaldo_{datetime.now():%Y%m%d_%H%M}.db",
            filetypes=[("Respaldo del inventario", "*.db")])
        if not ruta:
            return
        self.respaldos.crear(ruta)
        messagebox.showinfo("Respaldo", f"Respaldo creado en:\n{ruta}", parent=self)

    @manejar_errores
    def restaurar_respaldo(self):
        opciones = {}
        if self.respaldos.carpeta.is_dir():
            opciones["initialdir"] = str(self.respaldos.carpeta)
        ruta = filedialog.askopenfilename(
            parent=self, title="Elegir respaldo a restaurar",
            filetypes=[("Respaldo del inventario", "*.db"), ("Todos los archivos", "*.*")],
            **opciones)
        if not ruta:
            return
        info = self.respaldos.inspeccionar(ruta)          # si no es válido, avisa aquí
        if not messagebox.askyesno(
                "Restaurar respaldo",
                f"El respaldo contiene {info['productos']} producto(s), "
                f"{info['categorias']} categoría(s) y {info['movimientos']} movimiento(s).\n\n"
                "Se REEMPLAZARÁN todos los datos actuales (también las cuentas y "
                "contraseñas). Antes se guarda una copia de seguridad de lo actual.\n\n"
                "¿Continuar?", icon="warning", parent=self):
            return
        r = self.respaldos.restaurar(ruta)
        self.inventario.limpiar_deshacer()
        self.cargar_tabla()
        messagebox.showinfo(
            "Respaldo restaurado",
            f"Datos restaurados correctamente.\n\nLo que había antes quedó guardado en:\n"
            f"{r.copia_de_seguridad}", parent=self)

    @manejar_errores
    def cambiar_clave(self):
        if CambiarClave(self, self.auth, self.usuario).mostrar():
            messagebox.showinfo("Contraseña", "Contraseña actualizada.", parent=self)

    # ---------- reporte ----------
    @manejar_errores
    def exportar_reporte(self):
        ruta = filedialog.asksaveasfilename(
            parent=self, defaultextension=".txt",
            initialfile=f"reporte_{datetime.now():%Y%m%d_%H%M}.txt",
            filetypes=self.reportes.tipos_de_archivo())
        if not ruta:
            return
        self.reportes.guardar(ruta, self.usuario)
        messagebox.showinfo("Reporte", f"Reporte guardado en:\n{ruta}", parent=self)


# =====================================================================
#  FORMULARIO DE PRODUCTO (agregar / editar)
# =====================================================================
class FormularioProducto(DialogoModal):
    """`guardar_fn(datos)` hace la operación real; si lanza un error, el
    formulario sigue abierto con lo que el usuario escribió."""

    def __init__(self, padre, categorias, guardar_fn, producto=None):
        super().__init__(padre, "Editar producto" if producto else "Nuevo producto")
        self._guardar_fn = guardar_fn
        self._producto = producto
        self._ids_categoria = [None] + [c[0] for c in categorias]   # c = (id, ruta)

        c = self.cuerpo
        c.columnconfigure(0, weight=1, uniform="col")
        c.columnconfigure(1, weight=1, uniform="col")
        ttk.Label(c, text="Editar producto" if producto else "Nuevo producto",
                  style="Titulo.TLabel", font=(None, 16, "bold")
                  ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, px(14)))

        valores = {"nombre": "", "descripcion": "", "precio": "0", "cantidad": "0"}
        if producto:
            valores = {"nombre": producto.nombre, "descripcion": producto.descripcion,
                       "precio": f"{producto.precio:.2f}", "cantidad": str(producto.cantidad)}
        self.entries = {}

        def campo(clave, etiqueta, fila, columna=0, span=2):
            ttk.Label(c, text=etiqueta, style="Etiqueta.TLabel").grid(
                row=fila, column=columna, columnspan=span, sticky="w")
            e = ttk.Entry(c, width=44 if span == 2 else 20)
            e.grid(row=fila + 1, column=columna, columnspan=span, sticky="ew",
                   pady=(px(3), px(12)), padx=(0 if columna == 0 else px(8), 0))
            e.insert(0, valores[clave])
            self.entries[clave] = e

        campo("nombre", "Nombre", 1)
        campo("descripcion", "Descripción (opcional)", 3)
        campo("precio", "Precio", 5, columna=0, span=1)
        campo("cantidad", "Cantidad inicial" if not producto else "Cantidad actual",
              5, columna=1, span=1)
        if producto:                  # la cantidad solo cambia con Entrada/Salida
            self.entries["cantidad"].config(state="disabled")
            ttk.Label(c, text="Para cambiar la cantidad usa Entrada / Salida.",
                      style="Suave.TLabel").grid(row=7, column=0, columnspan=2,
                                                 sticky="w", pady=(0, px(10)))

        ttk.Label(c, text="Categoría", style="Etiqueta.TLabel").grid(
            row=8, column=0, columnspan=2, sticky="w")
        self.combo_cat = ttk.Combobox(
            c, state="readonly", width=42,
            values=[SIN_CATEGORIA] + [c[1] for c in categorias])
        self.combo_cat.grid(row=9, column=0, columnspan=2, sticky="ew", pady=(px(3), 0))
        indice = 0
        if producto and producto.id_categoria in self._ids_categoria:
            indice = self._ids_categoria.index(producto.id_categoria)
        self.combo_cat.current(indice)

        self._fila_botones(10, "Guardar", self._guardar, columnas=2)
        self.bind("<Return>", lambda e: self._guardar())
        self.entries["nombre"].focus_set()

    def _leer(self):
        try:
            precio = numero_desde_texto(self.entries["precio"].get())
            cantidad = (self._producto.cantidad if self._producto
                        else int(self.entries["cantidad"].get().strip()))
        except ValueError:
            raise ErrorValidacion(
                "El precio debe ser un número y la cantidad un número entero.")
        datos = {"nombre": self.entries["nombre"].get(),
                 "descripcion": self.entries["descripcion"].get(),
                 "precio": precio, "cantidad": cantidad,
                 "id_categoria": self._ids_categoria[max(self.combo_cat.current(), 0)]}
        errores = Producto(datos["nombre"].strip(), datos["descripcion"].strip(),
                           precio, cantidad).validar()
        if errores:
            raise ErrorValidacion(errores)
        return datos

    @manejar_errores
    def _guardar(self):
        self._guardar_fn(self._leer())
        self.resultado = True
        self.destroy()


# =====================================================================
#  DIÁLOGO DE CANTIDAD (entrada / salida)
# =====================================================================
class DialogoCantidad(DialogoModal):
    def __init__(self, padre, tipo, nombre_producto="", stock_actual=None):
        super().__init__(padre, f"Registrar {tipo}")
        c = self.cuerpo
        ttk.Label(c, text=f"Registrar {tipo}", style="Titulo.TLabel",
                  font=(None, 16, "bold")).grid(row=0, column=0, sticky="w")
        if nombre_producto:
            detalle = nombre_producto if stock_actual is None else \
                f"{nombre_producto}  ·  stock actual: {stock_actual}"
            ttk.Label(c, text=detalle, style="Suave.TLabel").grid(
                row=1, column=0, sticky="w", pady=(0, px(14)))
        ttk.Label(c, text=f"Cantidad a {tipo}", style="Etiqueta.TLabel").grid(
            row=2, column=0, sticky="w")
        self.ent = ttk.Entry(c, width=30)
        self.ent.grid(row=3, column=0, sticky="ew", pady=(px(3), 0))
        self.ent.focus_set()
        self.ent.bind("<Return>", lambda e: self._ok())
        self._fila_botones(4, "Aceptar", self._ok,
                           estilo_ok="Exito" if tipo == "entrada" else "Aviso")

    def _ok(self):
        try:
            cantidad = int(self.ent.get().strip())
            if cantidad <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Error", "Ingresa un número entero mayor que 0.",
                                 parent=self)
            return
        self.resultado = cantidad
        self.destroy()


# =====================================================================
#  CAMBIAR CONTRASEÑA
# =====================================================================
class CambiarClave(DialogoModal):
    def __init__(self, padre, auth, usuario):
        super().__init__(padre, "Cambiar contraseña")
        self.auth, self.usuario = auth, usuario
        c = self.cuerpo
        ttk.Label(c, text="Cambiar contraseña", style="Titulo.TLabel",
                  font=(None, 16, "bold")).grid(row=0, column=0, sticky="w", pady=(0, px(14)))
        self.entries = []
        for i, etiqueta in enumerate(["Contraseña actual", "Nueva contraseña",
                                      "Repetir nueva contraseña"]):
            ttk.Label(c, text=etiqueta, style="Etiqueta.TLabel").grid(
                row=1 + 2 * i, column=0, sticky="w")
            e = ttk.Entry(c, show="•", width=34)
            e.grid(row=2 + 2 * i, column=0, sticky="ew", pady=(px(3), px(12)))
            self.entries.append(e)
        self._fila_botones(7, "Guardar", self._guardar)
        self.bind("<Return>", lambda e: self._guardar())
        self.entries[0].focus_set()

    @manejar_errores
    def _guardar(self):
        actual, nueva, repetida = (e.get() for e in self.entries)
        if nueva != repetida:
            raise ErrorValidacion("La nueva contraseña y su repetición no coinciden.")
        self.auth.cambiar_clave(self.usuario, actual, nueva)
        self.resultado = True
        self.destroy()


# =====================================================================
#  HISTORIAL DE MOVIMIENTOS
# =====================================================================
class Historial(tk.Toplevel):
    def __init__(self, padre, inventario):
        super().__init__(padre)
        self.title("Historial de movimientos")
        self.configure(background=tema.FONDO)
        self.geometry(f"{px(680)}x{px(500)}")
        self.minsize(px(520), px(300))
        self.transient(padre)

        cuerpo = ttk.Frame(self, padding=px(20))
        cuerpo.pack(fill="both", expand=True)
        ttk.Label(cuerpo, text="Historial de movimientos", style="Titulo.TLabel",
                  font=(None, 16, "bold")).pack(anchor="w")
        ttk.Label(cuerpo, text="Más recientes primero.", style="Suave.TLabel"
                  ).pack(anchor="w", pady=(0, px(12)))
        columnas = ("id", "producto", "tipo", "cantidad", "fecha")
        marco, self.tabla = tabla_con_scroll(cuerpo, columnas)
        marco.pack(fill="both", expand=True)
        for c, t, w, anc, estira in [("id", "ID", 56, "center", False),
                                     ("producto", "Producto", 220, "w", True),
                                     ("tipo", "Tipo", 100, "center", False),
                                     ("cantidad", "Cantidad", 90, "center", False),
                                     ("fecha", "Fecha", 160, "center", False)]:
            self.tabla.heading(c, text=t)
            self.tabla.column(c, width=px(w), anchor=anc, stretch=estira)
        self.tabla.tag_configure("entrada", foreground=tema.EXITO_HOVER)
        self.tabla.tag_configure("salida", foreground=tema.PELIGRO)
        try:
            for m in inventario.listar_movimientos():
                self.tabla.insert("", "end", tags=(m.tipo,),
                                  values=(m.id, m.producto, m.tipo, m.cantidad, m.fecha))
        except sqlite3.Error as e:
            messagebox.showerror("Error de base de datos", str(e), parent=self)


# =====================================================================
#  VENTANA DE CATEGORÍAS (árbol de categorías y subcategorías)
# =====================================================================
class DialogoMoverCategoria(DialogoModal):
    """Elige la nueva categoría padre. Solo ofrece destinos válidos: la propia
    categoría y sus descendientes quedan excluidos (evita ciclos)."""

    def __init__(self, padre, inventario, categoria):
        super().__init__(padre, "Mover categoría")
        opciones = inventario.categorias_para_seleccion(excluir_subarbol_de=categoria.id)
        self._ids = [None] + [o[0] for o in opciones]
        c = self.cuerpo
        ttk.Label(c, text="Mover categoría", style="Titulo.TLabel",
                  font=(None, 16, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(c, text=f"«{categoria.nombre}» pasará a estar dentro de:",
                  style="Suave.TLabel").grid(row=1, column=0, sticky="w", pady=(0, px(12)))
        self.combo = ttk.Combobox(c, state="readonly", width=40,
                                  values=[CATEGORIA_RAIZ] + [o[1] for o in opciones])
        self.combo.grid(row=2, column=0, sticky="ew")
        actual = categoria.id_padre
        self.combo.current(self._ids.index(actual) if actual in self._ids else 0)
        self._fila_botones(3, "Mover", self._ok)
        self.bind("<Return>", lambda e: self._ok())

    def _ok(self):
        self.resultado = {"id_padre": self._ids[max(self.combo.current(), 0)]}
        self.destroy()


class Categorias(tk.Toplevel):
    def __init__(self, padre, inventario, al_cambiar=None):
        super().__init__(padre)
        self.inventario = inventario
        self._al_cambiar = al_cambiar
        self._ids_padre = [None]
        self.title("Categorías")
        self.configure(background=tema.FONDO)
        self.minsize(px(760), px(440))
        self.geometry(f"{px(800)}x{px(500)}")
        self.transient(padre)

        cuerpo = ttk.Frame(self, padding=px(24))
        cuerpo.pack(fill="both", expand=True)
        cuerpo.columnconfigure(0, weight=1)
        cuerpo.rowconfigure(2, weight=1)
        ttk.Label(cuerpo, text="Categorías", style="Titulo.TLabel",
                  font=(None, 16, "bold")).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(cuerpo, text="Organízalas en subcategorías; los totales suman las hijas.",
                  style="Suave.TLabel").grid(row=1, column=0, columnspan=2, sticky="w",
                                             pady=(0, px(12)))

        marco = tk.Frame(cuerpo, background=tema.TARJETA,
                         highlightbackground=tema.BORDE, highlightthickness=1)
        marco.grid(row=2, column=0, sticky="nsew", padx=(0, px(18)))
        self.arbol = ttk.Treeview(marco, columns=("productos", "valor"),
                                  show="tree headings", selectmode="browse")
        self.arbol.heading("#0", text="Categoría", anchor="w")
        self.arbol.heading("productos", text="Productos")
        self.arbol.heading("valor", text="Valor")
        self.arbol.column("#0", width=px(240), stretch=True)
        self.arbol.column("productos", width=px(96), anchor="center", stretch=False)
        self.arbol.column("valor", width=px(100), anchor="e", stretch=False)
        scroll = ttk.Scrollbar(marco, orient="vertical", command=self.arbol.yview)
        self.arbol.configure(yscrollcommand=scroll.set)
        self.arbol.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.arbol.bind("<<TreeviewSelect>>", lambda e: self._al_seleccionar())

        lateral = ttk.Frame(cuerpo)
        lateral.grid(row=2, column=1, sticky="nsew")
        ttk.Label(lateral, text="Nueva categoría", style="Etiqueta.TLabel").pack(anchor="w")
        self.ent = ttk.Entry(lateral, width=24)
        self.ent.pack(fill="x", pady=(px(3), px(10)))
        self.ent.bind("<Return>", lambda e: self._agregar())
        ttk.Label(lateral, text="Dentro de", style="Etiqueta.TLabel").pack(anchor="w")
        self.combo_padre = ttk.Combobox(lateral, state="readonly", width=22)
        self.combo_padre.pack(fill="x", pady=(px(3), px(10)))
        ttk.Button(lateral, text="+ Agregar", style="Primario.TButton",
                   command=self._agregar).pack(fill="x")
        ttk.Separator(lateral).pack(fill="x", pady=px(16))
        ttk.Button(lateral, text="Renombrar", style="Secundario.TButton",
                   command=self._renombrar).pack(fill="x", pady=(0, px(6)))
        ttk.Button(lateral, text="Mover a…", style="Secundario.TButton",
                   command=self._mover).pack(fill="x", pady=(0, px(6)))
        ttk.Button(lateral, text="Eliminar", style="Peligro.TButton",
                   command=self._eliminar).pack(fill="x")
        self._cargar()

    # ---------- pintado del árbol (RECURSIVO) ----------
    def _pintar(self, nodos, padre_iid, resumen):
        """Inserta cada nodo y, recursivamente, sus hijos dentro de él."""
        for n in nodos:
            r = resumen[n.id]
            self.arbol.insert(padre_iid, "end", iid=str(n.id), text=n.nombre, open=True,
                              values=(r.productos, f"{r.valor:,.2f}"))
            self._pintar(n.hijos, str(n.id), resumen)

    def _cargar(self, seleccionar=None):
        seleccionado = seleccionar if seleccionar is not None else self._id_seleccionado()
        self.arbol.delete(*self.arbol.get_children())
        arbol = self.inventario.arbol_categorias()
        resumen = {r.id: r for r in self.inventario.resumen_categorias()}
        self._pintar(arbol.raices, "", resumen)
        opciones = self.inventario.categorias_para_seleccion()
        self._ids_padre = [None] + [o[0] for o in opciones]
        self.combo_padre.configure(values=[CATEGORIA_RAIZ] + [o[1] for o in opciones])
        self.combo_padre.current(0)
        if seleccionado is not None and self.arbol.exists(str(seleccionado)):
            self.arbol.selection_set(str(seleccionado))
            self.arbol.see(str(seleccionado))

    def _al_seleccionar(self):
        """Al elegir una categoría, 'Dentro de' propone esa misma (crear una subcategoría)."""
        id_sel = self._id_seleccionado()
        if id_sel in self._ids_padre:
            self.combo_padre.current(self._ids_padre.index(id_sel))

    def _id_seleccionado(self):
        sel = self.arbol.selection()
        return int(sel[0]) if sel else None

    def _notificar_cambio(self, seleccionar=None):
        self._cargar(seleccionar)
        if self._al_cambiar:
            self._al_cambiar()

    def _categoria_seleccionada(self):
        id_sel = self._id_seleccionado()
        if id_sel is None:
            messagebox.showwarning("Categorías", "Selecciona una categoría del árbol.",
                                   parent=self)
            return None
        return next(c for c in self.inventario.listar_categorias() if c.id == id_sel)

    @manejar_errores
    def _agregar(self):
        nombre = self.ent.get().strip()
        if not nombre:
            return
        id_padre = self._ids_padre[max(self.combo_padre.current(), 0)]
        nueva = self.inventario.agregar_categoria(nombre, id_padre)
        self.ent.delete(0, "end")
        self._notificar_cambio(seleccionar=nueva.id)

    @manejar_errores
    def _renombrar(self):
        cat = self._categoria_seleccionada()
        if cat is None:
            return
        nuevo = simpledialog.askstring("Renombrar categoría", "Nuevo nombre:",
                                       initialvalue=cat.nombre, parent=self)
        if nuevo is None:
            return
        self.inventario.renombrar_categoria(cat.id, nuevo)
        self._notificar_cambio(seleccionar=cat.id)

    @manejar_errores
    def _mover(self):
        cat = self._categoria_seleccionada()
        if cat is None:
            return
        eleccion = DialogoMoverCategoria(self, self.inventario, cat).mostrar()
        if eleccion is None:
            return
        self.inventario.mover_categoria(cat.id, eleccion["id_padre"])
        self._notificar_cambio(seleccionar=cat.id)

    @manejar_errores
    def _eliminar(self):
        cat = self._categoria_seleccionada()
        if cat is None:
            return
        if messagebox.askyesno("Confirmar", f"¿Eliminar la categoría '{cat.nombre}'?",
                               parent=self):
            self.inventario.eliminar_categoria(cat.id)
            self._notificar_cambio()


# =====================================================================
#  PAPELERA: recuperar productos eliminados
# =====================================================================
class Papelera(tk.Toplevel):
    def __init__(self, padre, inventario, al_cambiar=None):
        super().__init__(padre)
        self.inventario = inventario
        self._al_cambiar = al_cambiar
        self.title("Productos eliminados")
        self.configure(background=tema.FONDO)
        self.geometry(f"{px(720)}x{px(460)}")
        self.minsize(px(560), px(320))
        self.transient(padre)

        cuerpo = ttk.Frame(self, padding=px(22))
        cuerpo.pack(fill="both", expand=True)
        ttk.Label(cuerpo, text="Productos eliminados", style="Titulo.TLabel",
                  font=(None, 16, "bold")).pack(anchor="w")
        ttk.Label(cuerpo, text="Selecciona un producto y restáuralo con su stock e historial.",
                  style="Suave.TLabel").pack(anchor="w", pady=(0, px(12)))
        pie = ttk.Frame(cuerpo)
        pie.pack(side="bottom", fill="x", pady=(px(14), 0))
        ttk.Button(pie, text="Cerrar", style="Secundario.TButton",
                   command=self.destroy).pack(side="right")
        ttk.Button(pie, text="Restaurar seleccionado", style="Exito.TButton",
                   command=self._restaurar).pack(side="right", padx=(0, px(8)))

        columnas = ("id", "nombre", "precio", "cantidad", "categoria")
        marco, self.tabla = tabla_con_scroll(cuerpo, columnas, selectmode="browse")
        marco.pack(fill="both", expand=True)
        for c, t, w, anc, estira in [("id", "ID", 50, "center", False),
                                     ("nombre", "Nombre", 240, "w", True),
                                     ("precio", "Precio", 90, "e", False),
                                     ("cantidad", "Cant.", 70, "center", False),
                                     ("categoria", "Categoría", 150, "w", False)]:
            self.tabla.heading(c, text=t)
            self.tabla.column(c, width=px(w), anchor=anc, stretch=estira)
        self.tabla.bind("<Double-1>", lambda e: self._restaurar())
        self.lbl_vacio = ttk.Label(marco, text="La papelera está vacía.",
                                   style="Vacio.TLabel")
        self._cargar()

    @manejar_errores
    def _cargar(self):
        self.tabla.delete(*self.tabla.get_children())
        rutas = self.inventario.rutas_categorias()
        productos = self.inventario.listar_eliminados()
        for p in productos:
            self.tabla.insert("", "end", iid=str(p.id),
                              values=(p.id, p.nombre, f"{p.precio:,.2f}", p.cantidad,
                                      rutas.get(p.id_categoria, "—")))
        if productos:
            self.lbl_vacio.place_forget()
        else:
            self.lbl_vacio.place(relx=0.5, rely=0.45, anchor="center")

    @manejar_errores
    def _restaurar(self):
        sel = self.tabla.selection()
        if not sel:
            messagebox.showwarning("Productos eliminados", "Selecciona un producto.",
                                   parent=self)
            return
        p = self.inventario.restaurar_producto(int(sel[0]))
        self._cargar()
        if self._al_cambiar:
            self._al_cambiar()
        messagebox.showinfo("Productos eliminados", f"«{p.nombre}» fue restaurado.",
                            parent=self)
