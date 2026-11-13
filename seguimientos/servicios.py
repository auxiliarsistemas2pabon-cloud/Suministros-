from copy import deepcopy
from datetime import datetime, time
from decimal import Decimal
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from django.core.serializers.json import DjangoJSONEncoder
import json

from bitacora.servicios import registrar, guardar_con_bitacora
from cuentas.models import Rol
from cuentas.permisos import es_admin
from compras.models import OrdenCompra, Contrato
from compras.numeracion_ordenes import _bloquear_orden
from compras.operacion_archivos import transaccion, adjuntar
from compras import recepcion_servicios
from compras.aprobacion_orden_servicios import guardar_estado
from parametros.catalogo import AUTO_SEGUIMIENTO, REABRIR_SEGUIMIENTO, CIERRE_CON_SALDO, CONSULTA_COORDINADOR_SEGUIMIENTO, validar_cierre_saldo
from parametros.servicios import obtener
from proveedores.models import Proveedor
from proveedores.servicios import _exigir_admin, _exigir_motivo
from seguimientos.models import Seguimiento, TipoSeguimiento, TipoEvento, EventoSeguimiento, PlantillaHito, HitoSeguimiento, MovimientoLinea, CierreSeguimiento, ResultadoCierre
from seguimientos import estados


def alcance(consulta, actor):
    if es_admin(actor):
        return consulta
    if (getattr(actor, "is_authenticated", False) and actor.is_active and actor.rol == Rol.COORDINADOR and obtener(CONSULTA_COORDINADOR_SEGUIMIENTO) is True):
        return consulta.filter(area_id=actor.area_id)
    raise PermissionDenied


def bloquear(seguimiento):
    datos = Seguimiento.objects.values("orden_id", "contrato__decision__cotizacion_id").get(pk=seguimiento.pk)
    if datos["orden_id"]:
        _bloquear_orden(OrdenCompra(pk=datos["orden_id"]))
    else:
        from compras.models import Cotizacion
        Cotizacion.objects.select_for_update().get(pk=datos["contrato__decision__cotizacion_id"])
    return Seguimiento.objects.select_for_update(of=("self",)).select_related("orden", "contrato", "tipo").get(pk=seguimiento.pk)


def _guardar(seguimiento):
    seguimiento._operacion = True
    try:
        seguimiento.revision += 1
        seguimiento.full_clean()
        seguimiento.save()
    finally:
        seguimiento._operacion = False


def _exigir_abierto(seguimiento, revision_esperada=None):
    if seguimiento.cerrado:
        raise ValidationError("El seguimiento está cerrado. Requiere reapertura autorizada para agregar movimientos.")
    if revision_esperada is not None and seguimiento.revision != revision_esperada:
        raise ValidationError("El seguimiento cambió. Recargue antes de continuar.")


def foto(seguimiento):
    return json.loads(json.dumps({"id": seguimiento.pk, "orden_id": seguimiento.orden_id, "contrato_id": seguimiento.contrato_id,
        "tipo_id": seguimiento.tipo_id, "tipo": seguimiento.tipo_nombre, "area_id": seguimiento.area_id,
        "proveedor_id": seguimiento.proveedor_id, "nit": seguimiento.nit, "razon_social": seguimiento.razon_social,
        "objeto": seguimiento.objeto, "valor": seguimiento.valor, "comite": seguimiento.comite, "fecha_comite": seguimiento.fecha_comite,
        "cerrado": seguimiento.cerrado, "revision": seguimiento.revision, "version_hitos": seguimiento.version_hitos}, cls=DjangoJSONEncoder))


def _copiar_hitos(seguimiento):
    for plantilla in PlantillaHito.objects.filter(tipo_seguimiento=seguimiento.tipo, activo=True):
        HitoSeguimiento.objects.create(seguimiento=seguimiento, version=seguimiento.version_hitos, plantilla=plantilla,
            nombre=plantilla.nombre, referencia_id_guardada=plantilla.referencia_id, cumple_id_guardada=plantilla.cumple_id, plazo_dias=plantilla.plazo_dias)


