"""Cálculo puro Decimal; no consulta catálogos ni modifica registros."""
from decimal import Decimal, DecimalException, ROUND_DOWN, localcontext

from django.core.exceptions import ValidationError

from compras.importes import decimal_valido
from parametros.catalogo import validar_decimales_oferta, validar_redondeo_oferta


def validar_reglas(reglas):
    resultado = {"decimales": validar_decimales_oferta(reglas.get("decimales")), "modo": validar_redondeo_oferta(reglas.get("modo", "")),
        "orden_descuento": reglas.get("orden_descuento"), "nivel_redondeo": reglas.get("nivel_redondeo")}
    if resultado["orden_descuento"] not in ("antes_impuesto", "despues_impuesto") or resultado["nivel_redondeo"] not in ("linea", "total"):
        raise ValidationError("Configure descuento antes_impuesto/despues_impuesto y redondeo linea/total.")
    return resultado


def _repartir(importes, paso, modo, topes=None):
    """Reparte el total redondeado por residuos, con desempate por posición."""
    valores = [i.quantize(paso, rounding=ROUND_DOWN) for i in importes]
    objetivo = sum(importes, Decimal(0)).quantize(paso, rounding=modo)
    faltan = int((objetivo - sum(valores, Decimal(0))) / paso)
    prioridad = sorted(range(len(importes)), key=lambda i: (-(importes[i] - valores[i]), i))
    while faltan:
        avance = False
        for i in prioridad:
            if topes is None or valores[i] + paso <= topes[i]:
                valores[i] += paso
                faltan -= 1
                avance = True
                if not faltan:
                    break
        if not avance:
            raise ValidationError("No se puede distribuir el descuento sin superar el bruto de una línea.")
    return valores


def calcular_orden(lineas, reglas, retenciones=()):
    try:
        return _calcular_orden(lineas, reglas, retenciones)
    except DecimalException:
        raise ValidationError("Los importes superan la precisión admitida.") from None


def _calcular_orden(lineas, reglas, retenciones):
    reglas = validar_reglas(reglas)
    if not lineas:
        raise ValidationError("La orden debe tener al menos una línea.")
    with localcontext() as contexto:
        contexto.prec = 60
        paso = Decimal(1).scaleb(-reglas["decimales"])
        q = lambda v: v.quantize(paso, rounding=reglas["modo"])
        brutos, descuentos, porcentajes, impuestos_raw = [], [], [], []
        for linea in lineas:
            cantidad, precio, porcentaje, descuento = [decimal_valido(linea.get(k, 0)) for k in ("cantidad", "precio_unitario", "porcentaje", "descuento")]
            bruto = cantidad * precio
            if cantidad <= 0 or porcentaje > 100 or descuento > bruto:
                raise ValidationError("Cantidad positiva, tarifa entre 0 y 100 %, y descuento no superior al bruto de su línea.")
            brutos.append(bruto)
            descuentos.append(descuento)
            porcentajes.append(porcentaje)
            base_impuesto = bruto - descuento if reglas["orden_descuento"] == "antes_impuesto" else bruto
            impuestos_raw.append(base_impuesto * porcentaje / 100)
        if reglas["nivel_redondeo"] == "total":
            brutos_q = _repartir(brutos, paso, reglas["modo"])
            descuentos_q = _repartir(descuentos, paso, reglas["modo"], topes=brutos_q)
            impuestos_q = _repartir(impuestos_raw, paso, reglas["modo"])
        else:
            brutos_q, descuentos_q = [q(v) for v in brutos], [q(v) for v in descuentos]
            impuestos_q = [q((b - d if reglas["orden_descuento"] == "antes_impuesto" else b) * p / 100)
                for b, d, p in zip(brutos_q, descuentos_q, porcentajes)]
        resultado = []
        for i, linea in enumerate(lineas):
            base = brutos_q[i] - descuentos_q[i]
            resultado.append({"id": linea.get("id", i + 1), "subtotal": brutos_q[i], "descuento_aplicado": descuentos_q[i],
                "base": base, "base_impuesto": base if reglas["orden_descuento"] == "antes_impuesto" else brutos_q[i],
                "impuesto": impuestos_q[i], "total": base + impuestos_q[i],
                "sin_redondear": {"subtotal": str(brutos[i]), "descuento": str(descuentos[i]), "impuesto": str(impuestos_raw[i])}})
        subtotal = sum(brutos_q, Decimal(0))
        descuento = sum(descuentos_q, Decimal(0))
        base = subtotal - descuento
        impuesto = sum(impuestos_q, Decimal(0))
        bruto_total = base + impuesto
        aplicadas = []
        for retencion in retenciones:
            porcentaje = decimal_valido(retencion["porcentaje"])
            minimo = decimal_valido(retencion["base_minima"]) if retencion.get("base_minima") is not None else None
            tipo_base = retencion.get("base_calculo", "base_neta")
            if porcentaje > 100 or tipo_base not in ("base_neta", "subtotal", "total_con_impuestos"):
                raise ValidationError("Retención con porcentaje entre 0 y 100 % y base de cálculo conocida.")
            base_retencion = {"base_neta": base, "subtotal": subtotal, "total_con_impuestos": bruto_total}[tipo_base]
            aplica = minimo is None or base_retencion >= minimo
            importe = q(base_retencion * porcentaje / 100) if aplica else Decimal(0)
            aplicadas.append({"id": retencion.get("id"), "nombre": retencion["nombre"], "porcentaje": str(porcentaje),
                "base_minima": str(minimo) if minimo is not None else None, "base_calculo": tipo_base,
                "base": str(base_retencion), "aplicada": aplica, "importe": str(importe)})
        retenido = sum((Decimal(r["importe"]) for r in aplicadas), Decimal(0))
        if retenido > bruto_total:
            raise ValidationError("Las retenciones no pueden superar el total con impuestos.")
        return {"lineas": resultado, "subtotal": subtotal, "descuento": descuento, "base": base, "impuesto": impuesto,
            "total_sin_retenciones": bruto_total, "retencion": retenido, "total": bruto_total - retenido,
            "retenciones_aplicadas": aplicadas, "reglas": reglas}
