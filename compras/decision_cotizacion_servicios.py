"""Propuesta, aprobaciones distintas y anulación auditada de la decisión B13."""
from copy import deepcopy
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from bitacora.servicios import registrar
from compras import comparativo, proveedor_unico_servicios
from compras.models import AdjudicacionCotizacion, AprobacionCotizacion, Cotizacion, DecisionCotizacion, TipoVerificacion
from config.utilidades import normalizar_espacios
from parametros.catalogo import APROBACIONES_COTIZACION, CONTROL_VERIFICACIONES, MODALIDAD_ADJUDICACION, ROLES_DECISION_COTIZACION, lista_de_roles
from parametros.models import Parametro
from parametros.servicios import obtener
from proveedores.servicios import _exigir_admin, _exigir_motivo


def reglas_actuales():
    reglas = {"aprobaciones": obtener(APROBACIONES_COTIZACION), "roles": lista_de_roles(obtener(ROLES_DECISION_COTIZACION)),
        "control_verificaciones": obtener(CONTROL_VERIFICACIONES)}
    if type(reglas["aprobaciones"]) is not int or reglas["aprobaciones"] < 1 or not reglas["roles"] or any(r not in ("administrador", "desarrollador") for r in reglas["roles"]) or reglas["control_verificaciones"] not in ("advertir", "bloquear"):
        raise ValidationError("Revise los parámetros de aprobación y control de verificaciones de cotización.")
    return reglas


def modalidad_inicial():
    valor = obtener(MODALIDAD_ADJUDICACION)
    if valor not in ("completa", "lineas"):
        raise ValidationError("Configure modalidad completa o lineas.")
    return valor


def _contexto(cotizacion, actor):
    # Los servicios de ofertas/verificaciones toman primero el mismo bloqueo de cotización.
    list(TipoVerificacion.objects.select_for_update().order_by("pk"))
    datos = comparativo.construir(cotizacion, actor=actor)
    unico = proveedor_unico_servicios.validar_para_decidir(cotizacion, actor=actor)
    return datos, unico, comparativo.huella({"comparativo": datos, "unico": unico})


def _seleccion(datos, modalidad, oferta_id, selecciones):
    if modalidad not in ("completa", "lineas"):
        raise ValidationError("Seleccione oferta completa o adjudicación por línea.")
    ofertas = {o["id"]: o for o in datos["ofertas"]}
    if not datos["filas"] or not ofertas:
        raise ValidationError("La cotización debe tener especificaciones y ofertas completas.")
    if modalidad == "completa":
        if type(oferta_id) is not int or oferta_id not in ofertas or selecciones:
            raise ValidationError("Seleccione una oferta de esta cotización sin mezclar adjudicaciones por línea.")
        seleccionadas = {f["id"]: oferta_id for f in datos["filas"]}
    else:
        if oferta_id is not None or not isinstance(selecciones, (list, tuple)):
            raise ValidationError("En modalidad por línea seleccione un oferente para cada especificación.")
        seleccionadas = {}
        for dato in selecciones:
            if not isinstance(dato, dict) or type(dato.get("linea_id")) is not int or type(dato.get("oferta_id")) is not int or dato["linea_id"] in seleccionadas:
                raise ValidationError("No repita líneas y use selecciones válidas.")
            seleccionadas[dato["linea_id"]] = dato["oferta_id"]
        if set(seleccionadas) != {f["id"] for f in datos["filas"]} or any(o not in ofertas for o in seleccionadas.values()):
            raise ValidationError("Adjudique todas las líneas, una vez, a oferentes de esta cotización.")
    resultado, total = [], Decimal(0)
    for fila in datos["filas"]:
        celda = next(c for c in fila["celdas"] if c["oferta_id"] == seleccionadas[fila["id"]])
        if not celda["oferta_linea_id"]:
            raise ValidationError("La oferta seleccionada no tiene precio para una especificación.")
        oferente = ofertas[celda["oferta_id"]]
        resultado.append({"linea_id": fila["id"], "descripcion": fila["descripcion"], "nit": oferente["nit"], "razon_social": oferente["razon_social"], **deepcopy(celda)})
        total += Decimal(celda["total"])
    mas_costosa = total > Decimal(datos["minimo_total"]) if modalidad == "completa" else any(not c["menor"] for c in resultado)
    return resultado, total, mas_costosa


