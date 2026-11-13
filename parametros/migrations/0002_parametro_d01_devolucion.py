"""Crea el parámetro de la decisión D-01 con su valor por defecto documentado (Sí).

Los valores se copian aquí (y no se importan de parametros/catalogo.py) para que la
migración siga igual aunque el catálogo cambie después.
"""

from django.db import migrations

D01 = {
    "clave": "proyeccion.permitir_devolucion",
    "nombre": "Permitir devolver proyecciones al área",
    "descripcion": (
        "Si está en Sí, administración puede devolver una proyección enviada al área para que la "
        "corrija; vuelve a borrador. Si está en No, administración solo puede corregirla directamente. "
        "Valor por defecto: Sí, mientras la clínica confirma la decisión D-01."
    ),
    "decision": "D-01",
    "tipo": "booleano",
    "valor": "true",
    "valor_por_defecto": "true",
}


def crear_d01(apps, schema_editor):
    Parametro = apps.get_model("parametros", "Parametro")
    datos = dict(D01)
    clave = datos.pop("clave")
    Parametro.objects.get_or_create(clave=clave, defaults=datos)


class Migration(migrations.Migration):
    dependencies = [("parametros", "0001_initial")]

    # Al revertir no se borra: los parámetros no se eliminan.
    operations = [migrations.RunPython(crear_d01, migrations.RunPython.noop)]
