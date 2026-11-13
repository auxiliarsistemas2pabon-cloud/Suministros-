"""Alta pública sin enumeración de cuentas ni escalada de privilegios."""

from unittest.mock import patch

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from bitacora.models import RegistroBitacora
from cuentas.models import Rol, Usuario
from cuentas.tests.utilidades import crear_usuario
from parametros.catalogo import ACTIVAR_REGISTRO_PORTAL
from parametros.models import Parametro
from portal import servicios
from proveedores.models import Proveedor


class RegistroPortalTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.url = reverse("portal:registro")
        self.datos = {
            "nit": "900.123.456-8", "razon_social": "Proveedor Ficticio del Portal",
            "tipo_persona": "juridica", "contacto_nombre": "Contacto Ficticio",
            "contacto_telefono": "601 555 0100", "direccion": "Calle Ficticia 1",
            "correo": "NUEVO@ejemplo.test", "clave1": "Clave-Ficticia-2026", "clave2": "Clave-Ficticia-2026",
        }

    def test_alta_crea_ficha_y_usuario_vinculado_sin_privilegios(self):
        respuesta = self.client.post(self.url, {**self.datos, "rol": "desarrollador", "activo": False, "is_staff": True, "is_superuser": True})
        self.assertRedirects(respuesta, reverse("portal:registro_recibido"))
        usuario = Usuario.objects.get()
        proveedor = Proveedor.objects.get()
        self.assertEqual(usuario.proveedor, proveedor)
        self.assertEqual(usuario.correo, "nuevo@ejemplo.test")
        self.assertEqual(usuario.rol, Rol.PROVEEDOR)
        self.assertTrue(usuario.activo)
        self.assertFalse(usuario.is_staff)
        self.assertFalse(usuario.is_superuser)
        self.assertFalse(usuario.debe_cambiar_clave)
        self.assertTrue(usuario.check_password(self.datos["clave1"]))
        self.assertEqual(proveedor.nit, "900123456")
        self.assertEqual(proveedor.estado, Proveedor.Estado.REGISTRADO)
        self.assertEqual(RegistroBitacora.objects.count(), 2)
        for registro in RegistroBitacora.objects.all():
            self.assertEqual(registro.actor, usuario)
            self.assertTrue(registro.motivo)
            self.assertNotIn(self.datos["clave1"], str(registro.valor_nuevo))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_parametro_desactiva_cuenta_hasta_revision(self):
        Parametro.objects.filter(clave=ACTIVAR_REGISTRO_PORTAL).update(valor="false")
        self.client.post(self.url, self.datos)
        usuario = Usuario.objects.get()
        self.assertFalse(usuario.activo)
        self.client.post(reverse("cuentas:ingresar"), {"username": usuario.correo, "password": self.datos["clave1"]})
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(usuario.proveedor.estado, "registrado")

    def test_nit_duplicado_no_revela_ficha_y_da_la_misma_respuesta(self):
        primera = self.client.post(self.url, self.datos, follow=True)
        segunda = self.client.post(self.url, {**self.datos, "nit": "900123456", "correo": "otro@ejemplo.test"}, follow=True)
        self.assertEqual(primera.redirect_chain, segunda.redirect_chain)
        self.assertEqual(primera.content, segunda.content)
        self.assertNotContains(segunda, "Proveedor Ficticio del Portal")
        self.assertEqual(Usuario.objects.count(), 1)
        self.assertEqual(Proveedor.objects.count(), 1)
        self.assertEqual(RegistroBitacora.objects.count(), 2)

    def test_correo_duplicado_no_crea_ficha_suelta(self):
        crear_usuario(Rol.ADMINISTRADOR, correo="nuevo@ejemplo.test")
        respuesta = self.client.post(self.url, self.datos)
        self.assertRedirects(respuesta, reverse("portal:registro_recibido"))
        self.assertFalse(Proveedor.objects.exists())

    def test_claves_debiles_y_distintas_y_nit_invalido_no_crean_cuentas(self):
        for cambio in ({"clave1": "123", "clave2": "123"}, {"clave2": "Otra-Clave-2026"}, {"nit": "no valido"}, {"contacto_telefono": "xx"}):
            with self.subTest(cambio=cambio):
                self.assertEqual(self.client.post(self.url, {**self.datos, **cambio}).status_code, 200)
                self.assertFalse(Proveedor.objects.exists())
                self.assertFalse(Usuario.objects.exists())

    def test_honeypot_no_crea_registros(self):
        respuesta = self.client.post(self.url, {**self.datos, "sitio_web": "https://bot.ejemplo.test"})
        self.assertRedirects(respuesta, reverse("portal:registro_recibido"))
        self.assertFalse(Proveedor.objects.exists())

    @override_settings(PORTAL_REGISTRO_INTENTOS=2)
    def test_limite_por_ip_comparte_sesiones_y_no_confia_en_forwarded(self):
        self.assertEqual(Client().post(self.url, {}).status_code, 200)
        self.assertEqual(Client().post(self.url, {}, HTTP_X_FORWARDED_FOR="10.0.0.1").status_code, 200)
        respuesta = Client().post(self.url, {}, HTTP_X_FORWARDED_FOR="10.0.0.2")
        self.assertEqual(respuesta.status_code, 429)
        self.assertEqual(respuesta["Retry-After"], "900")
        self.assertEqual(Client().post(self.url, {}, REMOTE_ADDR="10.0.0.3").status_code, 200)
        cache.clear()
        self.assertEqual(Client().post(self.url, {}).status_code, 200)

    def test_registro_requiere_csrf(self):
        self.assertEqual(Client(enforce_csrf_checks=True).post(self.url, self.datos).status_code, 403)
        self.assertFalse(Proveedor.objects.exists())

    def test_registro_revierte_ficha_y_usuario_si_falla_auditoria(self):
        with patch("portal.servicios.registrar", side_effect=ValidationError("Fallo simulado")):
            with self.assertRaises(ValidationError):
                servicios.registrar_proveedor(self.datos)
        self.assertFalse(Proveedor.objects.exists())
        self.assertFalse(Usuario.objects.exists())

    def test_sesion_administrativa_no_usa_el_registro_publico(self):
        self.client.force_login(crear_usuario(Rol.ADMINISTRADOR))
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.post(self.url, self.datos).status_code, 403)
