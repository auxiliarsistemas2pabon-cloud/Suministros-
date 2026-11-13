"""Cálculo puro FR14. No consulta modelos ni modifica la entrada."""
import json
from decimal import Decimal, ROUND_HALF_UP

from parametros.catalogo import validar_reglas_fr14


def calcular_evaluacion(filas, reglas):
    reglas = json.loads(validar_reglas_fr14(json.dumps(reglas)))
    lineas, grupos = [], {}
    puntos, maximo, sin_responder = Decimal("0"), Decimal("0"), 0
    for fila in filas:
        peso = Decimal(str(fila["peso"]))
        respuesta = fila.get("respuesta")
        if peso not in (Decimal("1"), Decimal("2")) or respuesta not in (None, "si", "no", "na"):
            raise ValueError("Peso o respuesta no válidos.")
        if respuesta is None:
            sin_responder += 1
        aplicable = Decimal("0") if respuesta == "na" and reglas["excluir_na"] else peso
        obtenido = peso * Decimal(reglas[respuesta]) if respuesta in ("si", "no") else Decimal("0")
        puntos += obtenido
        maximo += aplicable
        grupo = grupos.setdefault(fila["grupo"], {"grupo": fila["grupo"], "puntos": Decimal("0"), "maximo": Decimal("0")})
        grupo["puntos"] += obtenido
        grupo["maximo"] += aplicable
        lineas.append({**fila, "puntos": str(obtenido), "maximo": str(aplicable)})

    def resumen(puntos, maximo):
        porcentaje = (puntos / maximo * Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if maximo else None
        calificacion = (5 if porcentaje >= Decimal(reglas["umbral5"]) else 3 if porcentaje >= Decimal(reglas["umbral3"]) else 1) if porcentaje is not None else None
        return {"puntos": str(puntos), "maximo": str(maximo), "porcentaje": str(porcentaje) if porcentaje is not None else None, "calificacion": calificacion}

    return {**resumen(puntos, maximo), "grupos": [{**resumen(g["puntos"], g["maximo"]), "grupo": g["grupo"]} for g in grupos.values()],
            "lineas": lineas, "reglas": reglas, "sin_responder": sin_responder,
            "finalizable": bool(lineas) and not sin_responder and maximo > 0, "version_calculo": 1}
