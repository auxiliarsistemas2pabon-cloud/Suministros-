import os
import re
from datetime import date, timedelta
from unittest import mock

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from bitacora.models import RegistroBitacora
from cuentas.models import Rol
from cuentas.tests.utilidades import crear_usuario
from proveedores import archivos, servicios
from proveedores.models import DocumentoProveedor
from proveedores.tests.utilidades import CONTENIDO_PDF, MOTIVO, MediaTemporal, crear_proveedor, pdf, tipo_documento

RUTA_UUID = re.compile(r"^documentos/\d{4}/\d{2}/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.pdf$")


class ValidarPdfTests(SimpleTestCase):
    def test_pdf_valido(self):
        archivos.validar_pdf(pdf())

    def test_pdf_falso_sin_cabecera_rechazado(self):
        falso = SimpleUploadedFile("factura.pdf", b"<html>no soy un PDF</html>", content_type="application/pdf")
        with self.assertRaisesMessage(ValidationError, archivos.MENSAJE_CABECERA):
            archivos.validar_pdf(falso)

    def test_cabecera_en_otra_posicion_rechazada(self):
        with self.assertRaisesMessage(ValidationError, archivos.MENSAJE_CABECERA):
            archivos.validar_pdf(SimpleUploadedFile("x.pdf", b" %PDF-1.4"))

    def test_mas_de_10_mb_rechazado(self):
        grande = SimpleUploadedFile("grande.pdf", CONTENIDO_PDF + b"0" * (archivos.TAMANO_MAXIMO + 1 - len(CONTENIDO_PDF)))
        with self.assertRaisesMessage(ValidationError, archivos.MENSAJE_TAMANO):
            archivos.validar_pdf(grande)

    def test_exactamente_10_mb_aceptado(self):
        limite = SimpleUploadedFile("limite.pdf", CONTENIDO_PDF + b"0" * (archivos.TAMANO_MAXIMO - len(CONTENIDO_PDF)))
        archivos.validar_pdf(limite)

    def test_extension_distinta_rechazada(self):
        for nombre in ("documento.exe", "documento.pdf.exe", "documento", "documento.html"):
            with self.subTest(nombre=nombre), self.assertRaisesMessage(ValidationError, archivos.MENSAJE_EXTENSION):
                archivos.validar_pdf(SimpleUploadedFile(nombre, CONTENIDO_PDF))

    def test_extension_en_mayusculas_aceptada(self):
        archivos.validar_pdf(SimpleUploadedFile("RUT.PDF", CONTENIDO_PDF))

    def test_vacio_rechazado(self):
        with self.assertRaisesMessage(ValidationError, archivos.MENSAJE_VACIO):
            archivos.validar_pdf(SimpleUploadedFile("vacio.pdf", b""))

    def test_ruta_con_anio_mes_y_uuid(self):
        self.assertTrue(RUTA_UUID.match(archivos.ruta_nueva(fecha=date(2026, 3, 9))))
        self.assertTrue(archivos.ruta_nueva(fecha=date(2026, 3, 9)).startswith("documentos/2026/03/"))
        self.assertNotEqual(archivos.ruta_nueva(), archivos.ruta_nueva())

    def test_nombre_original_sin_carpetas(self):
        self.assertEqual(archivos.nombre_original(SimpleUploadedFile("..\\..\\otro  archivo.pdf", b"")), "otro archivo.pdf")

    def test_no_borra_rutas_fuera_de_la_carpeta(self):
        with mock.patch.object(default_storage, "delete") as borrar:
            for nombre in ("", "../config/settings.py", "/etc/passwd.pdf", "documentos/../../x.pdf", "documentos/x.txt"):
                archivos.borrar_ahora(nombre)
            borrar.assert_not_called()


