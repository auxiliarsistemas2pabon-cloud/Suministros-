from contextlib import contextmanager
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from proveedores import archivos


@contextmanager
def transaccion(archivo=None):
    if archivo is not None:
        archivos.validar_pdf(archivo)
        if any(not getattr(b, "_from_testcase", False) for b in connection.atomic_blocks):
            raise ValidationError("Cargue el PDF fuera de una transacción externa.")
    rutas = []
    try:
        with transaction.atomic(durable=archivo is not None):
            yield rutas
    except BaseException:
        for ruta in rutas:
            archivos.borrar_ahora(ruta)
        raise


def adjuntar(registro, archivo, rutas, carpeta):
    if archivo is not None:
        registro.archivo = archivos.guardar_pdf(archivo, carpeta=carpeta)
        rutas.append(registro.archivo.name)
        registro.nombre_archivo = archivos.nombre_original(archivo)
