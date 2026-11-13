"""Reglas de negocio de catálogos, periodos y proyecciones."""

from decimal import Decimal
import hashlib
import json
import secrets
from datetime import datetime, timedelta

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import BigIntegerField, Count, DecimalField, ExpressionWrapper, F, Q, Sum, Value
from django.db.models.functions import Cast, Coalesce
from django.utils import timezone

from areas.models import Area
from bitacora.models import RegistroBitacora
from bitacora.servicios import guardar_con_bitacora, instantanea, registrar
from cuentas.models import ROLES_ADMIN, Rol
from parametros import servicios as servicios_parametros
from parametros.catalogo import APROBACIONES_REQUERIDAS, PERMITIR_DEVOLUCION
from proyecciones.models import (
    CAMPOS_AJUSTABLES,
    CAMPOS_CANTIDADES_MENSUALES,
    Ajuste,
    AprobacionProyeccion,
    Linea,
    Periodo,
    ProyeccionArea,
    UnidadMedida,
)

CAMPOS_AUDITADOS_UNIDAD = ["nombre", "abreviatura", "activa"]
CAMPOS_AUDITADOS_PRODUCTO = ["nombre", "unidad_por_defecto", "activo"]
CAMPOS_AUDITADOS_PERIODO = [
    "anio",
    "fecha_apertura",
    "fecha_limite_diligenciamiento",
    "estado",
    "creado_por",
]
CAMPOS_AUDITADOS_PROYECCION_AREA = [
    "periodo",
    "area",
    "estado",
    "fecha_envio",
    "enviado_por",
    "fecha_aprobacion",
    "aprobado_por",
]
CAMPOS_AUDITADOS_LINEA = [
    "proyeccion",
    "producto_servicio",
    "dependencia",
    "unidad",
    "cantidad_enero",
    "cantidad_febrero",
    "cantidad_marzo",
    "cantidad_abril",
    "cantidad_mayo",
    "cantidad_junio",
    "cantidad_julio",
    "cantidad_agosto",
    "cantidad_septiembre",
    "cantidad_octubre",
    "cantidad_noviembre",
    "cantidad_diciembre",
    "precio_estimado",
    "cantidad_autorizada",
]


def _validar_motivo(motivo):
    if not (motivo or "").strip():
        raise ValidationError({"motivo": "El motivo es obligatorio."})


def validar_edicion_coordinador(proyeccion, actor):
    """Impide que un coordinador edite otra área o un periodo cerrado."""
    if getattr(actor, "rol", None) != Rol.COORDINADOR:
        return
    if actor.area_id != proyeccion.area_id:
        raise PermissionDenied("Un coordinador solo puede editar la proyección de su área.")
    if proyeccion.periodo.estado != Periodo.Estado.ABIERTO:
        raise ValidationError({"proyeccion": "El periodo está cerrado y no admite edición ordinaria."})


MENSAJE_APROBADA = "La proyección está aprobada: la edición ordinaria está bloqueada; registre un ajuste justificado."


def validar_no_aprobada(proyeccion_id):
    """La aprobación bloquea la edición ordinaria para cualquier rol (se consulta la base, no la instancia)."""
    if proyeccion_id and ProyeccionArea.objects.filter(pk=proyeccion_id, estado=ProyeccionArea.Estado.APROBADA).exists():
        raise ValidationError({"proyeccion": MENSAJE_APROBADA})


def validar_importacion(proyeccion, actor):
    if not getattr(actor, "is_authenticated", False) or not getattr(actor, "is_active", False):
        raise PermissionDenied
    if actor.rol not in (*ROLES_ADMIN, Rol.COORDINADOR):
        raise PermissionDenied
    validar_edicion_coordinador(proyeccion, actor)
    validar_no_aprobada(proyeccion.pk)
    if actor.rol == Rol.COORDINADOR:
        validar_proyeccion_editable(proyeccion, actor)
    if aprobaciones_vigentes(proyeccion).exists():
        raise ValidationError("Ya hay aprobaciones registradas. Devuelva la proyección antes de importar.")


def _huella_importacion(proyeccion):
    datos = {
        "estado": proyeccion.estado,
        "periodo": proyeccion.periodo.estado,
        "envio": proyeccion.fecha_envio,
        "lineas": list(proyeccion.lineas.order_by("pk").values()),
    }
    return hashlib.sha256(json.dumps(datos, cls=DjangoJSONEncoder, sort_keys=True).encode()).hexdigest()


