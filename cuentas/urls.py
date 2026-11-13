from django.urls import path

from cuentas import views

app_name = "cuentas"

urlpatterns = [
    path("ingresar/", views.Ingresar.as_view(), name="ingresar"),
    path("salir/", views.Salir.as_view(), name="salir"),
    path("cambiar-clave/", views.CambiarClave.as_view(), name="cambiar_clave"),
]
