from django.db import migrations


def cargar(apps, schema_editor):
    apps.get_model("parametros", "Parametro").objects.using(schema_editor.connection.alias).get_or_create(
        clave="evaluacion.bloquear_si_documento_vencido", defaults={
            "nombre": "Bloquear Sí con evidencia documental vencida", "tipo": "booleano", "decision": "D-05",
            "valor": "false", "valor_por_defecto": "false",
            "descripcion": "Con No, se advierte y se permite responder Sí con evidencia vencida; con Sí, se bloquea. Una evidencia no expedida a la fecha de evaluación tampoco es vigente. Por defecto No, pendiente de decisión D-05. Los faltantes no bloquean automáticamente.",
        },
    )


class Migration(migrations.Migration):
    dependencies = [("parametros", "0007_reglas_fr14")]
    operations = [migrations.RunPython(cargar, migrations.RunPython.noop)]