def preparar_importacion(proyeccion, archivo, *, actor):
    from proyecciones.importar import leer_excel

    validar_importacion(proyeccion, actor)
    huella = _huella_importacion(proyeccion)
    filas, errores = leer_excel(archivo, proyeccion)
    return {
        "token": secrets.token_urlsafe(24), "actor": actor.pk, "proyeccion": proyeccion.pk,
        "creada": timezone.now().isoformat(), "huella": huella, "filas": filas, "errores": errores,
    }


@transaction.atomic
def confirmar_importacion(proyeccion, previa, *, actor, modo, motivo, request=None):
    """Confirma solo datos guardados en servidor; bloquea el destino y detecta cambios desde la vista previa."""
    _validar_motivo(motivo)
    # El cierre del periodo y la aprobación usan estos mismos bloqueos.
    periodo = Periodo.objects.select_for_update().get(pk=proyeccion.periodo_id)
    proyeccion = ProyeccionArea.objects.select_for_update().get(pk=proyeccion.pk)
    proyeccion.periodo = periodo
    validar_importacion(proyeccion, actor)
    if modo not in ("agregar", "reemplazar"):
        raise ValidationError("Seleccione agregar o reemplazar.")
    if not previa or previa["actor"] != actor.pk or previa["proyeccion"] != proyeccion.pk:
        raise PermissionDenied
    if timezone.now() - datetime.fromisoformat(previa["creada"]) > timedelta(minutes=30):
        raise ValidationError("La vista previa venció. Cargue el archivo nuevamente.")
    if previa["huella"] != _huella_importacion(proyeccion):
        raise ValidationError("La proyección cambió desde la vista previa. Cargue el archivo nuevamente.")
    if not previa["filas"]:
        raise ValidationError("No hay filas válidas para importar.")
    lineas = []
    for fila in previa["filas"]:
        linea = Linea(proyeccion=proyeccion, **fila["datos"])
        linea.full_clean()
        validar_unidad_de_linea(linea)
        lineas.append(linea)
    anteriores = list(proyeccion.lineas.select_related("unidad").order_by("pk")) if modo == "reemplazar" else []
    for linea in anteriores:
        registrar(
            "linea.eliminada", actor=actor, objeto=linea,
            anterior=instantanea(linea, CAMPOS_AUDITADOS_LINEA), motivo=motivo, request=request,
        )
        linea.delete()
    for linea in lineas:
        guardar_linea(linea, actor=actor, motivo=motivo, request=request)
    registrar(
        "proyeccion_area.importada", actor=actor, objeto=proyeccion,
        anterior={"lineas_reemplazadas": len(anteriores)},
        nuevo={"modo": modo, "filas_importadas": len(lineas), "filas_con_error": len(previa["errores"])},
        motivo=motivo, request=request,
    )
    return len(lineas)


def validar_proyeccion_editable(proyeccion, actor):
    """Verifica que la proyección pueda modificarse como borrador."""
    validar_edicion_coordinador(proyeccion, actor)
    if proyeccion.periodo.estado != Periodo.Estado.ABIERTO:
        raise ValidationError({"proyeccion": "El periodo está cerrado y no admite edición ordinaria."})
    if proyeccion.estado != ProyeccionArea.Estado.BORRADOR:
        raise ValidationError({"proyeccion": "La proyección ya fue enviada y está en solo lectura."})


def periodos_abiertos_sin_proyeccion(area):
    """Periodos abiertos que todavía no tienen proyección para un área activa."""
    if not area.activa:
        return Periodo.objects.none()
    return (
        Periodo.objects.filter(estado=Periodo.Estado.ABIERTO)
        .exclude(proyecciones_area__area=area)
        .order_by("-anio")
    )


def areas_sin_proyeccion(periodo):
    """Áreas activas que aún no tienen proyección en el periodo indicado."""
    return Area.objects.filter(activa=True).exclude(proyecciones__periodo=periodo).order_by("nombre")


@transaction.atomic
def abrir_periodo(
    anio,
    fecha_limite,
    *,
    actor,
    motivo,
    request=None,
    fecha_apertura=None,
):
    """Crea un periodo abierto y una proyección borrador por cada área activa."""
    fecha_apertura = fecha_apertura or timezone.localdate()
    periodo = Periodo(
        anio=anio,
        fecha_apertura=fecha_apertura,
        fecha_limite_diligenciamiento=fecha_limite,
        estado=Periodo.Estado.ABIERTO,
        creado_por=actor,
    )
    guardar_periodo(
        periodo,
        actor=actor,
        motivo=motivo,
        request=request,
        accion_crear="periodo.abierto",
        accion_modificar="periodo.abierto",
    )
    for area in Area.objects.filter(activa=True).order_by("pk"):
        guardar_proyeccion_area(
            ProyeccionArea(periodo=periodo, area=area),
            actor=actor,
            motivo=motivo,
            request=request,
            accion_modificar="proyeccion_area.creada",
        )
    return periodo


