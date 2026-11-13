"""Firmas por ciclo, política y contenido congelados, emisión atómica."""
from copy import deepcopy
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q, Max
from django.utils import timezone

from bitacora.servicios import registrar, guardar_con_bitacora
from compras.models import AprobacionOrden, EvidenciaEnvioOrden, ReglaAprobacionOrden, SolicitudAprobacionOrden
from compras import orden_calculo_servicios as calculo, orden_servicios
from compras.numeracion_ordenes import _bloquear_orden
from compras.operacion_archivos import transaccion, adjuntar
from parametros.catalogo import AUTOAPROBAR_ORDEN, CLIENTE_ORDEN, NIT_CLIENTE_ORDEN
from parametros.servicios import obtener
from proveedores.servicios import _exigir_admin, _exigir_motivo


def guardar_estado(orden, actor, motivo, accion):
    orden._operacion_flujo = True
    try:
        orden_servicios._revision(orden, actor, motivo, accion)
    finally:
        orden._operacion_flujo = False


def revisar_revision(orden, esperada):
    if esperada is not None and orden.revision != esperada:
        raise ValidationError("La orden cambió. Recargue antes de continuar.")


def contenido(orden):
    return {"orden_id": orden.pk, "elaborada_por_id": orden.elaborada_por_id, "fecha_elaboracion": orden.fecha_elaboracion.isoformat(),
        "fecha_vencimiento": orden.fecha_vencimiento.isoformat() if orden.fecha_vencimiento else None,
        "fecha_esperada_entrega": orden.fecha_esperada_entrega.isoformat() if orden.fecha_esperada_entrega else None,
        "condiciones_pago": orden.condiciones_pago, "origen": deepcopy(orden.origen_datos),
        "lineas": [{"id": l.pk, "referencia": l.referencia, "descripcion": l.descripcion, "especificacion": l.especificacion, "unidad": l.unidad} for l in orden.lineas.all()],
        "importes": calculo.validar_para_emitir(orden)}


def reglas_actuales(orden):
    reglas = list(ReglaAprobacionOrden.objects.filter(activo=True, monto_desde__lte=orden.total)
        .filter(Q(monto_hasta__isnull=True) | Q(monto_hasta__gt=orden.total))
        .filter(Q(categoria__isnull=True) | Q(categoria_id=orden.proveedor.categoria_id)).order_by("pk"))
    propia = obtener(AUTOAPROBAR_ORDEN)
    if type(propia) is not bool:
        raise ValidationError("Configure Sí/No para aprobar la propia orden.")
    return {"aprobaciones": max([1, *[r.aprobaciones for r in reglas]]), "permitir_propia": propia,
        "monto_base": str(orden.total), "categoria_id": orden.proveedor.categoria_id,
        "coincidencias": [{"id": r.pk, "nombre": r.nombre, "desde": str(r.monto_desde), "hasta": str(r.monto_hasta) if r.monto_hasta is not None else None,
            "categoria_id": r.categoria_id, "aprobaciones": r.aprobaciones} for r in reglas]}


@transaction.atomic
def guardar_regla(regla, *, actor, motivo):
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    regla.full_clean()
    guardar_con_bitacora(regla, ["nombre", "monto_desde", "monto_hasta", "categoria", "aprobaciones", "activo"],
        accion_crear="orden.regla_aprobacion_creada", accion_modificar="orden.regla_aprobacion_modificada", actor=actor, motivo=motivo)
    return regla


@transaction.atomic
def solicitar(orden, *, actor, motivo, revision_esperada=None):
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    orden = _bloquear_orden(orden)
    revisar_revision(orden, revision_esperada)
    if orden.estado != "borrador" or orden.decision.estado != "aprobada" or orden.cotizacion.estado != "decidida":
        raise ValidationError("Solo se solicita aprobación de un borrador con origen aprobado vigente.")
    cliente = {"nombre": obtener(CLIENTE_ORDEN), "nit": obtener(NIT_CLIENTE_ORDEN)}
    if any(v.strip().upper() == "POR CONFIGURAR" or not v.strip() for v in cliente.values()):
        raise ValidationError("Configure nombre y NIT de la clínica en Parámetros antes de solicitar aprobación.")
    orden.ciclo_aprobacion += 1
    solicitud = SolicitudAprobacionOrden(orden=orden, ciclo=orden.ciclo_aprobacion, revision_borrador=orden.revision,
        reglas=reglas_actuales(orden), contenido=contenido(orden), cliente={**cliente, "elaborada_por": str(orden.elaborada_por), "area": str(orden.cotizacion.area)},
        solicitada_por=actor, motivo=motivo.strip())
    solicitud.full_clean()
    solicitud.save()
    orden.estado = "en_aprobacion"
    guardar_estado(orden, actor, motivo, "orden.aprobacion_solicitada")
    return orden


