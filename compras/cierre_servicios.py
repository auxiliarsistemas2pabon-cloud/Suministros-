"""Transiciones de elegibles y archivo completo de cada cierre."""
from copy import deepcopy

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from bitacora.servicios import guardar_con_bitacora, registrar
from compras import decision_servicios, documental_servicios
from compras.cotizacion_origen import hay_cotizacion
from compras.models import CierreListaElegibles, ListaElegibles, Necesidad
from parametros.catalogo import CONTROL_DOCUMENTAL_ELEGIBLES, MESES_EVALUACION_ELEGIBLES
from parametros.models import Parametro
from proveedores.servicios import _exigir_admin, _exigir_motivo

CAMPOS_ESTADO = ["estado", "cerrada_por", "fecha_cierre", "resultado_cierre", "reabierta_por", "fecha_reapertura", "anulada_por", "fecha_anulacion", "motivo_anulacion"]
CAMPOS_DOCUMENTALES = ["justificacion_documental", "documental_reglas", "documental_referencia", "documental_fecha", "documental_por"]


def _bloquear(lista):
    necesidad_id = ListaElegibles.objects.values_list("necesidad_id", flat=True).get(pk=lista.pk)
    Necesidad.objects.select_for_update().get(pk=necesidad_id)
    return ListaElegibles.objects.select_for_update().get(pk=lista.pk)


def _foto_resultado(lista, resultado, decision):
    necesidad = lista.necesidad
    filas = []
    for fila in resultado["filas"]:
        p, desempate = fila["participante"], fila["desempate"]
        filas.append({"participante_id": p.pk, "proveedor_id": p.proveedor_id, "nit": p.nit, "razon_social": p.razon_social,
            "cantidad_autorizada": str(p.cantidad_autorizada), "elegido": p.cantidad_autorizada > 0,
            "observacion": p.observacion, "justificacion_eleccion": p.justificacion_eleccion,
            "decision_por_id": p.decision_por_id, "decision_por": str(p.decision_por) if p.decision_por_id else "",
            "decision_fecha": p.decision_fecha.isoformat() if p.decision_fecha else None,
            "total": str(fila["total"]), "parcial": str(fila["parcial"]), "maximo": str(fila["maximo"]),
            "completo": fila["completo"], "puesto": fila["puesto"], "puesto_calculado": fila["puesto_calculado"], "empate": fila["empate"],
            "desempate": {"pk": desempate.pk, "orden": desempate.orden, "justificacion": desempate.justificacion,
                          "registrado_por": str(desempate.registrado_por), "fecha": desempate.fecha.isoformat()} if desempate else None,
            "celdas": [{"id": c["id"], "nombre": c["nombre"], "orden": c["orden"], "peso": str(c["peso"]),
                         "cumplimiento": str(c["cumplimiento"]) if c["cumplimiento"] is not None else None,
                         "subtotal": str(c["subtotal"]) if c["subtotal"] is not None else None, "observacion": c["observacion"]} for c in fila["celdas"]]})
    registro = decision["registro"]
    return {"version": lista.version_criterios_id, "numero_version": lista.version_criterios.numero, "reglas": deepcopy(lista.reglas_calculo),
            "criterios": [{"id": c["id"], "nombre": c["nombre"], "orden": c["orden"], "peso": str(c["peso"])} for c in resultado["criterios"]],
            "base": {**resultado["base"], "cantidad": str(resultado["base"]["cantidad"])}, "filas": filas,
            "necesidad": {"id": necesidad.pk, "objeto": necesidad.objeto, "area_id": necesidad.area_id, "area": str(necesidad.area), "fecha": necesidad.fecha.isoformat()},
            "origenes": [{"linea_origen_id": o.linea_id, "cantidad": str(o.cantidad), **deepcopy(o.datos_origen)} for o in necesidad.origenes.all()],
            "decision": {"justificacion_unico": registro.justificacion_unico, "justificacion_cantidad": registro.justificacion_cantidad,
                         "registrada_por": str(registro.registrada_por), "fecha": registro.fecha.isoformat()}}


