from io import BytesIO
from django.test import TestCase
from django.urls import reverse
from django.core.exceptions import PermissionDenied
from openpyxl import load_workbook
from compras.tests_aprobacion_ordenes import DatosOrdenOperativa
from compras.models import Necesidad
from areas.models import Area
from config.listados import preparar, aplicar_alcance
from proveedores.nit import formatear


class FiltrosGlobalesTests(DatosOrdenOperativa, TestCase):
    def test_estado_derivado_filtra_seguimientos_en_pantalla_y_excel(self):
        orden = self.emitir()
        self.client.force_login(self.admin)
        ruta = reverse("configuracion:listado_global", args=["seguimientos"])
        respuesta = self.client.get(ruta, {"estado": "cerrado"})
        self.assertEqual(respuesta.context["pagina"].paginator.count, 0)
        respuesta = self.client.get(ruta, {"estado": "cerrado", "formato": "excel"})
        libro = load_workbook(BytesIO(respuesta.content), data_only=True)
        self.assertEqual(libro.active.max_row, 1)
        respuesta = self.client.get(ruta, {"estado": "abierto"})
        self.assertEqual(respuesta.context["pagina"].paginator.count, 1)
        self.assertContains(respuesta, "Abierto")
        self.assertEqual(self.client.get(ruta, {"estado": "inventado", "formato": "excel"}).status_code, 400)

    def test_nit_formateado_y_canonico_coinciden_y_exportacion_usa_mismo_filtro(self):
        orden = self.emitir()
        self.client.force_login(self.admin)
        valores = (orden.nit, formatear(orden.nit), formatear(orden.nit, orden.proveedor.digito_verificacion))
        for texto in valores:
            filtro, consulta = preparar("ordenes", {"q": texto}, self.admin)
            self.assertTrue(filtro.is_valid())
            self.assertEqual(list(consulta.values_list("pk", flat=True)), [orden.pk])
            respuesta = self.client.get(reverse("configuracion:listado_global", args=["ordenes"]), {"q": texto, "formato": "excel"})
            libro = load_workbook(BytesIO(respuesta.content), data_only=True)
            self.assertEqual(libro.active.max_row, 2)
        self.assertEqual(self.client.get(reverse("configuracion:buscar"), {"q": valores[-1]}).status_code, 200)
        self.assertContains(self.client.get(reverse("configuracion:buscar"), {"q": orden.consecutivo}), orden.consecutivo)

    def test_todos_los_listados_y_filtros_invalidos_no_amplian_resultados(self):
        self.emitir()
        self.client.force_login(self.admin)
        for clase in ("proyecciones", "proveedores", "evaluaciones", "necesidades", "elegibles", "cotizaciones", "ordenes", "seguimientos"):
            ruta = reverse("configuracion:listado_global", args=[clase])
            self.assertEqual(self.client.get(ruta).status_code, 200, clase)
            self.assertEqual(self.client.get(ruta, {"formato": "excel"}).status_code, 200, clase)
            self.assertEqual(self.client.get(ruta, {"area": "invalida", "formato": "excel"}).status_code, 400 if clase not in ("proveedores", "evaluaciones") else 200)

    def test_alcance_se_aplica_antes_de_filtros_y_coordinador_no_ve_otra_area(self):
        propia = self.coordinador.area
        otra = Area.objects.create(nombre="Área ajena de filtros", codigo_area="AJENA")
        Necesidad.objects.create(area=propia, responsable=self.admin, objeto="Necesidad propia")
        ajena = Necesidad.objects.create(area=otra, responsable=self.admin, objeto="Necesidad ajena")
        consulta = aplicar_alcance(Necesidad.objects.all(), self.coordinador, "area_id")
        self.assertFalse(consulta.filter(pk=ajena.pk).exists())
        filtro, filtrada = preparar("necesidades", {"area": otra.pk}, self.coordinador)
        self.assertFalse(filtro.is_valid())
        self.assertFalse(filtrada.exists())
        self.client.force_login(self.coordinador)
        self.assertEqual(self.client.get(reverse("configuracion:listado_global", args=["ordenes"]), {"area": otra.pk, "formato": "excel"}).status_code, 403)
        self.assertEqual(self.client.get(reverse("configuracion:buscar"), {"q": "900"}).status_code, 403)
        with self.assertRaises(PermissionDenied):
            preparar("proveedores", {}, self.coordinador)
