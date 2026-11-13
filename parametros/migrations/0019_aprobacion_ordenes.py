from django.db import migrations


def cargar(apps, schema_editor):
    Parametro = apps.get_model("parametros", "Parametro")
    for clave, nombre, tipo, valor, descripcion in [
        ("orden.permitir_aprobar_propia", "Permitir aprobar la propia orden", "booleano", "false", "Provisional: No; requiere otro administrador. Política conservada por solicitud, D-12."),
        ("orden.cliente_nombre", "Nombre de la clínica en órdenes", "texto", "POR CONFIGURAR", "Configure antes de solicitar aprobación; se conserva en la emisión."),
        ("orden.cliente_nit", "NIT de la clínica en órdenes", "texto", "POR CONFIGURAR", "Configure antes de solicitar aprobación; no se precargan datos reales."),
    ]:
        Parametro.objects.using(schema_editor.connection.alias).get_or_create(clave=clave, defaults={"nombre": nombre, "tipo": tipo,
            "valor": valor, "valor_por_defecto": valor, "decision": "D-12", "descripcion": descripcion})


class Migration(migrations.Migration):
    dependencies = [("parametros", "0018_importes_ordenes")]
    operations = [migrations.RunPython(cargar, migrations.RunPython.noop)]
