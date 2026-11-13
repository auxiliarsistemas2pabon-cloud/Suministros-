"""Reglas y catálogos congelados: el motor puro nunca consulta datos vivos."""
from copy import deepcopy
from decimal import Decimal, localcontext

from django.core.exceptions import ValidationError

from compras.importes_orden import calcular_orden, validar_reglas
from compras.models import TipoRetencion
from parametros.catalogo import DECIMALES_ORDEN, MODO_REDONDEO_ORDEN, DESCUENTO_ORDEN, NIVEL_REDONDEO_ORDEN
from parametros.servicios import obtener

CAMPOS_TOTALES = ("subtotal", "descuento", "base", "impuesto", "total_sin_retenciones", "retencion", "total")
CAMPOS_CALCULO_LINEA = ("subtotal", "descuento_aplicado", "base", "base_impuesto", "impuesto", "total")


def reglas_origen(reglas):
    return {**reglas, "orden_descuento": "antes_impuesto", "nivel_redondeo": "linea"}


def reglas_actuales():
    return validar_reglas({"decimales": obtener(DECIMALES_ORDEN), "modo": obtener(MODO_REDONDEO_ORDEN),
        "orden_descuento": obtener(DESCUENTO_ORDEN), "nivel_redondeo": obtener(NIVEL_REDONDEO_ORDEN)})


def describir_reglas(reglas):
    reglas = validar_reglas(reglas)
    descuento = "antes del impuesto" if reglas["orden_descuento"] == "antes_impuesto" else "después del impuesto"
    nivel = "por línea" if reglas["nivel_redondeo"] == "linea" else "al total"
    return f'Descuento {descuento}; redondeo {nivel}, {reglas["decimales"]} decimales, {reglas["modo"]}.'


def seleccionar_retenciones(orden, ids=None, *, actualizar=False):
    guardadas = {r["id"]: r for r in orden.retenciones_aplicadas}
    if ids is None:
        ids = list(guardadas)
    if not isinstance(ids, (list, tuple)) or any(type(i) is not int for i in ids) or len(set(ids)) != len(ids):
        raise ValidationError("Seleccione cada retención una sola vez.")
    resultado = []
    for pk in sorted(ids):
        if pk in guardadas and not actualizar:
            resultado.append(deepcopy(guardadas[pk]))
            continue
        try:
            tipo = TipoRetencion.objects.get(pk=pk, activo=True)
        except TipoRetencion.DoesNotExist:
            raise ValidationError("Seleccione retenciones activas; las guardadas pueden conservar su foto anterior.") from None
        resultado.append({"id": tipo.pk, "nombre": tipo.nombre, "porcentaje": str(tipo.porcentaje),
            "base_minima": str(tipo.base_minima) if tipo.base_minima is not None else None, "base_calculo": tipo.base_calculo})
    return resultado


def calcular(orden, lineas, retenciones):
    return calcular_orden([{"id": l.pk, "cantidad": l.cantidad, "precio_unitario": l.precio_unitario,
        "porcentaje": l.porcentaje, "descuento": l.descuento} for l in lineas], orden.reglas_importes, retenciones)


def aplicar(orden, lineas, resultado):
    for linea, datos in zip(lineas, resultado["lineas"]):
        for campo in CAMPOS_CALCULO_LINEA:
            setattr(linea, campo, datos[campo])
        linea.desglose_calculo = datos["sin_redondear"]
        linea.reglas_calculo = deepcopy(orden.reglas_importes)
    with localcontext() as contexto:
        contexto.prec = 50
        for campo in CAMPOS_TOTALES:
            setattr(orden, campo, resultado[campo].quantize(Decimal("0.01")))
    orden.retenciones_aplicadas = resultado["retenciones_aplicadas"]


def validar_para_emitir(orden):
    lineas = list(orden.lineas.order_by("posicion"))
    resultado = calcular(orden, lineas, orden.retenciones_aplicadas)
    if any(getattr(orden, c) != resultado[c] for c in CAMPOS_TOTALES):
        raise ValidationError("Los totales no coinciden con las reglas guardadas. Devuelva la orden al borrador para revisarla.")
    for linea, datos in zip(lineas, resultado["lineas"]):
        reglas_linea = {"orden_descuento": "antes_impuesto", "nivel_redondeo": "linea", **linea.reglas_calculo}
        if validar_reglas(reglas_linea) != validar_reglas(orden.reglas_importes):
            raise ValidationError("Las reglas de una línea no coinciden con las guardadas en la orden.")
        if any(getattr(linea, c) != datos[c] for c in CAMPOS_CALCULO_LINEA):
            raise ValidationError("Una línea no coincide con sus importes calculados.")
    if resultado["retenciones_aplicadas"] != orden.retenciones_aplicadas:
        raise ValidationError("Las retenciones no coinciden con su desglose guardado.")
    return {"version": 1, "validacion_financiera": "pendiente de validar con financiera", "reglas": deepcopy(orden.reglas_importes),
        "totales": {c: str(resultado[c]) for c in CAMPOS_TOTALES}, "retenciones": deepcopy(orden.retenciones_aplicadas),
        "lineas": [{"id": l.pk, "cantidad": str(l.cantidad), "precio_unitario": str(l.precio_unitario),
            "tarifa_nombre": l.tarifa_nombre, "porcentaje": str(l.porcentaje), "descuento": str(l.descuento),
            **{c: str(getattr(l, c)) for c in CAMPOS_CALCULO_LINEA}} for l in lineas]}