@transaction.atomic
def crear(*, orden=None, contrato=None, tipo=None, comite="", fecha_comite=None, actor, motivo):
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    if orden is None and contrato is None:
        raise ValidationError("Indique una orden o un contrato como origen.")
    if orden is not None:
        orden = _bloquear_orden(orden)
        if orden.numero is None or orden.estado not in ("emitida", "recibida_parcial", "recibida_total"):
            raise ValidationError("Inicie seguimiento desde una orden emitida vigente.")
        existente = Seguimiento.objects.filter(orden=orden).first()
        if existente:
            _incorporar_recepciones(existente, actor, motivo)
            existente.refresh_from_db()
            return existente
        contrato_id = orden.origen_datos.get("contrato", {}).get("contrato", {}).get("id")
        if contrato is not None and contrato.pk != contrato_id:
            raise ValidationError("El contrato no coincide con la orden.")
        contrato = Contrato.objects.filter(pk=contrato_id).first() if contrato_id else None
        datos = {"orden": orden, "contrato": contrato, "area": orden.cotizacion.area, "proveedor": orden.proveedor,
            "nit": orden.nit, "razon_social": orden.razon_social, "objeto": orden.origen_datos["trazabilidad"]["objeto"], "valor": orden.total,
            "origen_datos": {"orden_id": orden.pk, "consecutivo": orden.consecutivo, "origen": deepcopy(orden.origen_datos)}}
        codigo, nombre = "compras_generales", "Compras generales"
    else:
        from compras.models import Cotizacion
        contrato = Contrato.objects.select_related("decision__cotizacion").get(pk=contrato.pk)
        Cotizacion.objects.select_for_update().get(pk=contrato.decision.cotizacion_id)
        if contrato.decision.estado != "aprobada":
            raise ValidationError("El contrato requiere decisión aprobada.")
        existente = Seguimiento.objects.filter(contrato=contrato, orden__isnull=True).first()
        if existente:
            return existente
        aprobacion = contrato.decision.aprobaciones.order_by("fecha", "pk").last()
        contrato_foto = aprobacion.contrato_datos.get("contrato", {}) if aprobacion else {}
        ofertas = contrato.decision.contenido.get("comparativo", {}).get("ofertas", [])
        proveedores = {a.oferta.proveedor_id for a in contrato.decision.adjudicaciones.select_related("oferta")}
        if len(proveedores) != 1 or not contrato_foto or contrato_foto.get("valor") is None:
            raise ValidationError("Un contrato sin orden requiere proveedor único adjudicado y valor contractual aprobado; use las órdenes por proveedor si hubo reparto.")
        proveedor_id = next(iter(proveedores))
        oferta = next(o for o in ofertas if o["proveedor_id"] == proveedor_id)
        datos = {"contrato": contrato, "area": contrato.decision.cotizacion.area, "proveedor_id": proveedor_id,
            "nit": oferta["nit"], "razon_social": oferta["razon_social"], "objeto": contrato.decision.cotizacion.objeto,
            "valor": Decimal(contrato_foto["valor"]), "origen_datos": {"contrato_id": contrato.pk, "contrato": deepcopy(contrato_foto)}}
        codigo, nombre = "contratos", "Contratos"
    if tipo is None:
        tipo, _ = TipoSeguimiento.objects.get_or_create(codigo=codigo, defaults={"nombre": nombre})
    else:
        tipo = TipoSeguimiento.objects.filter(pk=tipo.pk, activo=True).first()
    if tipo is None or not tipo.activo:
        raise ValidationError("Seleccione un tipo de seguimiento activo.")
    seguimiento = Seguimiento(**datos, tipo=tipo, tipo_nombre=tipo.nombre, comite=comite.strip(), fecha_comite=fecha_comite, abierto_por=actor)
    seguimiento.full_clean()
    seguimiento.save()
    _copiar_hitos(seguimiento)
    registrar("seguimiento.creado", actor=actor, objeto=seguimiento, nuevo=foto(seguimiento), motivo=motivo)
    if seguimiento.orden_id:
        _incorporar_recepciones(seguimiento, actor, motivo)
        seguimiento.refresh_from_db()
    return seguimiento


