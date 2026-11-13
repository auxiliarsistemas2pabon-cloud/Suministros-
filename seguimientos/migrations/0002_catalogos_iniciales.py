from django.db import migrations


def cargar(apps, schema_editor):
    alias = schema_editor.connection.alias
    for modelo, valores in [
        ("TipoSeguimiento", [("contratos", "Contratos"), ("compras_generales", "Compras generales"), ("servicio_farmaceutico", "Servicio farmacéutico"), ("hemodinamia", "Hemodinamia")]),
        ("ResultadoCierre", [("cumplido", "Cumplido"), ("cumplido_novedades", "Cumplido con novedades"), ("incumplido", "Incumplido"), ("anulado", "Anulado")]),
    ]:
        Catalogo = apps.get_model("seguimientos", modelo)
        for codigo, nombre in valores:
            Catalogo.objects.using(alias).get_or_create(codigo=codigo, defaults={"nombre": nombre})
    Evento = apps.get_model("seguimientos", "TipoEvento")
    for codigo, nombre, funcion in [
        ("solicitud_documentos", "Solicitud de documentos", "solicita_documentos"), ("documentos_recibidos", "Documentos recibidos", "recibe_documentos"),
        ("comunicacion", "Comunicación con proveedor", "informativo"), ("recepcion", "Recepción", "recepcion"), ("devolucion", "Devolución", "devolucion"),
        ("novedad", "Novedad", "informativo"), ("proyeccion_contrato", "Proyección de contrato", "informativo"), ("observacion", "Observación", "informativo"),
    ]:
        Evento.objects.using(alias).get_or_create(codigo=codigo, defaults={"nombre": nombre, "funcion": funcion})


class Migration(migrations.Migration):
    dependencies = [("seguimientos", "0001_estructura_seguimientos")]
    operations = [migrations.RunPython(cargar, migrations.RunPython.noop)]
