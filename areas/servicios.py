"""Reglas de negocio de áreas."""

from django.core.exceptions import ValidationError
from django.db import transaction

from areas.models import Area
from bitacora.servicios import guardar_con_bitacora
from cuentas.models import Rol, Usuario

CAMPOS_AUDITADOS_AREA = ["nombre", "codigo_area", "activa"]


def coordinadores_activos(area):
    return Usuario.objects.filter(area=area, rol=Rol.COORDINADOR, activo=True).order_by("nombre")


def mensaje_bloqueo_desactivacion(area):
    """Texto del error si el área no se puede desactivar; None si sí se puede."""
    cantidad = coordinadores_activos(area).count() if area.pk else 0
    if not cantidad:
        return None
    plural = "coordinador activo" if cantidad == 1 else "coordinadores activos"
    return (
        f"No se puede desactivar el área porque tiene {cantidad} {plural}. "
        "Reasígnelos a otra área o desactívelos primero."
    )


def validar_desactivacion(area):
    """Bloquea desactivar un área que todavía tiene coordinadores activos."""
    if area.activa or not area.pk:
        return
    estaba_activa = Area.objects.filter(pk=area.pk, activa=True).exists()
    mensaje = mensaje_bloqueo_desactivacion(area) if estaba_activa else None
    if mensaje:
        raise ValidationError(mensaje)


@transaction.atomic
def guardar_area(area, *, actor, motivo, request=None, accion_modificar="area.modificada"):
    """Crea o modifica un área y deja en la bitácora qué cambió y por qué."""
    area.full_clean()
    validar_desactivacion(area)
    return guardar_con_bitacora(
        area,
        CAMPOS_AUDITADOS_AREA,
        accion_crear="area.creada",
        accion_modificar=accion_modificar,
        actor=actor,
        motivo=motivo,
        request=request,
    )


def cambiar_estado_area(area, activa, *, actor, motivo, request=None):
    """Activa o desactiva un área. Desactivar no borra nada: el área, sus
    usuarios y su historial se conservan."""
    area.activa = activa
    return guardar_area(
        area,
        actor=actor,
        motivo=motivo,
        request=request,
        accion_modificar="area.activada" if activa else "area.desactivada",
    )


def coordinadores_disponibles(area):
    """Coordinadores activos de otras áreas que se pueden trasladar a esta."""
    return (
        Usuario.objects.filter(rol=Rol.COORDINADOR, activo=True)
        .exclude(area=area)
        .select_related("area")
        .order_by("nombre")
    )


@transaction.atomic
def asignar_coordinadores(area, coordinadores, *, actor, motivo, request=None):
    """Asigna los coordinadores al área. Cada coordinador tiene una sola área,
    así que asignarlo aquí lo traslada desde la suya; cada traslado queda en
    la bitácora del usuario."""
    from cuentas import servicios as servicios_cuentas

    if not area.activa:
        raise ValidationError("No se pueden asignar coordinadores a un área inactiva.")
    if not coordinadores:
        raise ValidationError("Seleccione al menos un coordinador.")
    asignados = []
    for coordinador in coordinadores:
        if coordinador.rol != Rol.COORDINADOR or not coordinador.activo:
            raise ValidationError(f"{coordinador} no es un coordinador activo.")
        if coordinador.area_id == area.pk:
            continue
        coordinador.area = area
        servicios_cuentas.guardar_usuario(
            coordinador,
            actor=actor,
            motivo=motivo,
            request=request,
            accion_modificar="usuario.coordinador_asignado",
        )
        asignados.append(coordinador)
    return asignados
