from datetime import timedelta

from axes.models import AccessAttempt
from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from cuentas.models import Rol
from cuentas.servicios import ACCESOS_ADMIN, ACCESOS_COORDINADOR
from cuentas.tests.utilidades import CLAVE, crear_usuario

MENSAJE_ERROR_INGRESO = "El correo o la clave no son correctos"


class InicioTests(TestCase):
    def test_sin_sesion_redirige_al_login(self):
        respuesta = self.client.get(reverse("inicio"))
        self.assertRedirects(respuesta, "/ingresar/?next=/", fetch_redirect_response=False)

    def test_coordinador_ve_mi_proyeccion(self):
        self.client.force_login(crear_usuario(Rol.COORDINADOR))
        respuesta = self.client.get(reverse("inicio"))
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.context["accesos"], ACCESOS_COORDINADOR)
        self.assertContains(respuesta, "Mi proyección")
        for acceso in ACCESOS_ADMIN:
            self.assertNotContains(respuesta, acceso.nombre)

    def test_administradores_ven_revision_configuracion_y_proveedores(self):
        for rol in (Rol.ADMINISTRADOR, Rol.DESARROLLADOR):
            with self.subTest(rol=rol):
                self.client.force_login(crear_usuario(rol))
                respuesta = self.client.get(reverse("inicio"))
                self.assertEqual(respuesta.status_code, 200)
                for nombre in ("Revisión", "Configuración", "Proveedores"):
                    self.assertContains(respuesta, nombre)
                self.assertNotContains(respuesta, "Mi proyección")
                # Solo un desarrollador superusuario ve el admin técnico.
                self.assertNotContains(respuesta, "Administración técnica")

    def test_desarrollador_superusuario_ve_administracion_tecnica(self):
        from cuentas.models import Usuario

        self.client.force_login(
            Usuario.objects.create_superuser(correo="raiz@ejemplo.test", password=CLAVE, nombre="Soporte")
        )
        respuesta = self.client.get(reverse("inicio"))
        self.assertContains(respuesta, 'href="/admin/"')

    def test_accesos_aun_no_construidos_se_muestran_como_proximamente(self):
        self.client.force_login(crear_usuario(Rol.ADMINISTRADOR))
        respuesta = self.client.get(reverse("inicio"))
        pendientes = [acceso for acceso in ACCESOS_ADMIN if acceso.url is None]
        self.assertContains(respuesta, "Disponible próximamente", count=len(pendientes))
        # "Configuración" ya existe: aparece como enlace en el inicio y en el menú.
        self.assertContains(respuesta, 'href="/configuracion/"', count=2)

    def test_proveedor_va_al_portal(self):
        self.client.force_login(crear_usuario(Rol.PROVEEDOR))
        respuesta = self.client.get(reverse("inicio"))
        self.assertRedirects(respuesta, reverse("portal:inicio"))

    def test_todos_los_roles_tienen_cerrar_sesion_y_cambiar_clave(self):
        for rol in Rol.values:
            with self.subTest(rol=rol):
                self.client.force_login(crear_usuario(rol))
                respuesta = self.client.get(reverse("inicio"), follow=True)
                self.assertEqual(respuesta.status_code, 200)
                self.assertContains(respuesta, "Cerrar sesión")
                self.assertContains(respuesta, 'href="/cambiar-clave/"')


class IngresoTests(TestCase):
    def setUp(self):
        self.usuario = crear_usuario(Rol.ADMINISTRADOR, correo="admin@ejemplo.test")
        self.url = reverse("cuentas:ingresar")

    def ingresar(self, correo, clave):
        return self.client.post(self.url, {"username": correo, "password": clave})

    def test_rutas(self):
        self.assertEqual(reverse("cuentas:ingresar"), "/ingresar/")
        self.assertEqual(reverse("cuentas:salir"), "/salir/")
        self.assertEqual(reverse("cuentas:cambiar_clave"), "/cambiar-clave/")

    def test_formulario_en_espanol(self):
        respuesta = self.client.get(self.url)
        self.assertContains(respuesta, "Correo electrónico")
        self.assertContains(respuesta, "Clave")

    def test_ingreso_correcto(self):
        respuesta = self.ingresar("admin@ejemplo.test", CLAVE)
        self.assertRedirects(respuesta, reverse("inicio"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.usuario.pk)

    def test_ingreso_con_mayusculas_en_el_correo(self):
        respuesta = self.ingresar("Admin@Ejemplo.TEST", CLAVE)
        self.assertRedirects(respuesta, reverse("inicio"))

    def test_ingreso_incorrecto(self):
        respuesta = self.ingresar("admin@ejemplo.test", "otra-clave-errada")
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, MENSAJE_ERROR_INGRESO)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_mismo_mensaje_si_el_correo_no_existe_o_esta_inactivo(self):
        """No se revela si el correo está registrado."""
        inactivo = crear_usuario(Rol.ADMINISTRADOR, correo="inactivo@ejemplo.test", activo=False)
        casos = [
            ("admin@ejemplo.test", "otra-clave-errada"),
            ("no.existe@ejemplo.test", CLAVE),
            (inactivo.correo, CLAVE),
        ]
        contenidos = []
        for correo, clave in casos:
            with self.subTest(correo=correo):
                respuesta = self.ingresar(correo, clave)
                self.assertEqual(respuesta.status_code, 200)
                self.assertContains(respuesta, MENSAJE_ERROR_INGRESO)
                self.assertNotIn("_auth_user_id", self.client.session)
                contenidos.append(respuesta.context["form"].errors.as_data()["__all__"][0].message)
        self.assertEqual(len(set(contenidos)), 1)

    def test_next_externo_no_se_sigue(self):
        respuesta = self.client.post(
            f"{self.url}?next=https://sitio-externo.ejemplo.test/",
            {"username": "admin@ejemplo.test", "password": CLAVE},
        )
        self.assertRedirects(respuesta, reverse("inicio"))


