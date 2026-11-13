from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction

from areas.models import Area
from bitacora.servicios import guardar_con_bitacora, instantanea, registrar
from compras.models import ListaElegibles, Necesidad, OrigenNecesidad, ParticipanteElegible, TipoOrigen
from compras.criterios_servicios import preparar_lista
from proveedores.models import Proveedor
from proveedores.servicios import _exigir_admin, _exigir_motivo
from proyecciones.models import Linea
from proyecciones.servicios import valores_vigentes


def lineas_disponibles(*, area=None, periodo=None):
    consulta = Linea.objects.filter(proyeccion__estado="aprobada").select_related("proyeccion__area", "proyeccion__periodo", "unidad")
    if area is not None:
        consulta = consulta.filter(proyeccion__area=area)
    if periodo is not None:
        consulta = consulta.filter(proyeccion__periodo=periodo)
    return consulta.order_by("proyeccion__periodo__anio", "producto_servicio", "pk")


@transaction.atomic
def crear_necesidad(*, objeto, area, fecha, tipo_origen=None, origen_texto="", lineas=(), cantidad_base=None, unidad_base="", actor, motivo):
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    area = Area.objects.select_for_update().get(pk=area.pk)
    if not area.activa:
        raise ValidationError("Seleccione un área activa.")
    if tipo_origen and not TipoOrigen.objects.filter(pk=tipo_origen.pk, activo=True).exists():
        raise ValidationError("El tipo de origen está inactivo.")
    if not lineas and not tipo_origen and not origen_texto.strip():
        raise ValidationError("Indique el origen de la necesidad sin proyección.")
    if isinstance(cantidad_base, (float, bool)):
        raise ValidationError("Indique una cantidad base decimal positiva.")
    necesidad = Necesidad(objeto=objeto, area=area, fecha=fecha, responsable=actor,
                          tipo_origen=tipo_origen, origen_texto=origen_texto.strip(), cantidad_base=cantidad_base, unidad_base=unidad_base)
    necesidad.full_clean()
    necesidad.save()
    ids = set()
    for linea_id, cantidad in lineas:
        if linea_id in ids:
            raise ValidationError("Una línea de proyección está repetida.")
        ids.add(linea_id)
        try:
            linea = Linea.objects.select_for_update().select_related("proyeccion", "unidad").get(pk=linea_id)
        except Linea.DoesNotExist:
            raise ValidationError("La línea de proyección no existe.") from None
        if linea.proyeccion.estado != "aprobada" or linea.proyeccion.area_id != area.pk:
            raise ValidationError("Solo se toman líneas aprobadas del área seleccionada.")
        try:
            if isinstance(cantidad, (float, bool)):
                raise ValueError
            valor = Decimal(str(cantidad))
            if not valor.is_finite():
                raise ValueError
        except (InvalidOperation, ValueError):
            raise ValidationError("Indique cantidades decimales válidas y positivas.") from None
        vigente = valores_vigentes(linea)
        origen = OrigenNecesidad(necesidad=necesidad, linea=linea, cantidad=valor,
            datos_origen={"producto": linea.producto_servicio, "unidad": str(linea.unidad),
                          "periodo": linea.proyeccion.periodo.anio, "cantidad_autorizada": vigente["cantidad_autorizada"]})
        origen.full_clean()
        origen.save()
        registrar("necesidad.origen_agregado", actor=actor, objeto=origen,
                  nuevo={"necesidad": necesidad.pk, "linea": linea.pk, "cantidad": valor, "datos": origen.datos_origen}, motivo=motivo)
    registrar("necesidad.creada", actor=actor, objeto=necesidad,
              nuevo=instantanea(necesidad, ["objeto", "area", "fecha", "responsable", "tipo_origen", "origen_texto", "estado", "cantidad_base", "unidad_base"]), motivo=motivo)
    return necesidad


@transaction.atomic
def crear_lista(necesidad, *, fecha, actor, motivo):
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    necesidad = Necesidad.objects.select_for_update().get(pk=necesidad.pk)
    if necesidad.estado != "abierta":
        raise ValidationError("Solo una necesidad abierta admite listas nuevas.")
    lista = ListaElegibles(necesidad=necesidad, fecha=fecha, creada_por=actor)
    preparar_lista(lista)
    lista.full_clean()
    lista.save()
    registrar("lista_elegibles.creada", actor=actor, objeto=lista,
              nuevo={"necesidad": necesidad.pk, "fecha": fecha, "estado": lista.estado,
                     "version_criterios": lista.version_criterios_id, "reglas_calculo": lista.reglas_calculo}, motivo=motivo)
    return lista


@transaction.atomic
def agregar_participante(lista, proveedor, *, actor, motivo):
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    lista = ListaElegibles.objects.select_for_update().get(pk=lista.pk)
    if lista.estado != "borrador":
        raise ValidationError("Solo una lista en borrador admite participantes.")
    proveedor = Proveedor.objects.select_for_update().get(pk=proveedor.pk)
    if not proveedor.activo:
        raise ValidationError("El proveedor está inactivo.")
    participante = lista.participantes.filter(proveedor=proveedor).first()
    if participante and participante.activo:
        raise ValidationError("El proveedor ya participa en esta lista.")
    nit = participante.nit if participante else proveedor.nit
    if lista.participantes.filter(nit=nit).exclude(proveedor=proveedor).exists():
        raise ValidationError("Ese NIT ya está registrado en la lista.")
    participante = participante or ParticipanteElegible(lista=lista, proveedor=proveedor,
                                                        nit=proveedor.nit, razon_social=proveedor.razon_social)
    participante.activo = True
    participante.full_clean()
    guardar_con_bitacora(participante, ["lista", "proveedor", "nit", "razon_social", "activo"],
        accion_crear="participante.agregado", accion_modificar="participante.reactivado", actor=actor, motivo=motivo)
    from compras.decision_servicios import invalidar_decisiones
    invalidar_decisiones(lista, actor=actor, motivo=motivo)
    return participante


@transaction.atomic
def quitar_participante(lista, participante, *, actor, motivo):
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    lista = ListaElegibles.objects.select_for_update().get(pk=lista.pk)
    if lista.estado != "borrador":
        raise ValidationError("La lista ya no está en borrador.")
    participante = ParticipanteElegible.objects.select_for_update().get(pk=participante.pk)
    if participante.lista_id != lista.pk or not participante.activo:
        raise ValidationError("El participante no está activo en esta lista.")
    participante.activo = False
    guardar_con_bitacora(participante, ["lista", "proveedor", "nit", "razon_social", "activo"],
        accion_crear="participante.agregado", accion_modificar="participante.retirado", actor=actor, motivo=motivo)
    from compras.decision_servicios import invalidar_decisiones
    invalidar_decisiones(lista, actor=actor, motivo=motivo)
    return participante


@transaction.atomic
def guardar_tipo_origen(tipo, *, actor, motivo):
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    tipo.full_clean()
    guardar_con_bitacora(tipo, ["nombre", "activo"], accion_crear="tipo_origen.creado",
                        accion_modificar="tipo_origen.modificado", actor=actor, motivo=motivo)
    return tipo
