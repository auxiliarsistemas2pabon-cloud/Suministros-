"""Consultas del portal acotadas a la ficha de la persona autenticada."""
from django.shortcuts import get_object_or_404
from portal.servicios import ficha_de
from proveedores.models import DocumentoProveedor, EnvioProveedor
from proveedores.servicios import documentos_de


def panel(actor):
    proveedor = ficha_de(actor)
    return {"proveedor": proveedor, "envios": proveedor.envios.select_related("tipo").order_by("-fecha_envio", "-pk"),
        "documentos": documentos_de(proveedor)}


def envio_propio(actor, pk):
    return get_object_or_404(EnvioProveedor, pk=pk, proveedor=ficha_de(actor))


def documento_propio(actor, pk):
    return get_object_or_404(DocumentoProveedor, pk=pk, proveedor=ficha_de(actor))
