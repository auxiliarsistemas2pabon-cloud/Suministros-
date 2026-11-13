from django.db import migrations


def cargar(apps, schema_editor):
    Parametro = apps.get_model("parametros", "Parametro")
    for clave, nombre, tipo, valor, descripcion in [
        ("cotizacion.proveedor_unico_min_caracteres", "Mínimo de caracteres para justificar proveedor único", "entero", "20",
         "Provisional, pendiente de aprobación de la clínica: mínimo 20 caracteres tras normalizar espacios. Nunca se admite justificación vacía. Se comprueba al confirmar el caso y antes de decidir la cotización."),
        ("cotizacion.proveedor_unico_evidencia_obligatoria", "Exigir PDF para proveedor único", "booleano", "false",
         "Provisional, pendiente de aprobación de la clínica: No permite evidencia PDF opcional. Sí exige PDF al confirmar el caso y antes de decidir. Cambiar el parámetro no reescribe el historial; la decisión debe cumplir la regla vigente."),
    ]:
        Parametro.objects.using(schema_editor.connection.alias).get_or_create(clave=clave, defaults={
            "nombre": nombre, "tipo": tipo, "valor": valor, "valor_por_defecto": valor, "descripcion": descripcion})


class Migration(migrations.Migration):
    dependencies = [("parametros", "0013_redondeo_ofertas")]
    operations = [migrations.RunPython(cargar, migrations.RunPython.noop)]
