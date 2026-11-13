"""Derivación pura con fecha inyectada; no consulta base de datos."""
from datetime import timedelta

ESTADOS = [("abierto", "Abierto"), ("en_espera_documentos", "En espera de documentos"), ("parcial", "Parcial"),
    ("atrasado", "Atrasado"), ("completo", "Completo"), ("cerrado", "Cerrado")]


def eventos_vigentes(eventos):
    corregidos = {e.get("corrige_id") for e in eventos if e.get("corrige_id")}
    return sorted((e for e in eventos if e["id"] not in corregidos), key=lambda e: (e["fecha"], e["id"]))


def evaluar_hitos(plantillas, eventos, apertura, hoy):
    eventos = eventos_vigentes([e for e in eventos if e["fecha"].date() <= hoy])
    resultado = []
    for hito in plantillas:
        referencias = [e["fecha"] for e in eventos if e["tipo_id"] == hito["referencia_id"]]
        referencia = max(referencias) if referencias else apertura if hito["referencia_id"] is None else None
        fecha_limite = referencia.date()+timedelta(days=hito["plazo_dias"]) if referencia else None
        cumplido = bool(referencia and any(e["tipo_id"] == hito["cumple_id"] and e["fecha"] >= referencia for e in eventos))
        resultado.append({**hito, "fecha_limite": fecha_limite, "cumplido": cumplido,
            "atrasado": bool(fecha_limite and fecha_limite < hoy and not cumplido)})
    return resultado


def derivar(*, cerrado, eventos, lineas, hitos, hoy, fecha_esperada=None):
    if cerrado:
        return "cerrado"
    if any(h["atrasado"] for h in hitos) or (fecha_esperada and fecha_esperada < hoy and any(l["pendiente"] > 0 and not l.get("cerrada", False) for l in lineas)):
        return "atrasado"
    documentos = [e for e in eventos_vigentes([e for e in eventos if e["fecha"].date() <= hoy]) if e["funcion"] in ("solicita_documentos", "recibe_documentos")]
    if documentos and documentos[-1]["funcion"] == "solicita_documentos":
        return "en_espera_documentos"
    if lineas and all(l["pendiente"] == 0 or l.get("cerrada", False) for l in lineas):
        return "completo"
    if any(l["recibido"] > 0 for l in lineas):
        return "parcial"
    return "abierto"
