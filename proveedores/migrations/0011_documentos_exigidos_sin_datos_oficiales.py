"""D-05: no cargar obligaciones sin aprobación de la clínica."""
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("proveedores", "0010_respuestaevaluacion_control_documental_and_more")]
    operations = [migrations.RunPython(migrations.RunPython.noop, migrations.RunPython.noop)]
