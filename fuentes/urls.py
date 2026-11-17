from django.urls import path
from fuentes import views

app_name = "fuentes"
urlpatterns = [path("", views.inicio, name="inicio"), path("formatos/<int:pk>/", views.detalle, name="detalle"),
    path("formatos/<int:pk>/descargar/", views.descargar, name="descargar"),
    path("historico/", views.historico, name="historico"), path("elegibles/", views.elegibles, name="elegibles"),
    path("consecutivos/", views.consecutivos, name="consecutivos")]
