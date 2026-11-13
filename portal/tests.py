from django.test import TestCase
from django.urls import reverse

from cuentas.models import Rol
from cuentas.tests.utilidades import crear_usuario


class PortalTests(TestCase):
    url = "/portal/"

    def test_ruta(self):
        self.assertEqual(reverse("portal:inicio"), self.url)

    def test_sin_sesion_redirige_al_login(self):
        respuesta = self.client.get(self.url)
        self.assertRedirects(respuesta, "/ingresar/?next=/portal/", fetch_redirect_response=False)

    def test_solo_el_proveedor_entra(self):
        for rol in Rol.values:
            with self.subTest(rol=rol):
                self.client.force_login(crear_usuario(rol))
                respuesta = self.client.get(self.url)
                self.assertEqual(respuesta.status_code, 200 if rol == Rol.PROVEEDOR else 403)

    def test_portal_en_espanol_con_menu_de_proveedor(self):
        self.client.force_login(crear_usuario(Rol.PROVEEDOR))
        respuesta = self.client.get(self.url)
        self.assertContains(respuesta, "Portal de proveedores")
        self.assertContains(respuesta, 'href="/portal/" aria-current="page"')
        # El proveedor no ve el enlace a Inicio (lo redirigiría al portal).
        self.assertNotContains(respuesta, '>Inicio</a>')
