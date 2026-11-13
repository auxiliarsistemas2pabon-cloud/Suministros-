from django.urls import path

from configuracion import catalogos_proveedores, views
from configuracion import busqueda

app_name = "configuracion"

urlpatterns = [
    path("buscar/", busqueda.global_, name="buscar"),
    path("listados/", busqueda.listado, {"clase": "ordenes"}, name="listados"),
    path("listados/<str:clase>/", busqueda.listado, name="listado_global"),
    path("proveedores/<slug:catalogo>/", catalogos_proveedores.lista, name="catalogos_proveedores"),
    path("proveedores/<slug:catalogo>/nuevo/", catalogos_proveedores.formulario, name="catalogo_proveedor_nuevo"),
    path("proveedores/<slug:catalogo>/<int:pk>/editar/", catalogos_proveedores.formulario, name="catalogo_proveedor_editar"),
    path("proveedores/<slug:catalogo>/<int:pk>/estado/", catalogos_proveedores.estado, name="catalogo_proveedor_estado"),
    path("", views.inicio, name="inicio"),
    # Áreas
    path("areas/", views.areas_lista, name="areas"),
    path("areas/nueva/", views.area_formulario, name="area_nueva"),
    path("areas/<int:pk>/editar/", views.area_formulario, name="area_editar"),
    path("areas/<int:pk>/estado/", views.area_estado, name="area_estado"),
    path("areas/<int:pk>/coordinadores/", views.area_coordinadores, name="area_coordinadores"),
    # Unidades de medida
    path("unidades/", views.unidades_lista, name="unidades"),
    path("unidades/nueva/", views.unidad_formulario, name="unidad_nueva"),
    path("unidades/<int:pk>/editar/", views.unidad_formulario, name="unidad_editar"),
    path("unidades/<int:pk>/estado/", views.unidad_estado, name="unidad_estado"),
    # Productos sugeridos
    path("productos/", views.productos_lista, name="productos"),
    path("productos/nuevo/", views.producto_formulario, name="producto_nuevo"),
    path("productos/<int:pk>/editar/", views.producto_formulario, name="producto_editar"),
    path("productos/<int:pk>/estado/", views.producto_estado, name="producto_estado"),
    # Usuarios
    path("usuarios/", views.usuarios_lista, name="usuarios"),
    path("usuarios/nuevo/", views.usuario_nuevo, name="usuario_nuevo"),
    path("usuarios/<int:pk>/editar/", views.usuario_editar, name="usuario_editar"),
    path("usuarios/<int:pk>/estado/", views.usuario_estado, name="usuario_estado"),
    path("usuarios/<int:pk>/restablecer-clave/", views.usuario_restablecer_clave, name="usuario_restablecer_clave"),
    path("usuarios/<int:pk>/clave-temporal/", views.usuario_clave_temporal, name="usuario_clave_temporal"),
    # Parámetros de las reglas pendientes de decisión
    path("parametros/", views.parametros_lista, name="parametros"),
    path("parametros/<int:pk>/editar/", views.parametro_editar, name="parametro_editar"),
]
