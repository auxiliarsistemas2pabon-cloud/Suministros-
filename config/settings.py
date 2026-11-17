"""Configuración del Sistema de Gestión de Suministros.

Todos los valores sensibles o dependientes del entorno se leen del archivo
.env (ver .env.example). Nunca escriba secretos en este archivo.
"""

from datetime import timedelta
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

from config.entorno import (
    env_bool,
    env_entero,
    env_lista,
    env_obligatoria,
    env_texto,
)

BASE_DIR = Path(__file__).resolve().parent.parent

# Las variables ya definidas en el entorno del sistema tienen prioridad
# sobre las del archivo .env (override=False).
load_dotenv(Path(env_texto("DJANGO_ENV_FILE", defecto=str(BASE_DIR / ".env"))), override=False)


# --- Seguridad básica --------------------------------------------------------

SECRET_KEY = env_obligatoria("DJANGO_SECRET_KEY")

DEBUG = env_bool("DJANGO_DEBUG", defecto=False)

ALLOWED_HOSTS = env_lista("DJANGO_ALLOWED_HOSTS")


# --- Aplicaciones ------------------------------------------------------------

INSTALLED_APPS = [
    # Admin de Django restringido a desarrolladores (config/admin_sitio.py).
    "config.apps.AdminTecnicoConfig",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "axes",
    # Apps del proyecto
    "bitacora",
    "areas",
    "cuentas",
    "parametros",
    "portal",
    "proyecciones",
    "configuracion",
    "proveedores",
    "compras",
    "seguimientos",
    "fuentes",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    # Obliga a cambiar la clave cuando Usuario.debe_cambiar_clave es True.
    "cuentas.middleware.ObligarCambioClaveMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # django-axes debe ir al final para registrar los intentos de acceso.
    "axes.middleware.AxesMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "cuentas.contexto.accesos",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# --- Base de datos (SQLite local; PostgreSQL configurable) -------------------

MOTOR_BASE_DATOS = env_texto(
    "DJANGO_BASE_DATOS", defecto="postgresql" if env_bool("DJANGO_PRODUCCION", defecto=False) else "sqlite",
)
if MOTOR_BASE_DATOS == "sqlite":
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}
elif MOTOR_BASE_DATOS == "postgresql":
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env_obligatoria("POSTGRES_DB"),
        "USER": env_obligatoria("POSTGRES_USER"),
        "PASSWORD": env_obligatoria("POSTGRES_PASSWORD"),
        "HOST": env_texto("POSTGRES_HOST", defecto="127.0.0.1"),
        "PORT": env_entero("POSTGRES_PORT", defecto=5433),
    }}
else:
    raise ImproperlyConfigured("DJANGO_BASE_DATOS debe ser sqlite o postgresql.")


# --- Autenticación -----------------------------------------------------------

AUTH_USER_MODEL = "cuentas.Usuario"

LOGIN_URL = "cuentas:ingresar"
LOGIN_REDIRECT_URL = "inicio"
LOGOUT_REDIRECT_URL = "cuentas:ingresar"

AUTHENTICATION_BACKENDS = [
    # django-axes primero, para bloquear antes de validar la contraseña.
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]

# Mensajes en español por la traducción de Django (LANGUAGE_CODE es-co).
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
        # Los nombres por defecto (username, email...) no existen en Usuario.
        "OPTIONS": {"user_attributes": ("correo", "nombre")},
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 10},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Sesión: se cierra tras 30 minutos sin actividad y al cerrar el navegador.
SESSION_COOKIE_AGE = 30 * 60
SESSION_SAVE_EVERY_REQUEST = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = True

