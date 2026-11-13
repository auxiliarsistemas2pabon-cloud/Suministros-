from django.db import migrations


def cargar(apps, schema_editor):
    alias = schema_editor.connection.alias
    Version = apps.get_model("compras", "VersionCriterios")
    Criterio = apps.get_model("compras", "CriterioElegible")
    version, _ = Version.objects.using(alias).get_or_create(numero=1, defaults={
        "estado": "borrador", "notas": "Criterios iniciales FR-GDS-20. Revise y publique su vigencia; cálculo D-07 provisional."})
    for orden, (nombre, peso) in enumerate([
        ("Administrativos", "30.00"), ("Precio", "20.00"),
        ("Valor agregado", "20.00"), ("Certificaciones", "30.00"),
    ], 1):
        Criterio.objects.using(alias).get_or_create(version=version, orden=orden, defaults={"nombre": nombre, "peso": peso})


class Migration(migrations.Migration):
    dependencies = [("compras", "0002_listaelegibles_reglas_calculo_versioncriterios_and_more")]
    operations = [migrations.RunPython(cargar, migrations.RunPython.noop)]