def crear_al_emitir(orden, actor, motivo):
    if obtener(AUTO_SEGUIMIENTO) is True:
        return crear(orden=orden, actor=actor, motivo=motivo)


@transaction.atomic
def corregir(seguimiento, *, proveedor, objeto, valor, tipo, comite="", fecha_comite=None, actor, motivo, revision_esperada=None):
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    seguimiento = bloquear(seguimiento)
    _exigir_abierto(seguimiento, revision_esperada)
    anterior = foto(seguimiento)
    proveedor = Proveedor.objects.get(pk=proveedor.pk)
    if not tipo.activo:
        raise ValidationError("Seleccione un tipo activo.")
    from compras.importes import decimal_valido
    seguimiento.proveedor, seguimiento.nit, seguimiento.razon_social = proveedor, proveedor.nit, proveedor.razon_social
    seguimiento.objeto, seguimiento.valor, seguimiento.tipo, seguimiento.tipo_nombre = objeto.strip(), decimal_valido(valor), tipo, tipo.nombre
    seguimiento.comite, seguimiento.fecha_comite = comite.strip(), fecha_comite
    if {k: v for k, v in foto(seguimiento).items() if k != "revision"} == {k: v for k, v in anterior.items() if k != "revision"}:
        raise ValidationError("No hay cambios para guardar.")
    _guardar(seguimiento)
    registrar("seguimiento.corregido", actor=actor, objeto=seguimiento, anterior=anterior, nuevo=foto(seguimiento), motivo=motivo)
    return seguimiento


@transaction.atomic
def guardar_catalogo(registro, *, actor, motivo):
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    registro.full_clean()
    campos = [f.name for f in registro._meta.fields if f.name != "id"]
    guardar_con_bitacora(registro, campos, accion_crear="seguimiento.catalogo_creado", accion_modificar="seguimiento.catalogo_modificado", actor=actor, motivo=motivo)
    return registro


def agregar_evento(seguimiento, *, tipo, fecha, nota, actor, motivo, corrige_id=None, archivo=None, revision_esperada=None):
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    with transaccion(archivo) as rutas:
        seguimiento = bloquear(seguimiento)
        _exigir_abierto(seguimiento, revision_esperada)
        tipo = TipoEvento.objects.filter(pk=tipo.pk, activo=True).first()
        if tipo is None:
            raise ValidationError("Seleccione un tipo de evento activo.")
        if not nota.strip():
            raise ValidationError("Indique la nota del evento.")
        evento = EventoSeguimiento(seguimiento=seguimiento, tipo=tipo, tipo_nombre=tipo.nombre, funcion=tipo.funcion,
            fecha=fecha, nota=nota.strip(), registrado_por=actor, corrige_id=corrige_id)
        adjuntar(evento, archivo, rutas, "eventos_seguimiento")
        evento.full_clean()
        evento.save()
        _guardar(seguimiento)
        registrar("seguimiento.evento_creado", actor=actor, objeto=evento, nuevo={"seguimiento_id": seguimiento.pk, "tipo": evento.tipo_nombre, "fecha": fecha.isoformat(), "nota": evento.nota, "corrige_id": corrige_id}, motivo=motivo)
    return evento


def _incorporar_recepciones(seguimiento, actor, motivo):
    for recepcion in seguimiento.orden.recepciones.filter(evento__isnull=True).select_related("recibido_por").order_by("fecha_registro", "pk"):
        evento_recepcion(recepcion, recepcion.recibido_por, recepcion.observacion, actor_auditoria=actor, motivo_auditoria=motivo)


