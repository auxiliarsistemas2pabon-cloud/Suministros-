from cuentas.servicios import accesos_para


def accesos(request):
    """Accesos del menú según el rol, disponibles en todas las plantillas."""
    usuario = getattr(request, "user", None)
    return {"accesos_menu": [a for a in accesos_para(usuario) if a.url]}
