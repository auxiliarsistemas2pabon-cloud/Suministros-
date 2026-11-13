from django.db import migrations


def cargar(apps, schema_editor):
    alias = schema_editor.connection.alias
    Estado = apps.get_model("compras", "EstadoVerificacion")
    Tipo = apps.get_model("compras", "TipoVerificacion")
    for orden, (nombre, clasificacion) in enumerate([("Sí", "si"), ("No", "no"), ("Pendiente", "pendiente"), ("N/A", "na")], 1):
        Estado.objects.using(alias).get_or_create(nombre=nombre, defaults={"clasificacion": clasificacion, "orden": orden})
    for orden, (nombre, origen) in enumerate([("Vigencia documental", "documental"), ("Requisitos técnicos", "manual"), ("Sarlaft", "manual"), ("Sicof", "manual")], 1):
        Tipo.objects.using(alias).get_or_create(nombre=nombre, defaults={"orden": orden, "origen": origen, "obligatoria": False})


class Migration(migrations.Migration):
    dependencies = [("compras", "0011_estadoverificacion_pdfverificacionoferta_and_more")]
    operations = [migrations.RunPython(cargar, migrations.RunPython.noop)]
