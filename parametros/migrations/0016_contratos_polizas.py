from django.db import migrations


def cargar(apps, schema_editor):
    Parametro = apps.get_model("parametros", "Parametro")
    for clave, nombre, tipo, valor, descripcion in [
        ("contrato.campos_obligatorios", "Campos obligatorios del contrato", "texto", '{"numero":true,"supervisor":true,"cargo":true,"fecha_inicio":true,"fecha_fin":true,"forma_pago":true,"valor":true,"pdf":false}',
         "Provisional: true exige el campo antes de aprobar una decisión que requiere contrato. PDF opcional inicialmente. supervisor admite usuario o texto. Puede guardar borradores incompletos. Los campos no se exigen si no requiere contrato."),
        ("poliza.campos_obligatorios", "Campos obligatorios de cada póliza", "texto", '{"tipo":true,"aseguradora":true,"numero":true,"valor_asegurado":true,"vigencia_desde":true,"vigencia_hasta":true,"pdf":true}',
         "Provisional: true exige el campo en cada póliza activa antes de aprobar. Inicialmente se exige también su PDF. No establece tipos de póliza ni porcentajes oficiales de cobertura. La obligación de tener alguna póliza se configura por separado."),
        ("contrato.exigir_poliza", "Exigir al menos una póliza para el contrato", "booleano", "false",
         "Provisional: No permite contratos sin pólizas. Sí exige al menos una póliza activa y completa antes de aprobar la decisión. No se aplica a compras que no requieren contrato. Pendiente de aprobación de la clínica."),
    ]:
        Parametro.objects.using(schema_editor.connection.alias).get_or_create(clave=clave, defaults={"nombre": nombre, "tipo": tipo, "valor": valor, "valor_por_defecto": valor, "descripcion": descripcion})


class Migration(migrations.Migration):
    dependencies = [("parametros", "0015_decision_cotizacion")]
    operations = [migrations.RunPython(cargar, migrations.RunPython.noop)]
