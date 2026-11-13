"""Importes de ofertas con Decimal y redondeo explícito por línea."""
from decimal import Decimal, InvalidOperation, localcontext

from django.core.exceptions import ValidationError

from parametros.catalogo import validar_decimales_oferta, validar_redondeo_oferta


def decimal_valido(valor):
    try:
        if isinstance(valor, (bool, float)):
            raise ValueError
        numero = Decimal(str(valor))
        if not numero.is_finite() or numero < 0:
            raise ValueError
        return numero
    except (InvalidOperation, ValueError):
        raise ValidationError("Use números decimales finitos mayores o iguales a cero.") from None


def calcular_importes(cantidad, precio_unitario, porcentaje, reglas):
    decimales = validar_decimales_oferta(reglas["decimales"])
    modo = validar_redondeo_oferta(reglas["modo"])
    cantidad, precio, porcentaje = map(decimal_valido, (cantidad, precio_unitario, porcentaje))
    if cantidad <= 0 or porcentaje > 100:
        raise ValidationError("La cantidad debe ser positiva y la tarifa debe estar entre 0 y 100 %.")
    with localcontext() as contexto:
        contexto.prec = 50
        try:
            paso = Decimal(1).scaleb(-decimales)
            subtotal = (cantidad * precio).quantize(paso, rounding=modo)
            impuesto = (subtotal * porcentaje / 100).quantize(paso, rounding=modo)
        except InvalidOperation:
            raise ValidationError("Los importes superan la precisión admitida.") from None
        return {"subtotal": subtotal, "impuesto": impuesto, "total": subtotal + impuesto}
