from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_safe

from bitacora.servicios import registrar
from compras import proveedor_unico_forms as forms, proveedor_unico_servicios as servicios
from compras.models import CausalProveedorUnico, Cotizacion, PdfProveedorUnico, RevisionProveedorUnico
from config.utilidades import agregar_errores
from cuentas.models import ROLES_ADMIN
from cuentas.permisos import rol_requerido


@rol_requerido(*ROLES_ADMIN)
@never_cache
@require_http_methods(["GET", "POST"])
def caso(request, pk):
    cotizacion = get_object_or_404(Cotizacion.objects.select_related("pdf_proveedor_unico"), pk=pk)
    editable = cotizacion.estado in ("borrador", "en_comparacion")
    ofertas = list(cotizacion.ofertas.all())
    inicial = {"proveedor_unico": cotizacion.proveedor_unico or (cotizacion.revision_proveedor_unico == 0 and len(ofertas) == 1),
        "causal": cotizacion.causal_proveedor_unico_id, "justificacion": cotizacion.justificacion_proveedor_unico,
        "revision_esperada": cotizacion.revision_proveedor_unico}
    formulario = forms.FormularioCaso(request.POST if request.method == "POST" else None, request.FILES or None, initial=inicial)
    if request.method == "POST":
        if not editable:
            messages.error(request, "La cotización solo permite consultar el caso de proveedor único.")
            return redirect("compras:proveedor_unico", pk=pk)
        if formulario.is_valid():
            try:
                servicios.guardar_caso(cotizacion, actor=request.user, **formulario.cleaned_data)
            except ValidationError as error:
                agregar_errores(formulario, error)
            else:
                messages.success(request, "Caso de proveedor único guardado con motivo e historial.")
                return redirect("compras:proveedor_unico", pk=pk)
    return render(request, "compras/proveedor_unico.html", {"cotizacion": cotizacion, "formulario": formulario,
        "editable": editable, "ofertas": ofertas, "reglas": servicios.reglas_actuales(),
        "revisiones": cotizacion.revisiones_proveedor_unico.select_related("actor", "pdf")})


@rol_requerido(*ROLES_ADMIN)
@never_cache
@require_safe
def revision(request, pk, revision_pk):
    cotizacion = get_object_or_404(Cotizacion, pk=pk)
    historico = get_object_or_404(RevisionProveedorUnico.objects.select_related("pdf", "actor"), pk=revision_pk, cotizacion=cotizacion)
    return render(request, "compras/proveedor_unico_revision.html", {"cotizacion": cotizacion, "revision": historico, "foto": historico.contenido})


@rol_requerido(*ROLES_ADMIN)
@never_cache
@require_safe
def descargar(request, pk, adjunto_pk):
    adjunto = get_object_or_404(PdfProveedorUnico, pk=adjunto_pk, cotizacion_id=pk)
    try:
        archivo = adjunto.archivo.open("rb")
    except FileNotFoundError:
        raise Http404("La evidencia no está disponible.") from None
    try:
        registrar("unico.evidencia_descargada", actor=request.user, objeto=adjunto, motivo="Descarga privada de evidencia de proveedor único", request=request)
    except BaseException:
        archivo.close()
        raise
    respuesta = FileResponse(archivo, as_attachment=True, filename=adjunto.nombre_archivo, content_type="application/pdf")
    respuesta["X-Content-Type-Options"] = "nosniff"
    respuesta["Cache-Control"] = "private, no-store"
    return respuesta


@rol_requerido(*ROLES_ADMIN)
@require_http_methods(["GET", "POST"])
def causales(request, pk=None):
    causal = get_object_or_404(CausalProveedorUnico, pk=pk) if pk else CausalProveedorUnico()
    formulario = forms.FormularioCausal(request.POST if request.method == "POST" else None, instance=causal)
    if request.method == "POST" and formulario.is_valid():
        try:
            servicios.guardar_causal(formulario.instance, actor=request.user, motivo=formulario.cleaned_data["motivo"])
        except ValidationError as error:
            agregar_errores(formulario, error)
        else:
            return redirect("compras:proveedor_unico_causales")
    return render(request, "compras/proveedor_unico_causales.html", {"formulario": formulario, "causales": CausalProveedorUnico.objects.all()})
