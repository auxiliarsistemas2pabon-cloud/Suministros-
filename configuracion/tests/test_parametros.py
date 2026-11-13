from django.urls import reverse

from bitacora.models import RegistroBitacora
from configuracion.tests.base import MOTIVO, BasePanel
from parametros.catalogo import PERMITIR_DEVOLUCION
from parametros.models import Parametro


class ParametrosPanelTests(BasePanel):
    def setUp(self):
        super().setUp()
        self.parametro = Parametro.objects.get(clave=PERMITIR_DEVOLUCION)
        self.url = reverse("configuracion:parametro_editar", args=[self.parametro.pk])

    def test_lista_muestra_d01_con_valor_y_defecto(self):
        respuesta = self.client.get(reverse("configuracion:parametros"))
        self.assertContains(respuesta, "D-01")
        self.assertContains(respuesta, "Permitir devolver proyecciones al área")

    def test_editar_sin_motivo_se_rechaza(self):
        respuesta = self.client.post(self.url, {"valor": "false", "motivo": ""})
        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(respuesta.context["formulario"].errors["motivo"])
        self.assertEqual(self.recargar(self.parametro).valor, "true")

    def test_editar_con_motivo_cambia_y_registra(self):
        respuesta = self.client.post(self.url, {"valor": "false", "motivo": MOTIVO})
        self.assertRedirects(respuesta, reverse("configuracion:parametros"))
        self.assertEqual(self.recargar(self.parametro).valor, "false")
        registro = RegistroBitacora.objects.get(accion="parametro.modificado")
        self.assertEqual(registro.valor_anterior, {"valor": "true"})
        self.assertEqual(registro.valor_nuevo, {"valor": "false"})

    def test_mismo_valor_muestra_error(self):
        respuesta = self.client.post(self.url, {"valor": "true", "motivo": MOTIVO})
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "igual al actual")
