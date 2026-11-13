"""Usuario.proveedor: ficha del proveedor al que pertenece un usuario del portal.

Regla (también en Usuario.clean): el rol proveedor exige ficha y los demás roles no la
pueden tener. Si ya hay usuarios con rol proveedor (creados antes de existir las fichas),
la migración se detiene con instrucciones en lugar de inventar fichas.
"""

import django.db.models.deletion
from django.db import migrations, models


def verificar_usuarios_proveedor(apps, schema_editor):
    Usuario = apps.get_model("cuentas", "Usuario")
    pendientes = list(Usuario.objects.filter(rol="proveedor", proveedor__isnull=True).values_list("correo", flat=True))
    if pendientes:
        raise RuntimeError(
            "No se puede aplicar la regla «rol proveedor exige ficha»: estos usuarios tienen rol proveedor y "
            f"todavía no hay fichas de proveedor: {', '.join(pendientes)}. Antes de migrar, cámbieles el rol "
            "desde /configuracion/usuarios/ (o desactívelos y cámbieles el rol); después de migrar, cree la "
            "ficha en /proveedores/ y vuelva a asignarles el rol proveedor con su ficha."
        )


class Migration(migrations.Migration):

    dependencies = [
        ("areas", "0001_initial"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("cuentas", "0001_initial"),
        ("proveedores", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="usuario",
            name="proveedor",
            field=models.ForeignKey(
                blank=True,
                help_text="Ficha del proveedor al que pertenece. Obligatoria para el rol proveedor; vacía para los demás.",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="usuarios",
                to="proveedores.proveedor",
                verbose_name="proveedor",
            ),
        ),
        migrations.RunPython(verificar_usuarios_proveedor, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="usuario",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("rol", "proveedor"), ("proveedor__isnull", False)),
                    models.Q(models.Q(("rol", "proveedor"), _negated=True), ("proveedor__isnull", True)),
                    _connector="OR",
                ),
                name="usuario_proveedor_con_ficha",
                violation_error_message=(
                    "Un usuario con rol proveedor debe tener la ficha de su proveedor, y los demás roles no pueden "
                    "tenerla."
                ),
            ),
        ),
    ]