@transaction.atomic
def crear_proyeccion_area(periodo, area, *, actor, motivo, request=None):
    """Crea la proyección borrador de un área activa en un periodo abierto."""
    periodo = Periodo.objects.select_for_update().get(pk=periodo.pk)
    area = Area.objects.get(pk=area.pk)
    if periodo.estado != Periodo.Estado.ABIERTO:
        raise ValidationError({"periodo": "Solo se puede crear una proyección en un periodo abierto."})
    if not area.activa:
        raise ValidationError({"area": "Solo se puede proyectar un área activa."})
    if ProyeccionArea.objects.filter(periodo=periodo, area=area).exists():
        raise ValidationError({"area": "El área ya tiene una proyección para este periodo."})
    return guardar_proyeccion_area(
        ProyeccionArea(periodo=periodo, area=area),
        actor=actor,
        motivo=motivo,
        request=request,
        accion_modificar="proyeccion_area.creada",
    )


@transaction.atomic
def cambiar_estado_periodo(periodo, estado, *, actor, motivo, request=None):
    """Cierra o reabre un periodo, siempre con motivo y bitácora."""
    _validar_motivo(motivo)
    if estado not in (Periodo.Estado.ABIERTO, Periodo.Estado.CERRADO):
        raise ValidationError({"estado": "El estado del periodo no es válido."})
    periodo = Periodo.objects.select_for_update().get(pk=periodo.pk)
    if periodo.estado == estado:
        etiqueta = "abierto" if estado == Periodo.Estado.ABIERTO else "cerrado"
        raise ValidationError({"estado": f"El periodo ya está {etiqueta}."})
    periodo.estado = estado
    accion = "periodo.abierto" if estado == Periodo.Estado.ABIERTO else "periodo.cerrado"
    guardar_periodo(periodo, actor=actor, motivo=motivo, request=request, accion_modificar=accion)
    return periodo


def cerrar_periodo(periodo, *, actor, motivo, request=None):
    return cambiar_estado_periodo(
        periodo,
        Periodo.Estado.CERRADO,
        actor=actor,
        motivo=motivo,
        request=request,
    )


def reabrir_periodo(periodo, *, actor, motivo, request=None):
    return cambiar_estado_periodo(
        periodo,
        Periodo.Estado.ABIERTO,
        actor=actor,
        motivo=motivo,
        request=request,
    )


@transaction.atomic
def eliminar_linea(linea, *, actor, motivo, request=None):
    """Elimina una línea del borrador y registra sus valores anteriores."""
    _validar_motivo(motivo)
    linea = (
        Linea.objects.select_for_update()
        .select_related("proyeccion__periodo", "proyeccion__area", "unidad")
        .get(pk=linea.pk)
    )
    validar_no_aprobada(linea.proyeccion_id)
    validar_proyeccion_editable(linea.proyeccion, actor)
    anterior = instantanea(linea, CAMPOS_AUDITADOS_LINEA)
    registro = registrar(
        "linea.eliminada",
        actor=actor,
        objeto=linea,
        anterior=anterior,
        nuevo=None,
        motivo=motivo,
        request=request,
    )
    linea.delete()
    return registro


@transaction.atomic
def guardar_lineas_borrador(proyeccion, formset, *, actor, motivo, request=None, enviar=False):
    """Guarda cambios del formset y, si se solicita, envía la proyección."""
    _validar_motivo(motivo)
    proyeccion = (
        ProyeccionArea.objects.select_for_update()
        .select_related("periodo", "area")
        .get(pk=proyeccion.pk)
    )
    validar_proyeccion_editable(proyeccion, actor)
    if not formset.is_valid():
        raise ValidationError({"lineas": "Corrija los errores de las líneas antes de guardar."})

    lineas_guardadas = formset.save(commit=False)
    lineas_eliminadas = list(formset.deleted_objects)
    ids_eliminados = [linea.pk for linea in lineas_eliminadas if linea.pk]
    cantidad_resultante = proyeccion.lineas.exclude(pk__in=ids_eliminados).count()
    cantidad_resultante += sum(1 for linea in lineas_guardadas if linea.pk is None)
    if enviar and cantidad_resultante == 0:
        raise ValidationError({"lineas": "Para enviar la proyección debe existir al menos una línea."})

    for linea in lineas_eliminadas:
        eliminar_linea(linea, actor=actor, motivo=motivo, request=request)
    for linea in lineas_guardadas:
        linea.proyeccion = proyeccion
        guardar_linea(linea, actor=actor, motivo=motivo, request=request)

    if enviar:
        proyeccion.estado = ProyeccionArea.Estado.ENVIADA
        proyeccion.fecha_envio = timezone.now()
        proyeccion.enviado_por = actor
        guardar_proyeccion_area(
            proyeccion,
            actor=actor,
            motivo=motivo,
            request=request,
            accion_modificar="proyeccion_area.enviada",
            permitir_envio=True,
        )
    return proyeccion


