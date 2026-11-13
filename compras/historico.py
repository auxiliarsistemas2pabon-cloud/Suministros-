"""Adaptación de la foto de cierre al formato de consulta de matrices y puestos."""
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace


def matriz_cierre(lista):
    if lista.estado == "borrador" or not lista.resultado_cierre:
        return None
    foto = deepcopy(lista.resultado_cierre)
    filas, grupos, desempates = [], {}, {}
    for dato in foto["filas"]:
        p = SimpleNamespace(pk=dato["participante_id"], lista_id=lista.pk, proveedor_id=dato["proveedor_id"], nit=dato["nit"],
            razon_social=dato["razon_social"], activo=True, cantidad_autorizada=Decimal(dato["cantidad_autorizada"]),
            observacion=dato["observacion"], justificacion_eleccion=dato["justificacion_eleccion"],
            decision_por_id=dato["decision_por_id"], decision_por=dato["decision_por"],
            decision_fecha=datetime.fromisoformat(dato["decision_fecha"]) if dato["decision_fecha"] else None)
        desempate = None
        if dato["desempate"]:
            d = dato["desempate"]
            if d["pk"] not in desempates:
                desempates[d["pk"]] = SimpleNamespace(**{**d, "fecha": datetime.fromisoformat(d["fecha"])})
            desempate = desempates[d["pk"]]
        fila = {"participante": p, "completo": dato["completo"], "total": Decimal(dato["total"]),
                "parcial": Decimal(dato["parcial"]), "maximo": Decimal(dato["maximo"]), "puesto": dato["puesto"],
                "puesto_calculado": dato["puesto_calculado"], "empate": dato["empate"], "desempate": desempate,
                "celdas": [{**c, "peso": Decimal(c["peso"]), "cumplimiento": Decimal(c["cumplimiento"]) if c["cumplimiento"] is not None else None,
                            "subtotal": Decimal(c["subtotal"]) if c["subtotal"] is not None else None} for c in dato["celdas"]]}
        filas.append(fila)
        if dato["empate"]:
            grupo = grupos.setdefault(fila["total"], {"total": fila["total"], "filas": [], "desempate": desempate})
            grupo["filas"].append(fila)
    return {"historico": True, "criterios": [{**c, "peso": Decimal(c["peso"])} for c in foto["criterios"]],
            "reglas": foto["reglas"], "filas": filas, "completa": True,
            "base": {**foto["base"], "cantidad": Decimal(foto["base"]["cantidad"])}, "empates": list(grupos.values())}
