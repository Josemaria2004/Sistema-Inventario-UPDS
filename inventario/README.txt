SISTEMA DE INVENTARIO - Proyecto final de Programación III
==========================================================

REQUISITOS
----------
- Python 3.8 o superior. Solo librería estándar (tkinter y sqlite3 ya vienen incluidos).
  (En Linux, si falta tkinter:  sudo apt install python3-tk)

EJECUCIÓN
---------
    python main.py

LOGIN INICIAL
-------------
    Usuario: admin      Clave: admin123
  La app avisa al entrar y ofrece cambiarla (botón "Cambiar clave").

TESTS
-----
    python -m unittest discover -s tests -v
  - tests/test_inventario.py : lógica base: seguridad, validación, stock, migración (46 tests).
  - tests/test_requisitos.py : recursividad, estructuras dinámicas, clases abstractas,
                               respaldos, papelera, deshacer, reportes (67 tests).
  - tests/test_ui.py         : ventanas reales de Tkinter (58 tests). Si no hay
    pantalla/tkinter se omiten solos. En Linux sin escritorio:
        xvfb-run -a python -m unittest discover -s tests -v

FUNCIONALIDADES
---------------
1. Login con contraseñas protegidas (PBKDF2-HMAC-SHA256 con sal) y bloqueo
   temporal tras 5 intentos fallidos. Cambio de contraseña.
2. CRUD completo de productos (agregar, editar, eliminar, búsqueda en vivo
   por nombre, descripción o categoría).
3. CRUD completo de categorías (agregar, renombrar, eliminar si no están en uso).
4. Entradas y salidas de stock con validación de stock suficiente.
5. Historial de movimientos (verde = entrada, rojo = salida).
6. Valor total del inventario en tiempo real.
7. Alerta y resaltado en rojo de productos con stock menor a 5. Tarjetas de resumen
   (valor total, nº de productos, nº con stock bajo) y columna de valor por producto.
8. Exportación de reporte a .txt o .csv (se elige el formato en "Guardar como").
9. Categorías jerárquicas (subcategorías) con totales que suman las hijas.
10. Deshacer la última entrada/salida de stock.
11. Recuperación de datos: productos eliminados (papelera), crear y restaurar respaldos,
    respaldo automático diario.
12. Ordenar la tabla haciendo clic en cualquier encabezado.

CUMPLIMIENTO DEL ENUNCIADO (dónde está cada requisito)
-----------------------------------------------------
RECURSIVIDAD
  - estructuras.py  ArbolCategorias: recorrer/_recorrer (preorden), ruta/_ruta (sube hasta la
    raíz), ids_subarbol/_ids, altura/_altura, total/_total (suma de las subcategorías),
    _ordenar. Casos base: nodo sin padre / lista de hijos vacía.
  - algoritmos.py   merge_sort: divide y vencerás, recursivo y estable. Se usa al hacer clic
    en los encabezados de la tabla.
  - ui.py           Categorias._pintar: pinta el árbol de categorías recursivamente.
MEMORIA DINÁMICA
  - estructuras.py  Nodo, ListaEnlazada (cabeza y cola, nodos creados en tiempo de
    ejecución), Pila (LIFO sobre la lista enlazada, con capacidad). Se usa en "Deshacer":
    InventarioService.pila_deshacer.
  - estructuras.py  NodoCategoria/ArbolCategorias: árbol construido en memoria a partir
    de la base de datos.
CLASES BASE ABSTRACTAS (módulo abc)
  - models.py       Entidad(ABC): validar() abstracto. Producto y Categoria la implementan.
  - database.py     RepositorioBase(ABC): listar() y obtener() abstractos. Los 4 repositorios
    la implementan.
  - reportes.py     Reporte(ABC): extension, descripcion y renderizar() abstractos;
    guardar() es un método plantilla. ReporteTxt y ReporteCsv son las subclases
    (polimorfismo). Para otro formato basta con crear otra subclase.
RECUPERACIÓN DE DATOS
  - respaldos.py    RespaldoService: crear() un respaldo, inspeccionar() (valida que sea un
    respaldo correcto), restaurar() (con copia de seguridad previa) y respaldo_automatico()
    (uno por día en la carpeta "respaldos", conserva los 7 últimos).
  - Papelera: "Productos eliminados" recupera un producto con su stock e historial.
  - Deshacer: revierte la última entrada/salida registrando el movimiento contrario.

NOTAS DE USO
------------
- Restaurar un respaldo REEMPLAZA todos los datos, incluidas las cuentas y contraseñas;
  antes se guarda una copia de lo que había en la carpeta "respaldos".
- "Deshacer" solo recuerda las operaciones de la sesión actual (la pila vive en memoria).
- Los nombres de categoría son únicos en todo el árbol.
- El CSV usa ";" como separador y coma decimal (se abre bien en Excel en español).

DECISIONES DE DISEÑO (para el informe)
--------------------------------------
- Arquitectura en capas:  ui.py -> servicios.py -> database.py (repositorios) -> SQLite.
  La interfaz NO contiene SQL ni reglas de negocio.
- models.py:     entidades (Producto, Categoria, Movimiento, Usuario), constantes y
                 excepciones propias (ErrorInventario, ErrorValidacion, StockInsuficiente...).
- database.py:   Database (conexión y transacciones) + un repositorio por entidad
                 (patrón Repository/DAO). Solo ejecutan SQL parametrizado.
- servicios.py:  AuthService, InventarioService (capa de servicio).
- seguridad.py:  hash y verificación de contraseñas.
- estructuras.py / algoritmos.py: estructuras enlazadas y algoritmos recursivos.
- reportes.py / respaldos.py:    reportes (TXT/CSV) y recuperación de datos.
- tema.py:       paleta de colores, fuentes y estilos ttk (cambiar el aspecto = tocar solo este archivo).
- ui.py:         DialogoModal es la clase base de los diálogos (herencia); Login,
                 FormularioProducto, DialogoCantidad y CambiarClave la extienden.
- Cada operación que modifica datos es atómica: o se guarda todo o se revierte todo
  (Database.transaccion()).
- El stock solo cambia mediante Entrada/Salida, así el historial siempre cuadra con el stock.
- "Eliminar" un producto es un borrado lógico: desaparece de la lista pero conserva
  su historial de movimientos.
- Seguridad: consultas parametrizadas (sin SQL injection), validación de datos
  (rechaza nan/inf/negativos/valores gigantes), errores mostrados al usuario.

BASE DE DATOS (se crea sola junto a main.py: inventario.db)
-----------------------------------------------------------
    usuarios(id, usuario, clave_hash)
    categorias(id, nombre, id_padre)
    productos(id, nombre, descripcion, precio, cantidad, id_categoria, activo)
    movimientos(id, id_producto, tipo, cantidad, fecha)
  Si ya tienes un inventario.db de la versión anterior, se actualiza solo
  (añade las columnas 'activo' e 'id_padre' y migra el hash de la contraseña al primer login).
