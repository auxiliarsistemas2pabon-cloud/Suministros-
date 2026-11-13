"""Administrador técnico de Django, exclusivo de desarrolladores.

Los administradores del negocio trabajan en las vistas propias del sistema
(con rol_requerido), no aquí. Restringirlo a desarrolladores superusuarios
evita que un usuario con is_staff y permisos sueltos se otorgue privilegios.
"""

from django.contrib import admin


class SitioAdminTecnico(admin.AdminSite):
    site_header = "Administración técnica · Gestión de Suministros"
    site_title = "Administración técnica"
    index_title = "Administración técnica"

    def has_permission(self, request):
        return bool(getattr(request.user, "puede_usar_admin_tecnico", False))