@transaction.atomic
def guardar_periodo(
    periodo,
    *,
    actor,
    motivo,
    request=None,
    accion_crear="periodo.creado",
    accion_modificar="periodo.modificado",
):
    """Guarda un periodo y registra su creación o modificación."""
    _validar_motivo(motivo)
    periodo.full_clean()
    return guardar_con_bitacora(
        periodo,
        CAMPOS_AUDITADOS_PERIODO,
        accion_crear=accion_crear,
        accion_modificar=accion_modificar,
        actor=actor,
        motivo=motivo,
        request=request,
    )


@transaction.atomic
def guardar_proyeccion_area(
    proyeccion,
    *,
    actor,
    motivo,
    request=None,
    accion_modificar="proyeccion_area.modificada",
    permitir_envio=False,
):
    """Guarda una proyección de área y registra el cambio."""
    _validar_motivo(motivo)
    validar_no_aprobada(proyeccion.pk)
    validar_edicion_coordinador(proyeccion, actor)
    if (
        getattr(actor, "rol", None) == Rol.COORDINADOR
        and proyeccion.estado != ProyeccionArea.Estado.BORRADOR
        and not permitir_envio
    ):
        raise ValidationError({"proyeccion": "La proyección ya fue enviada y está en solo lectura."})
    proyeccion.full_clean()
    return guardar_con_bitacora(
        proyeccion,
        CAMPOS_AUDITADOS_PROYECCION_AREA,
        accion_crear="proyeccion_area.creada",
        accion_modificar=accion_modificar,
        actor=actor,
        motivo=motivo,
        request=request,
    )


@transaction.atomic
def guardar_linea(linea, *, actor, motivo, request=None, accion_modificar="linea.modificada"):
    """Guarda una línea de proyección y registra el cambio."""
    _validar_motivo(motivo)
    validar_no_aprobada(linea.proyeccion_id)
    validar_edicion_coordinador(linea.proyeccion, actor)
    if (
        getattr(actor, "rol", None) == Rol.COORDINADOR
        and linea.proyeccion.estado != ProyeccionArea.Estado.BORRADOR
    ):
        raise ValidationError({"proyeccion": "La proyección ya fue enviada y está en solo lectura."})
    linea.full_clean()
    validar_unidad_de_linea(linea)
    return guardar_con_bitacora(
        linea,
        CAMPOS_AUDITADOS_LINEA,
        accion_crear="linea.creada",
        accion_modificar=accion_modificar,
        actor=actor,
        motivo=motivo,
        request=request,
    )


@transaction.atomic
def guardar_unidad(unidad, *, actor, motivo, request=None, accion_modificar="unidad.modificada"):
    unidad.full_clean()
    return guardar_con_bitacora(
        unidad,
        CAMPOS_AUDITADOS_UNIDAD,
        accion_crear="unidad.creada",
        accion_modificar=accion_modificar,
        actor=actor,
        motivo=motivo,
        request=request,
    )


def cambiar_estado_unidad(unidad, activa, *, actor, motivo, request=None):
    """Activa o desactiva una unidad. Los productos que la usan la conservan."""
    unidad.activa = activa
    return guardar_unidad(
        unidad,
        actor=actor,
        motivo=motivo,
        request=request,
        accion_modificar="unidad.activada" if activa else "unidad.desactivada",
    )


