"""Respuestas HTTP para PDF privados; el llamador comprueba el alcance del registro."""
from django.http import FileResponse, Http404


def pdf_privado(documento):
    if not documento.archivo:
        raise Http404("El documento no tiene un PDF disponible.")
    try:
        archivo = documento.archivo.open("rb")
    except (OSError, ValueError):
        raise Http404("El archivo no está disponible.") from None
    respuesta = FileResponse(archivo, as_attachment=True, filename=documento.nombre_archivo or "documento.pdf", content_type="application/pdf")
    respuesta["X-Content-Type-Options"] = "nosniff"
    respuesta["Cache-Control"] = "private, no-store"
    return respuesta
