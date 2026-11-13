from django.db import migrations


def cargar(apps, schema_editor):
    Parametro = apps.get_model("parametros", "Parametro")
    for clave, nombre, tipo, valor, descripcion in [
        ("seguimiento.crear_al_emitir", "Crear seguimiento al emitir orden", "booleano", "true", "Un seguimiento por orden, en la misma transacción de emisión. Si se desactiva, puede iniciarlo manualmente."),
        ("seguimiento.permitir_reapertura", "Permitir reapertura de seguimientos", "booleano", "false", "Deshabilitada inicialmente; solo administración, con motivo e historial."),
        ("seguimiento.cierre_con_saldo", "Cierre de seguimiento con líneas pendientes", "texto", "bloquear", "advertir o bloquear. Inicialmente exige cierre justificado de las líneas con saldo."),
        ("seguimiento.dias_alerta", "Días de próximos vencimientos de seguimiento", "entero", "7", "Ventana del panel; sin plantillas SLA reales precargadas."),
        ("seguimiento.coordinador_puede_consultar", "Coordinadores pueden consultar seguimientos del área", "booleano", "false", "Preparado para uso futuro; al habilitar, coordinadores solo consultan su área. Sin mutaciones."),
    ]:
        Parametro.objects.using(schema_editor.connection.alias).get_or_create(clave=clave, defaults={"nombre": nombre, "tipo": tipo,
            "valor": valor, "valor_por_defecto": valor, "decision": "D-15", "descripcion": descripcion})


class Migration(migrations.Migration):
    dependencies = [("parametros", "0020_recepcion_ordenes")]
    operations = [migrations.RunPython(cargar, migrations.RunPython.noop)]