class DocumentosConArchivoTests(MediaTemporal, TestCase):
    def setUp(self):
        super().setUp()
        self.administrador = crear_usuario(Rol.ADMINISTRADOR, correo="admin@ejemplo.test")
        self.proveedor = crear_proveedor()
        self.tipo = tipo_documento()
        self.hoy = timezone.localdate()

    def _nuevo(self, **campos):
        datos = {
            "proveedor": self.proveedor,
            "tipo": self.tipo,
            "fecha_expedicion": self.hoy - timedelta(days=5),
            "fecha_vencimiento": self.hoy + timedelta(days=200),
        }
        datos.update(campos)
        return DocumentoProveedor(**datos)

    def _guardar(self, documento, **kwargs):
        with self.captureOnCommitCallbacks(execute=True):
            return servicios.guardar_documento(documento, actor=self.administrador, motivo=MOTIVO, **kwargs)

    def _existe(self, nombre):
        return os.path.exists(os.path.join(settings.MEDIA_ROOT, nombre))

    def test_no_crea_pdf_dentro_de_transaccion_externa_que_pueda_revertirse(self):
        with transaction.atomic(), self.assertRaisesMessage(ValidationError, "fuera de otra transacción"):
            self._guardar(self._nuevo(), archivo_subido=pdf())
        self.assertFalse(DocumentoProveedor.objects.exists())
        self.assertFalse(os.path.exists(os.path.join(settings.MEDIA_ROOT, "documentos")))

    def test_guarda_en_media_root_con_nombre_uuid_y_nombre_original_aparte(self):
        documento = self._guardar(self._nuevo(), archivo_subido=pdf("Certificación Bancaria.pdf"))
        self.assertTrue(RUTA_UUID.match(documento.archivo.name), documento.archivo.name)
        self.assertTrue(self._existe(documento.archivo.name))
        self.assertTrue(os.path.abspath(documento.archivo.path).startswith(os.path.abspath(settings.MEDIA_ROOT)))
        self.assertEqual(documento.nombre_archivo, "Certificación Bancaria.pdf")
        self.assertEqual(documento.cargado_por, self.administrador)
        registro = RegistroBitacora.objects.get(accion="documento_proveedor.creado")
        self.assertEqual(registro.valor_nuevo["archivo"], documento.archivo.name)
        self.assertEqual(registro.motivo, MOTIVO)

    def test_servicio_rechaza_pdf_falso_y_no_guarda_nada(self):
        with self.assertRaises(ValidationError) as contexto:
            self._guardar(self._nuevo(), archivo_subido=SimpleUploadedFile("falso.pdf", b"MZ ejecutable"))
        self.assertIn("archivo", contexto.exception.message_dict)
        self.assertFalse(DocumentoProveedor.objects.exists())
        self.assertFalse(os.path.exists(os.path.join(settings.MEDIA_ROOT, "documentos")))

    def test_borrar_documento_borra_su_archivo(self):
        documento = self._guardar(self._nuevo(), archivo_subido=pdf())
        nombre = documento.archivo.name
        with self.captureOnCommitCallbacks(execute=True):
            servicios.eliminar_documento(documento, actor=self.administrador, motivo=MOTIVO)
        self.assertFalse(DocumentoProveedor.objects.exists())
        self.assertFalse(self._existe(nombre))
        registro = RegistroBitacora.objects.get(accion="documento_proveedor.eliminado")
        self.assertEqual(registro.valor_anterior["archivo"], nombre)

    def test_borrar_con_queryset_tambien_borra_el_archivo(self):
        documento = self._guardar(self._nuevo(), archivo_subido=pdf())
        with self.captureOnCommitCallbacks(execute=True):
            DocumentoProveedor.objects.filter(pk=documento.pk).delete()
        self.assertFalse(self._existe(documento.archivo.name))

    def test_si_la_transaccion_se_revierte_el_archivo_se_conserva(self):
        documento = self._guardar(self._nuevo(), archivo_subido=pdf())
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            with self.assertRaises(RuntimeError), transaction.atomic():
                servicios.eliminar_documento(documento, actor=self.administrador, motivo=MOTIVO)
                # Algo falla después de borrar, dentro de la misma transacción.
                raise RuntimeError("falla de prueba")
        self.assertEqual(callbacks, [])
        self.assertTrue(DocumentoProveedor.objects.filter(pk=documento.pk).exists())
        self.assertTrue(self._existe(documento.archivo.name))

    def test_reemplazar_el_pdf_borra_el_anterior(self):
        documento = self._guardar(self._nuevo(), archivo_subido=pdf("primero.pdf"))
        anterior = documento.archivo.name
        documento = DocumentoProveedor.objects.get(pk=documento.pk)
        self._guardar(documento, archivo_subido=pdf("segundo.pdf"))
        documento.refresh_from_db()
        self.assertNotEqual(documento.archivo.name, anterior)
        self.assertFalse(self._existe(anterior))
        self.assertTrue(self._existe(documento.archivo.name))
        self.assertEqual(documento.nombre_archivo, "segundo.pdf")
        registro = RegistroBitacora.objects.get(accion="documento_proveedor.modificado")
        self.assertEqual(registro.valor_anterior["archivo"], anterior)

    def test_cambiar_el_pdf_por_un_enlace_borra_el_pdf(self):
        documento = self._guardar(self._nuevo(), archivo_subido=pdf())
        anterior = documento.archivo.name
        documento = DocumentoProveedor.objects.get(pk=documento.pk)
        documento.enlace = "https://documentos.ejemplo.test/certificado"
        self._guardar(documento)
        documento.refresh_from_db()
        self.assertEqual(documento.archivo.name, "")
        self.assertFalse(self._existe(anterior))

    def test_si_falla_el_reemplazo_se_borra_el_nuevo_y_se_conserva_el_anterior(self):
        documento = self._guardar(self._nuevo(), archivo_subido=pdf())
        anterior = documento.archivo.name
        documento = DocumentoProveedor.objects.get(pk=documento.pk)
        with mock.patch("proveedores.servicios.registrar", side_effect=RuntimeError("falla de prueba")):
            with self.assertRaises(RuntimeError):
                self._guardar(documento, archivo_subido=pdf("nuevo.pdf"))
        documento.refresh_from_db()
        self.assertEqual(documento.archivo.name, anterior)
        self.assertTrue(self._existe(anterior))
        carpeta = os.path.dirname(os.path.join(settings.MEDIA_ROOT, anterior))
        self.assertEqual(os.listdir(carpeta), [os.path.basename(anterior)])

    def test_pdf_o_enlace_obligatorio_y_no_ambos_en_la_base(self):
        with self.assertRaises(ValidationError) as contexto:
            self._guardar(self._nuevo())
        self.assertIn("PDF o un enlace", str(contexto.exception))
        documento = self._nuevo(cargado_por=self.administrador, enlace="https://documentos.ejemplo.test/a")
        documento.archivo.name = "documentos/2026/01/a.pdf"
        with self.assertRaises(ValidationError):
            documento.full_clean()


