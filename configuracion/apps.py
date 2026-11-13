from django.apps import AppConfig


class ConfiguracionConfig(AppConfig):
    """Panel de configuración para administradores y desarrolladores (sin modelos propios)."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "configuracion"
    verbose_name = "Configuración"