# django-axes: 5 intentos fallidos bloquean ese correo durante 15 minutos.
# Se bloquea por correo (no por IP). Si el portal se publica en internet,
# evalúe agregar también el bloqueo por IP (ver docs/avances.md).
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = timedelta(minutes=15)
AXES_RESET_ON_SUCCESS = True
AXES_LOCKOUT_PARAMETERS = ["username"]
# Cuenta los intentos por correo normalizado (sin distinguir mayúsculas).
AXES_USERNAME_CALLABLE = "cuentas.seguridad.usuario_para_axes"
AXES_LOCKOUT_TEMPLATE = "cuentas/bloqueado.html"

# Protección básica del registro público; la caché debe compartirse entre procesos
# cuando se publique el portal (ver docs/portal_proveedores.md).
PORTAL_REGISTRO_INTENTOS = env_entero("PORTAL_REGISTRO_INTENTOS", 5)
PORTAL_REGISTRO_VENTANA = env_entero("PORTAL_REGISTRO_VENTANA", 900)
if PORTAL_REGISTRO_INTENTOS < 1 or PORTAL_REGISTRO_VENTANA < 1:
    raise ImproperlyConfigured("Los límites PORTAL_REGISTRO_INTENTOS y PORTAL_REGISTRO_VENTANA deben ser positivos.")

SILENCED_SYSTEM_CHECKS = [
    # axes.W006 avisa que no se bloquea por IP. Es la decisión acordada
    # (bloqueo por correo); se revisará si el portal se publica en internet.
    "axes.W006",
]


# --- Idioma y zona horaria ---------------------------------------------------

LANGUAGE_CODE = "es-co"
TIME_ZONE = "America/Bogota"
USE_I18N = True
USE_TZ = True


# --- Archivos estáticos y privados -------------------------------------------

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = Path(env_texto("DJANGO_STATIC_ROOT", defecto=str(BASE_DIR / "staticfiles")))

# Archivos subidos (PDF): carpeta privada. A propósito NO se define MEDIA_URL
# ni se publica esta carpeta en urls.py; las descargas pasan siempre por una
# vista con control de permisos.
MEDIA_ROOT = Path(env_texto("DJANGO_ARCHIVOS_PRIVADOS", defecto=str(BASE_DIR / "archivos_privados")))

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

TEST_RUNNER = "config.pruebas.EjecutorPruebas"


# --- Producción (DJANGO_PRODUCCION=True) -------------------------------------

PRODUCCION = env_bool("DJANGO_PRODUCCION", defecto=False)

if PRODUCCION:
    if DEBUG:
        raise ImproperlyConfigured(
            "DJANGO_DEBUG debe ser False cuando DJANGO_PRODUCCION es True."
        )
    if not ALLOWED_HOSTS:
        raise ImproperlyConfigured(
            "Defina DJANGO_ALLOWED_HOSTS cuando DJANGO_PRODUCCION es True."
        )

    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

    # HSTS: empiece con un valor bajo y súbalo (p. ej. 31536000) cuando
    # confirme que todo el sitio funciona por HTTPS.
    SECURE_HSTS_SECONDS = env_entero("DJANGO_HSTS_SEGUNDOS", 3600)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("DJANGO_HSTS_SUBDOMINIOS", False)
    SECURE_HSTS_PRELOAD = env_bool("DJANGO_HSTS_PRELOAD", False)

    # Solo si un proxy inverso de confianza termina el HTTPS y envía
    # X-Forwarded-Proto y X-Forwarded-For. Sin proxy, activarlo permitiría
    # falsificar HTTPS y la IP del cliente.
    if env_bool("DJANGO_DETRAS_DE_PROXY", False):
        SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
        # Sin esto, django-axes vería siempre la IP del proxy.
        AXES_CLIENT_IP_CALLABLE = "config.seguridad.ip_cliente_detras_de_proxy"

    CSRF_TRUSTED_ORIGINS = env_lista("DJANGO_CSRF_TRUSTED_ORIGINS")
    for origen in CSRF_TRUSTED_ORIGINS:
        if not origen.startswith("https://"):
            raise ImproperlyConfigured(
                f"DJANGO_CSRF_TRUSTED_ORIGINS solo admite orígenes https:// ({origen!r})."
            )
