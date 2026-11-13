"""FR14 y documentos actuales en borrador; foto documental inmutable al cierre."""

from calendar import monthrange
from copy import deepcopy
from datetime import date

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from bitacora.servicios import guardar_con_bitacora
from compras.models import ListaElegibles, ParticipanteElegible
from parametros.catalogo import CONTROL_DOCUMENTAL_ELEGIBLES, MESES_EVALUACION_ELEGIBLES
from parametros.models import Parametro
from parametros.servicios import obtener
from proveedores.documental import tablero
from proveedores.servicios import _exigir_admin, _exigir_motivo


def reglas_actuales():
    modo, meses = obtener(CONTROL_DOCUMENTAL_ELEGIBLES), obtener(MESES_EVALUACION_ELEGIBLES)
    if modo not in ("advertir", "bloquear") or type(meses) is not int or meses < 1:
        raise ValidationError("Revise los parámetros de control documental de elegibles.")
    return {"modo": modo, "meses": meses, "pendiente": True}


def limite_antiguedad(fecha, meses):
    indice = fecha.year * 12 + fecha.month - 1 + meses
    anio, mes = divmod(indice, 12)
    mes += 1
    if anio > 9999:
        return date.max
    return date(anio, mes, min(fecha.day, monthrange(anio, mes)[1]))


def _foto_actual(participante, referencia, reglas):
    proveedor = participante.proveedor
    evaluacion = proveedor.evaluacion_vigente
    advertencias, informativas, bloqueos = [], [], []
    fr14 = None
    if evaluacion is None:
        advertencias.append("Sin evaluación FR-GDS-14 finalizada vigente.")
        bloqueos.append("sin_evaluacion")
    else:
        limite = limite_antiguedad(evaluacion.fecha, reglas["meses"])
        fr14 = {"id": evaluacion.pk, "fecha": evaluacion.fecha.isoformat(), "calificacion": evaluacion.resultado.get("calificacion"),
                "porcentaje": evaluacion.resultado.get("porcentaje"), "categoria": evaluacion.categoria_nombre,
                "categoria_id": evaluacion.categoria_id, "version": evaluacion.version.numero,
                "limite_antiguedad": limite.isoformat(), "vigente": evaluacion.fecha <= referencia <= limite}
        if evaluacion.fecha > referencia:
            advertencias.append("La evaluación FR-GDS-14 tiene una fecha posterior a la referencia.")
            bloqueos.append("evaluacion_futura")
        elif referencia > limite:
            advertencias.append(f"Evaluación FR-GDS-14 antigua: supera {reglas['meses']} meses.")
            bloqueos.append("evaluacion_antigua")
    filas = tablero(proveedor, categoria=evaluacion.categoria if evaluacion else proveedor.categoria,
                    version=evaluacion.version if evaluacion else None, hoy=referencia)
    documentos = []
    for fila in filas:
        exigencia, documento = fila["exigencia"], fila["documento"]
        foto = {"exigencia_id": exigencia.pk, "tipo_id": exigencia.tipo_id, "tipo": exigencia.tipo.nombre,
                "obligatorio": exigencia.obligatorio, "requisito_id": exigencia.requisito_id,
                "requisito": exigencia.requisito.texto if exigencia.requisito_id else "General",
                "requiere_vencimiento": exigencia.tipo.requiere_vencimiento,
                "estado": fila["estado"], "etiqueta": fila["etiqueta"], "dias_alerta": fila["dias"],
                "documento_id": documento.pk if documento else None,
                "expedicion": documento.fecha_expedicion.isoformat() if documento else None,
                "vencimiento": documento.fecha_vencimiento.isoformat() if documento and documento.fecha_vencimiento else None}
        documentos.append(foto)
        mensaje = f"{exigencia.tipo.nombre}: {fila['etiqueta']}."
        if fila["estado"] in ("vencido", "faltante"):
            advertencias.append(mensaje)
            if exigencia.obligatorio and fila["estado"] == "vencido":
                bloqueos.append(f"documento_vencido:{exigencia.tipo_id}")
        elif fila["estado"] == "por_vencer":
            informativas.append(mensaje)
    return {"referencia": referencia.isoformat(), "evaluacion": fr14, "documentos": documentos,
            "advertencias": list(dict.fromkeys(advertencias)), "informativas": list(dict.fromkeys(informativas)),
            "causas_bloqueo": list(dict.fromkeys(bloqueos))}