def _validar_unidad_activa(objeto, campo):
    """Solo se puede elegir una unidad activa; sí se conserva la que el objeto ya
    tenía guardada aunque después se haya desactivado."""
    unidad_id = getattr(objeto, f"{campo}_id")
    if unidad_id is None or UnidadMedida.objects.filter(pk=unidad_id, activa=True).exists():
        return
    anterior = None
    if objeto.pk:
        anterior = type(objeto).objects.filter(pk=objeto.pk).values_list(f"{campo}_id", flat=True).first()
    if anterior != unidad_id:
        raise ValidationError({campo: "La unidad seleccionada está inactiva. Elija una unidad activa."})


def validar_unidad_del_producto(producto):
    _validar_unidad_activa(producto, "unidad_por_defecto")


def validar_unidad_de_linea(linea):
    _validar_unidad_activa(linea, "unidad")


@transaction.atomic
def guardar_producto(producto, *, actor, motivo, request=None, accion_modificar="producto.modificado"):
    producto.full_clean()
    validar_unidad_del_producto(producto)
    return guardar_con_bitacora(
        producto,
        CAMPOS_AUDITADOS_PRODUCTO,
        accion_crear="producto.creado",
        accion_modificar=accion_modificar,
        actor=actor,
        motivo=motivo,
        request=request,
    )


def cambiar_estado_producto(producto, activo, *, actor, motivo, request=None):
    producto.activo = activo
    return guardar_producto(
        producto,
        actor=actor,
        motivo=motivo,
        request=request,
        accion_modificar="producto.activado" if activo else "producto.desactivado",
    )


def unidades_para_producto(producto=None):
    """Unidades que se ofrecen al elegir la unidad de un producto: las activas
    y, si el producto ya tiene una inactiva, también esa."""
    consulta = UnidadMedida.objects.filter(activa=True)
    if producto is not None and producto.unidad_por_defecto_id:
        consulta = UnidadMedida.objects.filter(activa=True) | UnidadMedida.objects.filter(
            pk=producto.unidad_por_defecto_id
        )
    return consulta.order_by("nombre")


# --- Revisión por administración (GDS-PRY-04) ----------------------------------------

CAMPOS_CORREGIBLES_LINEA = [
    "producto_servicio",
    "dependencia",
    "unidad",
    *CAMPOS_CANTIDADES_MENSUALES,
    "precio_estimado",
]

_DECIMAL_COSTO = DecimalField(max_digits=30, decimal_places=2)


def _expresion_costo(prefijo=""):
    """Costo de una línea en la base: (suma de los 12 meses) × precio, sin pasar por float.

    El primer término se convierte a bigint para que la suma de los meses no desborde un int.
    """
    primero, *resto = CAMPOS_CANTIDADES_MENSUALES
    cantidades = Cast(F(f"{prefijo}{primero}"), BigIntegerField())
    for campo in resto:
        cantidades = cantidades + F(f"{prefijo}{campo}")
    return ExpressionWrapper(cantidades * F(f"{prefijo}precio_estimado"), output_field=_DECIMAL_COSTO)


def _exigir_administracion(actor):
    """Defensa en profundidad: además del decorador de la vista, el servicio exige el rol."""
    if getattr(actor, "rol", None) not in ROLES_ADMIN or not getattr(actor, "is_active", False):
        raise PermissionDenied("Solo administración puede revisar proyecciones.")


def filtrar_proyecciones(*, periodo=None, area=None, estado=None):
    """Proyecciones de todas las áreas, filtradas por periodo, área y estado."""
    consulta = ProyeccionArea.objects.all()
    if periodo is not None:
        consulta = consulta.filter(periodo=periodo)
    if area is not None:
        consulta = consulta.filter(area=area)
    if estado:
        consulta = consulta.filter(estado=estado)
    return consulta


def resumen_revision(consulta):
    """Agrega a cada proyección su número de líneas y su costo total (Decimal)."""
    return (
        consulta.select_related("periodo", "area", "enviado_por")
        .annotate(
            numero_lineas=Count("lineas"),
            costo_total=Coalesce(Sum(_expresion_costo("lineas__")), Value(Decimal("0")), output_field=_DECIMAL_COSTO),
        )
        .order_by("-periodo__anio", "area__nombre")
    )


def anotar_costos_vigentes(proyecciones):
    from proyecciones import consolidado

    ids = [p.pk for p in proyecciones]
    costos = {f["proyeccion"].pk: f["costo_ajustado"]
              for f in consolidado.filas_por_area(ProyeccionArea.objects.filter(pk__in=ids))}
    for proyeccion in proyecciones:
        proyeccion.costo_vigente = costos[proyeccion.pk]


