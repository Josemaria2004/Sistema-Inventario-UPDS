"""tema.py - Colores, fuentes y estilos (ttk) de toda la aplicación.

Se usa el tema "clam" porque se ve igual en Windows, macOS y Linux y permite
personalizar colores (el tema nativo de Windows no deja).
"""
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

# ------------------------------- paleta -------------------------------
FONDO = "#F3F4F6"
TARJETA = "#FFFFFF"
BORDE = "#E5E7EB"
TEXTO = "#111827"
TEXTO_SUAVE = "#6B7280"

LATERAL = "#0F172A"
LATERAL_HOVER = "#1E293B"
LATERAL_TEXTO = "#E2E8F0"
LATERAL_SUAVE = "#94A3B8"

PRIMARIO = "#2563EB"
PRIMARIO_HOVER = "#1D4ED8"
PRIMARIO_SUAVE = "#DBEAFE"
PELIGRO = "#DC2626"
PELIGRO_HOVER = "#B91C1C"
EXITO = "#16A34A"
EXITO_HOVER = "#15803D"
AVISO = "#EA580C"
AVISO_HOVER = "#C2410C"

FILA_PAR = "#F8FAFC"
FILA_BAJA = "#FEE2E2"
TEXTO_BAJO = "#991B1B"

ESCALA = 1.0          # se ajusta según los DPI de la pantalla (ver aplicar_tema)


def px(n):
    """Convierte píxeles 'de diseño' a píxeles reales según la escala de la pantalla."""
    return int(round(n * ESCALA))


def _familia(raiz):
    disponibles = set(tkfont.families(raiz))
    for f in ("Segoe UI", "Helvetica Neue", "Inter", "Roboto", "Noto Sans", "DejaVu Sans"):
        if f in disponibles:
            return f
    return tkfont.nametofont("TkDefaultFont").actual("family")


