"""Borradores de orden desde fotos aprobadas, con copia e historial independientes."""
from copy import deepcopy
from decimal import Decimal, localcontext
import json

from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.utils import timezone

from bitacora.servicios import registrar
from compras.importes import decimal_valido
from compras.models import Cotizacion, DecisionCotizacion, OrdenCompra, OrdenLinea, RevisionOferta, RevisionOrdenCompra
from compras.models import TarifaImpuesto
from compras import orden_calculo_servicios as calculo
from config.utilidades import normalizar_espacios
from parametros.catalogo import ETIQUETA_VALIDEZ_ORDEN, validar_etiqueta_validez
from parametros.servicios import obtener
from proveedores.servicios import _exigir_admin, _exigir_motivo

CAMPOS_LINEA = ["referencia", "descripcion", "especificacion", "unidad", "cantidad", "precio_unitario", "tarifa_nombre", "porcentaje", "descuento", "subtotal", "impuesto", "total"]
_SIN_CAMBIO = object()


def etiqueta_validez(orden=None):
    if orden and orden.numero is not None and orden.etiqueta_vencimiento:
        return orden.etiqueta_vencimiento
    return validar_etiqueta_validez(obtener(ETIQUETA_VALIDEZ_ORDEN))


def _json(datos):
    return json.loads(json.dumps(datos, cls=DjangoJSONEncoder))


def _datos_linea(linea):
    datos = {}
    for campo in CAMPOS_LINEA:
        valor = getattr(linea, campo)
        if isinstance(valor, Decimal):
            with localcontext() as contexto:
                contexto.prec = 50
                valor = format(valor.normalize(), "f")
        datos[campo] = valor
    return datos


def foto(orden):
    return _json({"id": orden.pk, "decision_id": orden.decision_id, "cotizacion_id": orden.cotizacion_id,
        "proveedor_id": orden.proveedor_id, "nit": orden.nit, "razon_social": orden.razon_social,
        "condiciones_pago": orden.condiciones_pago, "fecha_elaboracion": orden.fecha_elaboracion,
        "numero": orden.numero, "consecutivo": orden.consecutivo, "anio_consecutivo": orden.anio_consecutivo,
        "serie_consecutivo": orden.serie_consecutivo, "reglas_consecutivo": deepcopy(orden.reglas_consecutivo),
        "fecha_emision": orden.fecha_emision, "emitida_por": str(orden.emitida_por) if orden.emitida_por_id else "",
        "fecha_vencimiento": orden.fecha_vencimiento, "fecha_esperada_entrega": orden.fecha_esperada_entrega, "etiqueta_vencimiento": etiqueta_validez(orden),
        "anulada_por": str(orden.anulada_por) if orden.anulada_por_id else "", "fecha_anulacion": orden.fecha_anulacion,
        "motivo_anulacion": orden.motivo_anulacion,
        "estado": orden.estado, "subtotal": orden.subtotal, "descuento": orden.descuento, "impuesto": orden.impuesto,
        "total": orden.total, "revision": orden.revision, "base": orden.base, "total_sin_retenciones": orden.total_sin_retenciones,
        "retencion": orden.retencion, "retenciones_aplicadas": deepcopy(orden.retenciones_aplicadas),
        "reglas_importes": deepcopy(orden.reglas_importes), "calculo_emision": deepcopy(orden.calculo_emision),
        "lineas": [{"id": l.pk, "posicion": l.posicion, "oferta_linea_id": l.oferta_linea_id, **_datos_linea(l),
            "base": l.base, "base_impuesto": l.base_impuesto, "descuento_aplicado": l.descuento_aplicado,
            "reglas_calculo": deepcopy(l.reglas_calculo),
            "original": deepcopy(l.original), "modificada": l.modificada, "cambios": deepcopy(l.cambios)} for l in orden.lineas.order_by("posicion")]})


