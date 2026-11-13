"""Parámetros en el admin técnico: solo lectura. Se editan en /configuracion/parametros/."""

from django.contrib import admin

from parametros.models import Parametro


@admin.register(Parametro)
class ParametroAdmin(admin.ModelAdmin):
    list_display = ["clave", "nombre", "decision", "valor", "valor_por_defecto", "fecha_modificacion"]
    search_fields = ["clave", "nombre", "decision"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
