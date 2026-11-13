from django.apps import AppConfig


class ProveedoresConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "proveedores"
    verbose_name = "Proveedores"

    def ready(self):
        # Borrado seguro de los PDF al borrar o reemplazar documentos.
        from proveedores import signals  # noqa: F401
