from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from django.urls import reverse

from bitacora.models import RegistroBitacora
from cuentas.models import Rol
from cuentas.tests.utilidades import crear_usuario
from proveedores import matrices_servicios, servicios
from proveedores.models import DocumentoProveedor, EvidenciaEvaluacion, Peso, Requisito, RespuestaEvaluacion
from proveedores.respuestas_servicios import guardar_respuesta
from proveedores.tests import test_matrices
from proveedores.tests.utilidades import CONTENIDO_PDF, MOTIVO, MediaTemporal, crear_proveedor, pdf, tipo_documento


class RespuestasTests(MediaTemporal, TestCase):
    def setUp(self):
        super().setUp()
        test_matrices.MatricesTests.setUp(self)
        matrices_servicios.publicar_version(self.version, desde=self.fecha, actor=self.admin, motivo=MOTIVO)
        self.ev = matrices_servicios.crear_evaluacion(self.proveedor, self.categoria, self.fecha, actor=self.admin, motivo=MOTIVO)
        self.url = reverse("proveedores:evaluacion_responder", args=[self.ev.pk, self.req.pk])

    def guardar(self, **cambios):
        datos = dict(respuesta="si", observacion="Verificado", confirma_na=False, actor=self.admin, motivo=MOTIVO)
        datos.update(cambios)
        return guardar_respuesta(self.ev, self.req, **datos)

    def documento(self, proveedor=None, archivo=False):
        doc = DocumentoProveedor(proveedor=proveedor or self.proveedor, tipo=tipo_documento("Ejemplo sin caducidad", False), fecha_expedicion=self.fecha)
        return servicios.guardar_documento(doc, actor=self.admin, motivo=MOTIVO, archivo_subido=pdf()) if archivo else servicios.guardar_documento(self._con_enlace(doc), actor=self.admin, motivo=MOTIVO)

    def _con_enlace(self, doc):
        doc.enlace = "https://documentos.ejemplo.test/evidencia"
        return doc

    def test_crear_corregir_conserva_unica_respuesta_y_bitacora(self):
        primera = self.guardar()
        segunda = self.guardar(respuesta="no", observacion="Corrección")
        self.assertEqual(primera.pk, segunda.pk)
        self.assertEqual(RespuestaEvaluacion.objects.count(), 1)
        registro = RegistroBitacora.objects.get(accion="respuesta.modificada")
        self.assertEqual(registro.valor_anterior["respuesta"], "si")
        self.assertEqual(registro.valor_nuevo["respuesta"], "no")
        self.assertEqual(segunda.respondido_por, self.admin)
        self.assertIsNotNone(segunda.fecha)

    def test_na_exige_confirmacion_y_observacion(self):
        for confirmado, observacion in ((False, "Motivo"), (True, " ")):
            with self.assertRaises(ValidationError):
                self.guardar(respuesta="na", confirma_na=confirmado, observacion=observacion)
        self.assertEqual(self.guardar(respuesta="na", confirma_na=True, observacion="No aplica al servicio").respuesta, "na")

    def test_documento_de_otro_proveedor_rechazado(self):
        ajeno = self.documento(crear_proveedor())
        with self.assertRaises(ValidationError):
            self.guardar(documento=ajeno)
        self.client.force_login(self.admin)
        respuesta = self.client.post(self.url, {"respuesta": "si", "documento": ajeno.pk, "motivo": MOTIVO})
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(RespuestaEvaluacion.objects.exists())

    def test_requisito_de_otra_version_no_se_puede_responder(self):
        copia = matrices_servicios.copiar_version(self.version, actor=self.admin, motivo=MOTIVO)
        ajeno = copia.requisitos.get(numero=1)
        with self.assertRaises(ValidationError):
            guardar_respuesta(self.ev, ajeno, respuesta="si", observacion="", confirma_na=False, actor=self.admin, motivo=MOTIVO)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("proveedores:evaluacion_responder", args=[self.ev.pk, ajeno.pk])).status_code, 404)

    def test_pdf_privado_reemplazo_conserva_archivos_anteriores(self):
        registro = self.guardar(archivo=pdf("primero.pdf"))
        primero = registro.evidencia_pdf
        self.guardar(archivo=pdf("segundo.pdf"))
        self.assertTrue(Path(primero.archivo.path).exists())
        self.assertEqual(EvidenciaEvaluacion.objects.count(), 2)
        self.assertEqual(len(list(Path(settings.MEDIA_ROOT).rglob("*.pdf"))), 2)
        self.assertRegex(primero.archivo.name, r"^evidencias/\d{4}/\d{2}/[0-9a-f-]{36}\.pdf$")

    def test_documento_y_pdf_pueden_usarse_juntos(self):
        doc = self.documento()
        registro = self.guardar(documento=doc, archivo=pdf())
        self.assertEqual(registro.documento, doc)
        self.assertTrue(registro.evidencia_pdf_id)
        with self.assertRaises(ValidationError):
            servicios.eliminar_documento(doc, actor=self.admin, motivo=MOTIVO)

    def test_pdf_documental_original_se_conserva_y_descarga_tras_reemplazo(self):
        doc = self.documento(archivo=True)
        registro = self.guardar(documento=doc)
        anterior = Path(doc.archivo.path)
        with self.captureOnCommitCallbacks(execute=True):
            servicios.guardar_documento(doc, actor=self.admin, motivo=MOTIVO, archivo_subido=pdf("nuevo.pdf"))
        self.assertTrue(anterior.exists())
        self.client.force_login(self.admin)
        url = reverse("proveedores:respuesta_documento", args=[self.ev.pk, registro.pk])
        respuesta = self.client.get(url)
        self.assertEqual(b"".join(respuesta.streaming_content), CONTENIDO_PDF)

    def test_pdf_invalido_y_fallo_de_bitacora_no_dejan_huerfanos(self):
        with self.assertRaises(ValidationError):
            self.guardar(archivo=pdf("no.txt"))
        with patch("proveedores.respuestas_servicios.registrar", side_effect=RuntimeError("Fallo simulado")), self.assertRaises(RuntimeError):
            self.guardar(archivo=pdf())
        self.assertFalse(RespuestaEvaluacion.objects.exists())
        self.assertFalse(EvidenciaEvaluacion.objects.exists())
        self.assertEqual(list(Path(settings.MEDIA_ROOT).rglob("*.pdf")), [])

    def test_pdf_rechaza_transaccion_externa(self):
        with transaction.atomic(), self.assertRaises(ValidationError):
            self.guardar(archivo=pdf())

    def test_permisos_en_get_post_y_servicio(self):
        registro = self.guardar(documento=self.documento(archivo=True), archivo=pdf())
        rutas = [self.url, reverse("proveedores:evaluacion_evidencia", args=[self.ev.pk, registro.evidencia_pdf_id]),
                 reverse("proveedores:respuesta_documento", args=[self.ev.pk, registro.pk])]
        for rol in (Rol.COORDINADOR, Rol.PROVEEDOR):
            usuario = crear_usuario(rol)
            self.client.force_login(usuario)
            for url in rutas:
                self.assertEqual(self.client.get(url).status_code, 403)
                self.assertEqual(self.client.post(url, {}).status_code, 403)
            with self.assertRaises(PermissionDenied):
                self.guardar(actor=usuario)
        self.client.logout()
        for url in rutas:
            self.assertEqual(self.client.get(url).status_code, 302)

    def test_descarga_privada_y_id_de_otra_evaluacion_no_expuesto(self):
        registro = self.guardar(archivo=pdf())
        self.client.force_login(self.admin)
        url = reverse("proveedores:evaluacion_evidencia", args=[self.ev.pk, registro.evidencia_pdf_id])
        respuesta = self.client.get(url)
        self.assertEqual(b"".join(respuesta.streaming_content), CONTENIDO_PDF)
        self.assertEqual(respuesta["X-Content-Type-Options"], "nosniff")
        self.assertIn("private", respuesta["Cache-Control"])
        otra = matrices_servicios.crear_evaluacion(self.proveedor, self.categoria, self.fecha, actor=self.admin, motivo=MOTIVO)
        self.assertEqual(self.client.get(reverse("proveedores:evaluacion_evidencia", args=[otra.pk, registro.evidencia_pdf_id])).status_code, 404)

    def test_formulario_guardado_y_avance_agrupado(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(self.url, {"respuesta": "na", "motivo": MOTIVO}).status_code, 200)
        respuesta = self.client.post(self.url, {"respuesta": "na", "confirma_na": True, "observacion": "Justificación", "motivo": MOTIVO})
        self.assertEqual(respuesta.status_code, 302)
        detalle = self.client.get(reverse("proveedores:evaluacion_detalle", args=[self.ev.pk]))
        self.assertEqual(detalle.context["respondidos"], 1)
        self.assertEqual(detalle.context["total"], 1)
        for grupo in ("Calidad", "Ambiental", "SG-SST"):
            self.assertContains(detalle, grupo)

    def test_csrf_y_motivo_obligatorios(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(self.url, {"respuesta": "si"}).status_code, 200)
        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(self.admin)
        self.assertEqual(cliente.post(self.url, {"respuesta": "si", "motivo": MOTIVO}).status_code, 403)
        self.assertFalse(RespuestaEvaluacion.objects.exists())

    def test_restricciones_base_datos(self):
        registro = self.guardar()
        with self.assertRaises(IntegrityError), transaction.atomic():
            RespuestaEvaluacion.objects.filter(pk=registro.pk).update(respuesta="na", confirma_na=False)
        with self.assertRaises(IntegrityError), transaction.atomic():
            RespuestaEvaluacion.objects.create(evaluacion=self.ev, requisito=self.req, respuesta="no", respondido_por=self.admin)
