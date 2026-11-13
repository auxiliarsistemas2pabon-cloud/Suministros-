"""Cálculo Decimal de FR-GDS-20, sin escrituras ni consultas."""

import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext

from django.core.exceptions import ValidationError

from parametros.catalogo import validar_reglas_elegibles

PRECISION = Decimal("0.0001")


def calcular_puntaje(criterios, respuestas, reglas):
    reglas = json.loads(validar_reglas_elegibles(json.dumps(reglas)))
    criterios = list(criterios)
    try:
        pesos = [Decimal(str(c["peso"])) for c in criterios]
        validos = all(p.is_finite() and 0 < p <= 100 for p in pesos)
    except (ValueError, TypeError, InvalidOperation):
        validos = False
    if not criterios or not validos or sum(pesos, Decimal(0)) != 100:
        raise ValidationError("Los pesos de la versión deben sumar exactamente 100 %.")
    maximo_escala = max(Decimal(v) for v in reglas["escala"])
    escala = {Decimal(v) for v in reglas["escala"]}
    celdas, parcial, completo = [], Decimal(0), True
    with localcontext() as contexto:
        contexto.prec = 32
        for criterio in criterios:
            respuesta = respuestas.get(criterio["id"], {})
            valor = respuesta.get("cumplimiento")
            subtotal = None
            if valor is None:
                completo = False
            else:
                if isinstance(valor, (bool, float)):
                    raise ValidationError("Use valores decimales de la escala.")
                try:
                    valor = Decimal(str(valor))
                except (ValueError, InvalidOperation):
                    raise ValidationError("Use valores decimales de la escala.") from None
                if not valor.is_finite() or valor not in escala:
                    raise ValidationError("Un cumplimiento no pertenece a la escala de la lista.")
                peso = Decimal(str(criterio["peso"]))
                subtotal = (valor * peso / 100 if reglas["metodo"] == "directo" else valor / maximo_escala * peso).quantize(PRECISION, rounding=ROUND_HALF_UP)
                parcial += subtotal
            celdas.append({**criterio, "cumplimiento": valor, "subtotal": subtotal, "observacion": respuesta.get("observacion", "")})
    return {"celdas": celdas, "completo": completo, "parcial": parcial,
            "total": parcial if completo else None,
            "maximo": maximo_escala if reglas["metodo"] == "directo" else Decimal(100)}
