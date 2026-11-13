from django.db import migrations


def cargar(apps, schema_editor):
    Parametro = apps.get_model("parametros", "Parametro")
    for clave, nombre, tipo, valor, decision, descripcion in [
        ("orden.prefijo_consecutivo", "Prefijo del consecutivo de orden", "texto", "OC", "D-12", "Provisional: OC. Se aplica al emitir; no cambia números asignados. Letras, números, guiones y guiones bajos, máximo 20 caracteres."),
        ("orden.incluir_anio_consecutivo", "Incluir año en consecutivo de orden", "booleano", "true", "D-12", "Provisional: Sí, usa el año de emisión en Bogotá. Si se activa reinicio anual debe incluir el año. No usa el año de elaboración ni renumera documentos existentes."),
        ("orden.longitud_consecutivo", "Dígitos mínimos del consecutivo de orden", "entero", "4", "D-12", "Provisional: mínimo 4 dígitos, con ceros a la izquierda. No limita la capacidad: 9999 continúa en 10000 sin truncar ni reutilizar. Admite longitudes 1 a 20."),
        ("orden.reinicio_anual_consecutivo", "Reinicio anual del consecutivo de orden", "booleano", "false", "D-12", "Provisional: No, contador global. Sí mantiene contador por año de emisión y exige incluir el año. Los contadores nunca se borran ni retroceden; cambios de formato no reutilizan números existentes o anulados."),
        ("orden.etiqueta_fecha_validez", "Etiqueta de fecha de validez/vencimiento de orden", "texto", "Validez / vencimiento", "D-13", "Etiqueta provisional para una fecha opcional cuyo significado sigue pendiente. Borradores usan la etiqueta actual; al emitir se conserva. No se interpreta automáticamente como plazo de entrega."),
    ]:
        Parametro.objects.using(schema_editor.connection.alias).get_or_create(clave=clave, defaults={"nombre": nombre, "tipo": tipo,
            "valor": valor, "valor_por_defecto": valor, "decision": decision, "descripcion": descripcion})


class Migration(migrations.Migration):
    dependencies = [("parametros", "0016_contratos_polizas")]
    operations = [migrations.RunPython(cargar, migrations.RunPython.noop)]
