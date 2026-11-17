from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("proyecciones", "0005_ajuste_ajuste_linea_campo_fecha_idx")]

    operations = [
        migrations.AddField(
            model_name="linea",
            name="costo_proyectado_total",
            field=models.DecimalField(
                verbose_name="costo proyectado total informado",
                max_digits=30,
                decimal_places=2,
                null=True,
                blank=True,
                validators=[MinValueValidator(Decimal("0"))],
                help_text="Total anual informado. Si se indica, prevalece sobre cantidades por precio unitario; cero es un valor válido.",
            ),
        ),
        migrations.AddConstraint(
            model_name="linea",
            constraint=models.CheckConstraint(
                condition=models.Q(costo_proyectado_total__isnull=True) | models.Q(costo_proyectado_total__gte=0),
                name="linea_costo_total_no_negativo",
                violation_error_message="El costo proyectado total no puede ser negativo.",
            ),
        ),
    ]