def evento_recepcion(recepcion, actor, motivo, *, actor_auditoria=None, motivo_auditoria=None):
    seguimiento = Seguimiento.objects.filter(orden=recepcion.orden).first()
    if seguimiento is None:
        return
    seguimiento = bloquear(seguimiento)
    _exigir_abierto(seguimiento)
    codigo = "devolucion" if recepcion.tipo == "devolucion" else "recepcion"
    tipo, _ = TipoEvento.objects.get_or_create(codigo=codigo, defaults={"nombre": "Devolución" if codigo == "devolucion" else "Recepción", "funcion": codigo})
    if EventoSeguimiento.objects.filter(recepcion=recepcion).exists():
        return
    nota = f'{recepcion.get_tipo_display()} {recepcion.pk}: {motivo}'
    evento = EventoSeguimiento(seguimiento=seguimiento, recepcion=recepcion, tipo=tipo, tipo_nombre=tipo.nombre, funcion=codigo,
        fecha=timezone.make_aware(datetime.combine(recepcion.fecha, time.min)), registrado_por=actor, nota=nota,
        archivo=recepcion.archivo.name, nombre_archivo=recepcion.nombre_archivo)
    evento.full_clean()
    evento.save()
    _guardar(seguimiento)
    registrar("seguimiento.recepcion_vinculada", actor=actor_auditoria or actor, objeto=evento,
        nuevo={"recepcion_id": recepcion.pk, "incorporacion_historica": actor_auditoria is not None}, motivo=motivo_auditoria or motivo)


def lineas(seguimiento):
    if not seguimiento.orden_id:
        return []
    filas = recepcion_servicios.acumulados(seguimiento.orden)
    cerradas = {}
    for movimiento in seguimiento.movimientos_linea.order_by("pk"):
        cerradas[movimiento.linea_id] = movimiento.accion == "cerrar"
    for fila in filas:
        fila["cerrada"] = cerradas.get(fila["linea"].pk, False)
        if fila["cerrada"] and fila["pendiente"] > 0:
            fila["estado"] = "cerrada con saldo"
    return filas


@transaction.atomic
def mover_linea(seguimiento, *, linea_id, accion, actor, motivo, revision_esperada=None):
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    seguimiento = bloquear(seguimiento)
    _exigir_abierto(seguimiento, revision_esperada)
    fila = next((f for f in lineas(seguimiento) if f["linea"].pk == linea_id), None)
    if fila is None or accion not in ("cerrar", "reabrir") or fila["cerrada"] == (accion == "cerrar"):
        raise ValidationError("La acción no corresponde al estado actual de una línea propia.")
    registro = MovimientoLinea(seguimiento=seguimiento, linea=fila["linea"], accion=accion, actor=actor, motivo=motivo.strip(), saldo=fila["pendiente"])
    registro.full_clean()
    registro.save()
    _guardar(seguimiento)
    registrar("seguimiento.linea_"+accion, actor=actor, objeto=registro, nuevo={"linea_id": linea_id, "saldo": str(fila["pendiente"])}, motivo=motivo)
    return registro


def tablero(seguimiento, hoy=None):
    hoy = hoy or timezone.localdate()
    eventos = [{"id": e.pk, "fecha": timezone.localtime(e.fecha), "tipo_id": e.tipo_id, "funcion": e.funcion, "corrige_id": e.corrige_id} for e in seguimiento.eventos.all()]
    plantillas = [{"id": h.pk, "nombre": h.nombre, "referencia_id": h.referencia_id_guardada, "cumple_id": h.cumple_id_guardada, "plazo_dias": h.plazo_dias} for h in seguimiento.hitos.filter(version=seguimiento.version_hitos)]
    hitos = estados.evaluar_hitos(plantillas, eventos, timezone.localtime(seguimiento.fecha), hoy)
    filas = lineas(seguimiento)
    esperada = seguimiento.orden.fecha_esperada_entrega if seguimiento.orden_id else None
    estado = estados.derivar(cerrado=seguimiento.cerrado, eventos=eventos, lineas=filas, hitos=hitos, hoy=hoy, fecha_esperada=esperada)
    return {"estado": estado, "estado_texto": dict(estados.ESTADOS)[estado], "lineas": filas, "hitos": hitos}


