"""Catálogos de la proyección en el admin técnico: solo lectura.

Se administran en /configuracion/, donde cada cambio pide motivo y queda en la bitácora.
"""

from django.contrib import admin

from proyecciones.models import (
    Ajuste,
    AprobacionProyeccion,
    Linea,
    Periodo,
    ProductoSugerido,
    ProyeccionArea,
    UnidadMedida,
)


class SoloLecturaAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(UnidadMedida)
class UnidadMedidaAdmin(SoloLecturaAdmin):
    list_display = ["nombre", "abreviatura", "activa", "fecha_creacion"]
    list_filter = ["activa"]
    search_fields = ["nombre", "abreviatura"]


@admin.register(ProductoSugerido)
class ProductoSugeridoAdmin(SoloLecturaAdmin):
    list_display = ["nombre", "unidad_por_defecto", "activo", "fecha_creacion"]
    list_filter = ["activo", "unidad_por_defecto"]
    search_fields = ["nombre"]


@admin.register(Periodo)
class PeriodoAdmin(SoloLecturaAdmin):
    list_display = [
        "anio",
        "fecha_apertura",
        "fecha_limite_diligenciamiento",
        "estado",
        "creado_por",
    ]
    list_filter = ["estado"]
    search_fields = ["=anio", "creado_por__correo", "creado_por__nombre"]
    list_select_related = ["creado_por"]


@admin.register(ProyeccionArea)
class ProyeccionAreaAdmin(SoloLecturaAdmin):
    list_display = [
        "periodo",
        "area",
        "estado",
        "fecha_envio",
        "enviado_por",
        "fecha_aprobacion",
        "aprobado_por",
    ]
    list_filter = ["estado", "periodo", "area"]
    search_fields = [
        "=periodo__anio",
        "area__nombre",
        "area__codigo_area",
        "enviado_por__correo",
        "aprobado_por__correo",
    ]
    list_select_related = ["periodo", "area", "enviado_por", "aprobado_por"]


@admin.register(Linea)
class LineaAdmin(SoloLecturaAdmin):
    list_display = [
        "producto_servicio",
        "proyeccion",
        "unidad",
        "total_anual_admin",
        "precio_estimado",
        "costo_anual_admin",
        "cantidad_autorizada",
    ]
    list_filter = ["unidad", "proyeccion__periodo", "proyeccion__area"]
    search_fields = ["producto_servicio", "dependencia"]
    list_select_related = ["proyeccion__periodo", "proyeccion__area", "unidad"]

    @admin.display(description="total anual", ordering="cantidad_enero")
    def total_anual_admin(self, obj):
        return obj.total_anual

    @admin.display(description="costo anual")
    def costo_anual_admin(self, obj):
        return obj.costo_anual


@admin.register(Ajuste)
class AjusteAdmin(SoloLecturaAdmin):
    list_display = ["fecha", "linea", "campo", "valor_aprobado", "valor_anterior", "valor_nuevo", "usuario"]
    list_filter = ["fecha", "campo"]
    search_fields = [
        "linea__producto_servicio",
        "campo",
        "justificacion",
        "usuario__correo",
    ]
    date_hierarchy = "fecha"
    list_select_related = ["linea", "usuario"]


@admin.register(AprobacionProyeccion)
class AprobacionProyeccionAdmin(SoloLecturaAdmin):
    list_display = ["fecha", "proyeccion", "usuario", "fecha_envio_aprobada", "motivo"]
    list_filter = ["fecha"]
    search_fields = ["proyeccion__area__nombre", "usuario__correo", "motivo"]
    list_select_related = ["proyeccion__area", "proyeccion__periodo", "usuario"]
