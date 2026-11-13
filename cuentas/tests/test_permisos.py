from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings

from cuentas.models import ROLES_ADMIN, Rol
from cuentas.permisos import es_admin, rol_requerido
from cuentas.tests.utilidades import crear_usuario


@override_settings(ROOT_URLCONF="cuentas.tests.urls_prueba")
class RolRequeridoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuarios = {rol: crear_usuario(rol) for rol in Rol.values}

    def test_matriz_de_roles(self):
        """Cada vista solo responde 200 a su rol; los demás reciben 403."""
        for rol_vista in Rol.values:
            for rol_usuario, usuario in self.usuarios.items():
                with self.subTest(vista=rol_vista, usuario=rol_usuario):
                    self.client.force_login(usuario)
                    respuesta = self.client.get(f"/solo-{rol_vista}/")
                    esperado = 200 if rol_vista == rol_usuario else 403
                    self.assertEqual(respuesta.status_code, esperado)

    def test_vista_para_roles_admin(self):
        for rol, usuario in self.usuarios.items():
            with self.subTest(rol=rol):
                self.client.force_login(usuario)
                respuesta = self.client.get("/solo-admin/")
                self.assertEqual(respuesta.status_code, 200 if rol in ROLES_ADMIN else 403)

    def test_403_usa_plantilla_en_espanol(self):
        self.client.force_login(self.usuarios[Rol.PROVEEDOR])
        respuesta = self.client.get("/solo-administrador/")
        self.assertEqual(respuesta.status_code, 403)
        self.assertTemplateUsed(respuesta, "403.html")
        self.assertContains(respuesta, "Usted no tiene permiso", status_code=403)

    def test_sin_sesion_redirige_al_login(self):
        respuesta = self.client.get("/solo-coordinador/?x=1")
        self.assertRedirects(
            respuesta,
            "/ingresar/?next=/solo-coordinador/%3Fx%3D1",
            fetch_redirect_response=False,
        )

    def test_usuario_desactivado_pierde_la_sesion(self):
        usuario = self.usuarios[Rol.ADMINISTRADOR]
        self.client.force_login(usuario)
        usuario.activo = False
        usuario.save()
        respuesta = self.client.get("/solo-administrador/")
        self.assertEqual(respuesta.status_code, 302)
        self.assertIn("/ingresar/", respuesta["Location"])


class RolRequeridoUnitarioTests(TestCase):
    def setUp(self):
        self.fabrica = RequestFactory()

        @rol_requerido(Rol.ADMINISTRADOR)
        def vista(request):
            return HttpResponse("ok")

        self.vista = vista

    def test_inactivo_recibe_403(self):
        usuario = crear_usuario(Rol.ADMINISTRADOR, activo=False)
        request = self.fabrica.get("/")
        request.user = usuario
        with self.assertRaises(PermissionDenied):
            self.vista(request)

    def test_conserva_metadatos_de_la_vista(self):
        self.assertEqual(self.vista.__name__, "vista")
        self.assertEqual(self.vista.roles_permitidos, frozenset({Rol.ADMINISTRADOR}))

    def test_sin_roles_o_rol_desconocido_falla_al_definir(self):
        with self.assertRaises(ValueError):
            rol_requerido()
        with self.assertRaises(ValueError):
            rol_requerido("administrador", "jefe")


class EsAdminTests(TestCase):
    def test_por_rol(self):
        for rol in Rol.values:
            with self.subTest(rol=rol):
                self.assertEqual(es_admin(crear_usuario(rol)), rol in ROLES_ADMIN)

    def test_anonimo_inactivo_o_nulo(self):
        self.assertFalse(es_admin(AnonymousUser()))
        self.assertFalse(es_admin(None))
        self.assertFalse(es_admin(crear_usuario(Rol.ADMINISTRADOR, activo=False)))
