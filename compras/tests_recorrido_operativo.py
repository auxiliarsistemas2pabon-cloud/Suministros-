"""Recorrido por formularios con cambio de actor y datos de prueba aislados."""
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from decimal import Decimal
from compras.tests_aprobacion_ordenes import DatosOrdenOperativa
from compras.models import OrdenCompra, Recepcion
from parametros.catalogo import CLIENTE_ORDEN, NIT_CLIENTE_ORDEN
from seguimientos.models import Seguimiento, ResultadoCierre, TipoEvento
from openpyxl import load_workbook
from io import BytesIO

MOTIVO = "Recorrido ficticio de aprobación, entrega y cierre"


class RecorridoOperativoTests(DatosOrdenOperativa, TestCase):
    def test_aprobar_pdf_recibir_devolver_completar_y_cerrar_desde_formularios(self):
        orden, = self.crear()
        self.parametro(CLIENTE_ORDEN, "Clínica ficticia de pruebas")
        self.parametro(NIT_CLIENTE_ORDEN, "900000001-1")
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("compras:orden_editar", args=[orden.pk])).status_code, 200)
        def aprobar(accion):
            orden.refresh_from_db()
            respuesta = self.client.post(reverse("compras:orden_aprobacion", args=[orden.pk, accion]), {"motivo": MOTIVO, "revision_esperada": orden.revision})
            self.assertEqual(respuesta.status_code, 302)
            orden.refresh_from_db()
        aprobar("solicitar")
        self.assertEqual(orden.estado, "en_aprobacion")
        self.assertEqual(self.client.get(reverse("compras:orden_editar", args=[orden.pk])).status_code, 302)
        aprobar("aprobar")  # La persona que elaboró no puede emitir su propia orden.
        self.assertEqual(orden.estado, "en_aprobacion")
        self.assertIsNone(orden.numero)
        self.client.force_login(self.dev)
        aprobar("aprobar")
        self.assertEqual(orden.estado, "emitida")
        documento = self.client.get(reverse("compras:orden_imprimir", args=[orden.pk]))
        self.assertEqual(documento["Content-Type"], "application/pdf")
        self.assertTrue(documento.content.startswith(b"%PDF-"))
        seguimiento = Seguimiento.objects.get(orden=orden)
        self.client.force_login(self.admin)
        lineas = list(orden.lineas.all())
        def recibir(tipo, cantidades, devueltas=None, revision=None):
            orden.refresh_from_db()
            datos = {"fecha": timezone.localdate().isoformat(), "tipo": tipo, "motivo": MOTIVO,
                "revision_esperada": orden.revision if revision is None else revision, "lineas-TOTAL_FORMS": len(lineas), "lineas-INITIAL_FORMS": len(lineas)}
            for i, linea in enumerate(lineas):
                datos.update({f"lineas-{i}-id": linea.pk, f"lineas-{i}-cantidad": cantidades[i], f"lineas-{i}-rechazada": 0,
                    f"lineas-{i}-devuelta": (devueltas or [0]*len(lineas))[i]})
            respuesta = self.client.post(reverse("compras:orden_recibir", args=[orden.pk]), datos)
            orden.refresh_from_db()
            return respuesta
        self.assertEqual(recibir("recepcion", [".5", 0]).status_code, 302)
        self.assertEqual(orden.estado, "recibida_parcial")
        conteo = Recepcion.objects.filter(orden=orden).count()
        self.assertEqual(recibir("recepcion", [".1", 0], revision=1).status_code, 200)
        self.assertEqual(Recepcion.objects.filter(orden=orden).count(), conteo)
        self.assertEqual(recibir("devolucion", [0, 0], devueltas=[".25", 0]).status_code, 302)
        respuesta = self.client.get(reverse("seguimientos:lista"), {"estado": "parcial", "formato": "excel"})
        libro = load_workbook(BytesIO(respuesta.content), data_only=True)
        self.assertEqual(libro["Seguimientos"]["A2"].value, seguimiento.pk)
        self.assertEqual(libro["Cantidades por unidad"]["C2"].value, .25)
        self.assertEqual(recibir("recepcion", [".75", 2]).status_code, 302)
        self.assertEqual(orden.estado, "recibida_total")
        self.assertEqual(seguimiento.eventos.count(), 3)
        seguimiento.refresh_from_db()
        respuesta = self.client.post(reverse("seguimientos:cerrar", args=[seguimiento.pk]), {
            "resultado": ResultadoCierre.objects.get(codigo="cumplido").pk, "fecha": timezone.localdate().isoformat(),
            "revision_esperada": seguimiento.revision, "motivo": MOTIVO})
        self.assertEqual(respuesta.status_code, 302)
        seguimiento.refresh_from_db()
        orden.refresh_from_db()
        self.assertTrue(seguimiento.cerrado)
        self.assertEqual(orden.estado, "cerrada")
        self.assertEqual(orden.total, Decimal(52))
        self.assertEqual(self.client.get(reverse("seguimientos:detalle", args=[seguimiento.pk])).status_code, 200)
        respuesta = self.client.post(reverse("seguimientos:evento", args=[seguimiento.pk]), {"tipo": TipoEvento.objects.get(codigo="comunicacion").pk,
            "fecha": timezone.localtime().strftime("%Y-%m-%dT%H:%M"), "nota": "Evento tardío no permitido", "revision_esperada": seguimiento.revision, "motivo": MOTIVO})
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(seguimiento.eventos.count(), 3)
