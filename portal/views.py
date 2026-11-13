from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_safe

from config.utilidades import agregar_errores
from config.descargas import pdf_privado as _descarga
from cuentas.models import Rol
from cuentas.permisos import rol_requerido
from portal import forms, servicios, consultas


@never_cache
@require_http_methods(["GET", "POST"])
def registro(request):
    # Excepción pública a rol_requerido: crea una cuenta sin sesión previa.
    if request.user.is_authenticated:
        if request.user.rol == Rol.PROVEEDOR:
            return redirect("portal:inicio")
        raise PermissionDenied
    if request.method == "POST":
        if not servicios.admitir_intento_registro(request):
            respuesta = HttpResponse("Se alcanzó el límite de intentos. Inténtelo más tarde o comuníquese con la clínica.", status=429, content_type="text/plain; charset=utf-8")
            respuesta["Retry-After"] = str(getattr(settings, "PORTAL_REGISTRO_VENTANA", 900))
            return respuesta
        if request.POST.get("sitio_web"):
            return redirect("portal:registro_recibido")
    formulario = forms.FormularioRegistro(request.POST if request.method == "POST" else None)
    if request.method == "POST" and formulario.is_valid():
        try:
            servicios.registrar_proveedor(formulario.cleaned_data, request=request)
        except ValidationError as error:
            agregar_errores(formulario, error)
        else:
            return redirect("portal:registro_recibido")
    return render(request, "portal/registro.html", {"formulario": formulario})


@never_cache
@require_safe
def registro_recibido(request):
    return render(request, "portal/registro_recibido.html", {"mensaje": servicios.MENSAJE_REGISTRO})


@rol_requerido(Rol.PROVEEDOR)
@never_cache
@require_safe
def inicio(request):
    datos = consultas.panel(request.user)
    return render(request, "portal/inicio.html", {
        "proveedor": datos["proveedor"], "pagina": Paginator(datos["envios"], 25).get_page(request.GET.get("pagina")),
        "documentos": datos["documentos"],
    })


@rol_requerido(Rol.PROVEEDOR)
@never_cache
@require_http_methods(["GET", "POST"])
def envio_nuevo(request):
    proveedor = servicios.ficha_de(request.user)
    if not proveedor.activo:
        raise PermissionDenied
    formulario = forms.FormularioEnvio(request.POST if request.method == "POST" else None, request.FILES or None)
    if request.method == "POST" and formulario.is_valid():
        datos = formulario.cleaned_data
        try:
            servicios.enviar_documento(
                actor=request.user, tipo=datos["tipo"], fecha_expedicion=datos["fecha_expedicion"],
                fecha_vencimiento=datos["fecha_vencimiento"], archivo=datos["archivo_pdf"], request=request,
            )
        except ValidationError as error:
            agregar_errores(formulario, error)
        else:
            messages.success(request, "Su documento fue enviado y quedó pendiente de revisión.")
            return redirect("portal:inicio")
    return render(request, "portal/envio_formulario.html", {"formulario": formulario})


@rol_requerido(Rol.PROVEEDOR)
@never_cache
@require_safe
def envio_descargar(request, pk):
    return _descarga(consultas.envio_propio(request.user, pk))


@rol_requerido(Rol.PROVEEDOR)
@never_cache
@require_safe
def documento_descargar(request, pk):
    return _descarga(consultas.documento_propio(request.user, pk))
