"""Pruebas del esqueleto: lectura del entorno, settings y plantilla base."""

import importlib
import os
import re
import runpy
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.contrib.messages import constants as niveles
from django.contrib.messages.storage.base import Message
from django.core.exceptions import ImproperlyConfigured
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.urls import Resolver404, clear_url_caches, resolve
from django.views.static import serve

from config.entorno import (
    env_bool,
    env_entero,
    env_lista,
    env_obligatoria,
    env_texto,
)
from config.seguridad import ip_cliente_detras_de_proxy

RUTA_SETTINGS = Path(settings.BASE_DIR) / "config" / "settings.py"

# Todas las variables que lee settings.py. Se fijan explícitamente para que
# el archivo .env local no influya en las pruebas (load_dotenv no
# sobrescribe variables ya definidas).
ENTORNO_BASE = {
    "PORTAL_REGISTRO_INTENTOS": "",
    "PORTAL_REGISTRO_VENTANA": "",
    "DJANGO_BASE_DATOS": "postgresql",
    "DJANGO_SECRET_KEY": "clave-ficticia-solo-para-pruebas",
    "DJANGO_DEBUG": "",
    "DJANGO_ALLOWED_HOSTS": "",
    "POSTGRES_DB": "suministros_prueba",
    "POSTGRES_USER": "usuario_prueba",
    "POSTGRES_PASSWORD": "contrasena-ficticia",
    "POSTGRES_HOST": "",
    "POSTGRES_PORT": "",
    "DJANGO_PRODUCCION": "",
    "DJANGO_HSTS_SEGUNDOS": "",
    "DJANGO_HSTS_SUBDOMINIOS": "",
    "DJANGO_HSTS_PRELOAD": "",
    "DJANGO_DETRAS_DE_PROXY": "",
    "DJANGO_CSRF_TRUSTED_ORIGINS": "",
}


def cargar_settings(**variables):
    """Ejecuta settings.py con un entorno controlado y devuelve sus valores."""
    entorno = {**ENTORNO_BASE, **variables}
    with mock.patch.dict(os.environ, entorno):
        return runpy.run_path(str(RUTA_SETTINGS))


class EntornoTests(SimpleTestCase):
    def test_texto_vacio_usa_defecto(self):
        self.assertEqual(env_texto("X", "localhost", entorno={"X": "  "}), "localhost")
        self.assertEqual(env_texto("X", "localhost", entorno={}), "localhost")
        self.assertEqual(env_texto("X", "localhost", entorno={"X": " db "}), "db")

    def test_obligatoria_falta_o_vacia(self):
        for entorno in ({}, {"X": ""}, {"X": "   "}):
            with self.subTest(entorno=entorno), self.assertRaises(ImproperlyConfigured):
                env_obligatoria("X", entorno=entorno)
        self.assertEqual(env_obligatoria("X", entorno={"X": "valor"}), "valor")

    def test_bool(self):
        for texto in ("True", "true", "1", "sí", "si", "yes", "on"):
            with self.subTest(texto=texto):
                self.assertIs(env_bool("X", entorno={"X": texto}), True)
        for texto in ("False", "false", "0", "no", "off"):
            with self.subTest(texto=texto):
                self.assertIs(env_bool("X", True, entorno={"X": texto}), False)
        self.assertIs(env_bool("X", entorno={}), False)
        self.assertIs(env_bool("X", True, entorno={"X": ""}), True)

    def test_bool_invalido(self):
        with self.assertRaises(ImproperlyConfigured):
            env_bool("X", entorno={"X": "quizas"})

    def test_entero(self):
        self.assertEqual(env_entero("X", 5433, entorno={}), 5433)
        self.assertEqual(env_entero("X", 5433, entorno={"X": "5432"}), 5432)
        with self.assertRaises(ImproperlyConfigured):
            env_entero("X", 5433, entorno={"X": "puerto"})

    def test_lista(self):
        self.assertEqual(
            env_lista("X", entorno={"X": " localhost, 127.0.0.1 ,,"}),
            ["localhost", "127.0.0.1"],
        )
        self.assertEqual(env_lista("X", entorno={}), [])
        self.assertEqual(env_lista("X", ["a"], entorno={"X": ""}), ["a"])


