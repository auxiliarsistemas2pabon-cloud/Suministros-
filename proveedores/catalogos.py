"""Metadatos compartidos por los servicios y las pantallas de catálogos."""

from proveedores.models import CategoriaProveedor, DocumentoExigido, Peso, Requisito, TipoDocumento

CATALOGOS = {
    "documentos-exigidos": {
        "modelo": DocumentoExigido, "titulo": "Documentos exigidos por categoría (D-05)", "singular": "documento exigido",
        "campos": ["categoria", "tipo", "requisito", "obligatorio", "activo"], "accion": "documento_exigido",
    },
    "categorias": {
        "modelo": CategoriaProveedor, "titulo": "Categorías de proveedores", "singular": "categoría",
        "campos": ["nombre", "descripcion", "activo"], "accion": "categoria_proveedor",
    },
    "tipos-documento": {
        "modelo": TipoDocumento, "titulo": "Tipos de documento", "singular": "tipo de documento",
        "campos": ["nombre", "requiere_vencimiento", "dias_alerta", "usar_alerta_general", "activo"],
        "accion": "tipo_documento",
    },
    "requisitos": {
        "modelo": Requisito, "titulo": "Requisitos FR-GDS-14", "singular": "requisito",
        "campos": ["version", "numero", "grupo", "texto", "activo"], "accion": "requisito",
    },
    "pesos": {
        "modelo": Peso, "titulo": "Pesos por requisito y categoría", "singular": "peso",
        "campos": ["requisito", "categoria", "valor"], "accion": "peso",
    },
}
