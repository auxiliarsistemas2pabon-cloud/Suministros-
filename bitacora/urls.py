from django.urls import path

from bitacora import views

app_name = "bitacora"

urlpatterns = [
    path("", views.consulta, name="consulta"),
]
