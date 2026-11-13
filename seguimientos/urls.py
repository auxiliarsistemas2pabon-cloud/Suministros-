from django.urls import path
from seguimientos import views

app_name = "seguimientos"
urlpatterns = [
    path("", views.lista, name="lista"),
    path("nuevo/", views.crear, name="crear"),
    path("catalogos/<str:clase>/", views.catalogo, name="catalogo"),
    path("catalogos/<str:clase>/<int:pk>/", views.catalogo, name="catalogo_editar"),
    path("<int:pk>/", views.detalle, name="detalle"),
    path("<int:pk>/corregir/", views.corregir, name="corregir"),
    path("<int:pk>/eventos/nuevo/", views.evento, name="evento"),
    path("<int:pk>/eventos/<int:evento_pk>/pdf/", views.descargar, name="evento_pdf"),
    path("<int:pk>/cerrar/", views.cerrar, name="cerrar"),
    path("<int:pk>/lineas/<int:linea_pk>/<str:accion>/", views.mover_linea, name="linea_accion"),
    path("<int:pk>/<str:accion>/", views.actuar, name="accion"),
]