def obtener_control(lista, *, referencia=None, usar_historico=True):
    participantes = list(lista.participantes.filter(activo=True).select_related("proveedor", "evaluacion_fr14"))
    if usar_historico and lista.estado != "borrador":
        sin_foto = lista.documental_fecha is None
        return {"historico": True, "sin_foto": sin_foto, "referencia": lista.documental_referencia,
                "reglas": deepcopy(lista.documental_reglas),
                "filas": [{"participante": p, "foto": deepcopy(p.estado_documental), "elegido": p.cantidad_autorizada > 0} for p in participantes],
                "justificacion": lista.justificacion_documental}
    referencia = referencia or timezone.localdate()
    reglas = reglas_actuales()
    return {"historico": False, "sin_foto": False, "referencia": referencia, "reglas": reglas,
            "filas": [{"participante": p, "foto": _foto_actual(p, referencia, reglas), "elegido": p.cantidad_autorizada > 0} for p in participantes],
            "justificacion": lista.justificacion_documental}


def _validar(control, justificacion):
    elegidos = [f for f in control["filas"] if f["elegido"]]
    if control["sin_foto"]:
        raise ValidationError("La lista no tiene foto documental histórica. No se reconstruye con documentos actuales.")
    if control["reglas"]["modo"] == "bloquear" and any(f["foto"]["causas_bloqueo"] for f in elegidos):
        raise ValidationError("El control documental impide cerrar: un proveedor elegido no tiene FR14 vigente o tiene documentos obligatorios vencidos.")
    if any(f["foto"]["advertencias"] for f in elegidos) and not justificacion.strip():
        raise ValidationError("Justifique continuar con las advertencias documentales de los proveedores elegidos.")
    return control


def validar_para_cierre(lista, *, justificacion=None, referencia=None):
    lista = ListaElegibles.objects.get(pk=lista.pk)
    control = obtener_control(lista, referencia=referencia)
    return _validar(control, lista.justificacion_documental if justificacion is None else justificacion)


@transaction.atomic
def guardar_justificacion(lista, *, justificacion, actor, motivo, referencia=None):
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    lista = ListaElegibles.objects.select_for_update().get(pk=lista.pk)
    if lista.estado != "borrador":
        raise ValidationError("La justificación documental se conserva en listas cerradas o anuladas.")
    _validar(obtener_control(lista, referencia=referencia), justificacion)
    lista.justificacion_documental = justificacion.strip()
    lista.full_clean()
    guardar_con_bitacora(lista, ["justificacion_documental"], accion_crear="elegibles.justificacion_documental",
                        accion_modificar="elegibles.justificacion_documental", actor=actor, motivo=motivo)
    return lista


@transaction.atomic
def conservar_al_cerrar(lista, *, actor, motivo, referencia=None):
    """B8 deberá llamarlo tras cambiar el estado, dentro de su transacción de cierre."""
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    lista = ListaElegibles.objects.select_for_update().get(pk=lista.pk)
    if lista.estado != "cerrada" or lista.documental_fecha is not None:
        raise ValidationError("La foto documental se guarda una sola vez al cerrar la lista.")
    # Fija los parámetros durante la captura sin bloquear un JOIN nullable.
    list(Parametro.objects.select_for_update().filter(clave__in=[CONTROL_DOCUMENTAL_ELEGIBLES, MESES_EVALUACION_ELEGIBLES]).order_by("pk"))
    list(ParticipanteElegible.objects.select_for_update().filter(lista=lista).order_by("pk"))
    control = _validar(obtener_control(lista, referencia=referencia, usar_historico=False), lista.justificacion_documental)
    for fila in control["filas"]:
        p, foto = fila["participante"], fila["foto"]
        p.evaluacion_fr14_id = foto["evaluacion"]["id"] if foto["evaluacion"] else None
        p.estado_documental = foto
        p.full_clean()
        guardar_con_bitacora(p, ["evaluacion_fr14", "estado_documental"], accion_crear="elegibles.documentacion_conservada",
                            accion_modificar="elegibles.documentacion_conservada", actor=actor, motivo=motivo)
    lista.documental_reglas, lista.documental_referencia = control["reglas"], control["referencia"]
    lista.documental_fecha, lista.documental_por = timezone.now(), actor
    lista.full_clean()
    guardar_con_bitacora(lista, ["documental_reglas", "documental_referencia", "documental_fecha", "documental_por"],
                        accion_crear="elegibles.control_documental_conservado", accion_modificar="elegibles.control_documental_conservado", actor=actor, motivo=motivo)
    return lista
