"""Lectura y modificación de parámetros editables. Toda modificación queda en la bitácora."""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from bitacora.servicios import guardar_con_bitacora
from cuentas.models import ROLES_ADMIN
from parametros.catalogo import DEFINICIONES
from parametros.models import Parametro


def obtener(clave):
    """Valor tipado del parámetro; si aún no está en la base, su valor por defecto documentado."""
    parametro = Parametro.objects.filter(clave=clave).first()
    if parametro is not None:
        return parametro.valor_tipado
    try:
        definicion = DEFINICIONES[clave]
    except KeyError:
        raise LookupError(f"Parámetro desconocido: {clave}") from None
    return Parametro.convertir(definicion.tipo, definicion.valor_por_defecto)


@transaction.atomic
def cambiar_valor(parametro, valor, *, actor, motivo, request=None):
    """Cambia el valor de un parámetro. Solo administración; motivo obligatorio."""
    if getattr(actor, "rol", None) not in ROLES_ADMIN:
        raise PermissionDenied("Solo administración puede modificar parámetros.")
    if not (motivo or "").strip():
        raise ValidationError({"motivo": "El motivo es obligatorio."})
    parametro = Parametro.objects.select_for_update().get(pk=parametro.pk)
    convertido = Parametro.convertir(parametro.tipo, str(valor))
    definicion = DEFINICIONES.get(parametro.clave)
    if definicion and definicion.minimo is not None and convertido < definicion.minimo:
        raise ValidationError({"valor": f"El valor mínimo es {definicion.minimo}."})
    if definicion and definicion.validador is not None:
        convertido = definicion.validador(convertido)
    parametro.valor = Parametro.a_texto(parametro.tipo, convertido)
    parametro.full_clean()
    registro = guardar_con_bitacora(
        parametro,
        ["valor"],
        accion_crear="parametro.creado",
        accion_modificar="parametro.modificado",
        actor=actor,
        motivo=motivo,
        request=request,
    )
    if registro is None:
        raise ValidationError({"valor": "El valor es igual al actual; no hay cambios para guardar."})
    return parametro
