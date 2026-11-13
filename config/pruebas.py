"""Ejecutor de pruebas del proyecto (solo se usa con manage.py test)."""

import logging

from django.conf import settings
from django.test.runner import DiscoverRunner


class EjecutorPruebas(DiscoverRunner):
    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        # El hash real (PBKDF2) es lento a propósito; en pruebas no aporta y
        # multiplica el tiempo de ejecución. No afecta a producción.
        settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
        # django-axes registra cada intento fallido; en pruebas solo es ruido.
        logging.getLogger("axes").setLevel(logging.ERROR)
