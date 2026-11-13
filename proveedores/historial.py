from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST, require_safe

from config.utilidades import agregar_errores
from configuracion.forms import ConMotivo, FormularioMotivo
from cuentas.models import ROLES_ADMIN
from cuentas.permisos import rol_requerido
from proveedores.historial_servicios import anular_evaluacion, copiar_evaluacion
from proveedores.models import EvaluacionProveedor, Proveedor


class FormularioCopia(ConMotivo, forms.Form):
    copiar_respuestas = forms.BooleanField(label="Copiar las respuestas y evidencias actuales", required=False, initial=True)


@rol_requerido(*ROLES_ADMIN)
@never_cache
@require_safe
def lista(request, proveedor_pk):
    proveedor = get_object_or_404(Proveedor, pk=proveedor_pk)
    consulta = proveedor.evaluaciones.select_related("version", "evaluador").order_by("-fecha", "-pk")
    return render(request, "proveedores/evaluaciones_historial.html", {
        "proveedor": proveedor, "pagina": Paginator(consulta, 25).get_page(request.GET.get("pagina")),
        "vigente": proveedor.evaluacion_vigente,
    })


@rol_requerido(*ROLES_ADMIN)
@never_cache
@require_http_methods(["GET", "POST"])
def copiar(request, pk):
    origen = get_object_or_404(EvaluacionProveedor.objects.select_related("proveedor", "version"), pk=pk)
    formulario = FormularioCopia(request.POST if request.method == "POST" else None)
    if request.method == "POST" and formulario.is_valid():
        try:
            nueva = copiar_evaluacion(origen, actor=request.user, request=request, **formulario.cleaned_data)
        except ValidationError as error:
            agregar_errores(formulario, error)
        else:
            return redirect("proveedores:evaluacion_detalle", pk=nueva.pk)
    return render(request, "proveedores/evaluacion_copiar.html", {"origen": origen, "formulario": formulario})


@rol_requerido(*ROLES_ADMIN)
@never_cache
@require_POST
def anular(request, pk):
    evaluacion = get_object_or_404(EvaluacionProveedor, pk=pk)
    formulario = FormularioMotivo(request.POST)
    if formulario.is_valid():
        try:
            anular_evaluacion(evaluacion, actor=request.user, motivo=formulario.cleaned_data["motivo"], request=request)
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        else:
            messages.success(request, "La evaluación fue anulada. Sus resultados y evidencias se conservan.")
    else:
        messages.error(request, "Indique el motivo de la anulación.")
    return redirect("proveedores:evaluacion_detalle", pk=pk)
