from django.db import migrations


def cargar(apps, schema_editor):
    apps.get_model("compras", "TarifaImpuesto").objects.using(schema_editor.connection.alias).get_or_create(
        nombre="Exento/No gravado", defaults={"porcentaje": "0.0000", "activo": True})


class Migration(migrations.Migration):
    dependencies = [("compras", "0009_oferta_pdfoferta_oferta_pdf_revisionoferta_and_more")]
    operations = [migrations.RunPython(cargar, migrations.RunPython.noop)]
