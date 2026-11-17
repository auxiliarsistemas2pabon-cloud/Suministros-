"""El recorrido explicativo solo existe en el entorno de demostración."""
from django.urls import path

from config.demo.vistas import inicio
from config.urls import urlpatterns as rutas_aplicacion

urlpatterns = [path("ejemplo/", inicio, name="ejemplo_inicio"), *rutas_aplicacion]
