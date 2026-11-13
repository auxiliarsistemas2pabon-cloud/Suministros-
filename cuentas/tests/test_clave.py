from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from bitacora.models import RegistroBitacora
from cuentas.models import Rol, Usuario
from cuentas.tests.utilidades import CLAVE, crear_usuario

CLAVE_NUEVA = "Nueva-Clave-Segura-48"


class CambiarClaveTests(TestCase):
    url = "/cambiar-clave/"

    def setUp(self):
        self.usuario = crear_usuario(Rol.COORDINADOR, correo="coordinador@ejemplo.test")
        self.client.force_login(self.usuario)

    def cambiar(self, actual=CLAVE, nueva=CLAVE_NUEVA, confirmacion=None):
        return self.client.post(
            self.url,
            {"old_password": actual, "new_password1": nueva, "new_password2": confirmacion or nueva},
        )

    def test_sin_sesion_redirige_al_login(self):
        self.client.logout()
        respuesta = self.client.get(self.url)
        self.assertRedirects(respuesta, "/ingresar/?next=/cambiar-clave/", fetch_redirect_response=False)

    def test_todos_los_roles_pueden_cambiar_su_clave(self):
        for rol in Rol.values:
            with self.subTest(rol=rol):
                self.client.force_login(crear_usuario(rol, correo=f"todos-{rol}@ejemplo.test"))
                respuesta = self.client.get(self.url)
                self.assertEqual(respuesta.status_code, 200)
                self.assertContains(respuesta, "Clave actual")
                self.assertContains(respuesta, "Confirme la clave nueva")

    def test_cambio_correcto_mantiene_la_sesion_y_registra_bitacora(self):
        respuesta = self.cambiar()
        self.assertRedirects(respuesta, reverse("inicio"))
        self.usuario.refresh_from_db()
        self.assertTrue(self.usuario.check_password(CLAVE_NUEVA))
        # La sesión sigue abierta tras el cambio.
        self.assertEqual(self.client.get(reverse("inicio")).status_code, 200)
        registro = RegistroBitacora.objects.get(accion="cuenta.cambio_clave")
        self.assertEqual(registro.actor, self.usuario)
        self.assertEqual(registro.objeto_id, str(self.usuario.pk))
        self.assertNotIn(CLAVE_NUEVA, str(registro.valor_nuevo))

    def test_clave_actual_incorrecta(self):
        respuesta = self.cambiar(actual="no-es-la-actual")
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "La clave actual no es correcta")
        self.usuario.refresh_from_db()
        self.assertTrue(self.usuario.check_password(CLAVE))

    def test_confirmacion_distinta(self):
        respuesta = self.cambiar(confirmacion="Otra-Clave-Distinta-12")
        self.assertContains(respuesta, "Las dos claves nuevas no coinciden")

    def test_clave_nueva_igual_a_la_actual(self):
        respuesta = self.cambiar(nueva=CLAVE)
        self.assertContains(respuesta, "La clave nueva debe ser distinta de la actual")

    def test_validadores_en_espanol(self):
        respuesta = self.cambiar(nueva="123456789")
        self.assertEqual(respuesta.status_code, 200)
        for texto in ("demasiado corta", "por lo menos 10 caracteres", "demasiado común", "completamente numérica"):
            self.assertContains(respuesta, texto)


