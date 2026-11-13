from django.db import migrations


def cargar(apps, schema_editor):
    Parametro = apps.get_model("parametros", "Parametro")
    Parametro.objects.using(schema_editor.connection.alias).get_or_create(
        clave="portal.activar_cuenta_al_registrar", defaults={
            "nombre": "Activar cuentas al registrarse en el portal", "tipo": "booleano",
            "valor": "true", "valor_por_defecto": "true", "decision": "D-03",
            "descripcion": "Sí permite ingresar inmediatamente con la clave elegida. No deja la cuenta inactiva hasta que administración la active. No aprueba la ficha del proveedor. Pendiente de confirmación por la clínica.",
        },
    )


class Migration(migrations.Migration):
    dependencies = [("parametros", "0004_parametros_proveedores")]
    operations = [migrations.RunPython(cargar, migrations.RunPython.noop)]
