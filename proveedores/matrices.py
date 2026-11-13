"""Vistas administrativas de versiones y evaluaciones FR14."""
from django import forms
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from configuracion.forms import ConMotivo, FormularioMotivo
from config.utilidades import agregar_errores
from cuentas.models import ROLES_ADMIN
from cuentas.permisos import rol_requerido
from proveedores import matrices_servicios as servicios
from proveedores.evaluacion_servicios import obtener_resultado, finalizar_evaluacion
from django.views.decorators.http import require_POST
from proveedores.models import CategoriaProveedor, EvaluacionProveedor, Peso, Proveedor, Requisito, VersionMatriz


class Publicacion(ConMotivo, forms.Form):
    desde = forms.DateField(label="Vigente desde", widget=forms.DateInput(attrs={"type": "date"}))
    hasta = forms.DateField(label="Vigente hasta (opcional)", required=False, widget=forms.DateInput(attrs={"type": "date"}))


class NuevaEvaluacion(ConMotivo, forms.Form):
    categoria = forms.ModelChoiceField(label="Categoría", queryset=CategoriaProveedor.objects.filter(activo=True))
    fecha = forms.DateField(label="Fecha", initial=timezone.localdate, widget=forms.DateInput(attrs={"type": "date"}))


@rol_requerido(*ROLES_ADMIN)
@require_http_methods(["GET", "POST"])
def matriz(request, pk=None):
    versiones = VersionMatriz.objects.all()
    version = get_object_or_404(versiones, pk=pk) if pk else versiones.first()
    publicar, copiar = Publicacion(), FormularioMotivo()
    if request.method == "POST" and version:
        accion = request.POST.get("accion")
        form = Publicacion(request.POST) if accion == "publicar" else FormularioMotivo(request.POST)
        if accion not in ("publicar", "copiar"):
            form.add_error(None, "Seleccione publicar o copiar.")
        elif form.is_valid():
            try:
                if accion == "copiar":
                    version = servicios.copiar_version(version, actor=request.user, motivo=form.cleaned_data["motivo"])
                else:
                    version = servicios.publicar_version(version, actor=request.user, **form.cleaned_data)
            except ValidationError as error:
                agregar_errores(form, error)
            else:
                return redirect("proveedores:matriz_detalle", pk=version.pk)
        if accion == "publicar":
            publicar = form
        else:
            copiar = form
    return render(request, "proveedores/matriz.html", {
        "versiones": versiones, "version": version, "publicar": publicar, "copiar": copiar,
        "pesos": Peso.objects.filter(requisito__version=version).select_related("requisito", "categoria") if version else [],
    })


@rol_requerido(*ROLES_ADMIN)
@require_http_methods(["GET", "POST"])
def nueva_evaluacion(request, proveedor_pk):
    proveedor = get_object_or_404(Proveedor, pk=proveedor_pk)
    form = NuevaEvaluacion(request.POST if request.method == "POST" else None, initial={"categoria": proveedor.categoria_id})
    version, pesos = None, []
    if request.method == "POST" and form.is_valid():
        try:
            version = servicios.matriz_en_fecha(form.cleaned_data["fecha"])
            pesos = list(Peso.objects.filter(requisito__version=version, requisito__activo=True, categoria=form.cleaned_data["categoria"]).select_related("requisito"))
            if request.POST.get("accion") == "crear":
                evaluacion = servicios.crear_evaluacion(proveedor, actor=request.user, **form.cleaned_data)
                return redirect("proveedores:evaluacion_detalle", pk=evaluacion.pk)
        except ValidationError as error:
            agregar_errores(form, error)
    return render(request, "proveedores/evaluacion_nueva.html", {"proveedor": proveedor, "formulario": form, "version": version, "pesos": pesos})


@rol_requerido(*ROLES_ADMIN)
@require_http_methods(["GET"])
def evaluacion_detalle(request, pk):
    evaluacion = get_object_or_404(EvaluacionProveedor.objects.select_related("proveedor", "version", "evaluador"), pk=pk)
    pesos = list(Peso.objects.filter(requisito__version=evaluacion.version, requisito__activo=True, categoria=evaluacion.categoria).select_related("requisito"))
    respuestas = {r.requisito_id: r for r in evaluacion.respuestas.select_related("respondido_por", "documento", "evidencia_pdf")}
    from proveedores.documental import estado_guardado, tablero
    for respuesta in respuestas.values():
        respuesta.control_mostrado = estado_guardado(respuesta, evaluacion.fecha)
    for peso in pesos:
        peso.respuesta_actual = respuestas.get(peso.requisito_id)
    grupos = [{"nombre": etiqueta, "pesos": [p for p in pesos if p.requisito.grupo == grupo]}
              for grupo, etiqueta in Requisito.Grupo.choices]
    try:
        resultado = obtener_resultado(evaluacion)
        error_calculo = ""
    except ValidationError as error:
        resultado, error_calculo = None, " ".join(error.messages)
    return render(request, "proveedores/evaluacion_detalle.html", {"evaluacion": evaluacion, "pesos": pesos,
        "anulacion_form": FormularioMotivo(auto_id="anulacion_%s"), "vigente": evaluacion.proveedor.evaluacion_vigente,
        "resultado": resultado, "error_calculo": error_calculo, "finalizacion_form": FormularioMotivo(),
        "control_documental": tablero(evaluacion.proveedor, categoria=evaluacion.categoria, version=evaluacion.version, hoy=evaluacion.fecha),
        "referencia_documental": evaluacion.fecha,
        "grupos": grupos, "respondidos": sum(p.respuesta_actual is not None for p in pesos), "total": len(pesos)})


@rol_requerido(*ROLES_ADMIN)
@require_POST
def finalizar(request, pk):
    from django.contrib import messages
    evaluacion = get_object_or_404(EvaluacionProveedor, pk=pk)
    formulario = FormularioMotivo(request.POST)
    if formulario.is_valid():
        try:
            finalizar_evaluacion(evaluacion, actor=request.user, motivo=formulario.cleaned_data["motivo"], request=request)
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        else:
            messages.success(request, "La evaluación quedó finalizada con su resultado y reglas conservados.")
    else:
        messages.error(request, "Indique el motivo de finalización.")
    return redirect("proveedores:evaluacion_detalle", pk=pk)