def _revision(orden, actor, motivo, accion):
    orden.revision += 1
    orden.save()
    datos = foto(orden)
    revision = RevisionOrdenCompra(orden=orden, numero=orden.revision, contenido=datos, actor=actor, motivo=motivo.strip())
    revision.full_clean()
    revision.save()
    registrar(accion, actor=actor, objeto=orden, nuevo=datos, motivo=motivo)


def _bloquear_decision(decision):
    cotizacion_id = DecisionCotizacion.objects.values_list("cotizacion_id", flat=True).get(pk=decision.pk)
    cotizacion = Cotizacion.objects.select_for_update().get(pk=cotizacion_id)
    decision = DecisionCotizacion.objects.select_for_update().get(pk=decision.pk)
    requeridas = decision.reglas.get("aprobaciones", 0)
    if decision.estado != "aprobada" or cotizacion.estado != "decidida" or not decision.decidido_por_id or not decision.fecha_decision or type(requeridas) is not int or requeridas < 1 or decision.aprobaciones.count() < requeridas:
        raise ValidationError("Solo se crean órdenes desde una decisión aprobada con sus firmas y una cotización decidida.")
    return decision, cotizacion


def _trazabilidad(cotizacion, proveedor_id, oferta):
    evaluacion_id = None
    if cotizacion.cierre_origen_id:
        filas = cotizacion.cierre_origen.contenido.get("documental", {}).get("filas", [])
        resultado = cotizacion.cierre_origen.contenido.get("resultado", {}).get("filas", [])
        participante_id = next((r["participante_id"] for r in resultado if r["proveedor_id"] == proveedor_id), None)
        registro = next((r for r in filas if r["participante_id"] == participante_id), {})
        evaluacion_id = (registro.get("foto", {}).get("evaluacion") or {}).get("id")
    if evaluacion_id is None:
        evaluacion_id = next((c.get("propuesta_confirmada", {}).get("evaluacion_id") for c in oferta.get("verificaciones", []) if c.get("propuesta_confirmada", {}).get("evaluacion_id")), None)
    return {"cotizacion_id": cotizacion.pk, "consecutivo": cotizacion.consecutivo, "necesidad_id": cotizacion.necesidad_id,
        "lista_id": cotizacion.lista_elegibles_id, "cierre_id": cotizacion.cierre_origen_id, "evaluacion_id": evaluacion_id,
        "area": str(cotizacion.area), "objeto": cotizacion.objeto}


