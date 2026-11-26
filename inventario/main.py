"""main.py - Punto de entrada del Sistema de Inventario.

    python main.py
"""
import sys

from database import Database
from models import ErrorInventario
from reportes import ReporteService
from respaldos import RespaldoService
from servicios import AuthService, InventarioService
from ui import App


def _activar_nitidez_en_windows():
    """En pantallas con escala 125%/150% Tkinter se ve borroso si no se avisa a Windows."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass                      # no es grave: solo se vería menos nítido


def main(ruta_db=None):
    _activar_nitidez_en_windows()
    db = Database(ruta_db)              # crea inventario.db (y el usuario admin) si no existe
    try:
        auth = AuthService(db)
        inventario = InventarioService(db)
        reportes = ReporteService(inventario)
        respaldos = RespaldoService(db)
        try:                            # una copia por día en la carpeta 'respaldos'
            respaldos.respaldo_automatico()
        except ErrorInventario:
            pass                        # un fallo del respaldo no debe impedir usar el programa
        app = App(auth, inventario, reportes, respaldos)    # pide el login al crearse
        if app.autenticado:                                  # solo abre la app si el login fue correcto
            app.mainloop()
    finally:
        db.cerrar()


if __name__ == "__main__":
    main()
