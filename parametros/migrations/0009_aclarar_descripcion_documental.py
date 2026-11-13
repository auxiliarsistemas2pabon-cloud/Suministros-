"""Aclara los valores Sí/No sin modificar la decisión configurada."""
from django.db import migrations


def aclarar(apps, schema_editor):
    apps.get_model("parametros", "Parametro").objects.using(schema_editor.connection.alias).filter(
        clave="evaluacion.bloquear_si_documento_vencido",
        descripcion__startswith="No advierte y permite",
    ).update(descripcion="Con No, se advierte y se permite responder Sí con evidencia vencida; con Sí, se bloquea. Una evidencia no expedida a la fecha de evaluación tampoco es vigente. Por defecto No, pendiente de decisión D-05. Los faltantes no bloquean automáticamente.")


class Migration(migrations.Migration):
    dependencies = [("parametros", "0008_documento_vencido")]
    operations = [migrations.RunPython(aclarar, migrations.RunPython.noop)]