def costo_total(consulta):
    """Costo total de todas las líneas de las proyecciones indicadas."""
    return Linea.objects.filter(proyeccion__in=consulta.values("pk")).aggregate(
        total=Coalesce(Sum(_expresion_costo()), Value(Decimal("0")), output_field=_DECIMAL_COSTO)
    )["total"]


@transaction.atomic
def corregir_linea(linea, *, actor, motivo, request=None):
    """Administración corrige una línea de una proyección enviada.

    `linea` llega con los valores nuevos ya asignados (sin guardar). La bitácora guarda el
    autor, los campos que cambiaron con su valor anterior y nuevo, y el motivo como justificación.
    """
    _exigir_administracion(actor)
    _validar_motivo(motivo)
    proyeccion_guardada = Linea.objects.filter(pk=linea.pk).values_list("proyeccion_id", flat=True).first()
    if linea.pk is None or proyeccion_guardada is None or proyeccion_guardada != linea.proyeccion_id:
        raise ValidationError("La línea no pertenece a esta proyección.")
    proyeccion = (
        ProyeccionArea.objects.select_for_update().select_related("periodo", "area").get(pk=proyeccion_guardada)
    )
    if proyeccion.estado != ProyeccionArea.Estado.ENVIADA:
        raise ValidationError("Solo se pueden corregir líneas de una proyección enviada.")
    linea.proyeccion = proyeccion
    linea.full_clean()
    validar_unidad_de_linea(linea)
    registro = guardar_con_bitacora(
        linea,
        CAMPOS_AUDITADOS_LINEA,
        accion_crear="linea.creada",
        accion_modificar="linea.corregida",
        actor=actor,
        motivo=motivo,
        request=request,
    )
    if registro is None:
        raise ValidationError("No hay cambios para guardar: los valores son iguales a los actuales.")
    return registro


def devolucion_habilitada():
    """Decisión D-01 (pendiente): se lee del parámetro editable; por defecto, Sí."""
    return bool(servicios_parametros.obtener(PERMITIR_DEVOLUCION))


@transaction.atomic
def devolver_proyeccion(proyeccion, *, actor, motivo, request=None):
    """Devuelve una proyección enviada al área: vuelve a borrador para que la corrija.

    Se limpian la fecha y el usuario de envío; sus valores anteriores quedan en la bitácora.
    """
    _exigir_administracion(actor)
    _validar_motivo(motivo)
    if not devolucion_habilitada():
        raise ValidationError(
            "La devolución de proyecciones al área está desactivada (parámetro D-01). "
            "Puede corregir las líneas directamente."
        )
    proyeccion = ProyeccionArea.objects.select_for_update().select_related("periodo", "area").get(pk=proyeccion.pk)
    if proyeccion.estado != ProyeccionArea.Estado.ENVIADA:
        raise ValidationError("Solo se puede devolver una proyección enviada.")
    if proyeccion.periodo.estado != Periodo.Estado.ABIERTO:
        raise ValidationError(
            "El periodo está cerrado y el área no podría corregir la proyección. "
            "Reabra el periodo antes de devolverla."
        )
    proyeccion.estado = ProyeccionArea.Estado.BORRADOR
    proyeccion.fecha_envio = None
    proyeccion.enviado_por = None
    guardar_proyeccion_area(
        proyeccion,
        actor=actor,
        motivo=motivo,
        request=request,
        accion_modificar="proyeccion_area.devuelta",
    )
    return proyeccion


def historial_proyeccion(proyeccion):
    """Registros de bitácora de la proyección y de todas sus líneas, también las ya quitadas."""
    tipo_proyeccion = ContentType.objects.get_for_model(ProyeccionArea)
    tipo_linea = ContentType.objects.get_for_model(Linea)
    ids_lineas = {str(pk) for pk in proyeccion.lineas.values_list("pk", flat=True)}
    ids_lineas.update(
        RegistroBitacora.objects.filter(tipo_objeto=tipo_linea)
        .filter(Q(valor_nuevo__proyeccion__id=proyeccion.pk) | Q(valor_anterior__proyeccion__id=proyeccion.pk))
        .values_list("objeto_id", flat=True)
    )
    return (
        RegistroBitacora.objects.filter(
            Q(tipo_objeto=tipo_proyeccion, objeto_id=str(proyeccion.pk))
            | Q(tipo_objeto=tipo_linea, objeto_id__in=ids_lineas)
        )
        .select_related("actor", "tipo_objeto")
        .order_by("-fecha", "-id")
    )


