from django.db import migrations


def cargar(apps, schema_editor):
    Parametro = apps.get_model("parametros", "Parametro")
    for clave, nombre, descripcion in [
        ("orden.permitir_exceso_recepcion", "Permitir autorizar exceso de recepción", "Inicialmente bloqueado. Requiere parámetro habilitado, autorización administrativa expresa y motivo por movimiento."),
        ("orden.coordinador_puede_recibir", "Coordinadores pueden recibir en su área", "Elección del usuario: solo administradores y desarrolladores. Si se activa, coordinadores solo en el área de origen y sin autorización de exceso."),
    ]:
        Parametro.objects.using(schema_editor.connection.alias).get_or_create(clave=clave, defaults={"nombre": nombre, "tipo": "booleano",
            "valor": "false", "valor_por_defecto": "false", "decision": "D-14", "descripcion": descripcion})


class Migration(migrations.Migration):
    dependencies = [("parametros", "0019_aprobacion_ordenes")]
    operations = [migrations.RunPython(cargar, migrations.RunPython.noop)]
