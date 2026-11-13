"""Rutas principales del sistema.

Importante: aquí NO se publica MEDIA_ROOT (archivos_privados/). Los PDF se
descargan únicamente mediante vistas que validan permisos.
"""

from django.contrib import admin
from django.urls import include, path

from cuentas.views import inicio

urlpatterns = [
    path("", inicio, name="inicio"),
    # /ingresar/, /salir/ y /cambiar-clave/
    path("", include("cuentas.urls")),
    path("portal/", include("portal.urls")),
    # Consulta de la bitácora (app bitacora) publicada en /proyecciones/bitacora/.
    path("proyecciones/bitacora/", include("bitacora.urls")),
    path("proyecciones/", include("proyecciones.urls")),
    path("configuracion/", include("configuracion.urls")),
    path("proveedores/", include("proveedores.urls")),
    path("compras/", include("compras.urls")),
    path("seguimientos/", include("seguimientos.urls")),
    path("admin/", admin.site.urls),
]
