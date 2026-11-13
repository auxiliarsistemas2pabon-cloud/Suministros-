from django.apps import AppConfig


class PortalConfig(AppConfig):
    """Portal de proveedores (sin modelos propios)."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "portal"
    verbose_name = "Portal de proveedores"
