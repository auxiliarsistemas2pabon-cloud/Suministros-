from copy import deepcopy
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
from parametros.catalogo import REGLAS_FR14
from parametros.models import Parametro
from proveedores import matrices_servicios
from proveedores.evaluacion_servicios import finalizar_evaluacion, obtener_resultado
from proveedores.historial_servicios import anular_evaluacion, copiar_evaluacion
from proveedores.models import EvaluacionProveedor, RespuestaEvaluacion
from proveedores.respuestas_servicios import guardar_respuesta
from proveedores.tests import test_matrices
from proveedores.tests.utilidades import CONTENIDO_PDF, MOTIVO, MediaTemporal, pdf


class HistorialTests(MediaTemporal, TestCase):
    def setUp(self):
        super().setUp()
        test_matrices.MatricesTests.setUp(self)
        matrices_servicios.publicar_version(self.version, desde=self.fecha, actor=self.admin, motivo=MOTIVO)
        self.ev = matrices_servicios.crear_evaluacion(self.proveedor, self.categoria, self.fecha, actor=self.admin, motivo=MOTIVO)
        self.respuesta = guardar_respuesta(self.ev, self.req, respuesta="si", observacion="Verificado", confirma_na=False,
                                          archivo=pdf(), actor=self.admin, motivo=MOTIVO)

    def finalizar(self, evaluacion=None):
        return finalizar_evaluacion(evaluacion or self.ev, actor=self.admin, motivo=MOTIVO)

    def anular(self, evaluacion=None, **kwargs):
        return anular_evaluacion(evaluacion or self.ev, actor=kwargs.get("actor", self.admin), motivo=kwargs.get("motivo", MOTIVO))

    def copiar(self, **kwargs):
        return copiar_evaluacion(self.ev, actor=kwargs.pop("actor", self.admin), motivo=kwargs.pop("motivo", MOTIVO), **kwargs)

    def test_vigente_cambia_con_finalizacion_y_retrocede_al_anular(self):
        self.assertIsNone(self.proveedor.evaluacion_vigente)
        original = self.finalizar()
        self.assertEqual(self.proveedor.evaluacion_vigente.pk, original.pk)
        nueva = self.copiar()
        self.assertEqual(self.proveedor.evaluacion_vigente.pk, original.pk)
        self.finalizar(nueva)
        self.assertEqual(self.proveedor.evaluacion_vigente.pk, nueva.pk)
        self.anular(nueva)
        self.assertEqual(self.proveedor.evaluacion_vigente.pk, original.pk)
        self.anular(original)
        self.assertIsNone(self.proveedor.evaluacion_vigente)

    def test_anular_conserva_resultado_version_evidencias_y_auditoria(self):
        finalizada = self.finalizar()
        foto = deepcopy(finalizada.resultado)
        archivo = Path(self.respuesta.evidencia_pdf.archivo.path)
        anulada = self.anular()
        self.assertEqual(anulada.resultado, foto)
        self.assertEqual(anulada.version, finalizada.version)
        self.assertEqual(anulada.fecha_finalizacion, finalizada.fecha_finalizacion)
        self.assertEqual(anulada.anulada_por, self.admin)
        self.assertTrue(anulada.fecha_anulacion)
        self.assertEqual(anulada.motivo_anulacion, MOTIVO)
        self.assertEqual(obtener_resultado(anulada), foto)
        self.assertTrue(archivo.exists())
        registro = RegistroBitacora.objects.get(accion="evaluacion.anulada")
        self.assertEqual(registro.valor_anterior["estado"], "finalizada")
        self.assertEqual(registro.valor_nuevo["estado"], "anulada")
        self.assertEqual(registro.motivo, MOTIVO)

    def test_anulacion_exige_motivo_y_no_se_repite(self):
        with self.assertRaises(ValidationError):
            self.anular(motivo=" ")
        self.anular()
        with self.assertRaises(ValidationError):
            self.anular()

    def test_borrador_anulado_conserva_foto_ante_cambio_de_parametros(self):
        anulada = self.anular()
        foto = deepcopy(anulada.resultado)
        Parametro.objects.filter(clave=REGLAS_FR14).update(valor="JSON inválido para comprobar uso exclusivo de la foto")
        self.assertEqual(obtener_resultado(anulada), foto)
        self.assertIsNone(anulada.finalizada_por)

    def test_copia_independiente_y_pdf_sin_duplicacion(self):
        self.finalizar()
        archivos = set(Path(settings.MEDIA_ROOT).rglob("*.pdf"))
        copia = self.copiar()
        respuesta = copia.respuestas.get()
        self.assertNotEqual(copia.pk, self.ev.pk)
        self.assertEqual(copia.origen_id, self.ev.pk)
        self.assertEqual((copia.version_id, copia.categoria_id, copia.fecha), (self.ev.version_id, self.ev.categoria_id, self.ev.fecha))
        self.assertEqual(copia.estado, "borrador")
        self.assertEqual(copia.resultado, {})
        self.assertIsNone(copia.fecha_finalizacion)
        self.assertNotEqual(respuesta.pk, self.respuesta.pk)
        self.assertNotEqual(respuesta.evidencia_pdf_id, self.respuesta.evidencia_pdf_id)
        self.assertEqual(respuesta.evidencia_pdf.evaluacion_id, copia.pk)
        self.assertEqual(respuesta.evidencia_pdf.archivo.name, self.respuesta.evidencia_pdf.archivo.name)
        self.assertEqual(set(Path(settings.MEDIA_ROOT).rglob("*.pdf")), archivos)
        guardar_respuesta(copia, self.req, respuesta="no", observacion="Corregido", confirma_na=False, actor=self.admin, motivo=MOTIVO)
        self.respuesta.refresh_from_db()
        self.assertEqual(self.respuesta.respuesta, "si")
        self.assertTrue(RegistroBitacora.objects.filter(accion="evaluacion.copiada", objeto_id=str(copia.pk)).exists())

    def test_copia_vacia_de_anulada_y_fallo_revierte_copia(self):
        self.anular()
        copia = self.copiar(copiar_respuestas=False)
        self.assertFalse(copia.respuestas.exists())
        self.assertFalse(copia.adjuntos.exists())
        cantidad = EvaluacionProveedor.objects.count()
        archivos = set(Path(settings.MEDIA_ROOT).rglob("*.pdf"))
        with patch("proveedores.historial_servicios.registrar", side_effect=RuntimeError("Fallo simulado")), self.assertRaises(RuntimeError):
            self.copiar()
        self.assertEqual(EvaluacionProveedor.objects.count(), cantidad)
        self.assertEqual(set(Path(settings.MEDIA_ROOT).rglob("*.pdf")), archivos)

    def test_fallo_de_auditoria_revierte_anulacion(self):
        self.finalizar()
        with patch("proveedores.historial_servicios.registrar", side_effect=RuntimeError("Fallo simulado")), self.assertRaises(RuntimeError):
            self.anular()
        self.ev.refresh_from_db()
        self.assertEqual(self.ev.estado, "finalizada")
        self.assertIsNone(self.ev.fecha_anulacion)

    def test_finalizadas_y_anuladas_solo_lectura_en_vista_y_servicio(self):
        self.client.force_login(self.admin)
        url = reverse("proveedores:evaluacion_responder", args=[self.ev.pk, self.req.pk])
        for estado in ("finalizada", "anulada"):
            if estado == "finalizada":
                self.finalizar()
            else:
                self.anular()
            self.assertEqual(self.client.get(url).status_code, 403)
            self.assertEqual(self.client.post(url, {"respuesta": "no", "motivo": MOTIVO}).status_code, 403)
            with self.assertRaises(ValidationError):
                guardar_respuesta(self.ev, self.req, respuesta="no", observacion="", confirma_na=False, actor=self.admin, motivo=MOTIVO)
        self.assertEqual(RespuestaEvaluacion.objects.get(pk=self.respuesta.pk).respuesta, "si")

    def test_historial_y_ficha_muestran_datos_y_vigente(self):
        self.finalizar()
        self.client.force_login(self.admin)
        urls = [reverse("proveedores:evaluaciones_historial", args=[self.proveedor.pk]), reverse("proveedores:detalle", args=[self.proveedor.pk])]
        for url in urls:
            respuesta = self.client.get(url)
            self.assertContains(respuesta, "Historial de evaluaciones")
            self.assertContains(respuesta, "100.00")
            self.assertContains(respuesta, "Vigente")
            self.assertContains(respuesta, self.admin.nombre)

    def test_permisos_de_cada_ruta_y_servicios(self):
        rutas = [reverse("proveedores:evaluaciones_historial", args=[self.proveedor.pk]),
                 reverse("proveedores:evaluacion_copiar", args=[self.ev.pk]), reverse("proveedores:evaluacion_anular", args=[self.ev.pk])]
        for rol in (Rol.COORDINADOR, Rol.PROVEEDOR):
            usuario = crear_usuario(rol)
            self.client.force_login(usuario)
            for url in rutas:
                self.assertEqual(self.client.get(url).status_code, 403)
                self.assertEqual(self.client.post(url, {"motivo": MOTIVO}).status_code, 403)
            with self.assertRaises(PermissionDenied):
                self.copiar(actor=usuario)
            with self.assertRaises(PermissionDenied):
                self.anular(actor=usuario)
        self.client.logout()
        for url in rutas:
            self.assertEqual(self.client.get(url).status_code, 302)
        for usuario in (self.admin, crear_usuario(Rol.DESARROLLADOR)):
            self.client.force_login(usuario)
            for url in rutas:
                self.assertEqual(self.client.get(url).status_code, 405 if url.endswith("anular/") else 200)

    def test_csrf_y_motivos_en_anulacion_y_copia(self):
        self.client.force_login(self.admin)
        anular = reverse("proveedores:evaluacion_anular", args=[self.ev.pk])
        copiar = reverse("proveedores:evaluacion_copiar", args=[self.ev.pk])
        self.client.post(anular, {"motivo": ""})
        self.ev.refresh_from_db()
        self.assertEqual(self.ev.estado, "borrador")
        self.assertEqual(self.client.post(copiar, {"motivo": ""}).status_code, 200)
        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(self.admin)
        for url in (anular, copiar):
            self.assertEqual(cliente.post(url, {"motivo": MOTIVO}).status_code, 403)
        self.assertEqual(self.client.post(copiar, {"motivo": MOTIVO, "copiar_respuestas": True}).status_code, 302)

    def test_restriccion_anulacion_en_base(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            EvaluacionProveedor.objects.filter(pk=self.ev.pk)._finalizar(estado="anulada")