@transaction.atomic
def cerrar_lista(lista, *, actor, motivo, justificacion_documental=None):
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    lista = _bloquear(lista)
    if lista.estado != "borrador":
        raise ValidationError("Solo se cierra una lista en borrador.")
    if hay_cotizacion(lista):
        raise ValidationError("La lista ya tiene una cotización asociada.")
    resultado = decision_servicios.validar_para_cierre(lista)
    decision = decision_servicios.estado_decision(lista, resultado)
    instante = timezone.now()
    referencia = timezone.localdate(instante)
    list(Parametro.objects.select_for_update().filter(clave__in=[CONTROL_DOCUMENTAL_ELEGIBLES, MESES_EVALUACION_ELEGIBLES]).order_by("pk"))
    lista = documental_servicios.guardar_justificacion(lista, justificacion=lista.justificacion_documental if justificacion_documental is None else justificacion_documental,
        actor=actor, motivo=motivo, referencia=referencia)
    foto = _foto_resultado(lista, resultado, decision)
    lista.estado, lista.cerrada_por, lista.fecha_cierre = "cerrada", actor, instante
    lista.resultado_cierre = foto
    lista.full_clean()
    guardar_con_bitacora(lista, CAMPOS_ESTADO, accion_crear="elegibles.lista_cerrada", accion_modificar="elegibles.lista_cerrada", actor=actor, motivo=motivo)
    lista = documental_servicios.conservar_al_cerrar(lista, actor=actor, motivo=motivo, referencia=referencia)
    control = documental_servicios.obtener_control(lista)
    contenido = {"resultado": foto, "documental": {"reglas": control["reglas"], "referencia": referencia.isoformat(),
        "justificacion": control["justificacion"], "filas": [{"participante_id": f["participante"].pk, "razon_social": f["participante"].razon_social, "nit": f["participante"].nit, "foto": f["foto"]} for f in control["filas"]]}}
    cierre = CierreListaElegibles(lista=lista, actor=actor, fecha=instante, motivo=motivo.strip(), contenido=contenido)
    cierre.full_clean()
    cierre.save()
    registrar("elegibles.cierre_archivado", actor=actor, objeto=cierre, nuevo=contenido, motivo=motivo)
    return lista


@transaction.atomic
def reabrir_lista(lista, *, actor, motivo):
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    lista = _bloquear(lista)
    if lista.estado != "cerrada":
        raise ValidationError("Solo se reabre una lista cerrada.")
    if hay_cotizacion(lista):
        raise ValidationError("No se reabre una lista que ya tiene cotización asociada.")
    # El archivo inmutable conserva los ciclos anteriores; se limpia la foto activa.
    for p in lista.participantes.all():
        if p.evaluacion_fr14_id is not None or p.estado_documental:
            p.evaluacion_fr14, p.estado_documental = None, {}
            guardar_con_bitacora(p, ["evaluacion_fr14", "estado_documental"], accion_crear="elegibles.foto_liberada", accion_modificar="elegibles.foto_liberada", actor=actor, motivo=motivo)
    lista.estado, lista.reabierta_por, lista.fecha_reapertura = "borrador", actor, timezone.now()
    lista.cerrada_por, lista.fecha_cierre, lista.resultado_cierre = None, None, {}
    lista.justificacion_documental, lista.documental_reglas = "", {}
    lista.documental_referencia, lista.documental_fecha, lista.documental_por = None, None, None
    lista.full_clean()
    guardar_con_bitacora(lista, CAMPOS_ESTADO + CAMPOS_DOCUMENTALES, accion_crear="elegibles.lista_reabierta", accion_modificar="elegibles.lista_reabierta", actor=actor, motivo=motivo)
    decision_servicios.invalidar_decisiones(lista, actor=actor, motivo=motivo, desempates=False)
    return lista


@transaction.atomic
def anular_lista(lista, *, actor, motivo):
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    lista = _bloquear(lista)
    if lista.estado == "anulada":
        raise ValidationError("La lista ya está anulada.")
    if hay_cotizacion(lista):
        raise ValidationError("La lista tiene cotización asociada; conserve su referencia de origen.")
    lista.estado, lista.anulada_por, lista.fecha_anulacion = "anulada", actor, timezone.now()
    lista.motivo_anulacion = motivo.strip()
    lista.full_clean()
    guardar_con_bitacora(lista, CAMPOS_ESTADO, accion_crear="elegibles.lista_anulada", accion_modificar="elegibles.lista_anulada", actor=actor, motivo=motivo)
    return lista