def _fuente(decision, cotizacion):
    try:
        datos = decision.contenido["comparativo"]
        ofertas = {o["id"]: o for o in datos["ofertas"]}
        filas = {f["id"]: f for f in datos["filas"]}
        seleccion = decision.contenido["seleccion"]
        adjudicaciones = {a.linea_id: a for a in decision.adjudicaciones.select_related("oferta_linea__linea__origen__linea", "oferta")}
        if not seleccion or len(seleccion) != len(filas) or {s["linea_id"] for s in seleccion} != set(filas) or set(adjudicaciones) != set(filas):
            raise ValidationError("La selección aprobada no cubre exactamente las especificaciones.")
        contrato = deepcopy(decision.aprobaciones.order_by("fecha", "pk").last().contrato_datos)
        if datos.get("requiere_contrato") and not contrato.get("requiere_contrato"):
            raise ValidationError("Falta la foto contractual de la aprobación.")
        pago = contrato.get("contrato", {}).get("forma_pago", "")
        grupos, revisiones = {}, {}
        for s in seleccion:
            oferta, fila, a = ofertas[s["oferta_id"]], filas[s["linea_id"]], adjudicaciones[s["linea_id"]]
            if a.oferta_id != oferta["id"] or a.oferta_linea_id != s["oferta_linea_id"] or a.oferta.proveedor_id != oferta["proveedor_id"] or a.oferta.cotizacion_id != cotizacion.pk:
                raise ValidationError("La selección no coincide con las adjudicaciones de esta decisión.")
            if oferta["id"] not in revisiones:
                revisiones[oferta["id"]] = RevisionOferta.objects.get(oferta_id=oferta["id"], numero=oferta["revision"])
            revision = revisiones[oferta["id"]]
            precio = next(p for p in revision.contenido["lineas"] if p["linea_id"] == fila["id"])
            if any(decimal_valido(s[k]) != decimal_valido(precio[k]) for k in ("precio_unitario", "porcentaje", "subtotal", "impuesto", "total")) or decimal_valido(fila["cantidad"]) != decimal_valido(precio["cantidad"]):
                raise ValidationError("La foto de importes no coincide con su revisión de oferta conservada.")
            proveedor_id = oferta["proveedor_id"]
            if proveedor_id not in grupos:
                proveedor = {"id": proveedor_id, "nit": oferta["nit"], "razon_social": oferta["razon_social"],
                    **{k: revision.contenido.get(k, "") for k in ("contacto_nombre", "contacto_correo", "contacto_telefono")}}
                grupos[proveedor_id] = {"proveedor": proveedor, "trazabilidad": _trazabilidad(cotizacion, proveedor_id, oferta),
                    "contrato": contrato, "condiciones_pago": pago, "lineas": []}
            origen = a.oferta_linea.linea.origen
            grupos[proveedor_id]["lineas"].append({"oferta_linea_id": a.oferta_linea_id, "linea_cotizacion_id": fila["id"],
                "oferta_id": oferta["id"], "revision_oferta": oferta["revision"], "revision_oferta_id": revision.pk,
                "proyeccion_linea_id": origen.linea_id if origen else None, "proyeccion_id": origen.linea.proyeccion_id if origen else None,
                "posicion": fila["orden"], "referencia": "", "descripcion": fila["descripcion"], "especificacion": fila["especificacion"],
                "unidad": fila["unidad"], "cantidad": fila["cantidad"], "precio_unitario": s["precio_unitario"],
                "tarifa_nombre": s["tarifa"], "porcentaje": s["porcentaje"], "descuento": "0", "subtotal": s["subtotal"],
                "impuesto": s["impuesto"], "total": s["total"], "reglas_calculo": deepcopy(oferta["reglas_calculo"])})
        return [grupos[pk] for pk in sorted(grupos)]
    except (KeyError, TypeError, ValueError, StopIteration, RevisionOferta.DoesNotExist):
        raise ValidationError("El origen no tiene una foto aprobada completa con sus revisiones de oferta. Revise la decisión.") from None


@transaction.atomic
def preparar_ordenes(decision, *, actor):
    _exigir_admin(actor)
    decision, cotizacion = _bloquear_decision(decision)
    return _fuente(decision, cotizacion)


def _totales(orden):
    with localcontext() as contexto:
        contexto.prec = 50
        lineas = list(orden.lineas.all())
        orden.subtotal = sum((l.subtotal for l in lineas), Decimal(0))
        orden.descuento = sum((l.descuento for l in lineas), Decimal(0))
        orden.impuesto = sum((l.impuesto for l in lineas), Decimal(0))
        orden.total = sum((l.total for l in lineas), Decimal(0))


