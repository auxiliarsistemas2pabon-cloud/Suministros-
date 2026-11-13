"""Asociación real a cotizaciones y precarga sin crear registros."""
from copy import deepcopy

from django.apps import apps
from django.core.exceptions import ValidationError

from compras.models import ListaElegibles
from proveedores.servicios import _exigir_admin


def hay_cotizacion(lista):
    try:
        modelo = apps.get_model("compras", "Cotizacion")
    except LookupError:
        return False
    # La creación bloquea la misma lista que las transiciones de elegibles.
    return modelo.objects.filter(lista_elegibles_id=lista.pk).exists()


def preparar_cotizacion(lista, *, actor):
    """Datos conservados para el formulario; este servicio no crea registros."""
    _exigir_admin(actor)
    lista = ListaElegibles.objects.get(pk=lista.pk)
    if lista.estado != "cerrada":
        raise ValidationError("Solo se prepara una cotización desde una lista cerrada.")
    if not lista.resultado_cierre or lista.documental_fecha is None:
        raise ValidationError("Esta lista no tiene un cierre completo conservado. Reábrala, revísela y ciérrela antes de continuar.")
    foto = lista.resultado_cierre
    return {"lista": lista.pk, "necesidad": deepcopy(foto["necesidad"]), "base": deepcopy(foto["base"]),
            "lineas": deepcopy(foto["origenes"]),
            "invitados": [{"proveedor": f["proveedor_id"], "nit": f["nit"], "razon_social": f["razon_social"],
                           "cantidad_autorizada": f["cantidad_autorizada"]} for f in foto["filas"] if f["elegido"]]}
