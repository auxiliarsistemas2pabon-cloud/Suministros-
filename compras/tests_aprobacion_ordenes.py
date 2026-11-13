from copy import deepcopy
from datetime import timedelta
from unittest.mock import patch
from tempfile import TemporaryDirectory

from django.core.exceptions import ValidationError, PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone

from compras import tests_ordenes, aprobacion_orden_servicios as servicios, numeracion_ordenes
from compras.models import ReglaAprobacionOrden, AprobacionOrden, EvidenciaEnvioOrden, ContadorOrdenCompra
from parametros.catalogo import AUTOAPROBAR_ORDEN, CLIENTE_ORDEN, NIT_CLIENTE_ORDEN
from parametros.models import Parametro
from parametros.servicios import cambiar_valor
from cuentas.tests.utilidades import crear_usuario

MOTIVO = "Aprobación ficticia para verificar firmas y emisión"


class DatosOrdenOperativa:
    setUp = tests_ordenes.OrdenesTests.setUp
    calificar = tests_ordenes.OrdenesTests.calificar
    asignaciones = tests_ordenes.OrdenesTests.asignaciones
    decidir = tests_ordenes.OrdenesTests.decidir
    ofertar = tests_ordenes.OrdenesTests.ofertar
    proponer = tests_ordenes.OrdenesTests.proponer
    aprobar = tests_ordenes.OrdenesTests.aprobar
    crear = tests_ordenes.OrdenesTests.crear
    guardar = tests_ordenes.OrdenesTests.guardar

    def parametro(self, clave, valor):
        cambiar_valor(Parametro.objects.get(clave=clave), valor, actor=self.admin, motivo=MOTIVO)

    def solicitar(self, orden=None):
        if orden is None:
            orden, = self.crear()
        self.parametro_si_cambia(CLIENTE_ORDEN, "Clínica ficticia de pruebas")
        self.parametro_si_cambia(NIT_CLIENTE_ORDEN, "900000001-1")
        return servicios.solicitar(orden, actor=self.admin, motivo=MOTIVO, revision_esperada=orden.revision)

    def parametro_si_cambia(self, clave, valor):
        if Parametro.objects.get(clave=clave).valor != valor:
            self.parametro(clave, valor)

    def emitir(self, orden=None):
        return servicios.votar(self.solicitar(orden), decision="aprueba", actor=self.dev, motivo=MOTIVO)


