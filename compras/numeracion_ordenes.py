"""Numeración transaccional al emitir; el flujo de autorización se integra en B18."""
from copy import deepcopy

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from bitacora.servicios import guardar_con_bitacora
from compras.models import ContadorOrdenCompra, Cotizacion, OrdenCompra
from compras.orden_servicios import _revision, etiqueta_validez
from parametros.catalogo import ANIO_ORDEN, ETIQUETA_VALIDEZ_ORDEN, LONGITUD_ORDEN, PREFIJO_ORDEN, REINICIO_ORDEN, validar_longitud_orden, validar_prefijo_orden
from parametros.models import Parametro
from parametros.servicios import obtener
from proveedores.servicios import _exigir_admin, _exigir_motivo


def reglas_actuales():
    reglas = {"prefijo": validar_prefijo_orden(obtener(PREFIJO_ORDEN)), "incluir_anio": obtener(ANIO_ORDEN),
        "longitud": validar_longitud_orden(obtener(LONGITUD_ORDEN)), "reinicio_anual": obtener(REINICIO_ORDEN)}
    if type(reglas["incluir_anio"]) is not bool or type(reglas["reinicio_anual"]) is not bool:
        raise ValidationError("Configure Sí/No para año y reinicio anual del consecutivo.")
    if reglas["reinicio_anual"] and not reglas["incluir_anio"]:
        raise ValidationError("El reinicio anual requiere incluir el año en el consecutivo.")
    return reglas


def formatear(numero, anio, reglas):
    partes = [reglas["prefijo"]]
    if reglas["incluir_anio"]:
        partes.append(str(anio))
    partes.append(str(numero).zfill(reglas["longitud"]))
    return "-".join(partes)


def _bloquear_orden(orden):
    cotizacion_id = OrdenCompra.objects.values_list("cotizacion_id", flat=True).get(pk=orden.pk)
    Cotizacion.objects.select_for_update().get(pk=cotizacion_id)
    return OrdenCompra.objects.select_for_update().select_related("decision", "cotizacion").get(pk=orden.pk)


@transaction.atomic
def numerar_al_emitir(orden, *, actor, motivo, revision_esperada=None):
    """Gancho B16: B18 debe verificar sus aprobaciones antes de invocarlo en la misma transacción."""
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    orden = _bloquear_orden(orden)
    if orden.estado != "en_aprobacion" or orden.numero is not None:
        raise ValidationError("Solo se numera una orden En aprobación, sin número previo, al emitir.")
    if orden.decision.estado != "aprobada" or orden.cotizacion.estado != "decidida":
        raise ValidationError("La decisión y cotización de origen ya no autorizan emisión.")
    if revision_esperada is not None and revision_esperada != orden.revision:
        raise ValidationError("La orden cambió. Revise su revisión antes de emitir.")
    from compras.aprobacion_orden_servicios import validar_aprobaciones, documento
    solicitud = validar_aprobaciones(orden)
    from compras.orden_calculo_servicios import validar_para_emitir
    orden.calculo_emision = validar_para_emitir(orden)
    list(Parametro.objects.select_for_update().filter(clave__in=[PREFIJO_ORDEN, ANIO_ORDEN, LONGITUD_ORDEN, REINICIO_ORDEN, ETIQUETA_VALIDEZ_ORDEN]).order_by("pk"))
    reglas = reglas_actuales()
    instante = timezone.now()
    anio = timezone.localdate(instante).year
    clave = f"anio:{anio}" if reglas["reinicio_anual"] else "global"
    ContadorOrdenCompra.objects.get_or_create(clave=clave, defaults={"ultimo": 0})
    contador = ContadorOrdenCompra.objects.select_for_update().get(pk=clave)
    usadas = OrdenCompra.objects.filter(numero__isnull=False)
    if reglas["reinicio_anual"]:
        usadas = usadas.filter(anio_consecutivo=anio)
    maximo = usadas.aggregate(maximo=Max("numero"))["maximo"] or 0
    siguiente = max(contador.ultimo, maximo) + 1
    # Conserva unicidad incluso ante cambios de prefijo, ancho o modo de reinicio.
    while OrdenCompra.objects.filter(consecutivo=formatear(siguiente, anio, reglas)).exists():
        siguiente += 1
    contador.ultimo = siguiente
    contador.full_clean()
    guardar_con_bitacora(contador, ["ultimo"], accion_crear="orden.contador_creado", accion_modificar="orden.contador_avanzado", actor=actor, motivo=motivo)
    orden.numero, orden.consecutivo = siguiente, formatear(siguiente, anio, reglas)
    orden.anio_consecutivo, orden.serie_consecutivo = anio, clave
    orden.reglas_consecutivo = deepcopy(reglas)
    orden.fecha_emision, orden.emitida_por = instante, actor
    orden.etiqueta_vencimiento = etiqueta_validez()
    orden.estado = "emitida"
    orden.documento_emision = documento(orden, solicitud)
    orden.documento_emision["orden"]["revision"] = orden.revision + 1
    orden.full_clean()
    orden._numeracion_autorizada = True
    try:
        _revision(orden, actor, motivo, "orden.emitida_numerada")
    finally:
        orden._numeracion_autorizada = False
    from seguimientos.servicios import crear_al_emitir
    crear_al_emitir(orden, actor, motivo)
    return orden


@transaction.atomic
def anular_orden(orden, *, actor, motivo, revision_esperada=None):
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    orden = _bloquear_orden(orden)
    if orden.estado not in ("borrador", "en_aprobacion", "emitida"):
        raise ValidationError("Solo se anulan órdenes en borrador, en aprobación o emitidas sin recepción.")
    if revision_esperada is not None and revision_esperada != orden.revision:
        raise ValidationError("La orden cambió. Recargue antes de anular.")
    orden.estado, orden.anulada_por = "anulada", actor
    orden.fecha_anulacion, orden.motivo_anulacion = timezone.now(), motivo.strip()
    orden.full_clean()
    _revision(orden, actor, motivo, "orden.anulada")
    return orden
