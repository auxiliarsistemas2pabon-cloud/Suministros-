"""Consulta de la bitácora para administración (solo lectura)."""

from django.core.paginator import Paginator
from django.shortcuts import render
from django.views.decorators.http import require_safe

from bitacora import servicios
from bitacora.forms import FiltroBitacora
from bitacora.models import RegistroBitacora
from cuentas.models import ROLES_ADMIN
from cuentas.permisos import rol_requerido

POR_PAGINA = 50


@rol_requerido(*ROLES_ADMIN)
@require_safe
def consulta(request):
    filtro = FiltroBitacora(request.GET or None)
    registros = RegistroBitacora.objects.none()
    if not request.GET:
        registros = servicios.filtrar_registros()
    elif filtro.is_valid():
        registros = servicios.filtrar_registros(
            desde=filtro.cleaned_data["desde"],
            hasta=filtro.cleaned_data["hasta"],
            actor=filtro.cleaned_data["actor"],
            accion=filtro.cleaned_data["accion"],
            tipo_objeto=filtro.cleaned_data["tipo_objeto"],
            objeto_id=filtro.cleaned_data["objeto_id"],
            texto=filtro.cleaned_data["q"],
        )
    pagina = Paginator(registros, POR_PAGINA).get_page(request.GET.get("pagina"))
    for registro in pagina:
        registro.cambios = servicios.detalle_cambios(registro)
        registro.tipo_legible = servicios.nombre_tipo(registro.tipo_objeto) if registro.tipo_objeto_id else "—"
    return render(request, "bitacora/consulta.html", {"filtro": filtro, "pagina": pagina})