def ultima_devolucion(proyeccion):
    """Último registro de devolución de la proyección (para mostrar el motivo al área)."""
    return (
        RegistroBitacora.objects.filter(
            tipo_objeto=ContentType.objects.get_for_model(ProyeccionArea),
            objeto_id=str(proyeccion.pk),
            accion="proyeccion_area.devuelta",
        )
        .select_related("actor")
        .order_by("-fecha", "-id")
        .first()
    )


# --- Aprobación, cantidad autorizada y ajustes (GDS-PRY-05) ---------------------------


def aprobaciones_requeridas():
    """Decisión D-01 (pendiente): número de aprobaciones; por defecto 1 y nunca menos de 1."""
    return max(1, int(servicios_parametros.obtener(APROBACIONES_REQUERIDAS)))


def aprobaciones_vigentes(proyeccion):
    """Aprobaciones del envío actual. Las de envíos anteriores (antes de una devolución) no cuentan."""
    if proyeccion.fecha_envio is None:
        return AprobacionProyeccion.objects.none()
    return (
        AprobacionProyeccion.objects.filter(proyeccion=proyeccion, fecha_envio_aprobada=proyeccion.fecha_envio)
        .select_related("usuario")
        .order_by("fecha", "id")
    )


def _bloquear_enviada(proyeccion):
    proyeccion = ProyeccionArea.objects.select_for_update().select_related("periodo", "area").get(pk=proyeccion.pk)
    if proyeccion.estado != ProyeccionArea.Estado.ENVIADA:
        raise ValidationError("Solo se puede autorizar y aprobar una proyección enviada.")
    return proyeccion


@transaction.atomic
def guardar_cantidades_autorizadas(proyeccion, cantidades, *, actor, motivo, request=None):
    """Registra la cantidad autorizada de las líneas indicadas: {id_linea: entero o None}.

    None significa «valor por defecto»: el total anual de la línea. Devuelve cuántas cambiaron.
    """
    _exigir_administracion(actor)
    _validar_motivo(motivo)
    proyeccion = _bloquear_enviada(proyeccion)
    lineas = {linea.pk: linea for linea in proyeccion.lineas.select_for_update()}
    if set(cantidades) - set(lineas):
        raise ValidationError("Una de las líneas no pertenece a esta proyección.")
    cambios = 0
    for pk, valor in cantidades.items():
        linea = lineas[pk]
        valor = linea.total_anual if valor is None else valor
        if isinstance(valor, bool) or not isinstance(valor, int) or valor < 0:
            raise ValidationError(
                {"cantidad_autorizada": "La cantidad autorizada debe ser un número entero no negativo."}
            )
        if linea.cantidad_autorizada == valor:
            continue
        linea.cantidad_autorizada = valor
        linea.proyeccion = proyeccion
        guardar_linea(
            linea,
            actor=actor,
            motivo=motivo,
            request=request,
            accion_modificar="linea.cantidad_autorizada",
        )
        cambios += 1
    return cambios


@transaction.atomic
def aprobar_proyeccion(proyeccion, *, actor, motivo, cantidades=None, request=None):
    """Registra la aprobación de un administrador. Devuelve (proyección, quedó_aprobada).

    Con las aprobaciones requeridas (D-01, por defecto 1) la proyección pasa a aprobada con
    fecha y usuario; las líneas sin cantidad autorizada toman su total anual. Desde ese
    momento la edición ordinaria queda bloqueada y los cambios se registran como ajustes.
    """
    _exigir_administracion(actor)
    _validar_motivo(motivo)
    proyeccion = _bloquear_enviada(proyeccion)
    if not proyeccion.lineas.exists():
        raise ValidationError("La proyección no tiene líneas para aprobar.")
    if cantidades:
        guardar_cantidades_autorizadas(proyeccion, cantidades, actor=actor, motivo=motivo, request=request)
    if aprobaciones_vigentes(proyeccion).filter(usuario=actor).exists():
        raise ValidationError("Usted ya aprobó este envío; falta la aprobación de otro administrador.")

    aprobacion = AprobacionProyeccion(
        proyeccion=proyeccion,
        usuario=actor,
        fecha_envio_aprobada=proyeccion.fecha_envio,
        motivo=motivo,
    )
    aprobacion.full_clean()
    aprobacion.save()
    total, requeridas = aprobaciones_vigentes(proyeccion).count(), aprobaciones_requeridas()
    registrar(
        "proyeccion_area.aprobacion_registrada",
        actor=actor,
        objeto=proyeccion,
        nuevo={"aprobaciones": total, "requeridas": requeridas},
        motivo=motivo,
        request=request,
    )
    if total < requeridas:
        return proyeccion, False

    sin_autorizar = {pk: None for pk in proyeccion.lineas.filter(cantidad_autorizada=None).values_list("pk", flat=True)}
    if sin_autorizar:
        guardar_cantidades_autorizadas(proyeccion, sin_autorizar, actor=actor, motivo=motivo, request=request)
    proyeccion.estado = ProyeccionArea.Estado.APROBADA
    proyeccion.fecha_aprobacion = timezone.now()
    proyeccion.aprobado_por = actor
    guardar_proyeccion_area(
        proyeccion,
        actor=actor,
        motivo=motivo,
        request=request,
        accion_modificar="proyeccion_area.aprobada",
    )
    return proyeccion, True


