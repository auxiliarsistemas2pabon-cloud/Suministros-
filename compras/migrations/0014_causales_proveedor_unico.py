from django.db import migrations


def cargar(apps, schema_editor):
    Causal = apps.get_model("compras", "CausalProveedorUnico")
    for orden, nombre in enumerate(["Exclusividad", "Representación de marca", "Urgencia", "Otra"], 1):
        Causal.objects.using(schema_editor.connection.alias).get_or_create(nombre=nombre, defaults={"orden": orden})


class Migration(migrations.Migration):
    dependencies = [("compras", "0013_cotizacion_causal_unico_nombre_and_more")]
    operations = [migrations.RunPython(cargar, migrations.RunPython.noop)]
