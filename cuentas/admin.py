"""Admin técnico de usuarios. Solo lo usan desarrolladores (ver config/admin_sitio.py).

Todo cambio pide un motivo y queda en la bitácora (cuentas/servicios.py).
"""

from django.contrib import admin
from django.contrib.admin.utils import unquote
from django.contrib.auth.admin import UserAdmin
from django.db import transaction

from cuentas import servicios
from cuentas.forms import FormularioCambioUsuario, FormularioClaveAdmin, FormularioCreacionUsuario
from cuentas.models import Usuario


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    form = FormularioCambioUsuario
    add_form = FormularioCreacionUsuario
    change_password_form = FormularioClaveAdmin
    # Agrega el campo "motivo" a la pantalla de asignar clave.
    change_user_password_template = "admin/cuentas/usuario/cambiar_clave.html"

    list_display = ["correo", "nombre", "rol", "area", "activo", "debe_cambiar_clave", "is_staff"]
    list_filter = ["rol", "activo", "area", "debe_cambiar_clave", "is_staff"]
    search_fields = ["correo", "nombre"]
    ordering = ["correo"]
    readonly_fields = ["fecha_creacion", "last_login"]
    # Los permisos se manejan por rol (Usuario.rol), no con grupos de Django.
    filter_horizontal = []

    fieldsets = [
        (None, {"fields": ["correo", "password"]}),
        ("Datos personales", {"fields": ["nombre"]}),
        ("Rol, área y proveedor", {"fields": ["rol", "area", "proveedor"]}),
        ("Estado", {"fields": ["activo", "debe_cambiar_clave", "is_staff", "is_superuser"]}),
        ("Fechas", {"fields": ["fecha_creacion", "last_login"]}),
        ("Bitácora", {"fields": ["motivo"]}),
    ]
    add_fieldsets = [
        (
            None,
            {
                "classes": ["wide"],
                "fields": [
                    "correo",
                    "nombre",
                    "rol",
                    "area",
                    "proveedor",
                    "debe_cambiar_clave",
                    "password1",
                    "password2",
                    "motivo",
                ],
            },
        ),
    ]

    def save_model(self, request, obj, form, change):
        servicios.guardar_usuario(
            obj, actor=request.user, motivo=form.cleaned_data.get("motivo", ""), request=request
        )

    def user_change_password(self, request, id, form_url=""):
        # La clave y su registro en la bitácora se guardan juntos o no se guarda ninguno.
        with transaction.atomic():
            respuesta = super().user_change_password(request, id, form_url)
            if request.method == "POST" and respuesta.status_code == 302:
                usuario = self.get_object(request, unquote(id))
                servicios.registrar_restablecimiento_clave(request, usuario, request.POST.get("motivo", ""))
        return respuesta

    def has_delete_permission(self, request, obj=None):
        # Las personas se desactivan (campo "activo"), no se borran.
        return False
