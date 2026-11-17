import json

from django.conf import settings
from django.http import Http404
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

from cuentas.models import ROLES_ADMIN
from cuentas.permisos import rol_requerido


@rol_requerido(*ROLES_ADMIN)
@never_cache
@require_safe
def inicio(request):
    if not getattr(settings, "MODO_DEMOSTRACION", False):
        raise Http404
    ruta = settings.DIRECTORIO_DEMOSTRACION / "recorrido.json"
    if not ruta.is_file():
        raise Http404("Primero prepare el ejemplo.")
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    return render(request, "demostracion/inicio.html", datos)
