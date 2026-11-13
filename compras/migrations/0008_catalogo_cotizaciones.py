from django.db import migrations


def cargar(apps, schema_editor):
    alias = schema_editor.connection.alias
    apps.get_model("compras", "SecuenciaCotizacion").objects.using(alias).get_or_create(pk=1, defaults={"ultimo": 0})
    Tipo = apps.get_model("compras", "TipoCotizacion")
    for nombre in ("Compra", "Servicio", "Contrato"):
        Tipo.objects.using(alias).get_or_create(nombre=nombre)


class Migration(migrations.Migration):
    dependencies = [("compras", "0007_secuenciacotizacion_tipocotizacion_cotizacion_and_more")]
    operations = [migrations.RunPython(cargar, migrations.RunPython.noop)]
