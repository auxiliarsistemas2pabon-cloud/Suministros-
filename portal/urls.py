from django.urls import path

from portal import views

app_name = "portal"

urlpatterns = [
    path("registro/", views.registro, name="registro"),
    path("registro/recibido/", views.registro_recibido, name="registro_recibido"),
    path("envios/nuevo/", views.envio_nuevo, name="envio_nuevo"),
    path("envios/<int:pk>/descargar/", views.envio_descargar, name="envio_descargar"),
    path("documentos/<int:pk>/descargar/", views.documento_descargar, name="documento_descargar"),
    path("", views.inicio, name="inicio"),
]
