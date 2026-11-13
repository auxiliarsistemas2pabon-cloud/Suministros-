from django.db import migrations


def cargar(apps, schema_editor):
    valor = '{"metodo":"directo","escala":["5","3","1"],"pendiente":true}'
    apps.get_model("parametros", "Parametro").objects.using(schema_editor.connection.alias).get_or_create(
        clave="elegibles.reglas_calculo", defaults={
            "nombre": "Reglas de cálculo de elegibles FR-GDS-20 (D-07)", "tipo": "texto", "decision": "D-07",
            "valor": valor, "valor_por_defecto": valor,
            "descripcion": "JSON: metodo directo = cumplimiento × (peso % / 100), máximo igual al máximo de la escala; escalado = cumplimiento / máximo × peso %, máximo 100. Escala inicial 5/3/1. Provisional: pendiente=true; cambiar a false solo tras aprobación de la clínica. Cada lista conserva sus reglas al asignarle versión; cambios solo afectan nuevas asignaciones.",
        })


class Migration(migrations.Migration):
    dependencies = [("parametros", "0009_aclarar_descripcion_documental")]
    operations = [migrations.RunPython(cargar, migrations.RunPython.noop)]
