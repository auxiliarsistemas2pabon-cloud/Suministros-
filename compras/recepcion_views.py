from django.core.exceptions import ValidationError
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_safe
from cuentas.models import Rol
from cuentas.permisos import rol_requerido
from config.utilidades import agregar_errores
from compras.models import OrdenCompra, Recepcion
from compras import recepcion_servicios as servicios, orden_forms as forms
from bitacora.servicios import registrar


@rol_requerido(Rol.ADMINISTRADOR, Rol.DESARROLLADOR, Rol.COORDINADOR)
@never_cache
@require_http_methods(["GET", "POST"])
def recibir(request, pk):
    orden = get_object_or_404(OrdenCompra.objects.select_related("cotizacion"), pk=pk)
    servicios.exigir_receptor(orden, request.user)
    filas = servicios.acumulados(orden)
    inicial = [{"id": f["linea"].pk, "cantidad": 0, "rechazada": 0} for f in filas]
    formulario = forms.FormularioRecepcion(request.POST if request.method == "POST" else None, request.FILES or None, orden=orden,
        initial={"revision_esperada": orden.revision, "tipo": "recepcion"})
    lineas = forms.formulario_recepcion_lineas(request.POST if request.method == "POST" else None, inicial=inicial)
    if request.method == "POST" and formulario.is_valid() and lineas.is_valid():
        try:
            recepcion = servicios.registrar_recepcion(orden, lineas=[f.cleaned_data for f in lineas], actor=request.user, **formulario.cleaned_data)
        except ValidationError as error:
            agregar_errores(formulario, error)
        else:
            return redirect("compras:recepcion_detalle", pk=pk, recepcion_pk=recepcion.pk)
    return render(request, "compras/recepcion_form.html", {"orden": orden, "formulario": formulario, "filas": list(zip(filas, lineas)) , "lineas": lineas})


@rol_requerido(Rol.ADMINISTRADOR, Rol.DESARROLLADOR, Rol.COORDINADOR)
@never_cache
@require_safe
def detalle(request, pk, recepcion_pk):
    recepcion = get_object_or_404(Recepcion.objects.select_related("orden__cotizacion", "recibido_por"), pk=recepcion_pk, orden_id=pk)
    servicios.exigir_receptor(recepcion.orden, request.user)
    return render(request, "compras/recepcion_detalle.html", {"recepcion": recepcion})


@rol_requerido(Rol.ADMINISTRADOR, Rol.DESARROLLADOR, Rol.COORDINADOR)
@never_cache
@require_safe
def descargar(request, pk, recepcion_pk):
    registro = get_object_or_404(Recepcion.objects.select_related("orden__cotizacion"), pk=recepcion_pk, orden_id=pk)
    servicios.exigir_receptor(registro.orden, request.user)
    if not registro.archivo:
        raise Http404
    try:
        archivo = registro.archivo.open("rb")
    except (OSError, ValueError):
        raise Http404("El soporte no está disponible.") from None
    registrar("recepcion.pdf_descargado", actor=request.user, objeto=registro)
    respuesta = FileResponse(archivo, as_attachment=True, filename=registro.nombre_archivo, content_type="application/pdf")
    respuesta["Cache-Control"] = "private, no-store"
    return respuesta
