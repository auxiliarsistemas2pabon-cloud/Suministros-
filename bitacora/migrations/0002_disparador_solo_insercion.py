"""La base de datos rechaza UPDATE y DELETE sobre la bitácora.

Así el historial no se puede alterar ni siquiera con SQL directo o con
QuerySet.update(). (TRUNCATE no dispara triggers de fila; solo lo usan las
pruebas y el comando flush.)
"""

from django.db import migrations

CREAR = """
CREATE OR REPLACE FUNCTION bitacora_solo_insercion() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'La bitácora es de solo inserción: no se permite % sobre sus registros.', TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER bitacora_registro_inmutable
    BEFORE UPDATE OR DELETE ON bitacora_registrobitacora
    FOR EACH ROW EXECUTE FUNCTION bitacora_solo_insercion();
"""

BORRAR = """
DROP TRIGGER IF EXISTS bitacora_registro_inmutable ON bitacora_registrobitacora;
DROP FUNCTION IF EXISTS bitacora_solo_insercion();
"""


def crear_disparadores(apps, schema_editor):
    if schema_editor.connection.vendor == "sqlite":
        for accion in ("UPDATE", "DELETE"):
            schema_editor.execute(
                f"CREATE TRIGGER IF NOT EXISTS bitacora_inmutable_{accion.lower()} "
                f"BEFORE {accion} ON bitacora_registrobitacora BEGIN "
                "SELECT RAISE(ABORT, 'La bitácora es de solo inserción.'); END;"
            )
    else:
        schema_editor.execute(CREAR, params=None)


def borrar_disparadores(apps, schema_editor):
    if schema_editor.connection.vendor == "sqlite":
        for accion in ("update", "delete"):
            schema_editor.execute(f"DROP TRIGGER IF EXISTS bitacora_inmutable_{accion}")
    else:
        schema_editor.execute(BORRAR, params=None)


class Migration(migrations.Migration):
    dependencies = [
        ("bitacora", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(crear_disparadores, reverse_code=borrar_disparadores),
    ]