def solicitud_actual(orden):
    try:
        return orden.solicitudes_aprobacion.get(ciclo=orden.ciclo_aprobacion)
    except SolicitudAprobacionOrden.DoesNotExist:
        raise ValidationError("La orden no tiene solicitud de aprobación vigente.") from None


def validar_aprobaciones(orden):
    solicitud = solicitud_actual(orden)
    firmas = list(solicitud.firmas.all())
    if contenido(orden) != solicitud.contenido:
        raise ValidationError("La orden no coincide con lo solicitado. Rechace y solicite nuevamente después de corregir.")
    if any(f.decision != "aprueba" or f.orden_id != orden.pk or (f.usuario_id == orden.elaborada_por_id and not solicitud.reglas["permitir_propia"]) for f in firmas):
        raise ValidationError("La orden contiene un rechazo o una firma no permitida.")
    if len({f.usuario_id for f in firmas}) < solicitud.reglas["aprobaciones"]:
        raise ValidationError("Faltan aprobaciones distintas para emitir la orden.")
    return solicitud


@transaction.atomic
def votar(orden, *, decision, actor, motivo, revision_esperada=None):
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    orden = _bloquear_orden(orden)
    revisar_revision(orden, revision_esperada)
    if orden.estado != "en_aprobacion" or orden.decision.estado != "aprobada" or orden.cotizacion.estado != "decidida":
        raise ValidationError("Solo se responde una solicitud vigente de orden En aprobación.")
    solicitud = solicitud_actual(orden)
    if decision not in ("aprueba", "rechaza"):
        raise ValidationError("Indique Aprueba o Rechaza.")
    if actor.pk == orden.elaborada_por_id and not solicitud.reglas["permitir_propia"]:
        raise ValidationError("Debe responder un administrador distinto de quien elaboró la orden.")
    if solicitud.firmas.filter(usuario=actor).exists():
        raise ValidationError("Usted ya respondió esta solicitud.")
    if decision == "aprueba" and contenido(orden) != solicitud.contenido:
        raise ValidationError("El contenido cambió desde la solicitud. Rechace para volver al borrador.")
    firma = AprobacionOrden(solicitud=solicitud, orden=orden, usuario=actor, usuario_texto=str(actor), decision=decision, comentario=motivo.strip())
    firma.full_clean()
    firma.save()
    registrar("orden.aprobacion_registrada", actor=actor, objeto=firma, nuevo={"orden_id": orden.pk, "ciclo": solicitud.ciclo, "decision": decision}, motivo=motivo)
    if decision == "rechaza":
        orden.estado = "borrador"
        guardar_estado(orden, actor, motivo, "orden.devuelta_a_borrador")
    elif solicitud.firmas.filter(decision="aprueba").count() >= solicitud.reglas["aprobaciones"]:
        from compras.numeracion_ordenes import numerar_al_emitir
        orden = numerar_al_emitir(orden, actor=actor, motivo=motivo)
    else:
        guardar_estado(orden, actor, motivo, "orden.aprobacion_parcial")
    return orden


def documento(orden, solicitud):
    return {"cliente": deepcopy(solicitud.cliente), "orden": orden_servicios.foto(orden),
        "cotizacion": orden.origen_datos["trazabilidad"]["consecutivo"], "reglas_importes_texto": calculo.describir_reglas(orden.reglas_importes),
        "solicitud_id": solicitud.pk, "reglas_aprobacion": deepcopy(solicitud.reglas),
        "firmas": [{"usuario_id": f.usuario_id, "usuario": f.usuario_texto, "fecha": f.fecha.isoformat(), "decision": f.decision, "comentario": f.comentario} for f in solicitud.firmas.all()]}


def registrar_envio(orden, *, fecha_envio, actor, motivo, archivo=None, corrige_id=None):
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    with transaccion(archivo) as rutas:
        orden = _bloquear_orden(orden)
        if orden.numero is None or orden.estado not in ("emitida", "recibida_parcial", "recibida_total", "cerrada"):
            raise ValidationError("Solo se registra envío de una orden emitida vigente.")
        if fecha_envio > timezone.now() or fecha_envio < orden.fecha_emision:
            raise ValidationError("El envío no puede preceder a la emisión ni estar en el futuro.")
        registro = EvidenciaEnvioOrden(orden=orden, fecha_envio=fecha_envio, registrado_por=actor, observacion=motivo.strip(), corrige_id=corrige_id)
        adjuntar(registro, archivo, rutas, "envios_ordenes")
        registro.full_clean()
        registro.save()
        registrar("orden.envio_registrado", actor=actor, objeto=registro, nuevo={"orden_id": orden.pk, "fecha_envio": fecha_envio.isoformat(), "corrige_id": corrige_id, "nombre_archivo": registro.nombre_archivo}, motivo=motivo)
    return registro
