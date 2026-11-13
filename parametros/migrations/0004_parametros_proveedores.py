"""Crea los parámetros de proveedores con su valor por defecto:

- D-03 «proveedor.roles_aprobadores» = administrador,desarrollador
- «proveedor.dias_alerta_vencimiento» = 30

Los valores se copian aquí para que la migración no dependa de parametros/catalogo.py.
"""

from django.db import migrations

PARAMETROS = [
    {
        "clave": "proveedor.roles_aprobadores",
        "nombre": "Roles que pueden aprobar proveedores",
        "descripcion": (
            "Roles, separados por coma, que pueden pasar un proveedor al estado «Aprobado». Valores posibles: "
            "administrador, desarrollador. Valor por defecto: administrador,desarrollador, mientras la clínica "
            "confirma la decisión D-03 (quién aprueba proveedores)."
        ),
        "decision": "D-03",
        "tipo": "texto",
        "valor": "administrador,desarrollador",
        "valor_por_defecto": "administrador,desarrollador",
    },
    {
        "clave": "proveedor.dias_alerta_vencimiento",
        "nombre": "Días de aviso antes del vencimiento de documentos",
        "descripcion": (
            "Un documento de proveedor aparece en la alerta «por vencer» cuando le quedan estos días o menos. "
            "Los documentos ya vencidos siempre aparecen. Valor por defecto: 30."
        ),
        "decision": "",
        "tipo": "entero",
        "valor": "30",
        "valor_por_defecto": "30",
    },
]


def crear_parametros(apps, schema_editor):
    Parametro = apps.get_model("parametros", "Parametro")
    for datos in PARAMETROS:
        datos = dict(datos)
        clave = datos.pop("clave")
        Parametro.objects.get_or_create(clave=clave, defaults=datos)


class Migration(migrations.Migration):
    dependencies = [("parametros", "0003_parametro_d01_aprobaciones")]

    # Al revertir no se borra: los parámetros no se eliminan.
    operations = [migrations.RunPython(crear_parametros, migrations.RunPython.noop)]