class SettingsTests(SimpleTestCase):
    def test_sqlite_local_no_exige_credenciales_postgres(self):
        valores = cargar_settings(DJANGO_BASE_DATOS="sqlite", POSTGRES_DB="", POSTGRES_USER="", POSTGRES_PASSWORD="")
        self.assertEqual(valores["DATABASES"]["default"]["ENGINE"], "django.db.backends.sqlite3")

    def test_motor_desconocido_se_rechaza(self):
        with self.assertRaisesMessage(ImproperlyConfigured, "DJANGO_BASE_DATOS"):
            cargar_settings(DJANGO_BASE_DATOS="desconocido")

    def test_motor_por_defecto_local_y_produccion(self):
        self.assertEqual(cargar_settings(DJANGO_BASE_DATOS="")["MOTOR_BASE_DATOS"], "sqlite")
        valores = cargar_settings(DJANGO_BASE_DATOS="", DJANGO_PRODUCCION="True", DJANGO_ALLOWED_HOSTS="ejemplo.test")
        self.assertEqual(valores["MOTOR_BASE_DATOS"], "postgresql")

    def test_valores_por_defecto(self):
        valores = cargar_settings()
        self.assertIs(valores["DEBUG"], False)
        self.assertEqual(valores["ALLOWED_HOSTS"], [])
        base = valores["DATABASES"]["default"]
        self.assertEqual(base["ENGINE"], "django.db.backends.postgresql")
        self.assertEqual(base["HOST"], "127.0.0.1")
        self.assertEqual(base["PORT"], 5433)
        self.assertIs(valores["PRODUCCION"], False)
        self.assertNotIn("SECURE_SSL_REDIRECT", valores)

    def test_secret_key_obligatoria(self):
        with self.assertRaisesMessage(ImproperlyConfigured, "DJANGO_SECRET_KEY"):
            cargar_settings(DJANGO_SECRET_KEY="")

    def test_credenciales_postgres_obligatorias(self):
        for nombre in ("POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD"):
            with self.subTest(nombre=nombre), self.assertRaisesMessage(ImproperlyConfigured, nombre):
                cargar_settings(**{nombre: ""})

    def test_hosts_por_comas(self):
        valores = cargar_settings(DJANGO_ALLOWED_HOSTS="localhost, 127.0.0.1")
        self.assertEqual(valores["ALLOWED_HOSTS"], ["localhost", "127.0.0.1"])

    def test_produccion_activa_seguridad(self):
        valores = cargar_settings(
            DJANGO_PRODUCCION="True",
            DJANGO_ALLOWED_HOSTS="suministros.ejemplo.test",
            DJANGO_HSTS_SEGUNDOS="31536000",
            DJANGO_DETRAS_DE_PROXY="True",
            DJANGO_CSRF_TRUSTED_ORIGINS="https://suministros.ejemplo.test",
        )
        self.assertIs(valores["SECURE_SSL_REDIRECT"], True)
        self.assertIs(valores["SESSION_COOKIE_SECURE"], True)
        self.assertIs(valores["CSRF_COOKIE_SECURE"], True)
        self.assertEqual(valores["SECURE_HSTS_SECONDS"], 31536000)
        self.assertIs(valores["SECURE_HSTS_INCLUDE_SUBDOMAINS"], False)
        self.assertEqual(valores["SECURE_PROXY_SSL_HEADER"], ("HTTP_X_FORWARDED_PROTO", "https"))
        self.assertEqual(
            valores["AXES_CLIENT_IP_CALLABLE"], "config.seguridad.ip_cliente_detras_de_proxy"
        )
        self.assertEqual(valores["CSRF_TRUSTED_ORIGINS"], ["https://suministros.ejemplo.test"])

    def test_produccion_sin_proxy_no_confia_en_encabezado(self):
        valores = cargar_settings(
            DJANGO_PRODUCCION="True",
            DJANGO_ALLOWED_HOSTS="suministros.ejemplo.test",
        )
        self.assertNotIn("SECURE_PROXY_SSL_HEADER", valores)
        self.assertNotIn("AXES_CLIENT_IP_CALLABLE", valores)
        self.assertEqual(valores["SECURE_HSTS_SECONDS"], 3600)

    def test_produccion_rechaza_debug(self):
        with self.assertRaises(ImproperlyConfigured):
            cargar_settings(
                DJANGO_PRODUCCION="True",
                DJANGO_DEBUG="True",
                DJANGO_ALLOWED_HOSTS="suministros.ejemplo.test",
            )

    def test_produccion_exige_hosts(self):
        with self.assertRaises(ImproperlyConfigured):
            cargar_settings(DJANGO_PRODUCCION="True")

    def test_produccion_rechaza_origen_csrf_sin_https(self):
        with self.assertRaises(ImproperlyConfigured):
            cargar_settings(
                DJANGO_PRODUCCION="True",
                DJANGO_ALLOWED_HOSTS="suministros.ejemplo.test",
                DJANGO_CSRF_TRUSTED_ORIGINS="http://suministros.ejemplo.test",
            )

    def test_idioma_y_zona_horaria(self):
        self.assertEqual(settings.LANGUAGE_CODE, "es-co")
        self.assertEqual(settings.TIME_ZONE, "America/Bogota")
        self.assertIs(settings.USE_TZ, True)

    def test_archivos_privados_sin_url_publica(self):
        self.assertEqual(Path(settings.MEDIA_ROOT), Path(settings.BASE_DIR) / "archivos_privados")
        # settings.py no debe definir MEDIA_URL (Django lo deja en "/" por defecto,
        # pero ninguna ruta sirve los archivos).
        self.assertNotIn("MEDIA_URL", cargar_settings())
        with self.assertRaises(Resolver404):
            resolve("/archivos_privados/documento.pdf")
        with self.assertRaises(Resolver404):
            resolve("/media/documento.pdf")

    def test_ninguna_ruta_sirve_archivos_ni_siquiera_con_debug(self):
        """django.conf.urls.static.static() solo agrega rutas con DEBUG=True;
        por eso se recargan las URL con DEBUG activo y se buscan vistas serve."""

        def vistas(patrones):
            for patron in patrones:
                if hasattr(patron, "url_patterns"):
                    yield from vistas(patron.url_patterns)
                else:
                    yield patron.callback

        import config.urls

        try:
            with override_settings(DEBUG=True):
                importlib.reload(config.urls)
                callbacks = list(vistas(config.urls.urlpatterns))
        finally:
            importlib.reload(config.urls)
            clear_url_caches()
        self.assertNotIn(serve, callbacks)

    def test_interfaz_siempre_en_espanol(self):
        self.assertNotIn("django.middleware.locale.LocaleMiddleware", settings.MIDDLEWARE)

    def test_axes_configurado(self):
        self.assertIn("axes", settings.INSTALLED_APPS)
        self.assertEqual(settings.MIDDLEWARE[-1], "axes.middleware.AxesMiddleware")
        self.assertEqual(settings.AUTHENTICATION_BACKENDS[0], "axes.backends.AxesStandaloneBackend")


