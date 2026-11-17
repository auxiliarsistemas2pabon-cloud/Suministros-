from cuentas.servicios import accesos_para
from cuentas.navegacion import menu_para
from django.conf import settings


def accesos(request):
    """Accesos del menú según el rol, disponibles en todas las plantillas."""
    usuario = getattr(request, "user", None)
    return {"accesos_menu": [a for a in accesos_para(usuario) if a.url],
        "es_demostracion": getattr(settings, "MODO_DEMOSTRACION", False), **menu_para(usuario, request)}
