from django.db import migrations


def conservar(apps, schema_editor):
    Orden = apps.get_model("compras", "OrdenCompra")
    Linea = apps.get_model("compras", "OrdenLinea")
    alias = schema_editor.connection.alias
    for orden in Orden.objects.using(alias).iterator():
        primera = Linea.objects.using(alias).filter(orden_id=orden.pk).order_by("posicion").first()
        reglas = {**(primera.reglas_calculo if primera else {"decimales": 0, "modo": "ROUND_HALF_UP"}),
            "orden_descuento": "antes_impuesto", "nivel_redondeo": "linea"}
        Orden.objects.using(alias).filter(pk=orden.pk).update(base=orden.subtotal - orden.descuento, total_sin_retenciones=orden.total, reglas_importes=reglas)
        for linea in Linea.objects.using(alias).filter(orden_id=orden.pk).iterator():
            Linea.objects.using(alias).filter(pk=linea.pk).update(base=linea.subtotal-linea.descuento,
                base_impuesto=linea.subtotal-linea.descuento, descuento_aplicado=linea.descuento)
    # No se reescriben originales, revisiones, números ni importes históricos.


class Migration(migrations.Migration):
    dependencies = [("compras", "0021_importes_ordenes"), ("parametros", "0018_importes_ordenes")]
    operations = [migrations.RunPython(conservar, migrations.RunPython.noop)]
