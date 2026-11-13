from django.db import migrations


def cargar(apps, schema_editor):
    Contador = apps.get_model("compras", "ContadorOrdenCompra")
    Contador.objects.using(schema_editor.connection.alias).get_or_create(clave="global", defaults={"ultimo": 0})


class Migration(migrations.Migration):
    dependencies = [("compras", "0019_contadorordencompra_ordencompra_anio_consecutivo_and_more")]
    operations = [migrations.RunPython(cargar, migrations.RunPython.noop)]
