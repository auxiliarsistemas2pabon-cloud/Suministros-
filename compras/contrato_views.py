from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_safe

from bitacora.servicios import registrar
from compras import contrato_forms as forms, contrato_servicios as servicios
from compras.models import Contrato, Cotizacion, DecisionCotizacion, PdfContractual, Poliza, RevisionContrato, TipoPoliza
from config.utilidades import agregar_errores
from cuentas.models import ROLES_ADMIN
from cuentas.permisos import rol_requerido


def _editable(decision):
    return decision.estado == "pendiente" and decision.cotizacion.estado == "en_comparacion" and decision.contenido["comparativo"].get("requiere_contrato", False) and not decision.aprobaciones.exists()


@rol_requerido(*ROLES_ADMIN)
@never_cache
@require_http_methods(["GET", "POST"])
def requerimiento(request, pk):
    cotizacion = get_object_or_404(Cotizacion, pk=pk)
    editable = cotizacion.estado in ("borrador", "en_comparacion") and not cotizacion.decisiones.exclude(estado="anulada").exists()
    formulario = forms.FormularioRequiere(request.POST if request.method == "POST" else None,
        initial={"requiere_contrato": cotizacion.requiere_contrato, "revision_esperada": cotizacion.revision_requiere_contrato})
    if request.method == "POST" and formulario.is_valid():
        try:
            servicios.guardar_requiere(cotizacion, actor=request.user, **formulario.cleaned_data)
        except ValidationError as error:
            agregar_errores(formulario, error)
        else:
            return redirect("compras:cotizacion_detalle", pk=pk)
    return render(request, "compras/contrato_requerimiento.html", {"cotizacion": cotizacion, "editable": editable, "formulario": formulario})


@rol_requerido(*ROLES_ADMIN)
@never_cache
@require_http_methods(["GET", "POST"])
def contrato(request, pk, decision_pk):
    decision = get_object_or_404(DecisionCotizacion.objects.select_related("cotizacion"), pk=decision_pk, cotizacion_id=pk)
    actual = Contrato.objects.filter(decision=decision).select_related("pdf").first()
    editable = _editable(decision)
    formulario = forms.FormularioContrato(request.POST if request.method == "POST" else None, request.FILES or None,
        instance=actual or Contrato(decision=decision), initial={"revision_esperada": actual.revision if actual else 0})
    if request.method == "POST":
        if not editable:
            messages.error(request, "El contrato solo permite consulta. Anule la decisión para registrar cambios.")
            return redirect("compras:contrato", pk=pk, decision_pk=decision_pk)
        if formulario.is_valid():
            try:
                servicios.guardar_contrato(decision, actor=request.user, **formulario.cleaned_data)
            except ValidationError as error:
                agregar_errores(formulario, error)
            else:
                return redirect("compras:contrato", pk=pk, decision_pk=decision_pk)
    if actual:
        actual.refresh_from_db()
    return render(request, "compras/contrato.html", {"decision": decision, "contrato": actual, "editable": editable,
        "formulario": formulario, "reglas": servicios.reglas_actuales(), "foto": servicios.foto(actual) if actual else None,
        "polizas": actual.polizas.all() if actual else [], "tablero": servicios.tablero_polizas(actual) if actual else [],
        "revisiones": actual.revisiones.select_related("actor") if actual else []})


@rol_requerido(*ROLES_ADMIN)
@never_cache
@require_http_methods(["GET", "POST"])
def poliza(request, pk, decision_pk, poliza_pk=None):
    actual = get_object_or_404(Contrato.objects.select_related("decision__cotizacion"), decision_id=decision_pk, decision__cotizacion_id=pk)
    registro = get_object_or_404(Poliza, pk=poliza_pk, contrato=actual) if poliza_pk else Poliza(contrato=actual)
    if not _editable(actual.decision):
        messages.error(request, "Las pólizas solo permiten consulta después de la primera firma o de la anulación.")
        return redirect("compras:contrato", pk=pk, decision_pk=decision_pk)
    formulario = forms.FormularioPoliza(request.POST if request.method == "POST" else None, request.FILES or None, instance=registro,
        initial={"revision_esperada": actual.revision})
    if request.method == "POST" and formulario.is_valid():
        try:
            servicios.guardar_poliza(actual, poliza=registro if registro.pk else None, actor=request.user, **formulario.cleaned_data)
        except ValidationError as error:
            agregar_errores(formulario, error)
        else:
            return redirect("compras:contrato", pk=pk, decision_pk=decision_pk)
    return render(request, "compras/poliza_formulario.html", {"contrato": actual, "formulario": formulario})


@rol_requerido(*ROLES_ADMIN)
@never_cache
@require_safe
def revision(request, pk, decision_pk, revision_pk):
    registro = get_object_or_404(RevisionContrato.objects.select_related("contrato", "actor"), pk=revision_pk,
        contrato__decision_id=decision_pk, contrato__decision__cotizacion_id=pk)
    return render(request, "compras/contrato_revision.html", {"revision": registro, "foto": registro.contenido["contrato"]})


@rol_requerido(*ROLES_ADMIN)
@never_cache
@require_safe
def descargar(request, pk, decision_pk, adjunto_pk):
    adjunto = get_object_or_404(PdfContractual, pk=adjunto_pk, contrato__decision_id=decision_pk, contrato__decision__cotizacion_id=pk)
    try:
        archivo = adjunto.archivo.open("rb")
    except FileNotFoundError:
        raise Http404("La evidencia no está disponible.") from None
    try:
        registrar("contrato.pdf_descargado", actor=request.user, objeto=adjunto, motivo="Descarga privada de evidencia contractual", request=request)
    except BaseException:
        archivo.close()
        raise
    respuesta = FileResponse(archivo, as_attachment=True, filename=adjunto.nombre_archivo, content_type="application/pdf")
    respuesta["X-Content-Type-Options"] = "nosniff"
    respuesta["Cache-Control"] = "private, no-store"
    return respuesta


@rol_requerido(*ROLES_ADMIN)
@never_cache
@require_safe
def alertas(request):
    filtro = forms.FiltroPolizas(request.GET if request.GET else None)
    filas = []
    if not filtro.is_bound:
        filas = servicios.tablero_polizas()
    elif filtro.is_valid():
        filas = servicios.tablero_polizas(referencia=filtro.cleaned_data["fecha"])
        if filtro.cleaned_data["estado"]:
            filas = [f for f in filas if f["estado"] == filtro.cleaned_data["estado"]]
    return render(request, "compras/polizas_alertas.html", {"filtro": filtro, "filas": filas})


@rol_requerido(*ROLES_ADMIN)
@require_http_methods(["GET", "POST"])
def tipos(request, pk=None):
    tipo = get_object_or_404(TipoPoliza, pk=pk) if pk else TipoPoliza()
    formulario = forms.FormularioTipoPoliza(request.POST if request.method == "POST" else None, instance=tipo)
    if request.method == "POST" and formulario.is_valid():
        try:
            servicios.guardar_tipo(formulario.instance, actor=request.user, motivo=formulario.cleaned_data["motivo"])
        except ValidationError as error:
            agregar_errores(formulario, error)
        else:
            return redirect("compras:poliza_tipos")
    return render(request, "compras/poliza_tipos.html", {"formulario": formulario, "tipos": TipoPoliza.objects.all()})
