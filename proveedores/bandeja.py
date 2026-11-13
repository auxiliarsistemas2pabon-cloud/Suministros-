"""Bandeja administrativa de envíos. Todas las mutaciones pasan por servicios."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST, require_http_methods, require_safe

from config.utilidades import agregar_errores
from configuracion.forms import FormularioMotivo
from cuentas.models import ROLES_ADMIN
from cuentas.permisos import rol_requerido
from parametros import servicios as parametros
from parametros.catalogo import CONSERVAR_PDF_DESCARTADO
from proveedores import servicios
from proveedores.bandeja_forms import FiltroEnvios, FormularioEnvioManual
from proveedores.models import EnvioProveedor

solo_administradores = rol_requerido(*ROLES_ADMIN)


def _envio(pk):
    return get_object_or_404(EnvioProveedor.objects.select_related("proveedor", "tipo", "enviado_por", "revisado_por", "documento"), pk=pk)


@solo_administradores
@never_cache
@require_safe
def lista(request):
    datos = request.GET.copy()
    if "estado" not in datos:
        datos["estado"] = EnvioProveedor.Estado.PENDIENTE
    filtro = FiltroEnvios(datos)
    consulta = EnvioProveedor.objects.none()
    if filtro.is_valid():
        filtros = dict(filtro.cleaned_data)
        filtros["texto"] = filtros.pop("q")
        consulta = servicios.filtrar_envios(**filtros)
    return render(request, "proveedores/bandeja.html", {
        "filtro": filtro, "pagina": Paginator(consulta, 25).get_page(request.GET.get("pagina")),
    })


def _detalle(request, envio, formulario=None):
    return render(request, "proveedores/envio_detalle.html", {
        "envio": envio, "formulario": formulario or FormularioMotivo(),
        "pendiente": envio.estado == EnvioProveedor.Estado.PENDIENTE,
        "conservar_descartado": parametros.obtener(CONSERVAR_PDF_DESCARTADO),
    })


@solo_administradores
@never_cache
@require_safe
def detalle(request, pk):
    return _detalle(request, _envio(pk))


@solo_administradores
@never_cache
@require_POST
def revisar(request, pk, aceptar):
    envio = _envio(pk)
    formulario = FormularioMotivo(request.POST)
    if formulario.is_valid():
        try:
            servicios.revisar_envio(envio, aceptar=aceptar, actor=request.user,
                                    motivo=formulario.cleaned_data["motivo"], request=request)
        except ValidationError as error:
            agregar_errores(formulario, error)
        else:
            messages.success(request, "El envío fue aceptado y su documento quedó incorporado a la ficha." if aceptar else "El envío fue descartado. Su historial se conserva.")
            return redirect("proveedores:envio_detalle", pk=pk)
    return _detalle(request, _envio(pk), formulario)


@solo_administradores
@never_cache
@require_safe
def descargar(request, pk):
    envio = _envio(pk)
    if not envio.archivo:
        raise Http404("El envío no tiene un PDF disponible.")
    try:
        archivo = envio.archivo.open("rb")
    except FileNotFoundError:
        raise Http404("El PDF del envío no está disponible.") from None
    respuesta = FileResponse(archivo, as_attachment=True, filename=envio.nombre_archivo or "envio.pdf", content_type="application/pdf")
    respuesta["X-Content-Type-Options"] = "nosniff"
    respuesta["Cache-Control"] = "private, no-store"
    return respuesta


@solo_administradores
@never_cache
@require_http_methods(["GET", "POST"])
def manual(request):
    formulario = FormularioEnvioManual(request.POST if request.method == "POST" else None, request.FILES or None)
    if request.method == "POST" and formulario.is_valid():
        datos = formulario.cleaned_data
        try:
            envio = servicios.crear_envio(
                proveedor=datos["proveedor"], actor=request.user, tipo=datos["tipo"],
                fecha_expedicion=datos["fecha_expedicion"], fecha_vencimiento=datos["fecha_vencimiento"],
                archivo=datos["archivo_pdf"], motivo=datos["motivo"], request=request,
            )
        except ValidationError as error:
            agregar_errores(formulario, error)
        else:
            messages.success(request, "El envío manual quedó registrado y pendiente de revisión.")
            return redirect("proveedores:envio_detalle", pk=envio.pk)
    return render(request, "proveedores/envio_manual.html", {"formulario": formulario})
