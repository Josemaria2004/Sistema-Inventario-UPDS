"""estructuras.py - Estructuras de datos dinámicas (memoria dinámica) hechas a mano.

En Python no hay punteros, pero los *nodos enlazados* funcionan igual: cada
nodo se crea en tiempo de ejecución (memoria dinámica) y apunta a otro objeto.
Aquí se implementan:

- Nodo / ListaEnlazada : lista simplemente enlazada (con puntero a cabeza y cola).
- Pila                 : LIFO construida sobre la lista enlazada. Se usa para "Deshacer".
- NodoCategoria /
  ArbolCategorias      : árbol n-ario construido en tiempo de ejecución desde la BD.
                         Sus operaciones son RECURSIVAS (recorrido, ruta, totales...).
"""
from typing import Callable, Dict, Iterator, List, Optional, Set, Tuple

from models import Categoria


class EstructuraVacia(Exception):
    """Se intentó sacar un elemento de una estructura vacía."""


# =====================================================================
#  LISTA ENLAZADA Y PILA
# =====================================================================
class Nodo:
    """Un eslabón: guarda un valor y la referencia (puntero) al siguiente."""
    __slots__ = ("valor", "siguiente")

    def __init__(self, valor, siguiente: "Optional[Nodo]" = None):
        self.valor = valor
        self.siguiente = siguiente


class ListaEnlazada:
    """Lista simplemente enlazada con referencias a la cabeza y a la cola."""

    def __init__(self):
        self._cabeza: Optional[Nodo] = None
        self._cola: Optional[Nodo] = None
        self._tamano = 0

    def __len__(self):
        return self._tamano

    def esta_vacia(self):
        return self._tamano == 0

    def __iter__(self) -> Iterator:
        actual = self._cabeza
        while actual is not None:
            yield actual.valor
            actual = actual.siguiente

    def a_lista(self) -> list:
        return list(self)

    def agregar_al_inicio(self, valor):                     # O(1)
        self._cabeza = Nodo(valor, self._cabeza)
        if self._cola is None:
            self._cola = self._cabeza
        self._tamano += 1

    def agregar_al_final(self, valor):                      # O(1) gracias a la cola
        nuevo = Nodo(valor)
        if self._cola is None:
            self._cabeza = self._cola = nuevo
        else:
            self._cola.siguiente = nuevo
            self._cola = nuevo
        self._tamano += 1

    def primero(self):
        if self._cabeza is None:
            raise EstructuraVacia("La lista está vacía.")
        return self._cabeza.valor

    def eliminar_primero(self):                             # O(1)
        if self._cabeza is None:
            raise EstructuraVacia("La lista está vacía.")
        nodo = self._cabeza
        self._cabeza = nodo.siguiente
        if self._cabeza is None:
            self._cola = None
        self._tamano -= 1
        return nodo.valor

    def eliminar_ultimo(self):                              # O(n): hay que llegar al penúltimo
        if self._cabeza is None:
            raise EstructuraVacia("La lista está vacía.")
        if self._cabeza is self._cola:
            return self.eliminar_primero()
        penultimo = self._cabeza
        while penultimo.siguiente is not self._cola:
            penultimo = penultimo.siguiente
        valor = self._cola.valor
        penultimo.siguiente = None
        self._cola = penultimo
        self._tamano -= 1
        return valor

    def buscar(self, condicion: Callable[[object], bool]):
        """Primer valor que cumple `condicion`, o None."""
        for valor in self:
            if condicion(valor):
                return valor
        return None

    def vaciar(self):
        self._cabeza = self._cola = None                    # el resto lo libera el recolector
        self._tamano = 0


class Pila:
    """Pila (LIFO). El tope es la cabeza de la lista enlazada.

    Con `capacidad`, al llenarse se descarta el elemento MÁS ANTIGUO (el fondo).
    """

    def __init__(self, capacidad: Optional[int] = None):
        if capacidad is not None and capacidad < 1:
            raise ValueError("La capacidad debe ser al menos 1.")
        self._lista = ListaEnlazada()
        self.capacidad = capacidad

    def __len__(self):
        return len(self._lista)

    def __iter__(self):                                     # del tope hacia el fondo
        return iter(self._lista)

    def esta_vacia(self):
        return self._lista.esta_vacia()

    def apilar(self, valor):
        self._lista.agregar_al_inicio(valor)
        if self.capacidad is not None and len(self._lista) > self.capacidad:
            self._lista.eliminar_ultimo()

    def tope(self):
        try:
            return self._lista.primero()
        except EstructuraVacia:
            raise EstructuraVacia("La pila está vacía.") from None

    def desapilar(self):
        try:
            return self._lista.eliminar_primero()
        except EstructuraVacia:
            raise EstructuraVacia("La pila está vacía.") from None

    def vaciar(self):
        self._lista.vaciar()


# =====================================================================
#  ÁRBOL DE CATEGORÍAS (recursivo)
# =====================================================================
class NodoCategoria:
    """Nodo del árbol: una categoría, su padre y la lista (dinámica) de hijos."""

    def __init__(self, categoria: Categoria):
        self.categoria = categoria
        self.padre: Optional[NodoCategoria] = None
        self.hijos: List[NodoCategoria] = []

    @property
    def id(self):
        return self.categoria.id

    @property
    def nombre(self):
        return self.categoria.nombre


