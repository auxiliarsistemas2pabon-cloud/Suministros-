"""URL solo para pruebas: una vista protegida por cada rol."""

from django.http import HttpResponse
from django.urls import include, path

from cuentas.models import ROLES_ADMIN, Rol
from cuentas.permisos import rol_requerido


def _vista(roles):
    @rol_requerido(*roles)
    def vista(request):
        return HttpResponse("ok")

    return vista


urlpatterns = [
    path(f"solo-{rol}/", _vista([rol]), name=f"solo_{rol}") for rol in Rol.values
] + [
    path("solo-admin/", _vista(ROLES_ADMIN), name="solo_admin"),
    path("", include("config.urls")),
]
