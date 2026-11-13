"""Archivos privados (PDF) del sistema: validación, guardado y borrado seguro.

- Se guardan en MEDIA_ROOT (archivos_privados/), que NO se publica por URL: solo se
  descargan mediante vistas que validan permisos.
- El nombre en disco es un uuid; el nombre original se guarda aparte, solo para mostrarlo.
- El borrado se programa con transaction.on_commit: si la transacción se revierte, el
  archivo sigue existiendo y el registro también.

Lo usan los documentos de proveedores y lo usarán las apps de compras (cotizaciones,
órdenes, seguimiento).
"""

import logging
import os
import re
import uuid

from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils import timezone

from config.utilidades import normalizar_espacios

registro = logging.getLogger(__name__)

TAMANO_MAXIMO = 10 * 1024 * 1024  # 10 MB
EXTENSION = ".pdf"
CABECERA = b"%PDF-"
CARPETA_DOCUMENTOS = "documentos"

MENSAJE_EXTENSION = "El archivo debe tener extensión .pdf."
MENSAJE_TAMANO = "El archivo supera el tamaño máximo de 10 MB."
MENSAJE_VACIO = "El archivo está vacío."
MENSAJE_CABECERA = "El archivo no es un PDF válido: su contenido no empieza como un PDF."


def validar_pdf(archivo):
    """ValidationError si el archivo no es un PDF aceptable (extensión, tamaño y cabecera %PDF-)."""
    nombre = getattr(archivo, "name", "") or ""
    if not nombre.lower().endswith(EXTENSION):
        raise ValidationError(MENSAJE_EXTENSION, code="pdf_extension")
    tamano = archivo.size
    if tamano > TAMANO_MAXIMO:
        raise ValidationError(MENSAJE_TAMANO, code="pdf_tamano")
    if not tamano:
        raise ValidationError(MENSAJE_VACIO, code="pdf_vacio")
    archivo.seek(0)
    cabecera = archivo.read(len(CABECERA))
    archivo.seek(0)
    if cabecera != CABECERA:
        raise ValidationError(MENSAJE_CABECERA, code="pdf_cabecera")


def ruta_nueva(carpeta=CARPETA_DOCUMENTOS, fecha=None):
    """«documentos/AAAA/MM/<uuid>.pdf» (año y mes de Bogotá)."""
    fecha = fecha or timezone.localdate()
    return f"{carpeta}/{fecha:%Y}/{fecha:%m}/{uuid.uuid4()}{EXTENSION}"


def guardar_pdf(archivo, carpeta=CARPETA_DOCUMENTOS):
    """Valida y guarda el PDF con nombre uuid. Devuelve la ruta relativa a MEDIA_ROOT."""
    validar_pdf(archivo)
    return default_storage.save(ruta_nueva(carpeta), archivo)


def nombre_original(archivo):
    """Nombre del archivo subido, sin carpetas, solo para mostrarlo y para la descarga."""
    nombre = os.path.basename((getattr(archivo, "name", "") or "").replace("\\", "/"))
    return normalizar_espacios(nombre)[:255]


_RUTA_PRIVADA = re.compile(r"^[a-z_]+/[0-9]{4}/[0-9]{2}/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.pdf$")


def _ruta_valida(nombre):
    """Solo se borran archivos con el formato exacto que crea este módulo
    (carpeta/AAAA/MM/<uuid>.pdf, relativo a MEDIA_ROOT)."""
    return bool(_RUTA_PRIVADA.fullmatch(nombre or ""))


def borrar_ahora(nombre):
    """Borra el archivo si existe. Úselo solo para deshacer un guardado que falló."""
    if not _ruta_valida(nombre):
        return
    try:
        default_storage.delete(nombre)
    except OSError:
        registro.warning("No se pudo borrar el archivo privado %s", nombre, exc_info=True)


def borrar_al_confirmar(nombre):
    """Programa el borrado del archivo para cuando la transacción actual se confirme."""
    if _ruta_valida(nombre):
        transaction.on_commit(lambda: borrar_sin_referencias(nombre))


def borrar_sin_referencias(nombre):
    """Un envío aceptado podrá compartir el PDF con su documento en A15."""
    from proveedores.models import DocumentoProveedor, EnvioProveedor, EvidenciaEvaluacion, RespuestaEvaluacion
    from bitacora.models import RegistroBitacora
    from compras.models import PdfContractual, PdfOferta, PdfProveedorUnico, PdfVerificacionOferta
    from compras.models import EvidenciaEnvioOrden, Recepcion
    from seguimientos.models import EventoSeguimiento

    if (not PdfOferta.objects.filter(archivo=nombre).exists()
            and not EvidenciaEnvioOrden.objects.filter(archivo=nombre).exists()
            and not Recepcion.objects.filter(archivo=nombre).exists()
            and not EventoSeguimiento.objects.filter(archivo=nombre).exists()
            and not PdfContractual.objects.filter(archivo=nombre).exists()
            and not PdfProveedorUnico.objects.filter(archivo=nombre).exists()
            and not PdfVerificacionOferta.objects.filter(archivo=nombre).exists()
            and not DocumentoProveedor.objects.filter(archivo=nombre).exists()
            and not EnvioProveedor.objects.filter(archivo=nombre).exists()
            and not EvidenciaEvaluacion.objects.filter(archivo=nombre).exists()
            and not RespuestaEvaluacion.objects.filter(documento_datos__archivo=nombre).exists()
            and not RegistroBitacora.objects.filter(accion__in=["respuesta.creada", "respuesta.modificada"], valor_nuevo__documento_datos__archivo=nombre).exists()):
        borrar_ahora(nombre)
