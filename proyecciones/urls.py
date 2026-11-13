from django.urls import path

from proyecciones import views

app_name = "proyecciones"

urlpatterns = [
    path("plantilla-excel/", views.plantilla_excel, name="plantilla_excel"),
    path("<int:pk>/importar/", views.importar_excel, name="importar_excel"),
    path("abrir-periodo/", views.abrir_periodo, name="abrir_periodo"),
    path("periodos/<int:pk>/estado/", views.periodo_estado, name="periodo_estado"),
    path(
        "periodos/<int:periodo_pk>/areas/<int:area_pk>/crear-proyeccion/",
        views.crear_proyeccion_area,
        name="crear_proyeccion_area",
    ),
    path("mi-proyeccion/", views.mi_proyeccion, name="mi_proyeccion"),
    path("mi-proyeccion/<int:pk>/", views.mi_proyeccion, name="mi_proyeccion_detalle"),
    path("revision/", views.revision_lista, name="revision"),
    path("consolidado/", views.consolidado_vista, name="consolidado"),
    path("consolidado/exportar/", views.consolidado_exportar, name="consolidado_exportar"),
    path("revision/<int:pk>/", views.revision_detalle, name="revision_detalle"),
    path(
        "revision/<int:pk>/lineas/<int:linea_pk>/corregir/",
        views.revision_corregir_linea,
        name="revision_corregir_linea",
    ),
    path("revision/<int:pk>/devolver/", views.revision_devolver, name="revision_devolver"),
    path("revision/<int:pk>/aprobar/", views.revision_aprobar, name="revision_aprobar"),
    path(
        "revision/<int:pk>/lineas/<int:linea_pk>/ajustar/",
        views.revision_ajustar_linea,
        name="revision_ajustar_linea",
    ),
]