@transaction.atomic
def crear_orden_desde_decision(decision, *, fecha_elaboracion=None, condiciones_pago=None, fecha_vencimiento=None, fecha_esperada_entrega=None, actor, motivo):
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    decision, cotizacion = _bloquear_decision(decision)
    grupos = _fuente(decision, cotizacion)
    existentes = list(decision.ordenes.order_by("proveedor_id"))
    if existentes:
        if {o.proveedor_id for o in existentes} != {g["proveedor"]["id"] for g in grupos}:
            raise ValidationError("La decisión tiene un conjunto parcial de órdenes. Revise su historial antes de continuar.")
        return existentes
    ordenes = []
    for grupo in grupos:
        proveedor, traza = grupo["proveedor"], grupo["trazabilidad"]
        origen = deepcopy(grupo)
        orden = OrdenCompra(decision=decision, cotizacion=cotizacion, proveedor_id=proveedor["id"], evaluacion_origen_id=traza["evaluacion_id"],
            nit=proveedor["nit"], razon_social=proveedor["razon_social"], elaborada_por=actor,
            fecha_elaboracion=fecha_elaboracion if fecha_elaboracion is not None else timezone.localdate(),
            fecha_vencimiento=fecha_vencimiento,
            fecha_esperada_entrega=fecha_esperada_entrega,
            condiciones_pago=grupo["condiciones_pago"] if condiciones_pago is None else condiciones_pago.strip(), origen_datos=origen)
        orden.reglas_importes = calculo.reglas_origen(grupo["lineas"][0]["reglas_calculo"])
        orden.full_clean()
        orden.save()
        for posicion, datos in enumerate(sorted(grupo["lineas"], key=lambda l: l["posicion"]), 1):
            linea = OrdenLinea(orden=orden, oferta_linea_id=datos["oferta_linea_id"], proyeccion_origen_id=datos["proyeccion_linea_id"], posicion=posicion,
                **{k: deepcopy(datos[k]) for k in CAMPOS_LINEA}, reglas_calculo=deepcopy(orden.reglas_importes))
            linea.base = linea.base_impuesto = decimal_valido(datos["subtotal"])
            # Valide tipos y escalas antes de crear la foto original; no recalcule al copiar.
            linea.full_clean(exclude=["original"])
            linea.original = _datos_linea(linea)
            linea.full_clean()
            linea.save()
        _totales(orden)
        orden.base = orden.subtotal - orden.descuento
        orden.total_sin_retenciones = orden.total
        orden.full_clean()
        _revision(orden, actor, motivo, "orden.creada_desde_decision")
        ordenes.append(orden)
    return ordenes


