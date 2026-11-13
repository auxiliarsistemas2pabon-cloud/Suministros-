"""Creación explícita FR-GDS-28, consecutivo e invitaciones desde elegibles."""
from copy import deepcopy
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction

from bitacora.servicios import guardar_con_bitacora, instantanea, registrar
from compras.cotizacion_origen import preparar_cotizacion
from compras.models import Cotizacion, InvitadoCotizacion, LineaCotizacion, ListaElegibles, Necesidad, OrigenNecesidad, SecuenciaCotizacion, TipoCotizacion
from parametros.catalogo import MAX_LINEAS_COTIZACION, MAX_OFERENTES_COTIZACION
from parametros.models import Parametro
from parametros.servicios import obtener
from proveedores.models import Proveedor
from proveedores.servicios import _exigir_admin, _exigir_motivo
from proyecciones.models import UnidadMedida


def limites_actuales():
    limites = {"lineas": obtener(MAX_LINEAS_COTIZACION), "oferentes": obtener(MAX_OFERENTES_COTIZACION)}
    if any(type(v) is not int or v < 0 for v in limites.values()):
        raise ValidationError("Configure límites enteros no negativos para cotizaciones.")
    return limites


@transaction.atomic
def guardar_tipo(tipo, *, actor, motivo):
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    tipo.full_clean()
    guardar_con_bitacora(tipo, ["nombre", "descripcion", "activo"], accion_crear="cotizacion.tipo_creado",
                        accion_modificar="cotizacion.tipo_modificado", actor=actor, motivo=motivo)
    return tipo


