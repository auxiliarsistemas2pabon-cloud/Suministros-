from django.db import migrations


def cargar(apps, schema_editor):
    Parametro = apps.get_model("parametros", "Parametro")
    for clave, nombre, valor, descripcion in [
        ("cotizacion.max_oferentes", "Máximo de proveedores invitados por cotización", "3",
         "Límite provisional pendiente de aprobación: 3 proveedores invitados por cotización. Use 0 para no imponer límite de negocio. La precarga no descarta elegidos silenciosamente; revise el parámetro o el origen si lo excede."),
        ("cotizacion.max_lineas", "Máximo de líneas por cotización", "10",
         "Límite provisional pendiente de aprobación: 10 líneas de especificación por cotización. Use 0 para no imponer límite de negocio. Se exige al menos una línea y nunca se trunca la precarga automáticamente."),
    ]:
        Parametro.objects.using(schema_editor.connection.alias).get_or_create(clave=clave, defaults={
            "nombre": nombre, "tipo": "entero", "decision": "D-10", "valor": valor, "valor_por_defecto": valor, "descripcion": descripcion})


class Migration(migrations.Migration):
    dependencies = [("parametros", "0011_control_documental_elegibles")]
    operations = [migrations.RunPython(cargar, migrations.RunPython.noop)]
