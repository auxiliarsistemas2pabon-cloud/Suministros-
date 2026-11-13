"""Integración de cuentas con django-axes."""

from cuentas.models import normalizar_correo


def usuario_para_axes(request, credentials):
    """Correo normalizado para contar intentos fallidos.

    Sin esto, "Ana@Ejemplo.test" y "ana@ejemplo.test" se contarían por
    separado y bastaría cambiar mayúsculas para evadir el bloqueo.
    """
    correo = None
    if credentials:
        correo = credentials.get("username") or credentials.get("correo")
    if correo is None and request is not None:
        datos = getattr(request, "POST", {}) or {}
        correo = datos.get("username")
    return normalizar_correo(correo) or None