def aplicar_tema(raiz):
    """Configura fuentes y estilos. Devuelve la escala de pantalla usada."""
    global ESCALA
    try:
        ESCALA = min(3.0, max(1.0, float(raiz.tk.call("tk", "scaling")) / (96 / 72)))
    except (tk.TclError, ValueError):
        ESCALA = 1.0

    familia = _familia(raiz)
    for nombre in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
        tkfont.nametofont(nombre).configure(family=familia, size=10)
    negrita = (familia, 10, "bold")
    grande = (familia, 20, "bold")
    mediana = (familia, 15, "bold")
    pequena = (familia, 9)

    raiz.configure(background=FONDO)
    raiz.option_add("*TCombobox*Listbox.background", TARJETA)
    raiz.option_add("*TCombobox*Listbox.foreground", TEXTO)
    raiz.option_add("*TCombobox*Listbox.selectBackground", PRIMARIO)
    raiz.option_add("*TCombobox*Listbox.selectForeground", "white")

    e = ttk.Style(raiz)
    e.theme_use("clam")
    e.configure(".", background=FONDO, foreground=TEXTO, bordercolor=BORDE,
                focuscolor=FONDO, font="TkDefaultFont")

    # ---- marcos y etiquetas
    e.configure("TFrame", background=FONDO)
    e.configure("TLabel", background=FONDO, foreground=TEXTO)
    e.configure("Titulo.TLabel", font=grande)
    e.configure("Suave.TLabel", foreground=TEXTO_SUAVE)
    e.configure("Etiqueta.TLabel", foreground=TEXTO_SUAVE, font=pequena)
    e.configure("Lateral.TLabel", background=LATERAL, foreground=LATERAL_TEXTO)
    e.configure("LateralTitulo.TLabel", background=LATERAL, foreground="white", font=mediana)
    e.configure("LateralSuave.TLabel", background=LATERAL, foreground=LATERAL_SUAVE, font=pequena)
    e.configure("Tarjeta.TLabel", background=TARJETA)
    e.configure("TituloTarjeta.TLabel", background=TARJETA, foreground=TEXTO_SUAVE, font=pequena)
    e.configure("ValorTarjeta.TLabel", background=TARJETA, foreground=TEXTO, font=grande)
    e.configure("Vacio.TLabel", background=TARJETA, foreground=TEXTO_SUAVE, font=("", 11))
    e.configure("Banda.TLabel", background=LATERAL, foreground="white", font=mediana)
    e.configure("BandaSuave.TLabel", background=LATERAL, foreground=LATERAL_SUAVE)

    # ---- botones
    def boton(nombre, fondo, hover, texto="white", borde=None, padding=None, **extra):
        borde = borde or fondo
        padding = padding or (px(14), px(8))
        e.configure(f"{nombre}.TButton", background=fondo, foreground=texto,
                    bordercolor=borde, lightcolor=fondo, darkcolor=fondo,
                    focuscolor=fondo, borderwidth=1, relief="flat",
                    padding=padding, font=negrita, width=0, **extra)   # width=0: ancho = el del texto
        e.map(f"{nombre}.TButton",
              background=[("disabled", BORDE), ("pressed", hover), ("active", hover)],
              bordercolor=[("disabled", BORDE), ("pressed", hover), ("active", hover)],
              lightcolor=[("pressed", hover), ("active", hover)],
              darkcolor=[("pressed", hover), ("active", hover)],
              foreground=[("disabled", TEXTO_SUAVE)])

    boton("Primario", PRIMARIO, PRIMARIO_HOVER)
    boton("Peligro", PELIGRO, PELIGRO_HOVER)
    boton("Exito", EXITO, EXITO_HOVER)
    boton("Aviso", AVISO, AVISO_HOVER)
    boton("Secundario", TARJETA, FONDO, texto=TEXTO, borde=BORDE)
    boton("Lateral", LATERAL, LATERAL_HOVER, texto=LATERAL_TEXTO,
          anchor="w", padding=(px(20), px(11)))
    e.configure("Lateral.TButton", font="TkDefaultFont")

    # ---- campos de texto
    campo = dict(fieldbackground=TARJETA, background=TARJETA, foreground=TEXTO,
                 bordercolor=BORDE, lightcolor=BORDE, darkcolor=BORDE,
                 insertcolor=TEXTO, padding=px(6))
    e.configure("TEntry", **campo)
    e.map("TEntry",
          bordercolor=[("focus", PRIMARIO)], lightcolor=[("focus", PRIMARIO)],
          darkcolor=[("focus", PRIMARIO)],
          fieldbackground=[("disabled", FONDO), ("readonly", FONDO)],
          foreground=[("disabled", TEXTO_SUAVE)])
    e.configure("TCombobox", arrowcolor=TEXTO_SUAVE, **campo)
    e.map("TCombobox",
          bordercolor=[("focus", PRIMARIO)], lightcolor=[("focus", PRIMARIO)],
          darkcolor=[("focus", PRIMARIO)],
          fieldbackground=[("readonly", TARJETA)],
          selectbackground=[("readonly", TARJETA)],
          selectforeground=[("readonly", TEXTO)])

    # ---- tablas
    e.configure("Treeview", background=TARJETA, fieldbackground=TARJETA, foreground=TEXTO,
                rowheight=px(32), borderwidth=0, relief="flat")
    e.map("Treeview", background=[("selected", PRIMARIO_SUAVE)],
          foreground=[("selected", TEXTO)])
    e.configure("Treeview.Heading", background="#F1F5F9", foreground=TEXTO_SUAVE,
                font=negrita, relief="flat", padding=(px(8), px(9)), borderwidth=0)
    e.map("Treeview.Heading", background=[("active", BORDE)])
    # arreglo para versiones de Tk (8.6.9) donde los colores de las filas no se aplican
    def _sin_error(opcion):
        return [x for x in e.map("Treeview", query_opt=opcion)
                if x[:2] != ("!disabled", "!selected")]
    e.map("Treeview", foreground=_sin_error("foreground"), background=_sin_error("background"))

    # ---- barra de desplazamiento
    e.configure("Vertical.TScrollbar", background="#CBD5E1", troughcolor=TARJETA,
                bordercolor=TARJETA, lightcolor="#CBD5E1", darkcolor="#CBD5E1",
                arrowcolor=TEXTO_SUAVE, gripcount=0, relief="flat")
    e.map("Vertical.TScrollbar", background=[("active", "#94A3B8")])
    e.configure("TSeparator", background=BORDE)
    return ESCALA
