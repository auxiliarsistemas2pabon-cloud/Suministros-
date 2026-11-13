from django.db import migrations


def cargar(apps, schema_editor):
    Parametro = apps.get_model("parametros", "Parametro")
    for clave, nombre, tipo, valor, descripcion in [
        ("cotizacion.modalidad_adjudicacion", "Modalidad inicial de adjudicación", "texto", "completa", "Oferta completa por elección del usuario. Alternativa lineas: cada línea a un oferente. Ambas modalidades están disponibles al proponer una decisión."),
        ("cotizacion.aprobaciones_requeridas", "Aprobaciones requeridas para decidir cotizaciones", "entero", "1", "Provisional: una aprobación administrativa. Se admiten varias de usuarios distintos; la regla queda fija en cada propuesta. Cambiarla afecta propuestas nuevas. Pendiente de aprobación de la clínica."),
        ("cotizacion.roles_aprobadores", "Roles que aprueban decisiones de cotización", "texto", "administrador", "Provisional: administrador. Puede habilitar también desarrollador. Cada propuesta conserva los roles requeridos; el usuario debe mantener un rol habilitado al aprobar."),
        ("cotizacion.control_verificaciones", "Control de verificaciones al decidir cotizaciones", "texto", "advertir", "Provisional: advertir exige justificación si una oferta seleccionada tiene verificaciones activas obligatorias en No, Pendiente o sin reconfirmar. bloquear impide aprobarla. Solo se revisan las ofertas seleccionadas. La regla se conserva por propuesta."),
    ]:
        Parametro.objects.using(schema_editor.connection.alias).get_or_create(clave=clave, defaults={"nombre": nombre, "tipo": tipo, "valor": valor, "valor_por_defecto": valor, "descripcion": descripcion})


class Migration(migrations.Migration):
    dependencies = [("parametros", "0014_proveedor_unico")]
    operations = [migrations.RunPython(cargar, migrations.RunPython.noop)]