@transaction.atomic
def crear_cotizacion(*, necesidad, fecha, tipo, objeto, lineas, invitados=(), lista_elegibles=None, cierre_esperado_id=None, actor, motivo):
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    necesidad = Necesidad.objects.select_for_update().select_related("area").get(pk=necesidad.pk)
    if necesidad.estado != "abierta" or not necesidad.area.activa:
        raise ValidationError("Seleccione una necesidad abierta de un área activa.")
    tipo = TipoCotizacion.objects.select_for_update().get(pk=tipo.pk)
    if not tipo.activo:
        raise ValidationError("El tipo de cotización está inactivo.")
    datos, cierre = {}, None
    if lista_elegibles:
        lista_elegibles = ListaElegibles.objects.select_for_update().get(pk=lista_elegibles.pk)
        if lista_elegibles.necesidad_id != necesidad.pk:
            raise ValidationError("La lista no pertenece a la necesidad indicada.")
        datos = preparar_cotizacion(lista_elegibles, actor=actor)
        cierre = lista_elegibles.cierres.first()
        if cierre is None:
            raise ValidationError("La lista no tiene un cierre histórico completo.")
        if cierre_esperado_id is not None and cierre.pk != cierre_esperado_id:
            raise ValidationError("El cierre de origen cambió. Recargue la precarga antes de guardar.")
        if invitados:
            raise ValidationError("Desde una lista cerrada se conservan sus elegidos; no envíe invitados distintos.")
        ids = [d["proveedor"] for d in datos["invitados"]]
    else:
        ids = [p.pk if isinstance(p, Proveedor) else p for p in invitados]
    if any(type(pk) is not int or pk <= 0 for pk in ids) or len(set(ids)) != len(ids):
        raise ValidationError("Seleccione proveedores distintos y válidos.")
    proveedores = {p.pk: p for p in Proveedor.objects.select_for_update().filter(pk__in=ids).order_by("pk")}
    if len(proveedores) != len(ids) or any(not p.activo for p in proveedores.values()):
        raise ValidationError("Todos los invitados deben ser proveedores activos registrados.")
    list(Parametro.objects.select_for_update().filter(clave__in=[MAX_LINEAS_COTIZACION, MAX_OFERENTES_COTIZACION]).order_by("pk"))
    limites = limites_actuales()
    if not lineas:
        raise ValidationError("Registre al menos una línea de especificación.")
    if limites["lineas"] and len(lineas) > limites["lineas"]:
        raise ValidationError(f"El límite D-10 actual es de {limites['lineas']} líneas; no se guardó una precarga parcial.")
    if limites["oferentes"] and len(ids) > limites["oferentes"]:
        raise ValidationError(f"El límite D-10 actual es de {limites['oferentes']} invitados; no se descartan elegidos automáticamente.")
    secuencia = SecuenciaCotizacion.objects.select_for_update().get(pk=1)
    secuencia.ultimo += 1
    cotizacion = Cotizacion(necesidad=necesidad, lista_elegibles=lista_elegibles, cierre_origen=cierre,
        area=necesidad.area, responsable=actor, fecha=fecha, tipo=tipo, objeto=objeto,
        numero=secuencia.ultimo, consecutivo=f"COT-{fecha.year}-{secuencia.ultimo:06d}",
        origen_datos=deepcopy(datos), limites_aplicados=limites)
    cotizacion.full_clean()
    guardar_con_bitacora(secuencia, ["ultimo"], accion_crear="cotizacion.secuencia_asignada", accion_modificar="cotizacion.secuencia_asignada", actor=actor, motivo=motivo)
    cotizacion.save()
    origenes_foto = {d["linea_origen_id"]: d for d in datos.get("lineas", [])}
    for orden, dato in enumerate(lineas, 1):
        try:
            cantidad = dato["cantidad"]
            if isinstance(cantidad, (float, bool)):
                raise ValueError
            cantidad = Decimal(str(cantidad))
            if not cantidad.is_finite() or cantidad <= 0:
                raise ValueError
        except (InvalidOperation, ValueError):
            raise ValidationError("Use cantidades decimales positivas y finitas.") from None
        unidad_id = dato["unidad"].pk if isinstance(dato["unidad"], UnidadMedida) else dato["unidad"]
        unidad = UnidadMedida.objects.select_for_update().filter(pk=unidad_id, activa=True).first()
        if unidad is None:
            raise ValidationError("Seleccione una unidad activa del catálogo.")
        origen, foto = None, {}
        if dato.get("origen"):
            origen_id = dato["origen"].pk if isinstance(dato["origen"], OrigenNecesidad) else dato["origen"]
            origen = OrigenNecesidad.objects.filter(pk=origen_id, necesidad=necesidad).first()
            if origen is None or (lista_elegibles and origen.linea_id not in origenes_foto):
                raise ValidationError("La línea de origen no pertenece a esta necesidad o al cierre elegido.")
            foto = deepcopy(origenes_foto[origen.linea_id] if lista_elegibles else {**origen.datos_origen, "cantidad": str(origen.cantidad)})
        linea = LineaCotizacion(cotizacion=cotizacion, orden=orden, descripcion=dato["descripcion"], unidad=unidad,
            unidad_texto=str(unidad), cantidad=cantidad, especificacion=dato.get("especificacion", "").strip(), origen=origen, origen_datos=foto)
        linea.full_clean()
        linea.save()
        registrar("cotizacion.linea_creada", actor=actor, objeto=linea,
            nuevo=instantanea(linea, ["cotizacion", "orden", "descripcion", "unidad", "unidad_texto", "cantidad", "especificacion", "origen", "origen_datos"]), motivo=motivo)
    seleccionados = {d["proveedor"]: d for d in datos.get("invitados", [])}
    filas_foto = {d["proveedor_id"]: d for d in lista_elegibles.resultado_cierre["filas"]} if lista_elegibles else {}
    for pk in ids:
        proveedor = proveedores[pk]
        foto = seleccionados.get(pk)
        invitado = InvitadoCotizacion(cotizacion=cotizacion, proveedor=proveedor,
            nit=foto["nit"] if foto else proveedor.nit, razon_social=foto["razon_social"] if foto else proveedor.razon_social,
            participante_origen_id=filas_foto[pk]["participante_id"] if foto else None,
            cantidad_autorizada=Decimal(foto["cantidad_autorizada"]) if foto else None)
        invitado.full_clean()
        invitado.save()
        registrar("cotizacion.invitado_agregado", actor=actor, objeto=invitado,
            nuevo=instantanea(invitado, ["cotizacion", "proveedor", "participante_origen", "nit", "razon_social", "cantidad_autorizada"]), motivo=motivo)
    registrar("cotizacion.creada", actor=actor, objeto=cotizacion,
        nuevo=instantanea(cotizacion, ["consecutivo", "necesidad", "lista_elegibles", "cierre_origen", "fecha", "area", "responsable", "tipo", "objeto", "estado", "limites_aplicados"]), motivo=motivo)
    return cotizacion
