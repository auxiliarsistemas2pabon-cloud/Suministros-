from django.db import migrations


def cargar(apps, schema_editor):
    valor = '{"si":"1","no":"0","excluir_na":true,"umbral3":"60","umbral5":"80","pendiente":true}'
    apps.get_model("parametros", "Parametro").objects.using(schema_editor.connection.alias).get_or_create(
        clave="evaluacion.reglas_calculo", defaults={
            "nombre": "Reglas de cálculo FR-GDS-14 (D-06)", "tipo": "texto", "decision": "D-06",
            "valor": valor, "valor_por_defecto": valor,
            "descripcion": "Reglas JSON provisionales: Sí=peso, No=0, N/A excluido; umbrales 60/80 pendientes de aprobación. Cambiar pendiente a false solo tras aprobación de la clínica. Las evaluaciones finalizadas conservan su resultado.",
        },
    )


class Migration(migrations.Migration):
    dependencies = [("parametros", "0006_retencion_pdf_descartado")]
    operations = [migrations.RunPython(cargar, migrations.RunPython.noop)]
