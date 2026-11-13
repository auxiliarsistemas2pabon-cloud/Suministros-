from django.db import migrations


def cargar(apps, schema_editor):
    Parametro = apps.get_model("parametros", "Parametro")
    for clave, nombre, tipo, valor, descripcion in [
        ("cotizacion.decimales_importes", "Decimales de importes de ofertas", "entero", "0",
         "Provisional: 0 redondea a pesos; también se admiten 1 o 2 decimales. Por línea se redondea cantidad × precio, luego el impuesto sobre ese subtotal; total = subtotal + impuesto. El encabezado suma los valores de líneas. Se conservan las reglas de cada guardado."),
        ("cotizacion.modo_redondeo", "Modo de redondeo de ofertas", "texto", "ROUND_HALF_UP",
         "Provisional: ROUND_HALF_UP por defecto. Alternativas ROUND_HALF_EVEN, ROUND_DOWN y ROUND_UP. Solo afecta nuevos guardados; las revisiones anteriores conservan reglas y resultados. No define IVA fijo ni aplica descuentos implícitos."),
    ]:
        Parametro.objects.using(schema_editor.connection.alias).get_or_create(clave=clave, defaults={
            "nombre": nombre, "tipo": tipo, "decision": "D-11", "valor": valor, "valor_por_defecto": valor, "descripcion": descripcion})


class Migration(migrations.Migration):
    dependencies = [("parametros", "0012_limites_cotizaciones")]
    operations = [migrations.RunPython(cargar, migrations.RunPython.noop)]