def _validar_alertas(datos, seleccion, reglas, justificacion):
    ids = {s["oferta_id"] for s in seleccion}
    alertas = [o for o in datos["ofertas"] if o["id"] in ids and o["alertas"]]
    if alertas and reglas["control_verificaciones"] == "bloquear":
        raise ValidationError("Hay verificaciones obligatorias en No, Pendiente o sin reconfirmar de oferentes seleccionados.")
    if alertas and not normalizar_espacios(justificacion):
        raise ValidationError({"justificacion_verificaciones": "Justifique las alertas de verificaciones de los oferentes seleccionados."})


@transaction.atomic
def proponer_decision(cotizacion, *, modalidad, recomendacion, motivo_eleccion="", justificacion_verificaciones="",
                     oferta_id=None, selecciones=None, huella_esperada=None, actor, motivo):
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    cotizacion = Cotizacion.objects.select_for_update().get(pk=cotizacion.pk)
    if cotizacion.estado not in ("borrador", "en_comparacion") or cotizacion.decisiones.exclude(estado="anulada").exists():
        raise ValidationError("Anule la decisión vigente antes de registrar otra propuesta.")
    list(Parametro.objects.select_for_update().filter(clave__in=[APROBACIONES_COTIZACION, ROLES_DECISION_COTIZACION, CONTROL_VERIFICACIONES]).order_by("pk"))
    reglas = reglas_actuales()
    datos, unico, huella = _contexto(cotizacion, actor)
    # La pantalla firma la comparación mostrada; B12 se confirma en su propio formulario.
    if huella_esperada is not None and huella_esperada != comparativo.huella(datos):
        raise ValidationError("El comparativo cambió. Revise ofertas, verificaciones y proveedor único antes de proponer.")
    seleccion, total, mas_costosa = _seleccion(datos, modalidad, oferta_id, selecciones)
    if not normalizar_espacios(recomendacion):
        raise ValidationError({"recomendacion": "Registre la recomendación de compra."})
    if mas_costosa and not normalizar_espacios(motivo_eleccion):
        raise ValidationError({"motivo_eleccion": "Justifique la elección de un costo mayor al menor total con impuestos."})
    _validar_alertas(datos, seleccion, reglas, justificacion_verificaciones)
    contenido = {"comparativo": datos, "proveedor_unico": unico, "seleccion": seleccion, "total_adjudicado": str(total), "mas_costosa": mas_costosa}
    decision = DecisionCotizacion(cotizacion=cotizacion, modalidad=modalidad, recomendacion=recomendacion.strip(),
        motivo_eleccion=motivo_eleccion.strip(), justificacion_verificaciones=justificacion_verificaciones.strip(),
        reglas=reglas, contenido=contenido, huella=huella, propuesta_por=actor)
    decision.full_clean()
    decision.save()
    for seleccionada in seleccion:
        adjudicacion = AdjudicacionCotizacion(decision=decision, linea_id=seleccionada["linea_id"], oferta_id=seleccionada["oferta_id"], oferta_linea_id=seleccionada["oferta_linea_id"])
        adjudicacion.full_clean()
        adjudicacion.save()
    cotizacion.estado = "en_comparacion"
    cotizacion.save(update_fields=["estado"])
    registrar("cotizacion.decision_propuesta", actor=actor, objeto=decision, nuevo={"modalidad": modalidad, "reglas": reglas, "contenido": contenido,
        "recomendacion": decision.recomendacion, "motivo_eleccion": decision.motivo_eleccion, "justificacion_verificaciones": decision.justificacion_verificaciones}, motivo=motivo)
    return decision


