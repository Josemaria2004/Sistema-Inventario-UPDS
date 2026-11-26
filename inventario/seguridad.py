"""seguridad.py - Hash y verificación de contraseñas.

Formato guardado:  pbkdf2_sha256$<iteraciones>$<sal_hex>$<hash_hex>

Se usa PBKDF2-HMAC-SHA256 (SHA-256 + sal aleatoria por usuario + muchas
iteraciones) de la librería estándar. También se reconoce el formato antiguo
(SHA-256 simple, 64 caracteres hex) para poder migrar bases de datos ya
existentes: al primer login correcto se vuelve a guardar con el formato nuevo.
"""
import hashlib
import hmac
import os

ALGORITMO = "pbkdf2_sha256"
ITERACIONES = 200_000          # los tests lo bajan para ir rápido
TAM_SAL = 16


def hash_clave(clave, sal=None, iteraciones=None):
    """Devuelve el hash con sal de `clave` en el formato nuevo."""
    iteraciones = iteraciones or ITERACIONES
    sal = sal if sal is not None else os.urandom(TAM_SAL)
    h = hashlib.pbkdf2_hmac("sha256", clave.encode("utf-8"), sal, iteraciones)
    return f"{ALGORITMO}${iteraciones}${sal.hex()}${h.hex()}"


def es_hash_legacy(almacenado):
    """True si es el SHA-256 simple (64 hex) del proyecto original."""
    if not isinstance(almacenado, str) or len(almacenado) != 64:
        return False
    try:
        int(almacenado, 16)
    except ValueError:
        return False
    return True


def verificar_clave(clave, almacenado):
    """Compara `clave` contra el hash guardado (nuevo o legacy)."""
    if not isinstance(almacenado, str) or not isinstance(clave, str):
        return False
    if es_hash_legacy(almacenado):
        calculado = hashlib.sha256(clave.encode("utf-8")).hexdigest()
        return hmac.compare_digest(calculado, almacenado)
    try:
        algoritmo, iters, sal_hex, hash_hex = almacenado.split("$")
        if algoritmo != ALGORITMO:
            return False
        esperado = bytes.fromhex(hash_hex)
        calculado = hashlib.pbkdf2_hmac(
            "sha256", clave.encode("utf-8"), bytes.fromhex(sal_hex), int(iters))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(calculado, esperado)


def necesita_actualizar(almacenado):
    """True si el hash es legacy o usa menos iteraciones que las actuales."""
    if es_hash_legacy(almacenado):
        return True
    try:
        return int(almacenado.split("$")[1]) < ITERACIONES
    except (IndexError, ValueError, AttributeError):
        return True