class BloqueoTests(TestCase):
    def setUp(self):
        self.usuario = crear_usuario(Rol.ADMINISTRADOR, correo="admin@ejemplo.test")
        self.url = reverse("cuentas:ingresar")

    def ingresar(self, correo, clave, ip="127.0.0.1"):
        return self.client.post(self.url, {"username": correo, "password": clave}, REMOTE_ADDR=ip)

    def assertBloqueado(self, respuesta):
        self.assertEqual(respuesta.status_code, 429)
        self.assertTemplateUsed(respuesta, "cuentas/bloqueado.html")
        self.assertContains(respuesta, "Acceso bloqueado temporalmente", status_code=429)

    def test_configuracion(self):
        self.assertEqual(settings.AXES_FAILURE_LIMIT, 5)
        self.assertEqual(settings.AXES_COOLOFF_TIME, timedelta(minutes=15))
        self.assertEqual(settings.AXES_LOCKOUT_PARAMETERS, ["username"])

    def test_bloqueo_al_quinto_intento(self):
        for intento in range(1, settings.AXES_FAILURE_LIMIT):
            with self.subTest(intento=intento):
                self.assertEqual(self.ingresar("admin@ejemplo.test", "errada").status_code, 200)
        self.assertBloqueado(self.ingresar("admin@ejemplo.test", "errada"))
        # Ni siquiera la clave correcta entra mientras dure el bloqueo.
        self.assertBloqueado(self.ingresar("admin@ejemplo.test", CLAVE))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_bloqueo_por_correo_aunque_cambien_mayusculas_e_ip(self):
        variantes = ["admin@ejemplo.test", "ADMIN@ejemplo.test", "Admin@Ejemplo.test", "admin@EJEMPLO.TEST"]
        for intento in range(settings.AXES_FAILURE_LIMIT):
            self.ingresar(variantes[intento % len(variantes)], "errada", ip=f"10.0.0.{intento + 1}")
        self.assertBloqueado(self.ingresar("admin@ejemplo.test", CLAVE, ip="10.0.0.99"))

    def test_bloqueo_no_revela_si_el_correo_existe(self):
        for _ in range(settings.AXES_FAILURE_LIMIT):
            respuesta = self.ingresar("no.existe@ejemplo.test", "errada")
        self.assertBloqueado(respuesta)
        self.assertNotContains(respuesta, "no.existe@ejemplo.test", status_code=429)

    def test_bloqueo_de_un_correo_no_afecta_a_otro(self):
        crear_usuario(Rol.DESARROLLADOR, correo="otro@ejemplo.test")
        for _ in range(settings.AXES_FAILURE_LIMIT):
            self.ingresar("admin@ejemplo.test", "errada")
        self.assertRedirects(self.ingresar("otro@ejemplo.test", CLAVE), reverse("inicio"))

    def test_se_desbloquea_a_los_15_minutos(self):
        for _ in range(settings.AXES_FAILURE_LIMIT):
            self.ingresar("admin@ejemplo.test", "errada")
        self.assertBloqueado(self.ingresar("admin@ejemplo.test", CLAVE))
        AccessAttempt.objects.update(attempt_time=AccessAttempt.objects.get().attempt_time - timedelta(minutes=16))
        self.assertRedirects(self.ingresar("admin@ejemplo.test", CLAVE), reverse("inicio"))


class SalirTests(TestCase):
    def setUp(self):
        self.usuario = crear_usuario(Rol.ADMINISTRADOR)
        self.client.force_login(self.usuario)

    def test_salir_por_get_no_cierra_la_sesion(self):
        respuesta = self.client.get(reverse("cuentas:salir"))
        self.assertEqual(respuesta.status_code, 405)
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.usuario.pk)
        self.assertEqual(self.client.get(reverse("inicio")).status_code, 200)

    def test_salir_por_post_cierra_la_sesion(self):
        respuesta = self.client.post(reverse("cuentas:salir"))
        self.assertRedirects(respuesta, reverse("cuentas:ingresar"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_salir_exige_csrf(self):
        from django.test import Client

        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(self.usuario)
        self.assertEqual(cliente.post(reverse("cuentas:salir")).status_code, 403)
        self.assertIn("_auth_user_id", cliente.session)
