from django.db import migrations


def cargar(apps, schema_editor):
    apps.get_model("parametros", "Parametro").objects.using(schema_editor.connection.alias).get_or_create(
        clave="proveedor.conservar_pdf_descartado", defaults={
            "nombre": "Conservar PDF de envíos descartados", "tipo": "booleano", "valor": "true",
            "valor_por_defecto": "true", "decision": "",
            "descripcion": "Sí conserva el PDF descartado para consulta del historial. Si se elige No, el archivo se elimina después del commit si no tiene otras referencias. El historial del envío siempre se conserva. Por defecto: Sí, pendiente de la política de retención de la clínica. Cambiarlo no elimina archivos de descartes anteriores.",
        },
    )


class Migration(migrations.Migration):
    dependencies = [("parametros", "0005_activacion_registro_portal")]
    operations = [migrations.RunPython(cargar, migrations.RunPython.noop)]
