from django.urls import path

from proveedores import bandeja, historial, matrices, respuestas, views

app_name = "proveedores"

urlpatterns = [
    path("<int:proveedor_pk>/evaluaciones/", historial.lista, name="evaluaciones_historial"),
    path("evaluaciones/<int:pk>/copiar/", historial.copiar, name="evaluacion_copiar"),
    path("evaluaciones/<int:pk>/anular/", historial.anular, name="evaluacion_anular"),
    path("evaluaciones/<int:pk>/finalizar/", matrices.finalizar, name="evaluacion_finalizar"),
    path("evaluaciones/<int:pk>/respuestas/<int:respuesta_pk>/documento/", respuestas.documento_descargar, name="respuesta_documento"),
    path("evaluaciones/<int:pk>/requisitos/<int:requisito_pk>/", respuestas.responder, name="evaluacion_responder"),
    path("evaluaciones/<int:pk>/evidencias/<int:adjunto_pk>/", respuestas.descargar, name="evaluacion_evidencia"),
    path("matrices/", matrices.matriz, name="matrices"),
    path("matrices/<int:pk>/", matrices.matriz, name="matriz_detalle"),
    path("<int:proveedor_pk>/evaluaciones/nueva/", matrices.nueva_evaluacion, name="evaluacion_nueva"),
    path("evaluaciones/<int:pk>/", matrices.evaluacion_detalle, name="evaluacion_detalle"),
    path("bandeja/", bandeja.lista, name="bandeja"),
    path("bandeja/nuevo/", bandeja.manual, name="envio_manual"),
    path("bandeja/<int:pk>/", bandeja.detalle, name="envio_detalle"),
    path("bandeja/<int:pk>/descargar/", bandeja.descargar, name="envio_descargar"),
    path("bandeja/<int:pk>/aceptar/", bandeja.revisar, {"aceptar": True}, name="envio_aceptar"),
    path("bandeja/<int:pk>/descartar/", bandeja.revisar, {"aceptar": False}, name="envio_descartar"),
    path("", views.lista, name="lista"),
    path("nuevo/", views.formulario, name="nuevo"),
    path("vencimientos/", views.vencimientos, name="vencimientos"),
    path("<int:pk>/", views.detalle, name="detalle"),
    path("<int:pk>/editar/", views.formulario, name="editar"),
    path("<int:pk>/estado/", views.estado, name="estado"),
    path("<int:proveedor_pk>/documentos/nuevo/", views.documento_formulario, name="documento_nuevo"),
    path("<int:proveedor_pk>/documentos/<int:pk>/editar/", views.documento_formulario, name="documento_editar"),
    path("<int:proveedor_pk>/documentos/<int:pk>/eliminar/", views.documento_eliminar, name="documento_eliminar"),
    path("<int:proveedor_pk>/documentos/<int:pk>/descargar/", views.documento_descargar, name="documento_descargar"),
]