@transaction.atomic
def guardar_borrador(orden, *, lineas, fecha_elaboracion, condiciones_pago="", fecha_vencimiento=_SIN_CAMBIO, fecha_esperada_entrega=_SIN_CAMBIO, revision_esperada=None, retenciones=None, actualizar_reglas=False, actor, motivo):
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    cotizacion_id = OrdenCompra.objects.values_list("cotizacion_id", flat=True).get(pk=orden.pk)
    Cotizacion.objects.select_for_update().get(pk=cotizacion_id)
    orden = OrdenCompra.objects.select_for_update().select_related("decision", "cotizacion").get(pk=orden.pk)
    if orden.estado != "borrador" or orden.decision.estado != "aprobada" or orden.cotizacion.estado != "decidida":
        raise ValidationError("Solo se edita una orden en borrador con decisión aprobada vigente.")
    if revision_esperada is not None and revision_esperada != orden.revision:
        raise ValidationError("La orden cambió. Recargue antes de guardar.")
    actuales = {l.pk: l for l in orden.lineas.all()}
    if not isinstance(lineas, (list, tuple)) or any(not isinstance(d, dict) or type(d.get("id")) is not int for d in lineas) or len(lineas) != len(actuales) or {d["id"] for d in lineas} != set(actuales):
        raise ValidationError("Edite todas las líneas propias una vez, sin agregar, omitir o mezclar otras órdenes.")
    if any(set(d) - {"id", "referencia", "descripcion", "especificacion", "unidad", "cantidad", "precio_unitario", "descuento", "tarifa_id"} for d in lineas):
        raise ValidationError("No envíe porcentajes ni totales calculados desde el formulario.")
    if type(actualizar_reglas) is not bool:
        raise ValidationError("Indique Sí/No para actualizar reglas.")
    anterior = foto(orden)
    if actualizar_reglas:
        orden.reglas_importes = calculo.reglas_actuales()
    seleccionadas = calculo.seleccionar_retenciones(orden, retenciones, actualizar=actualizar_reglas)
    for datos in lineas:
        linea = actuales[datos["id"]]
        for campo in ("referencia", "descripcion", "unidad"):
            setattr(linea, campo, normalizar_espacios(datos.get(campo, getattr(linea, campo))))
        linea.especificacion = datos.get("especificacion", linea.especificacion).strip()
        linea.cantidad = decimal_valido(datos.get("cantidad", linea.cantidad))
        linea.precio_unitario = decimal_valido(datos.get("precio_unitario", linea.precio_unitario))
        linea.descuento = decimal_valido(datos.get("descuento", linea.descuento))
        if datos.get("tarifa_id") is not None:
            if type(datos["tarifa_id"]) is not int:
                raise ValidationError("Seleccione una tarifa activa del catálogo.")
            try:
                tarifa = TarifaImpuesto.objects.get(pk=datos["tarifa_id"], activo=True)
            except TarifaImpuesto.DoesNotExist:
                raise ValidationError("Seleccione una tarifa activa del catálogo.") from None
            linea.tarifa_nombre, linea.porcentaje = tarifa.nombre, tarifa.porcentaje
    # La posición define el desempate de residuos al redondear sobre el total.
    ordenadas = sorted(actuales.values(), key=lambda l: l.posicion)
    calculo.aplicar(orden, ordenadas, calculo.calcular(orden, ordenadas, seleccionadas))
    for linea in ordenadas:
        linea.full_clean()
        actual = _datos_linea(linea)
        linea.cambios = {k: {"etiqueta": str(linea._meta.get_field(k).verbose_name), "original": linea.original[k], "actual": actual[k]} for k in CAMPOS_LINEA if actual[k] != linea.original[k]}
        fuente = next(d for d in orden.origen_datos["lineas"] if d["oferta_linea_id"] == linea.oferta_linea_id)
        reglas_originales = calculo.reglas_origen(fuente["reglas_calculo"])
        if calculo.validar_reglas(orden.reglas_importes) != calculo.validar_reglas(reglas_originales):
            linea.cambios["reglas"] = {"etiqueta": "Reglas de importes", "original": calculo.describir_reglas(reglas_originales), "actual": calculo.describir_reglas(orden.reglas_importes)}
        linea.modificada = linea.modificada or bool(linea.cambios)
        linea.save()
    orden.fecha_elaboracion, orden.condiciones_pago = fecha_elaboracion, condiciones_pago.strip()
    if fecha_vencimiento is not _SIN_CAMBIO:
        orden.fecha_vencimiento = fecha_vencimiento
    if fecha_esperada_entrega is not _SIN_CAMBIO:
        orden.fecha_esperada_entrega = fecha_esperada_entrega
    orden.full_clean()
    if foto(orden) == anterior:
        raise ValidationError("No hay cambios para guardar.")
    _revision(orden, actor, motivo, "orden.borrador_modificado")
    return orden


@transaction.atomic
def anular_borradores_de_decision(decision, *, actor, motivo):
    """B13 mantiene el bloqueo de cotización y aún no ha anulado la decisión."""
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    cotizacion_id = DecisionCotizacion.objects.values_list("cotizacion_id", flat=True).get(pk=decision.pk)
    Cotizacion.objects.select_for_update().get(pk=cotizacion_id)
    ordenes = list(decision.ordenes.select_for_update().order_by("pk"))
    if any(o.estado not in ("borrador", "anulada") for o in ordenes):
        raise ValidationError("La decisión tiene órdenes que avanzaron del borrador. Resuelva su anulación antes de anular la decisión.")
    for orden in ordenes:
        if orden.estado == "borrador":
            orden.estado = "anulada"
            orden.anulada_por, orden.fecha_anulacion, orden.motivo_anulacion = actor, timezone.now(), motivo.strip()
            _revision(orden, actor, motivo, "orden.anulada_por_decision")
