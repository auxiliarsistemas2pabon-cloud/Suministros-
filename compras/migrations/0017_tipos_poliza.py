from django.db import migrations


def cargar(apps, schema_editor):
    Tipo = apps.get_model("compras", "TipoPoliza")
    for orden, nombre in enumerate(["Cumplimiento", "Calidad", "Responsabilidad civil"], 1):
        Tipo.objects.using(schema_editor.connection.alias).get_or_create(nombre=nombre, defaults={"orden": orden})


class Migration(migrations.Migration):
    dependencies = [("compras", "0016_aprobacioncotizacion_contrato_datos_and_more")]
    operations = [migrations.RunPython(cargar, migrations.RunPython.noop)]
