"""algoritmos.py - Algoritmos recursivos."""
from typing import Callable, List, Optional, Sequence, TypeVar

T = TypeVar("T")


def merge_sort(elementos: Sequence[T], clave: Optional[Callable[[T], object]] = None,
               reverso: bool = False) -> List[T]:
    """Ordenamiento por mezcla (divide y vencerás), RECURSIVO y ESTABLE.

    1. Caso base: una lista de 0 o 1 elementos ya está ordenada.
    2. Se divide por la mitad y se ordena cada mitad con la propia función.
    3. Se mezclan las dos mitades ordenadas.

    Complejidad O(n log n). No modifica la secuencia original: devuelve una lista nueva.
    Estable: los elementos con la misma clave conservan su orden relativo.
    """
    clave = clave or (lambda x: x)
    if len(elementos) <= 1:                                     # caso base
        return list(elementos)
    medio = len(elementos) // 2
    izquierda = merge_sort(elementos[:medio], clave, reverso)   # llamadas recursivas
    derecha = merge_sort(elementos[medio:], clave, reverso)
    return _mezclar(izquierda, derecha, clave, reverso)


def _mezclar(izq: List[T], der: List[T], clave, reverso: bool) -> List[T]:
    resultado: List[T] = []
    i = j = 0
    while i < len(izq) and j < len(der):
        ki, kd = clave(izq[i]), clave(der[j])
        # con claves iguales se toma el de la izquierda: eso hace al algoritmo estable
        tomar_izq = (ki >= kd) if reverso else (ki <= kd)
        if tomar_izq:
            resultado.append(izq[i]); i += 1
        else:
            resultado.append(der[j]); j += 1
    resultado.extend(izq[i:])
    resultado.extend(der[j:])
    return resultado