class IpClienteTests(SimpleTestCase):
    def setUp(self):
        self.fabrica = RequestFactory()

    def ip(self, **meta):
        return ip_cliente_detras_de_proxy(self.fabrica.get("/", **meta))

    def test_toma_la_ultima_entrada_agregada_por_el_proxy(self):
        # La primera entrada la puede falsificar el cliente; la última la pone el proxy.
        self.assertEqual(
            self.ip(HTTP_X_FORWARDED_FOR="1.2.3.4, 203.0.113.7", REMOTE_ADDR="10.0.0.2"),
            "203.0.113.7",
        )

    def test_sin_encabezado_usa_remote_addr(self):
        self.assertEqual(self.ip(REMOTE_ADDR="10.0.0.2"), "10.0.0.2")

    def test_valor_invalido_usa_remote_addr(self):
        self.assertEqual(self.ip(HTTP_X_FORWARDED_FOR="no-es-ip", REMOTE_ADDR="10.0.0.2"), "10.0.0.2")
        self.assertEqual(self.ip(HTTP_X_FORWARDED_FOR=" , ", REMOTE_ADDR="10.0.0.2"), "10.0.0.2")

    def test_ipv6(self):
        self.assertEqual(self.ip(HTTP_X_FORWARDED_FOR="2001:db8::1", REMOTE_ADDR="10.0.0.2"), "2001:db8::1")


class PlantillaBaseTests(SimpleTestCase):
    def test_muestra_nombre_mensajes_y_estilos(self):
        html = render_to_string(
            "base.html",
            {
                "user": AnonymousUser(),
                "messages": [
                    Message(niveles.SUCCESS, "Registro guardado."),
                    Message(niveles.ERROR, "No tiene permiso."),
                ],
            },
        )
        self.assertIn("Sistema de Gestión de Suministros", html)
        self.assertIn('lang="es-CO"', html)
        self.assertIn("css/estilos.css", html)
        self.assertIn(
            '<li class="mensaje mensaje--success"><span role="status">Registro guardado.</span></li>', html
        )
        self.assertIn(
            '<li class="mensaje mensaje--error"><span role="alert">No tiene permiso.</span></li>', html
        )
        # Sin sesión no se muestra el menú.
        self.assertNotIn('aria-label="Menú principal"', html)

    def test_colores_en_variables_css(self):
        css = (Path(settings.BASE_DIR) / "static" / "css" / "estilos.css").read_text(encoding="utf-8")
        for variable in (
            "--azul: #172554",
            "--azul-hover: #0f1a3d",
            "--azul-claro: #dbeafe",
            "--rojo: #991b1b",
            "--rojo-hover: #7f1d1d",
        ):
            with self.subTest(variable=variable):
                self.assertIn(variable, css)


class ConvencionesTests(SimpleTestCase):
    @override_settings(DEBUG=False)
    def test_error_404_en_espanol(self):
        respuesta = self.client.get("/pagina-que-no-existe/")
        self.assertContains(respuesta, "Página no encontrada", status_code=404)

    def test_error_500_no_depende_de_base_de_datos_ni_revela_excepcion(self):
        from django.views.defaults import server_error

        respuesta = server_error(RequestFactory().get("/"))
        self.assertContains(respuesta, "No fue posible completar la solicitud", status_code=500)
        self.assertNotContains(respuesta, "Traceback", status_code=500)

    def test_etiquetas_django_en_una_sola_linea(self):
        """Ninguna etiqueta {% %} ni {# #} puede partirse en varias líneas."""
        base = Path(settings.BASE_DIR)
        partida = re.compile(r"\{%(?:(?!%\}).)*\n|\{#(?:(?!#\}).)*\n", re.DOTALL)
        plantillas = [
            ruta
            for ruta in base.rglob("*.html")
            if not {".venv", "staticfiles", "node_modules"} & set(ruta.relative_to(base).parts)
        ]
        self.assertTrue(plantillas)
        for ruta in plantillas:
            with self.subTest(plantilla=str(ruta.relative_to(base))):
                self.assertIsNone(partida.search(ruta.read_text(encoding="utf-8")))
