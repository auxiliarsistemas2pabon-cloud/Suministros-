"""Crea el parámetro de aprobaciones requeridas (decisión D-01) con su valor por defecto (1).

Los valores se copian aquí para que la migración no dependa de parametros/catalogo.py.
"""

from django.db import migrations

APROBACIONES = {
    "clave": "proyeccion.aprobaciones_requeridas",
    "nombre": "Aprobaciones requeridas por proyección",
    "descripcion": (
        "Número de administradores distintos que deben aprobar un envío para que la proyección quede "
        "aprobada. Valor por defecto: 1, mientras la clínica confirma la decisión D-01 (una o varias "
        "aprobaciones)."
    ),
    "decision": "D-01",
    "tipo": "entero",
    "valor": "1",
    "valor_por_defecto": "1",
}


def crear_parametro(apps, schema_editor):
    Parametro = apps.get_model("parametros", "Parametro")
    datos = dict(APROBACIONES)
    clave = datos.pop("clave")
    Parametro.objects.get_or_create(clave=clave, defaults=datos)


class Migration(migrations.Migration):
    dependencies = [("parametros", "0002_parametro_d01_devolucion")]

    # Al revertir no se borra: los parámetros no se eliminan.
    operations = [migrations.RunPython(crear_parametro, migrations.RunPython.noop)]
