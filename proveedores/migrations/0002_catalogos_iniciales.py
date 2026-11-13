"""Tipos de documento y categorías iniciales.

Son catálogos editables (se desactivan, no se borran). Mientras no exista su pantalla en
/configuracion/, se cargan aquí; los desarrolladores pueden consultarlos en el admin técnico.
"""

from django.db import migrations

TIPOS_DOCUMENTO = [
    # (nombre, requiere_vencimiento)
    ("RUT", False),
    ("Certificado de existencia y representación legal", True),
    ("Certificación bancaria", True),
    ("Cédula del representante legal", False),
    ("Certificado de antecedentes", True),
    ("Póliza", True),
    ("Registro sanitario", True),
    ("Otro", False),
]

CATEGORIAS = [
    "Medicamentos",
    "Dispositivos médicos",
    "Insumos médico-quirúrgicos",
    "Aseo y cafetería",
    "Papelería y oficina",
    "Servicios",
]


def crear_catalogos(apps, schema_editor):
    TipoDocumento = apps.get_model("proveedores", "TipoDocumento")
    CategoriaProveedor = apps.get_model("proveedores", "CategoriaProveedor")
    for nombre, requiere in TIPOS_DOCUMENTO:
        if not TipoDocumento.objects.filter(nombre__iexact=nombre).exists():
            TipoDocumento.objects.create(nombre=nombre, requiere_vencimiento=requiere)
    for nombre in CATEGORIAS:
        if not CategoriaProveedor.objects.filter(nombre__iexact=nombre).exists():
            CategoriaProveedor.objects.create(nombre=nombre)


class Migration(migrations.Migration):
    dependencies = [("proveedores", "0001_initial")]

    # Al revertir no se borra: los catálogos se desactivan, no se eliminan.
    operations = [migrations.RunPython(crear_catalogos, migrations.RunPython.noop)]
