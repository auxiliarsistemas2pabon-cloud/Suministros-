from django.db import migrations


def cargar(apps, schema_editor):
    Parametro = apps.get_model("parametros", "Parametro")
    for clave, nombre, tipo, valor, descripcion in [
        ("elegibles.control_documental", "Control documental al cerrar elegibles (pendiente)", "texto", "advertir",
         "Regla provisional: advertir permite continuar con justificación si un proveedor elegido tiene alertas. bloquear impide cerrar si un elegido no tiene FR14 vigente (incluida antigüedad o fecha futura) o tiene documentos obligatorios vencidos. Faltantes y vencidos opcionales exigen justificación si se permite continuar; próximos a vencer son informativos. Solo aplica a cantidad autorizada > 0. Las fotos de listas cerradas se conservan."),
        ("elegibles.antiguedad_evaluacion_meses", "Antigüedad máxima de FR14 para elegibles (meses, pendiente)", "entero", "12",
         "Provisional, pendiente de aprobación de la clínica: 12 meses calendario desde la fecha de evaluación. El aniversario es válido; se considera antigua a partir del día siguiente. Se ajusta al último día del mes cuando corresponde. La referencia es la fecha de revisión/cierre en Bogotá, no la fecha de creación de la lista."),
    ]:
        Parametro.objects.using(schema_editor.connection.alias).get_or_create(clave=clave, defaults={
            "nombre": nombre, "tipo": tipo, "valor": valor, "valor_por_defecto": valor, "descripcion": descripcion})


class Migration(migrations.Migration):
    dependencies = [("parametros", "0010_reglas_elegibles")]
    operations = [migrations.RunPython(cargar, migrations.RunPython.noop)]
