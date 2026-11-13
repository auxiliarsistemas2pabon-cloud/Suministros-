"""NIT colombiano: forma canónica y dígito de verificación (algoritmo de la DIAN).

Forma canónica: solo dígitos, sin ceros a la izquierda, sin el dígito de verificación.
Se aceptan puntos, espacios y guiones como separadores. Solo se toma como dígito de
verificación un guion seguido de **un único** dígito al final («900.123.456-8»); así
«900-123-456» se lee como el NIT 900123456 y no como un dígito de verificación.
"""

import re

from django.core.exceptions import ValidationError

PESOS = (3, 7, 13, 17, 19, 23, 29, 37, 41, 43, 47, 53, 59, 67, 71)
LONGITUD_MINIMA = 5
LONGITUD_MAXIMA = len(PESOS)

_CON_DIGITO = re.compile(r"^(?P<nit>.*[0-9])\s*-\s*(?P<dv>[0-9])\s*$")
_SEPARADORES = re.compile(r"[.\s-]")
_SOLO_DIGITOS = re.compile(r"[0-9]+")

MENSAJE_CARACTERES = (
    "El NIT solo puede tener números, puntos, espacios y un guion antes del dígito de verificación."
)
MENSAJE_LONGITUD = f"El NIT debe tener entre {LONGITUD_MINIMA} y {LONGITUD_MAXIMA} dígitos."


def calcular_dv(nit):
    """Dígito de verificación de un NIT canónico (solo dígitos)."""
    suma = sum(int(digito) * peso for digito, peso in zip(reversed(nit), PESOS))
    residuo = suma % 11
    return residuo if residuo < 2 else 11 - residuo


def separar(texto):
    """(nit_canónico, dígito_escrito o None). ValidationError si el texto no es un NIT."""
    texto = (texto or "").strip()
    digito = None
    coincidencia = _CON_DIGITO.match(texto)
    if coincidencia:
        texto, digito = coincidencia["nit"], int(coincidencia["dv"])
    nit = _SEPARADORES.sub("", texto)
    if not _SOLO_DIGITOS.fullmatch(nit):
        raise ValidationError(MENSAJE_CARACTERES, code="nit_caracteres")
    nit = nit.lstrip("0")
    if not LONGITUD_MINIMA <= len(nit) <= LONGITUD_MAXIMA:
        raise ValidationError(MENSAJE_LONGITUD, code="nit_longitud")
    return nit, digito


def normalizar(texto):
    """(nit_canónico, dígito_de_verificación). Si se escribió el dígito, debe coincidir."""
    nit, escrito = separar(texto)
    calculado = calcular_dv(nit)
    if escrito is not None and escrito != calculado:
        raise ValidationError(
            f"El dígito de verificación no corresponde al NIT {formatear(nit)}; debería ser {calculado}.",
            code="nit_digito",
        )
    return nit, calculado


def formatear(nit, digito=None):
    """«900.123.456» o, con dígito, «900.123.456-8»."""
    if not nit or not nit.isdigit():
        return nit or ""
    texto = f"{int(nit):,}".replace(",", ".")
    return f"{texto}-{digito}" if digito is not None else texto


def digitos_para_buscar(texto):
    """Dígitos del NIT escrito en una búsqueda (sin separadores ni dígito de verificación),
    o "" si el texto no parece un NIT."""
    try:
        return separar(texto)[0]
    except ValidationError:
        return ""
