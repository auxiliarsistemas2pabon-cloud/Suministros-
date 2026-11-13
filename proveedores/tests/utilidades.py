"""Datos ficticios para las pruebas de proveedores (NIT inventados, correos @ejemplo.test)."""

import itertools
import shutil
import tempfile
from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone

from proveedores.models import CategoriaProveedor, DocumentoProveedor, Proveedor, TipoDocumento

MOTIVO = "Registro de prueba (caso ficticio)"
CONTENIDO_PDF = b"%PDF-1.4\n% documento ficticio\n1 0 obj << >> endobj\ntrailer << >>\n%%EOF\n"

# NIT ficticio con su dígito de verificación correcto (900123456 → 8).
NIT_FICTICIO = "900123456"
DV_FICTICIO = 8

_contador_nit = itertools.count(1)


def crear_proveedor(**campos):
    """Proveedor ficticio. Sin `nit`, usa uno nuevo en cada llamada."""
    datos = {
        "nit": str(800_000_000 + next(_contador_nit)),
        "razon_social": "Suministros Ficticios S.A.S.",
        "tipo_persona": Proveedor.TipoPersona.JURIDICA,
        "contacto_nombre": "Contacto Ficticio",
        "contacto_correo": "contacto@ejemplo.test",
        "contacto_telefono": "601 555 0100",
        "direccion": "Calle Ficticia 1 # 2-3",
    }
    datos.update(campos)
    proveedor = Proveedor(**datos)
    proveedor.full_clean()
    proveedor.save()
    return proveedor


def tipo_documento(nombre="Certificación bancaria", requiere_vencimiento=True):
    tipo, _ = TipoDocumento.objects.get_or_create(nombre=nombre, defaults={"requiere_vencimiento": requiere_vencimiento})
    return tipo


def categoria(nombre="Medicamentos"):
    return CategoriaProveedor.objects.get_or_create(nombre=nombre)[0]


def pdf(nombre="certificado.pdf", contenido=CONTENIDO_PDF):
    return SimpleUploadedFile(nombre, contenido, content_type="application/pdf")


def crear_documento_con_enlace(proveedor, cargado_por, *, tipo=None, vence_en_dias=None, expedido_hace_dias=10):
    """Documento con enlace (sin archivo) creado directamente, para pruebas de vencimiento."""
    hoy = timezone.localdate()
    return DocumentoProveedor.objects.create(
        proveedor=proveedor,
        tipo=tipo or tipo_documento(),
        fecha_expedicion=hoy - timedelta(days=expedido_hace_dias),
        fecha_vencimiento=None if vence_en_dias is None else hoy + timedelta(days=vence_en_dias),
        enlace="https://documentos.ejemplo.test/certificado",
        cargado_por=cargado_por,
    )


class MediaTemporal:
    """Mezcla para TestCase: cada prueba usa su propia carpeta temporal como MEDIA_ROOT,
    que se borra al terminar. Las subclases que definan setUp deben llamar super().setUp()."""

    def setUp(self):
        carpeta = tempfile.mkdtemp(prefix="suministros-pruebas-")
        self.addCleanup(shutil.rmtree, carpeta, ignore_errors=True)
        ajuste = override_settings(MEDIA_ROOT=carpeta)
        ajuste.enable()
        self.addCleanup(ajuste.disable)
        super().setUp()
