from django.db import migrations


def cargar(apps, schema_editor):
    Parametro = apps.get_model("parametros", "Parametro")
    for clave, nombre, tipo, valor, descripcion in [
        ("orden.orden_descuento", "Momento del descuento en orden", "texto", "antes_impuesto", "antes_impuesto o despues_impuesto. Aplicación explícita en borrador; pendiente de validar con financiera."),
        ("orden.nivel_redondeo", "Nivel de redondeo de orden", "texto", "linea", "linea o total. Total reparte residuos por posición, conservando sumas. Pendiente de validar con financiera."),
        ("orden.decimales_importes", "Decimales para cálculo de órdenes", "entero", "0", "0, 1 o 2 decimales; adopción explícita. No recalcula documentos emitidos."),
        ("orden.modo_redondeo", "Modo de redondeo de órdenes", "texto", "ROUND_HALF_UP", "ROUND_HALF_UP, ROUND_HALF_EVEN, ROUND_DOWN o ROUND_UP. Pendiente de validar con financiera."),
    ]:
        Parametro.objects.using(schema_editor.connection.alias).get_or_create(clave=clave, defaults={"nombre": nombre, "tipo": tipo,
            "valor": valor, "valor_por_defecto": valor, "decision": "D-11", "descripcion": descripcion})


class Migration(migrations.Migration):
    dependencies = [("parametros", "0017_numeracion_ordenes")]
    operations = [migrations.RunPython(cargar, migrations.RunPython.noop)]
