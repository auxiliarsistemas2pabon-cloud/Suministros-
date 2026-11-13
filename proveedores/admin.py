"""Proveedores en el admin técnico: solo lectura.

Se gestionan en /proveedores/, donde cada cambio pide motivo y queda en la bitácora.
"""

from django.contrib import admin

from proveedores.models import CategoriaProveedor, DocumentoProveedor, EnvioProveedor, Peso, Proveedor, Requisito, TipoDocumento
from proyecciones.admin import SoloLecturaAdmin
from proveedores.models import VersionMatriz, EvaluacionProveedor
from proveedores.models import RespuestaEvaluacion, EvidenciaEvaluacion
from proveedores.models import DocumentoExigido


@admin.register(DocumentoExigido)
class DocumentoExigidoAdmin(SoloLecturaAdmin):
    list_display = ["categoria", "tipo", "requisito", "obligatorio", "activo"]


@admin.register(RespuestaEvaluacion)
class RespuestaAdmin(SoloLecturaAdmin):
    list_display = ["evaluacion", "requisito", "respuesta", "respondido_por", "fecha"]


@admin.register(EvidenciaEvaluacion)
class EvidenciaAdmin(SoloLecturaAdmin):
    list_display = ["evaluacion", "nombre_archivo", "cargado_por", "fecha"]
    exclude = ["archivo"]


@admin.register(VersionMatriz)
class VersionMatrizAdmin(SoloLecturaAdmin):
    list_display = ["numero", "estado", "desde", "hasta"]


@admin.register(EvaluacionProveedor)
class EvaluacionProveedorAdmin(SoloLecturaAdmin):
    list_display = ["proveedor", "categoria_nombre", "version", "fecha", "evaluador"]


@admin.register(EnvioProveedor)
class EnvioProveedorAdmin(SoloLecturaAdmin):
    list_display = ["proveedor", "tipo", "estado", "enviado_por", "fecha_envio", "revisado_por"]
    list_filter = ["estado", "tipo"]
    exclude = ["archivo"]


@admin.register(CategoriaProveedor)
class CategoriaProveedorAdmin(SoloLecturaAdmin):
    list_display = ["nombre", "activo", "fecha_creacion"]
    list_filter = ["activo"]
    search_fields = ["nombre"]


@admin.register(TipoDocumento)
class TipoDocumentoAdmin(SoloLecturaAdmin):
    list_display = ["nombre", "requiere_vencimiento", "dias_alerta", "usar_alerta_general", "activo", "fecha_creacion"]
    list_filter = ["activo", "requiere_vencimiento"]
    search_fields = ["nombre"]


@admin.register(Requisito)
class RequisitoAdmin(SoloLecturaAdmin):
    list_display = ["numero", "grupo", "texto", "activo"]
    list_filter = ["grupo", "activo"]
    search_fields = ["texto"]


@admin.register(Peso)
class PesoAdmin(SoloLecturaAdmin):
    list_display = ["requisito", "categoria", "valor"]
    list_filter = ["categoria", "requisito__grupo"]
    list_select_related = ["categoria", "requisito"]


@admin.register(Proveedor)
class ProveedorAdmin(SoloLecturaAdmin):
    list_display = ["razon_social", "nit", "digito_verificacion", "tipo_persona", "categoria", "estado", "fecha_registro"]
    list_filter = ["estado", "tipo_persona", "categoria"]
    search_fields = ["razon_social", "nit"]


@admin.register(DocumentoProveedor)
class DocumentoProveedorAdmin(SoloLecturaAdmin):
    # Sin enlace al archivo: los PDF solo se descargan desde la vista protegida de /proveedores/.
    list_display = ["proveedor", "tipo", "fecha_expedicion", "fecha_vencimiento", "nombre_archivo", "cargado_por", "fecha_carga"]
    list_filter = ["tipo"]
    search_fields = ["proveedor__razon_social", "proveedor__nit"]
    exclude = ["archivo"]
