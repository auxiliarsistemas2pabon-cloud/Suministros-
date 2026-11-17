"""Entorno local de demostración con datos y sesiones independientes."""
import os

os.environ["DJANGO_BASE_DATOS"] = "sqlite"
os.environ["DJANGO_PRODUCCION"] = "false"

from .settings import *  # noqa: F403,E402

MODO_DEMOSTRACION = True
DIRECTORIO_DEMOSTRACION = BASE_DIR / ".demostracion"
DATABASES = {"default": {
    "ENGINE": "django.db.backends.sqlite3",
    "NAME": DIRECTORIO_DEMOSTRACION / "db_demo.sqlite3",
}}
MEDIA_ROOT = DIRECTORIO_DEMOSTRACION / "archivos_privados"
STATIC_ROOT = DIRECTORIO_DEMOSTRACION / "staticfiles"
ROOT_URLCONF = "config.urls_demo"
DEBUG = True
ALLOWED_HOSTS = ["127.0.0.1", "localhost", "testserver"]
SESSION_COOKIE_NAME = "suministros_demo_sessionid"
CSRF_COOKIE_NAME = "suministros_demo_csrftoken"
CSRF_TRUSTED_ORIGINS = ["http://127.0.0.1:8002", "http://localhost:8002"]
EMAIL_BACKEND = "django.core.mail.backends.dummy.EmailBackend"
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