@transaction.atomic
def actualizar_hitos(seguimiento, *, actor, motivo, revision_esperada=None):
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    seguimiento = bloquear(seguimiento)
    _exigir_abierto(seguimiento, revision_esperada)
    seguimiento.version_hitos += 1
    _copiar_hitos(seguimiento)
    _guardar(seguimiento)
    registrar("seguimiento.hitos_actualizados", actor=actor, objeto=seguimiento, nuevo={"version": seguimiento.version_hitos}, motivo=motivo)
    return seguimiento


@transaction.atomic
def cerrar(seguimiento, *, resultado, fecha, actor, motivo, revision_esperada=None):
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    seguimiento = bloquear(seguimiento)
    _exigir_abierto(seguimiento, revision_esperada)
    if not ResultadoCierre.objects.filter(pk=resultado.pk, activo=True).exists():
        raise ValidationError("Seleccione un resultado activo.")
    if fecha < timezone.localdate(seguimiento.fecha) or fecha > timezone.localdate():
        raise ValidationError("La fecha de cierre debe estar entre la apertura y hoy.")
    pendientes = [f for f in lineas(seguimiento) if f["pendiente"] > 0 and not f["cerrada"]]
    politica = validar_cierre_saldo(obtener(CIERRE_CON_SALDO))
    if pendientes and politica == "bloquear":
        raise ValidationError("Hay líneas con saldo pendiente sin cierre justificado.")
    registro = CierreSeguimiento(seguimiento=seguimiento, accion="cierre", resultado=resultado, resultado_nombre=resultado.nombre,
        fecha=fecha, registrado_por=actor, observacion=motivo.strip(), reglas={"saldos": politica, "pendientes": [f["linea"].pk for f in pendientes]})
    registro.full_clean()
    registro.save()
    seguimiento.cerrado = True
    _guardar(seguimiento)
    if seguimiento.orden_id and seguimiento.orden.estado in ("emitida", "recibida_parcial", "recibida_total"):
        seguimiento.orden.estado = "cerrada"
        guardar_estado(seguimiento.orden, actor, motivo, "orden.cerrada_por_seguimiento")
    registrar("seguimiento.cerrado", actor=actor, objeto=seguimiento, nuevo={**foto(seguimiento), "resultado": resultado.nombre, "fecha": fecha.isoformat(), "advertencia_saldos": bool(pendientes)}, motivo=motivo)
    return seguimiento


@transaction.atomic
def reabrir(seguimiento, *, actor, motivo, revision_esperada=None):
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    seguimiento = bloquear(seguimiento)
    if not seguimiento.cerrado or obtener(REABRIR_SEGUIMIENTO) is not True:
        raise ValidationError("La reapertura está deshabilitada o el seguimiento ya está abierto.")
    if revision_esperada is not None and revision_esperada != seguimiento.revision:
        raise ValidationError("El seguimiento cambió. Recargue antes de reabrir.")
    CierreSeguimiento.objects.create(seguimiento=seguimiento, accion="reapertura", registrado_por=actor, observacion=motivo.strip(), reglas={"reapertura_habilitada": True})
    seguimiento.cerrado = False
    _guardar(seguimiento)
    if seguimiento.orden_id and seguimiento.orden.estado == "cerrada":
        filas = recepcion_servicios.acumulados(seguimiento.orden)
        seguimiento.orden.estado = "recibida_total" if all(f["pendiente"] == 0 for f in filas) else "recibida_parcial" if any(f["recibido"] > 0 for f in filas) else "emitida"
        guardar_estado(seguimiento.orden, actor, motivo, "orden.reabierta_por_seguimiento")
    registrar("seguimiento.reabierto", actor=actor, objeto=seguimiento, nuevo=foto(seguimiento), motivo=motivo)
    return seguimiento