class ArbolCategorias:
    """Árbol n-ario de categorías/subcategorías construido en tiempo de ejecución.

    Casi todos los métodos son recursivos, porque la estructura lo es:
    cada subcategoría es, a su vez, un árbol más pequeño.
    """

    def __init__(self, categorias: List[Categoria]):
        self._nodos: Dict[int, NodoCategoria] = {c.id: NodoCategoria(c) for c in categorias}
        self.raices: List[NodoCategoria] = []
        for nodo in self._nodos.values():
            padre = self._nodos.get(nodo.categoria.id_padre) \
                if nodo.categoria.id_padre is not None else None
            if padre is not None and padre is not nodo:
                nodo.padre = padre
                padre.hijos.append(nodo)
            else:
                self.raices.append(nodo)
        self._romper_ciclos()
        self._ordenar(self.raices)

    # ---------- construcción ----------
    def _romper_ciclos(self):
        """Si una BD dañada tuviera un ciclo (A hijo de B y B hijo de A) esos nodos
        no se alcanzarían desde ninguna raíz: se convierten en raíces."""
        alcanzables: Set[int] = {n.id for n, _ in self._recorrer(self.raices, 0)}
        for nodo in self._nodos.values():
            if nodo.id not in alcanzables:
                nodo.padre.hijos.remove(nodo)
                nodo.padre = None
                self.raices.append(nodo)
                alcanzables |= {n.id for n, _ in self._recorrer([nodo], 0)}

    def _ordenar(self, nodos: List[NodoCategoria]):             # recursivo
        nodos.sort(key=lambda n: n.nombre.casefold())
        for n in nodos:
            self._ordenar(n.hijos)

    # ---------- consultas ----------
    def __len__(self):
        return len(self._nodos)

    def nodo(self, id_cat) -> Optional[NodoCategoria]:
        return self._nodos.get(id_cat)

    def _recorrer(self, nodos: List[NodoCategoria], nivel: int) \
            -> Iterator[Tuple[NodoCategoria, int]]:
        """Recorrido en preorden: primero el nodo, luego (recursivamente) sus hijos."""
        for n in nodos:
            yield n, nivel
            yield from self._recorrer(n.hijos, nivel + 1)

    def recorrer(self) -> Iterator[Tuple[NodoCategoria, int]]:
        """(nodo, nivel) de todo el árbol, en preorden y ordenado por nombre."""
        return self._recorrer(self.raices, 0)

    def ruta(self, id_cat, separador=" > ") -> str:
        """'Electrónica > Audio > Auriculares' (sube recursivamente hasta la raíz)."""
        nodo = self._nodos.get(id_cat)
        return "" if nodo is None else self._ruta(nodo, separador)

    def _ruta(self, nodo: NodoCategoria, separador: str) -> str:
        if nodo.padre is None:                                  # caso base
            return nodo.nombre
        return self._ruta(nodo.padre, separador) + separador + nodo.nombre

    def nivel(self, id_cat) -> int:
        nodo = self._nodos.get(id_cat)
        return 0 if nodo is None else self._nivel(nodo)

    def _nivel(self, nodo: NodoCategoria) -> int:
        return 0 if nodo.padre is None else 1 + self._nivel(nodo.padre)

    def ids_subarbol(self, id_cat) -> Set[int]:
        """Id de la categoría y de TODAS sus descendientes."""
        nodo = self._nodos.get(id_cat)
        return set() if nodo is None else self._ids(nodo)

    def _ids(self, nodo: NodoCategoria) -> Set[int]:
        ids = {nodo.id}
        for h in nodo.hijos:
            ids |= self._ids(h)
        return ids

    def altura(self) -> int:
        """Número de niveles del árbol (0 si está vacío)."""
        return self._altura(self.raices)

    def _altura(self, nodos: List[NodoCategoria]) -> int:
        return 0 if not nodos else 1 + max(self._altura(n.hijos) for n in nodos)

    def total(self, id_cat, directo: Dict[int, float]) -> float:
        """Suma `directo[id]` de la categoría y de todas sus subcategorías.
        (Ej.: productos o valor de una categoría incluyendo lo que hay en sus hijas.)"""
        nodo = self._nodos.get(id_cat)
        return 0 if nodo is None else self._total(nodo, directo)

    def _total(self, nodo: NodoCategoria, directo: Dict[int, float]) -> float:
        return directo.get(nodo.id, 0) + sum(self._total(h, directo) for h in nodo.hijos)

    def puede_ser_padre(self, id_cat, id_nuevo_padre) -> bool:
        """False si mover `id_cat` dentro de `id_nuevo_padre` crearía un ciclo
        (una categoría no puede quedar dentro de sí misma ni de sus descendientes)."""
        if id_nuevo_padre is None:
            return True
        return id_nuevo_padre not in self.ids_subarbol(id_cat)
