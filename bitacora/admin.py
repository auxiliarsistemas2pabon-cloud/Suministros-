from django.contrib import admin

from bitacora.models import RegistroBitacora


@admin.register(RegistroBitacora)
class RegistroBitacoraAdmin(admin.ModelAdmin):
    """Consulta de la bitácora: solo lectura."""

    list_display = ["fecha", "actor_texto", "accion", "objeto_texto", "motivo"]
    list_filter = ["accion", "tipo_objeto"]
    search_fields = ["actor_texto", "accion", "objeto_texto", "motivo"]
    date_hierarchy = "fecha"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