class AprobacionOrdenTests(DatosOrdenOperativa, TestCase):
    def test_no_emite_sin_firmas_ni_configuracion_cliente(self):
        orden, = self.crear()
        with self.assertRaisesMessage(ValidationError, "Configure nombre y NIT"):
            servicios.solicitar(orden, actor=self.admin, motivo=MOTIVO)
        orden = self.solicitar(orden)
        self.assertEqual(orden.estado, "en_aprobacion")
        with self.assertRaisesMessage(ValidationError, "Faltan aprobaciones"):
            numeracion_ordenes.numerar_al_emitir(orden, actor=self.admin, motivo=MOTIVO)
        self.assertEqual(ContadorOrdenCompra.objects.get(pk="global").ultimo, 0)

    def test_otro_administrador_emite_y_congela_documento(self):
        orden = self.solicitar()
        with self.assertRaisesMessage(ValidationError, "distinto"):
            servicios.votar(orden, decision="aprueba", actor=self.admin, motivo=MOTIVO)
        orden = servicios.votar(orden, decision="aprueba", actor=self.dev, motivo=MOTIVO)
        self.assertEqual((orden.estado, orden.numero), ("emitida", 1))
        self.assertEqual(orden.documento_emision["firmas"][0]["usuario_id"], self.dev.pk)
        self.assertEqual(orden.documento_emision["orden"]["revision"], orden.revision)
        foto = deepcopy(orden.documento_emision)
        self.parametro(CLIENTE_ORDEN, "Nombre ficticio posterior")
        orden.refresh_from_db()
        self.assertEqual(orden.documento_emision, foto)
        with self.assertRaises(ValidationError):
            servicios.votar(orden, decision="aprueba", actor=self.dev, motivo=MOTIVO)

    def test_rango_categoria_mayor_exigencia_conservada_hasta_completar(self):
        regla = servicios.guardar_regla(ReglaAprobacionOrden(nombre="Dos firmas ficticias", monto_desde=52, monto_hasta=53, aprobaciones=2), actor=self.admin, motivo=MOTIVO)
        orden = self.solicitar()
        regla.aprobaciones = 1
        servicios.guardar_regla(regla, actor=self.admin, motivo=MOTIVO)
        orden = servicios.votar(orden, decision="aprueba", actor=self.dev, motivo=MOTIVO)
        self.assertEqual(orden.estado, "en_aprobacion")
        self.assertIsNone(orden.numero)
        with self.assertRaises(ValidationError):
            servicios.votar(orden, decision="aprueba", actor=self.dev, motivo=MOTIVO)
        otro = crear_usuario("administrador", correo="segundo.firmante@ejemplo.test")
        orden = servicios.votar(orden, decision="aprueba", actor=otro, motivo=MOTIVO)
        self.assertEqual(orden.estado, "emitida")
        self.assertEqual(len(orden.documento_emision["firmas"]), 2)

    def test_rechazo_conserva_historial_y_nuevo_ciclo_no_reusa_firmas(self):
        orden = self.solicitar()
        orden = servicios.votar(orden, decision="rechaza", actor=self.dev, motivo=MOTIVO)
        self.assertEqual((orden.estado, orden.numero), ("borrador", None))
        orden = self.guardar(orden, condiciones_pago="Condición ficticia corregida")
        orden = self.solicitar(orden)
        self.assertEqual(orden.ciclo_aprobacion, 2)
        self.assertEqual(orden.aprobaciones.count(), 1)
        with self.assertRaises(ValidationError):
            numeracion_ordenes.numerar_al_emitir(orden, actor=self.dev, motivo=MOTIVO)
        orden = servicios.votar(orden, decision="aprueba", actor=self.dev, motivo=MOTIVO)
        self.assertEqual(orden.estado, "emitida")
        self.assertEqual(orden.aprobaciones.count(), 2)

    def test_parametro_propias_se_congela_y_permisos_revision_y_atomicidad(self):
        self.parametro(AUTOAPROBAR_ORDEN, "true")
        orden = self.solicitar()
        self.parametro(AUTOAPROBAR_ORDEN, "false")
        for actor in (self.coordinador, self.usuario_proveedor):
            with self.assertRaises(PermissionDenied):
                servicios.votar(orden, decision="aprueba", actor=actor, motivo=MOTIVO)
        with self.assertRaises(ValidationError):
            servicios.votar(orden, decision="aprueba", actor=self.admin, motivo=MOTIVO, revision_esperada=0)
        with patch("compras.numeracion_ordenes._revision", side_effect=RuntimeError("Fallo ficticio")), self.assertRaises(RuntimeError):
            servicios.votar(orden, decision="aprueba", actor=self.admin, motivo=MOTIVO)
        self.assertFalse(AprobacionOrden.objects.exists())
        self.assertEqual(ContadorOrdenCompra.objects.get(pk="global").ultimo, 0)
        orden = servicios.votar(orden, decision="aprueba", actor=self.admin, motivo=MOTIVO)
        self.assertEqual(orden.estado, "emitida")

    def test_pdf_y_pantallas_permisos_csrf_y_nombre_guardado(self):
        orden = self.emitir()
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("compras:orden_detalle", args=[orden.pk])), "Descargar orden PDF")
        pdf = self.client.get(reverse("compras:orden_imprimir", args=[orden.pk]))
        self.assertEqual(pdf["Content-Type"], "application/pdf")
        self.assertTrue(pdf.content.startswith(b"%PDF-"))
        self.assertGreater(len(pdf.content), 5000)
        self.assertEqual(self.client.get(reverse("compras:orden_reglas")).status_code, 200)
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.admin)
        self.assertEqual(csrf.post(reverse("compras:orden_aprobacion", args=[orden.pk, "aprobar"]), {"motivo": MOTIVO, "revision_esperada": orden.revision}).status_code, 403)
        self.client.force_login(self.coordinador)
        self.assertEqual(self.client.get(reverse("compras:orden_imprimir", args=[orden.pk])).status_code, 403)

    def test_evidencia_privada_inmutable_y_fallo_no_deja_archivo(self):
        orden = self.emitir()
        with TemporaryDirectory() as carpeta, override_settings(MEDIA_ROOT=carpeta):
            pdf = lambda: SimpleUploadedFile("soporte.pdf", b"%PDF-1.4 ficticio", content_type="application/pdf")
            envio = servicios.registrar_envio(orden, fecha_envio=timezone.now(), actor=self.admin, motivo=MOTIVO, archivo=pdf())
            with self.assertRaises(ValidationError):
                envio.save()
            self.client.force_login(self.admin)
            respuesta = self.client.get(reverse("compras:orden_envio_pdf", args=[orden.pk, envio.pk]))
            self.assertEqual(b"".join(respuesta.streaming_content), b"%PDF-1.4 ficticio")
            from pathlib import Path
            antes = list(Path(carpeta).rglob("*.pdf"))
            with patch("compras.aprobacion_orden_servicios.registrar", side_effect=RuntimeError("Fallo ficticio")), self.assertRaises(RuntimeError):
                servicios.registrar_envio(orden, fecha_envio=timezone.now(), actor=self.admin, motivo=MOTIVO, archivo=pdf())
            self.assertEqual(list(Path(carpeta).rglob("*.pdf")), antes)
            with self.assertRaises(ValidationError):
                servicios.registrar_envio(orden, fecha_envio=timezone.now()+timedelta(days=1), actor=self.admin, motivo=MOTIVO)
