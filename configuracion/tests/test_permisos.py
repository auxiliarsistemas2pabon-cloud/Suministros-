"""Cada URL del panel: 403 para coordinador y proveedor, login sin sesión,
200 para administrador y desarrollador."""

from django.urls import reverse

from configuracion.tests.base import BasePanel, Rol
from parametros.catalogo import PERMITIR_DEVOLUCION
from parametros.models import Parametro


class PermisosPanelTests(BasePanel):
    def urls(self):
        area, unidad, producto, usuario = self.area.pk, self.unidad.pk, self.producto.pk, self.coordinador.pk
        return [
            reverse("configuracion:inicio"),
            reverse("configuracion:areas"),
            reverse("configuracion:area_nueva"),
            reverse("configuracion:area_editar", args=[area]),
            reverse("configuracion:area_estado", args=[area]),
            reverse("configuracion:area_coordinadores", args=[area]),
            reverse("configuracion:unidades"),
            reverse("configuracion:unidad_nueva"),
            reverse("configuracion:unidad_editar", args=[unidad]),
            reverse("configuracion:unidad_estado", args=[unidad]),
            reverse("configuracion:productos"),
            reverse("configuracion:producto_nuevo"),
            reverse("configuracion:producto_editar", args=[producto]),
            reverse("configuracion:producto_estado", args=[producto]),
            reverse("configuracion:usuarios"),
            reverse("configuracion:usuario_nuevo"),
            reverse("configuracion:usuario_editar", args=[usuario]),
            reverse("configuracion:usuario_estado", args=[usuario]),
            reverse("configuracion:usuario_restablecer_clave", args=[usuario]),
            reverse("configuracion:usuario_clave_temporal", args=[usuario]),
            reverse("configuracion:parametros"),
            reverse("configuracion:parametro_editar", args=[Parametro.objects.get(clave=PERMITIR_DEVOLUCION).pk]),
        ]

    def test_coordinador_y_proveedor_reciben_403_en_get_y_post(self):
        for usuario in (self.coordinador, self.proveedor):
            self.como(usuario)
            for url in self.urls():
                with self.subTest(rol=usuario.rol, url=url):
                    self.assertEqual(self.client.get(url).status_code, 403)
                    self.assertEqual(self.client.post(url, {"motivo": "x"}).status_code, 403)

    def test_post_de_roles_no_autorizados_no_cambia_nada(self):
        self.como(self.coordinador)
        self.client.post(reverse("configuracion:area_estado", args=[self.otra_area.pk]), {"motivo": "x"})
        self.client.post(reverse("configuracion:usuario_estado", args=[self.proveedor.pk]), {"motivo": "x"})
        self.assertTrue(self.recargar(self.otra_area).activa)
        self.assertTrue(self.recargar(self.proveedor).activo)

    def test_sin_sesion_redirige_al_login(self):
        self.client.logout()
        for url in self.urls():
            with self.subTest(url=url):
                respuesta = self.client.get(url)
                self.assertEqual(respuesta.status_code, 302)
                self.assertTrue(respuesta["Location"].startswith("/ingresar/?next="))

    def test_administrador_y_desarrollador_entran(self):
        sin_clave_temporal = [u for u in self.urls() if not u.endswith("/clave-temporal/")]
        for usuario in (self.administrador, self.desarrollador):
            self.como(usuario)
            for url in sin_clave_temporal:
                with self.subTest(rol=usuario.rol, url=url):
                    self.assertEqual(self.client.get(url).status_code, 200)

    def test_menu_muestra_configuracion_solo_a_administradores(self):
        for usuario, ve in ((self.administrador, True), (self.desarrollador, True), (self.coordinador, False)):
            with self.subTest(rol=usuario.rol):
                self.como(usuario)
                respuesta = self.client.get("/")
                if ve:
                    self.assertContains(respuesta, 'href="/configuracion/"')
                else:
                    self.assertNotContains(respuesta, 'href="/configuracion/"')

    def test_no_existen_vistas_de_borrado(self):
        for ruta in ("areas", "unidades", "productos", "usuarios"):
            with self.subTest(ruta=ruta):
                self.assertEqual(self.client.get(f"/configuracion/{ruta}/1/borrar/").status_code, 404)
                self.assertEqual(self.client.post(f"/configuracion/{ruta}/1/eliminar/").status_code, 404)

    def test_roles_validos(self):
        self.assertEqual(set(Rol.values), {"coordinador", "administrador", "desarrollador", "proveedor"})
