"""Lectura tipada de variables de entorno para settings.

python-dotenv carga el archivo .env en os.environ; estas funciones solo
convierten los textos a los tipos que necesita Django. Un valor vacío se
trata igual que una variable ausente, de modo que un .env copiado de
.env.example (con valores vacíos) usa los valores por defecto.
"""

import os

from django.core.exceptions import ImproperlyConfigured

VALORES_VERDADEROS = {"1", "true", "t", "si", "sí", "s", "yes", "y", "on"}
VALORES_FALSOS = {"0", "false", "f", "no", "n", "off"}


def _leer(nombre, entorno):
    valor = (entorno if entorno is not None else os.environ).get(nombre)
    if valor is None:
        return None
    valor = valor.strip()
    return valor or None


def env_texto(nombre, defecto=None, entorno=None):
    valor = _leer(nombre, entorno)
    return defecto if valor is None else valor


def env_obligatoria(nombre, entorno=None):
    valor = _leer(nombre, entorno)
    if valor is None:
        raise ImproperlyConfigured(
            f"Falta la variable de entorno {nombre}. Defínala en el archivo .env "
            "(vea .env.example)."
        )
    return valor


def env_bool(nombre, defecto=False, entorno=None):
    valor = _leer(nombre, entorno)
    if valor is None:
        return defecto
    normalizado = valor.lower()
    if normalizado in VALORES_VERDADEROS:
        return True
    if normalizado in VALORES_FALSOS:
        return False
    raise ImproperlyConfigured(
        f"La variable {nombre} debe ser True o False; se recibió {valor!r}."
    )


def env_entero(nombre, defecto, entorno=None):
    valor = _leer(nombre, entorno)
    if valor is None:
        return defecto
    try:
        return int(valor)
    except ValueError:
        raise ImproperlyConfigured(
            f"La variable {nombre} debe ser un número entero; se recibió {valor!r}."
        ) from None


def env_lista(nombre, defecto=None, entorno=None):
    """Lista separada por comas; descarta espacios y elementos vacíos."""
    valor = _leer(nombre, entorno)
    if valor is None:
        return list(defecto or [])
    return [parte.strip() for parte in valor.split(",") if parte.strip()]
