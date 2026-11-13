"""Borrado seguro de los PDF de documentos de proveedor.

Funciona con cualquier forma de borrar o reemplazar (servicios, QuerySet.delete(), shell):
el archivo anterior se borra solo cuando la transacción se confirma, así que un error que
revierta la transacción no deja un registro apuntando a un archivo inexistente.
"""

from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from proveedores import archivos
from proveedores.models import DocumentoProveedor, EnvioProveedor


@receiver(pre_save, sender=DocumentoProveedor, dispatch_uid="documento_recordar_archivo_anterior")
def recordar_archivo_anterior(sender, instance, raw=False, **kwargs):
    instance._archivo_anterior = ""
    if raw or instance._state.adding or not instance.pk:
        return
    instance._archivo_anterior = (
        DocumentoProveedor.objects.filter(pk=instance.pk).values_list("archivo", flat=True).first() or ""
    )


@receiver(post_save, sender=DocumentoProveedor, dispatch_uid="documento_borrar_archivo_reemplazado")
def borrar_archivo_reemplazado(sender, instance, raw=False, **kwargs):
    anterior = getattr(instance, "_archivo_anterior", "")
    if not raw and anterior and anterior != (instance.archivo.name or ""):
        archivos.borrar_al_confirmar(anterior)
    instance._archivo_anterior = instance.archivo.name or ""


@receiver(post_delete, sender=DocumentoProveedor, dispatch_uid="documento_borrar_archivo")
def borrar_archivo_del_documento(sender, instance, **kwargs):
    archivos.borrar_al_confirmar(instance.archivo.name or "")


@receiver(post_delete, sender=EnvioProveedor, dispatch_uid="envio_borrar_archivo")
def borrar_archivo_del_envio(sender, instance, **kwargs):
    archivos.borrar_al_confirmar(instance.archivo.name or "")
