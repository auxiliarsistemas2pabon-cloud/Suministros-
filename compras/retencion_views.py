from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from bitacora.servicios import guardar_con_bitacora
from cuentas.permisos import rol_requerido
from compras.models import TipoRetencion
from compras.orden_forms import FormularioRetencion
from proveedores.servicios import _exigir_admin, _exigir_motivo
from cuentas.models import ROLES_ADMIN
from config.utilidades import agregar_errores


@transaction.atomic
def guardar_retencion(retencion, *, actor, motivo):
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    retencion.full_clean()
    return guardar_con_bitacora(retencion, ["nombre", "porcentaje", "base_minima", "base_calculo", "activo"],
        accion_crear="orden.retencion_creada", accion_modificar="orden.retencion_modificada", actor=actor, motivo=motivo)


@rol_requerido(*ROLES_ADMIN)
@never_cache
@require_http_methods(["GET", "POST"])
def catalogo(request, pk=None):
    registro = get_object_or_404(TipoRetencion, pk=pk) if pk else TipoRetencion()
    formulario = FormularioRetencion(request.POST if request.method == "POST" else None, instance=registro)
    if request.method == "POST" and formulario.is_valid():
        try:
            guardar_retencion(formulario.instance, actor=request.user, motivo=formulario.cleaned_data["motivo"])
        except ValidationError as error:
            agregar_errores(formulario, error)
        else:
            return redirect("compras:retenciones")
    return render(request, "compras/retenciones.html", {"formulario": formulario, "retenciones": TipoRetencion.objects.all()})