@transaction.atomic
def aprobar_decision(decision, *, actor, motivo):
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    cotizacion_id = DecisionCotizacion.objects.values_list("cotizacion_id", flat=True).get(pk=decision.pk)
    cotizacion = Cotizacion.objects.select_for_update().get(pk=cotizacion_id)
    decision = DecisionCotizacion.objects.select_for_update().get(pk=decision.pk)
    if decision.estado != "pendiente" or cotizacion.estado != "en_comparacion":
        raise ValidationError("Esta decisión ya no admite aprobaciones.")
    if actor.rol not in decision.reglas["roles"]:
        raise PermissionDenied("Su rol no está habilitado en la regla de esta propuesta.")
    if decision.aprobaciones.filter(actor=actor).exists():
        raise ValidationError("Cada usuario puede aprobar una sola vez esta decisión.")
    datos, unico, huella = _contexto(cotizacion, actor)
    if huella != decision.huella:
        raise ValidationError("Cambió la comparación o el caso de proveedor único. Anule la propuesta y registre una nueva para revisar las aprobaciones.")
    _validar_alertas(datos, decision.contenido["seleccion"], decision.reglas, decision.justificacion_verificaciones)
    from compras.contrato_servicios import validar_para_aprobar
    contrato_datos = validar_para_aprobar(decision, actor=actor)
    primera = decision.aprobaciones.first()
    if primera and primera.contrato_datos and primera.contrato_datos != contrato_datos:
        raise ValidationError("Cambió el contrato o su obligatoriedad desde la primera firma. Anule la propuesta y registre otra.")
    aprobacion = AprobacionCotizacion(decision=decision, actor=actor, motivo=motivo.strip(), contrato_datos=contrato_datos)
    aprobacion.full_clean()
    aprobacion.save()
    registrar("cotizacion.decision_aprobada", actor=actor, objeto=aprobacion, nuevo={"decision": decision.pk, "fecha": aprobacion.fecha}, motivo=motivo)
    if decision.aprobaciones.count() >= decision.reglas["aprobaciones"]:
        decision.estado = "aprobada"
        decision.decidido_por, decision.fecha_decision = actor, aprobacion.fecha
        decision.save(update_fields=["estado", "decidido_por", "fecha_decision"])
        cotizacion.estado = "decidida"
        cotizacion.save(update_fields=["estado"])
        registrar("cotizacion.decidida", actor=actor, objeto=cotizacion, nuevo={"decision": decision.pk, "fecha": decision.fecha_decision}, motivo=motivo)
    return decision


@transaction.atomic
def anular_decision(decision, *, actor, motivo):
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    cotizacion_id = DecisionCotizacion.objects.values_list("cotizacion_id", flat=True).get(pk=decision.pk)
    cotizacion = Cotizacion.objects.select_for_update().get(pk=cotizacion_id)
    decision = DecisionCotizacion.objects.select_for_update().get(pk=decision.pk)
    if decision.estado == "anulada" or cotizacion.estado == "anulada":
        raise ValidationError("La decisión o cotización ya está anulada.")
    from compras.orden_servicios import anular_borradores_de_decision
    anular_borradores_de_decision(decision, actor=actor, motivo=motivo)
    decision.estado, decision.anulada_por = "anulada", actor
    decision.fecha_anulacion, decision.motivo_anulacion = timezone.now(), motivo.strip()
    decision.save(update_fields=["estado", "anulada_por", "fecha_anulacion", "motivo_anulacion"])
    cotizacion.estado = "en_comparacion"
    cotizacion.save(update_fields=["estado"])
    registrar("cotizacion.decision_anulada", actor=actor, objeto=decision, nuevo={"fecha": decision.fecha_anulacion}, motivo=motivo)
    return decision
