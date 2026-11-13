from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST, require_safe, require_http_methods
from cuentas.models import ROLES_ADMIN
from cuentas.permisos import rol_requerido
from config.utilidades import agregar_errores
from compras.models import OrdenCompra, EvidenciaEnvioOrden, ReglaAprobacionOrden
from compras import aprobacion_orden_servicios as servicios, orden_forms as forms
from bitacora.servicios import registrar


@rol_requerido(*ROLES_ADMIN)
@require_POST
def actuar(request, pk, accion):
    orden = get_object_or_404(OrdenCompra, pk=pk)
    if accion not in ("solicitar", "aprobar", "rechazar"):
        raise Http404
    formulario = forms.FormularioAnularOrden(request.POST)
    if formulario.is_valid():
        try:
            if accion == "solicitar":
                servicios.solicitar(orden, actor=request.user, **formulario.cleaned_data)
            else:
                servicios.votar(orden, decision="aprueba" if accion == "aprobar" else "rechaza", actor=request.user, **formulario.cleaned_data)
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        else:
            messages.success(request, "Acción registrada con historial.")
    else:
        messages.error(request, "Indique motivo y revisión actual de la orden.")
    return redirect("compras:orden_detalle", pk=pk)


@rol_requerido(*ROLES_ADMIN)
@never_cache
@require_safe
def imprimir(request, pk):
    orden = get_object_or_404(OrdenCompra, pk=pk)
    if orden.numero is None or not orden.documento_emision:
        raise Http404("El documento está disponible después de la aprobación y emisión.")
    from compras.orden_pdf import generar
    respuesta = HttpResponse(generar(orden.documento_emision, anulada=orden.estado == "anulada", motivo_anulacion=orden.motivo_anulacion), content_type="application/pdf")
    respuesta["Content-Disposition"] = f'attachment; filename="{orden.consecutivo}.pdf"'
    respuesta["Cache-Control"] = "private, no-store"
    registrar("orden.documento_pdf_descargado", actor=request.user, objeto=orden)
    return respuesta


@rol_requerido(*ROLES_ADMIN)
@never_cache
@require_http_methods(["GET", "POST"])
def envio(request, pk):
    orden = get_object_or_404(OrdenCompra, pk=pk)
    formulario = forms.FormularioEnvioOrden(request.POST if request.method == "POST" else None, request.FILES or None)
    if request.method == "POST" and formulario.is_valid():
        try:
            servicios.registrar_envio(orden, actor=request.user, **formulario.cleaned_data)
        except ValidationError as error:
            agregar_errores(formulario, error)
        else:
            return redirect("compras:orden_detalle", pk=pk)
    return render(request, "compras/orden_envio.html", {"orden": orden, "formulario": formulario})


@rol_requerido(*ROLES_ADMIN)
@never_cache
@require_safe
def descargar(request, pk, adjunto_pk):
    registro = get_object_or_404(EvidenciaEnvioOrden, pk=adjunto_pk, orden_id=pk)
    if not registro.archivo:
        raise Http404
    try:
        archivo = registro.archivo.open("rb")
    except (OSError, ValueError):
        raise Http404("El soporte no está disponible.") from None
    registrar("orden.envio_pdf_descargado", actor=request.user, objeto=registro)
    respuesta = FileResponse(archivo, as_attachment=True, filename=registro.nombre_archivo, content_type="application/pdf")
    respuesta["Cache-Control"] = "private, no-store"
    return respuesta


@rol_requerido(*ROLES_ADMIN)
@never_cache
@require_http_methods(["GET", "POST"])
def reglas(request, pk=None):
    registro = get_object_or_404(ReglaAprobacionOrden, pk=pk) if pk else ReglaAprobacionOrden()
    formulario = forms.FormularioReglaAprobacion(request.POST if request.method == "POST" else None, instance=registro)
    if request.method == "POST" and formulario.is_valid():
        try:
            servicios.guardar_regla(formulario.instance, actor=request.user, motivo=formulario.cleaned_data["motivo"])
        except ValidationError as error:
            agregar_errores(formulario, error)
        else:
            return redirect("compras:orden_reglas")
    return render(request, "compras/orden_reglas.html", {"formulario": formulario, "reglas": ReglaAprobacionOrden.objects.all()})