class VistaDocumentoConArchivoTests(MediaTemporal, TestCase):
    def setUp(self):
        super().setUp()
        self.administrador = crear_usuario(Rol.ADMINISTRADOR, correo="admin@ejemplo.test")
        self.proveedor = crear_proveedor()
        self.tipo = tipo_documento()
        self.client.force_login(self.administrador)
        self.url = reverse("proveedores:documento_nuevo", args=[self.proveedor.pk])
        hoy = timezone.localdate()
        self.datos = {
            "tipo": self.tipo.pk,
            "fecha_expedicion": (hoy - timedelta(days=3)).isoformat(),
            "fecha_vencimiento": (hoy + timedelta(days=300)).isoformat(),
            "enlace": "",
            "motivo": MOTIVO,
        }

    def test_cargar_pdf_y_descargarlo(self):
        with self.captureOnCommitCallbacks(execute=True):
            respuesta = self.client.post(self.url, {**self.datos, "archivo_pdf": pdf("rut.pdf")})
        self.assertRedirects(respuesta, reverse("proveedores:detalle", args=[self.proveedor.pk]))
        documento = DocumentoProveedor.objects.get()
        descarga = self.client.get(reverse("proveedores:documento_descargar", args=[self.proveedor.pk, documento.pk]))
        self.assertEqual(descarga.status_code, 200)
        self.assertEqual(b"".join(descarga.streaming_content), CONTENIDO_PDF)
        self.assertEqual(descarga["Content-Type"], "application/pdf")
        self.assertEqual(descarga["X-Content-Type-Options"], "nosniff")
        self.assertIn("attachment", descarga["Content-Disposition"])
        self.assertIn("rut.pdf", descarga["Content-Disposition"])
        self.assertIn("no-store", descarga["Cache-Control"])

    def test_pdf_falso_rechazado_en_el_formulario(self):
        falso = SimpleUploadedFile("falso.pdf", b"GIF89a imagen", content_type="application/pdf")
        respuesta = self.client.post(self.url, {**self.datos, "archivo_pdf": falso})
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "no es un PDF válido")
        self.assertFalse(DocumentoProveedor.objects.exists())

    def test_pdf_de_mas_de_10_mb_rechazado_en_el_formulario(self):
        grande = SimpleUploadedFile("grande.pdf", CONTENIDO_PDF + b"0" * archivos.TAMANO_MAXIMO)
        respuesta = self.client.post(self.url, {**self.datos, "archivo_pdf": grande})
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "supera el tamaño máximo de 10 MB")
        self.assertFalse(DocumentoProveedor.objects.exists())
        self.assertFalse(os.path.exists(os.path.join(settings.MEDIA_ROOT, "documentos")))

    def test_pdf_y_enlace_a_la_vez_rechazado(self):
        datos = {**self.datos, "archivo_pdf": pdf(), "enlace": "https://documentos.ejemplo.test/x"}
        self.assertContains(self.client.post(self.url, datos), "no ambos")
        self.assertFalse(DocumentoProveedor.objects.exists())

    def test_sin_pdf_ni_enlace_rechazado(self):
        self.assertContains(self.client.post(self.url, self.datos), "Adjunte el PDF del documento o escriba su enlace.")

    def test_eliminar_desde_la_vista_borra_el_archivo(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(self.url, {**self.datos, "archivo_pdf": pdf()})
        documento = DocumentoProveedor.objects.get()
        ruta = documento.archivo.path
        url = reverse("proveedores:documento_eliminar", args=[self.proveedor.pk, documento.pk])
        self.assertContains(self.client.post(url, {"motivo": ""}), "Indique el motivo")
        self.assertTrue(os.path.exists(ruta))
        with self.captureOnCommitCallbacks(execute=True):
            respuesta = self.client.post(url, {"motivo": MOTIVO})
        self.assertRedirects(respuesta, reverse("proveedores:detalle", args=[self.proveedor.pk]))
        self.assertFalse(os.path.exists(ruta))

    def test_archivo_faltante_en_disco_da_404(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(self.url, {**self.datos, "archivo_pdf": pdf()})
        documento = DocumentoProveedor.objects.get()
        os.remove(documento.archivo.path)
        url = reverse("proveedores:documento_descargar", args=[self.proveedor.pk, documento.pk])
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_media_no_se_publica_por_url(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(self.url, {**self.datos, "archivo_pdf": pdf()})
        nombre = DocumentoProveedor.objects.get().archivo.name
        for url in (f"/{nombre}", f"/archivos_privados/{nombre}", f"/media/{nombre}"):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)