class ObligarCambioClaveTests(TestCase):
    def setUp(self):
        self.usuario = crear_usuario(Rol.ADMINISTRADOR, debe_cambiar_clave=True)
        self.client.force_login(self.usuario)

    def test_redirige_cualquier_pagina_a_cambiar_clave(self):
        for url in ("/", "/portal/", "/admin/", "/ruta/que/no/existe/"):
            with self.subTest(url=url):
                respuesta = self.client.get(url)
                self.assertRedirects(respuesta, "/cambiar-clave/", fetch_redirect_response=False)

    def test_tambien_redirige_peticiones_post(self):
        respuesta = self.client.post("/")
        self.assertRedirects(respuesta, "/cambiar-clave/", fetch_redirect_response=False)

    def test_deja_pasar_cambiar_clave_salir_y_estaticos(self):
        respuesta = self.client.get("/cambiar-clave/")
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "debe cambiar su clave antes de continuar")
        # Sin menú mientras no cambie la clave.
        self.assertNotContains(respuesta, 'aria-label="Menú principal"')
        estatico = self.client.get(f"{settings.STATIC_URL}css/estilos.css")
        self.assertNotEqual(estatico.status_code, 302)
        respuesta = self.client.post("/salir/")
        self.assertRedirects(respuesta, "/ingresar/")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_al_cambiar_la_clave_se_apaga_la_marca(self):
        respuesta = self.client.post(
            "/cambiar-clave/",
            {"old_password": CLAVE, "new_password1": CLAVE_NUEVA, "new_password2": CLAVE_NUEVA},
        )
        self.assertRedirects(respuesta, reverse("inicio"))
        self.usuario.refresh_from_db()
        self.assertFalse(self.usuario.debe_cambiar_clave)
        self.assertEqual(self.client.get("/").status_code, 200)
        registro = RegistroBitacora.objects.get(accion="cuenta.cambio_clave")
        self.assertEqual(registro.valor_anterior, {"debe_cambiar_clave": True})
        self.assertEqual(registro.valor_nuevo, {"debe_cambiar_clave": False})
        self.assertEqual(registro.motivo, "Cambio obligatorio de clave")

    def test_al_ingresar_va_directo_a_cambiar_clave(self):
        self.client.logout()
        respuesta = self.client.post("/ingresar/", {"username": self.usuario.correo, "password": CLAVE}, follow=True)
        self.assertEqual(respuesta.redirect_chain[-1][0], "/cambiar-clave/")

    def test_sin_sesion_no_aplica(self):
        self.client.logout()
        respuesta = self.client.get("/")
        self.assertRedirects(respuesta, "/ingresar/?next=/", fetch_redirect_response=False)


class SesionTests(TestCase):
    def test_configuracion_de_sesion(self):
        self.assertEqual(settings.SESSION_COOKIE_AGE, 1800)
        self.assertIs(settings.SESSION_SAVE_EVERY_REQUEST, True)
        self.assertIs(settings.SESSION_EXPIRE_AT_BROWSER_CLOSE, True)

    def test_cookie_de_sesion_expira_al_cerrar_el_navegador(self):
        usuario = crear_usuario(Rol.ADMINISTRADOR)
        respuesta = self.client.post("/ingresar/", {"username": usuario.correo, "password": CLAVE})
        cookie = respuesta.cookies[settings.SESSION_COOKIE_NAME]
        self.assertEqual(cookie["max-age"], "")
        self.assertEqual(cookie["expires"], "")
        self.assertEqual(self.client.session.get_expiry_age(), 1800)

    def test_cada_peticion_renueva_la_sesion(self):
        usuario = crear_usuario(Rol.ADMINISTRADOR)
        self.client.force_login(usuario)
        respuesta = self.client.get(reverse("inicio"))
        self.assertIn(settings.SESSION_COOKIE_NAME, respuesta.cookies)


class ValidadoresClaveTests(TestCase):
    def setUp(self):
        self.usuario = Usuario(correo="ana.perez@ejemplo.test", nombre="Ana Pérez Gómez", rol=Rol.ADMINISTRADOR)

    def mensajes(self, clave):
        try:
            validate_password(clave, self.usuario)
        except ValidationError as error:
            return " ".join(error.messages)
        return ""

    def test_longitud_minima_10(self):
        self.assertIn("por lo menos 10 caracteres", self.mensajes("Ab3$xyz9q"))
        self.assertEqual(self.mensajes("Ab3$xyz9qW"), "")

    def test_similitud_con_correo_y_nombre(self):
        self.assertIn("muy parecida", self.mensajes("ana.perez@ejemplo"))
        self.assertIn("muy parecida", self.mensajes("AnaPérezGómez"))

    def test_comun_y_numerica(self):
        self.assertIn("demasiado común", self.mensajes("password1234"))
        self.assertIn("completamente numérica", self.mensajes("4815162342"))

    def test_configuracion_tiene_los_cuatro_validadores(self):
        nombres = [v["NAME"].rsplit(".", 1)[-1] for v in settings.AUTH_PASSWORD_VALIDATORS]
        self.assertEqual(
            nombres,
            [
                "UserAttributeSimilarityValidator",
                "MinimumLengthValidator",
                "CommonPasswordValidator",
                "NumericPasswordValidator",
            ],
        )