def _valor_de_campo(campo, valor):
    """Convierte un valor guardado en JSON (p. ej. "12.50") al tipo del campo de la línea."""
    return None if valor is None else Linea._meta.get_field(campo).to_python(valor)


def valores_vigentes(linea, ajustes=None):
    """{campo ajustable: valor vigente}: el aprobado, reemplazado por el último ajuste de cada campo."""
    vigentes = {campo: getattr(linea, campo) for campo in CAMPOS_AJUSTABLES}
    ajustes = linea.ajustes.all() if ajustes is None else ajustes
    for ajuste in sorted(ajustes, key=lambda a: (a.fecha, a.pk)):
        if ajuste.campo in vigentes:
            vigentes[ajuste.campo] = _valor_de_campo(ajuste.campo, ajuste.valor_nuevo)
    return vigentes


def anotar_vigentes(lineas):
    """Agrega a cada línea sus valores vigentes, total y costo vigentes, y si tiene ajustes.

    Conviene pasar las líneas con `prefetch_related("ajustes")`.
    """
    lineas = list(lineas)
    for linea in lineas:
        vigente = valores_vigentes(linea)
        linea.vigente = vigente
        linea.total_vigente = sum(vigente[campo] or 0 for campo in CAMPOS_CANTIDADES_MENSUALES)
        linea.costo_vigente = Decimal(linea.total_vigente) * (vigente["precio_estimado"] or Decimal("0"))
        linea.campos_ajustados = {campo for campo in CAMPOS_AJUSTABLES if vigente[campo] != getattr(linea, campo)}
    return lineas


@transaction.atomic
def registrar_ajuste(linea, campo, valor_nuevo, *, actor, justificacion, request=None):
    """Ajuste justificado de una línea aprobada. La línea conserva el valor aprobado.

    El ajuste guarda el valor aprobado, el vigente antes del ajuste y el nuevo; además queda
    en la bitácora (`linea.ajustada`) con el autor y la justificación como motivo.
    """
    _exigir_administracion(actor)
    justificacion = (justificacion or "").strip()
    if not justificacion:
        raise ValidationError({"justificacion": "La justificación es obligatoria."})
    if campo not in CAMPOS_AJUSTABLES:
        raise ValidationError({"campo": "Ese campo no se puede ajustar."})
    linea = Linea.objects.get(pk=linea.pk)
    proyeccion = ProyeccionArea.objects.select_for_update().get(pk=linea.proyeccion_id)
    if proyeccion.estado != ProyeccionArea.Estado.APROBADA:
        raise ValidationError("Solo se pueden ajustar líneas de una proyección aprobada.")
    linea.proyeccion = proyeccion
    if valor_nuevo is None or str(valor_nuevo).strip() == "":
        raise ValidationError({"valor_nuevo": "Indique el nuevo valor."})
    try:
        valor = Linea._meta.get_field(campo).clean(str(valor_nuevo).strip(), linea)
    except ValidationError as error:
        raise ValidationError({"valor_nuevo": error.messages}) from None

    vigente = valores_vigentes(linea)[campo]
    if valor == vigente:
        raise ValidationError({"valor_nuevo": "El valor es igual al vigente; no hay cambios para registrar."})
    ajuste = Ajuste(
        linea=linea,
        campo=campo,
        valor_aprobado=getattr(linea, campo),
        valor_anterior=vigente,
        valor_nuevo=valor,
        justificacion=justificacion,
        usuario=actor,
    )
    ajuste.full_clean()
    ajuste.save()
    registrar(
        "linea.ajustada",
        actor=actor,
        objeto=linea,
        anterior={campo: vigente},
        nuevo={campo: valor},
        motivo=justificacion,
        request=request,
    )
    return ajuste
