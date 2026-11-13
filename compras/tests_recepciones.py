from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch
from tempfile import TemporaryDirectory
from django.core.exceptions import ValidationError, PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone
from compras.tests_aprobacion_ordenes import DatosOrdenOperativa
from compras import recepcion_servicios as servicios
from compras.models import Recepcion
from parametros.catalogo import EXCESO_RECEPCION, COORDINADOR_RECEPCION

MOTIVO = "Recepción ficticia con soporte y cantidades verificadas"


class RecepcionOrdenTests(DatosOrdenOperativa, TestCase):
    def recibir(self, orden, lineas=None, **cambios):
        datos = dict(fecha=timezone.localdate(), lineas=lineas or [{"id": l.pk, "cantidad": l.cantidad} for l in orden.lineas.all()], actor=self.admin, motivo=MOTIVO)
        datos.update(cambios)
        return servicios.registrar_recepcion(orden, **datos)

    def test_parcial_total_y_ajuste_no_editable_conservan_pendientes(self):
        orden = self.emitir()
        uno, dos = orden.lineas.all()
        primera = self.recibir(orden, [{"id": uno.pk, "cantidad": ".5", "rechazada": ".1"}])
        orden.refresh_from_db()
        self.assertEqual(orden.estado, "recibida_parcial")
        self.assertEqual(servicios.acumulados(orden)[0]["pendiente"], Decimal(".5"))
        self.recibir(orden, [{"id": uno.pk, "cantidad": ".5"}, {"id": dos.pk, "cantidad": 2}])
        orden.refresh_from_db()
        self.assertEqual(orden.estado, "recibida_total")
        self.recibir(orden, [{"id": uno.pk, "cantidad": "-.25", "rechazada": "-.1"}], tipo="ajuste", ajusta_id=primera.pk)
        orden.refresh_from_db()
        self.assertEqual(orden.estado, "recibida_parcial")
        self.assertEqual(servicios.acumulados(orden)[0]["pendiente"], Decimal(".25"))
        self.assertEqual(Recepcion.objects.count(), 3)
        for registro in (primera, primera.lineas.first()):
            with self.assertRaises(ValidationError):
                registro.save()
            with self.assertRaises(ValidationError):
                registro.delete()

    def test_exceso_requiere_parametro_autorizacion_y_administrador(self):
        orden = self.emitir()
        linea = orden.lineas.first()
        datos = [{"id": linea.pk, "cantidad": 2}]
        with self.assertRaises(ValidationError):
            self.recibir(orden, datos, autorizar_exceso=True)
        self.parametro(EXCESO_RECEPCION, "true")
        with self.assertRaises(ValidationError):
            self.recibir(orden, datos)
        recepcion = self.recibir(orden, datos, autorizar_exceso=True)
        self.assertTrue(recepcion.exceso_autorizado)
        self.assertEqual(servicios.acumulados(orden)[0]["exceso"], 1)
        self.parametro(EXCESO_RECEPCION, "false")
        self.recibir(orden, [{"id": linea.pk, "cantidad": "-.5"}], tipo="ajuste", ajusta_id=recepcion.pk)

    def test_no_emitida_ajustes_negativos_lineas_ajenas_y_revision(self):
        orden, = self.crear()
        with self.assertRaises(ValidationError):
            self.recibir(orden)
        orden = self.emitir(orden)
        linea = orden.lineas.first()
        for lineas, cambios in (([{"id": linea.pk, "cantidad": -1}], {}), ([{"id": linea.pk, "cantidad": "NaN"}], {}),
                ([{"id": linea.pk, "cantidad": 0.1}], {}), ([{"id": linea.pk, "cantidad": ".0001"}], {}),
                ([{"id": 999999, "cantidad": 1}], {}), ([{"id": linea.pk, "cantidad": ".1"}]*2, {}),
                ([{"id": linea.pk, "cantidad": 0}], {}), ([{"id": linea.pk, "cantidad": 1}], {"revision_esperada": 0})):
            with self.subTest(lineas=lineas), self.assertRaises(ValidationError):
                self.recibir(orden, lineas, **cambios)
        self.assertFalse(Recepcion.objects.exists())

    def test_recepcion_fuera_fecha_y_ajuste_no_deja_acumulado_negativo(self):
        orden = self.emitir()
        primera = self.recibir(orden)
        linea = orden.lineas.first()
        with self.assertRaises(ValidationError):
            self.recibir(orden, [{"id": linea.pk, "cantidad": -2}], tipo="ajuste", ajusta_id=primera.pk)
        with self.assertRaises(ValidationError):
            self.recibir(orden, [{"id": linea.pk, "cantidad": "-.1"}], tipo="ajuste", ajusta_id=999999)
        with self.assertRaises(ValidationError):
            self.recibir(orden, fecha=timezone.localdate()+timedelta(days=1))
        self.assertEqual(Recepcion.objects.count(), 1)

    def test_coordinador_configurable_solo_propia_area_no_autoriza_exceso(self):
        orden = self.emitir()
        with self.assertRaises(PermissionDenied):
            self.recibir(orden, actor=self.coordinador)
        self.parametro(COORDINADOR_RECEPCION, "true")
        self.coordinador.area = orden.cotizacion.area
        self.coordinador.save()
        self.recibir(orden, [{"id": orden.lineas.first().pk, "cantidad": ".1"}], actor=self.coordinador)
        self.parametro(EXCESO_RECEPCION, "true")
        with self.assertRaises(ValidationError):
            self.recibir(orden, [{"id": orden.lineas.first().pk, "cantidad": 2}], actor=self.coordinador, autorizar_exceso=True)
        with self.assertRaises(PermissionDenied):
            self.recibir(orden, actor=self.usuario_proveedor)

    def test_pdf_privado_csrf_pantallas_y_reversion_con_archivo(self):
        orden = self.emitir()
        self.client.force_login(self.admin)
        url = reverse("compras:orden_recibir", args=[orden.pk])
        self.assertContains(self.client.get(url), "Cantidad aceptada")
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.admin)
        self.assertEqual(csrf.post(url, {}).status_code, 403)
        with TemporaryDirectory() as carpeta, override_settings(MEDIA_ROOT=carpeta):
            pdf = lambda: SimpleUploadedFile("recepcion.pdf", b"%PDF-1.4 ficticio", content_type="application/pdf")
            with patch("compras.recepcion_servicios.registrar", side_effect=RuntimeError("Fallo ficticio")), self.assertRaises(RuntimeError):
                self.recibir(orden, archivo=pdf())
            self.assertFalse(Recepcion.objects.exists())
            from pathlib import Path
            self.assertEqual(list(Path(carpeta).rglob("*.pdf")), [])
            registro = self.recibir(orden, archivo=pdf())
            self.assertEqual(self.client.get(reverse("compras:recepcion_detalle", args=[orden.pk, registro.pk])).status_code, 200)
            respuesta = self.client.get(reverse("compras:recepcion_pdf", args=[orden.pk, registro.pk]))
            self.assertEqual(b"".join(respuesta.streaming_content), b"%PDF-1.4 ficticio")
            self.client.force_login(self.coordinador)
            self.assertEqual(self.client.get(reverse("compras:recepcion_pdf", args=[orden.pk, registro.pk])).status_code, 403)
