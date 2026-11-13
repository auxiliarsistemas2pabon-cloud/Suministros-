from urllib.parse import urlencode

from django.contrib import messages
from django.core import signing
from django.core.exceptions import ValidationError
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_safe

from bitacora.servicios import registrar
from compras import verificacion_forms as forms, verificacion_servicios as servicios
from compras.models import Cotizacion, EstadoVerificacion, Oferta, PdfVerificacionOferta, RevisionVerificacionOferta, TipoVerificacion, VerificacionOferta
from config.utilidades import agregar_errores
from cuentas.models import ROLES_ADMIN
from cuentas.permisos import rol_requerido


@rol_requerido(*ROLES_ADMIN)
@never_cache
@require_safe
def matriz(request, cotizacion_pk):
    cotizacion = get_object_or_404(Cotizacion, pk=cotizacion_pk)
    return render(request, "compras/verificaciones_matriz.html", {"cotizacion": cotizacion, "matriz": servicios.matriz_verificaciones(cotizacion)})


@rol_requerido(*ROLES_ADMIN)
@never_cache
@require_http_methods(["GET", "POST"])
def guardar(request, cotizacion_pk, oferta_pk, tipo_pk):
    oferta = get_object_or_404(Oferta.objects.select_related("cotizacion", "proveedor"), pk=oferta_pk, cotizacion_id=cotizacion_pk)
    tipo = get_object_or_404(TipoVerificacion, pk=tipo_pk)
    if oferta.cotizacion.estado not in ("borrador", "en_comparacion") or not tipo.activo:
        messages.error(request, "Esta cotización o tipo ya no admite modificaciones de verificaciones.")
        return redirect("compras:verificaciones", cotizacion_pk=cotizacion_pk)
    actual = VerificacionOferta.objects.filter(oferta=oferta, tipo=tipo).first()
    filtro = forms.FiltroFecha(request.GET if "fecha" in request.GET else None)
    fecha = filtro.cleaned_data["fecha"] if filtro.is_bound and filtro.is_valid() else timezone.localdate()
    propuesta = servicios.proponer_documental(oferta, fecha=fecha) if tipo.origen == "documental" else None
    inicial = {"fecha": fecha, "oferta_revision_esperada": oferta.revision, "revision_esperada": actual.revision if actual else 0}
    if actual:
        inicial.update(estado=actual.estado_id, observacion=actual.observacion)
        if tipo.origen == "manual":
            inicial["fecha"] = actual.fecha
    if propuesta:
        if not actual:
            inicial["estado"] = EstadoVerificacion.objects.filter(activo=True, clasificacion=propuesta["clasificacion"]).first()
        inicial["firma_propuesta"] = signing.dumps(propuesta, salt="propuesta-verificacion", compress=True)
    formulario = forms.FormularioVerificacion(request.POST if request.method == "POST" else None, request.FILES or None, tipo=tipo, initial=inicial)
    fecha_valida = not filtro.is_bound or filtro.is_valid()
    if request.method == "POST" and formulario.is_valid() and fecha_valida:
        try:
            registro = servicios.guardar_verificacion(oferta, tipo, actor=request.user, **formulario.cleaned_data)
        except ValidationError as error:
            agregar_errores(formulario, error)
        else:
            messages.success(request, "Verificación confirmada con usuario, fecha e historial de evidencia.")
            return redirect("compras:verificacion_detalle", cotizacion_pk=cotizacion_pk, oferta_pk=oferta_pk, pk=registro.pk)
    accion = reverse("compras:verificacion_guardar", args=[cotizacion_pk, oferta_pk, tipo_pk])
    if propuesta:
        accion += "?" + urlencode({"fecha": fecha.isoformat()})
    return render(request, "compras/verificacion_formulario.html", {"oferta": oferta, "tipo": tipo, "actual": actual,
        "formulario": formulario, "propuesta": propuesta, "filtro": filtro, "accion": accion})


@rol_requerido(*ROLES_ADMIN)
@never_cache
@require_safe
def detalle(request, cotizacion_pk, oferta_pk, pk):
    registro = get_object_or_404(VerificacionOferta.objects.select_related("oferta__cotizacion", "verificado_por", "pdf", "tipo"),
        pk=pk, oferta_id=oferta_pk, oferta__cotizacion_id=cotizacion_pk)
    return render(request, "compras/verificacion_detalle.html", {"registro": registro, "revisiones": registro.revisiones.select_related("actor", "pdf")})


@rol_requerido(*ROLES_ADMIN)
@never_cache
@require_safe
def revision(request, cotizacion_pk, oferta_pk, pk, revision_pk):
    registro = get_object_or_404(VerificacionOferta, pk=pk, oferta_id=oferta_pk, oferta__cotizacion_id=cotizacion_pk)
    historico = get_object_or_404(RevisionVerificacionOferta.objects.select_related("actor", "pdf"), pk=revision_pk, verificacion=registro)
    return render(request, "compras/verificacion_revision.html", {"registro": registro, "revision": historico, "foto": historico.contenido})


@rol_requerido(*ROLES_ADMIN)
@never_cache
@require_safe
def descargar(request, cotizacion_pk, oferta_pk, pk, adjunto_pk):
    registro = get_object_or_404(VerificacionOferta, pk=pk, oferta_id=oferta_pk, oferta__cotizacion_id=cotizacion_pk)
    adjunto = get_object_or_404(PdfVerificacionOferta, pk=adjunto_pk, verificacion=registro)
    try:
        archivo = adjunto.archivo.open("rb")
    except FileNotFoundError:
        raise Http404("La evidencia no está disponible.") from None
    try:
        registrar("verificacion.evidencia_descargada", actor=request.user, objeto=adjunto, motivo="Descarga privada de evidencia de verificación", request=request)
    except BaseException:
        archivo.close()
        raise
    respuesta = FileResponse(archivo, as_attachment=True, filename=adjunto.nombre_archivo, content_type="application/pdf")
    respuesta["X-Content-Type-Options"] = "nosniff"
    respuesta["Cache-Control"] = "private, no-store"
    return respuesta


@rol_requerido(*ROLES_ADMIN)
@require_http_methods(["GET", "POST"])
def catalogo(request, clase, pk=None):
    modelo, formulario_clase, servicio = (TipoVerificacion, forms.FormularioTipoVerificacion, servicios.guardar_tipo) if clase == "tipos" else (EstadoVerificacion, forms.FormularioEstadoVerificacion, servicios.guardar_estado)
    if clase not in ("tipos", "estados"):
        raise Http404("Catálogo no encontrado.")
    instancia = get_object_or_404(modelo, pk=pk) if pk else modelo()
    formulario = formulario_clase(request.POST if request.method == "POST" else None, instance=instancia)
    if request.method == "POST" and formulario.is_valid():
        try:
            servicio(formulario.instance, actor=request.user, motivo=formulario.cleaned_data["motivo"])
        except ValidationError as error:
            agregar_errores(formulario, error)
        else:
            return redirect("compras:verificacion_catalogo", clase=clase)
    return render(request, "compras/verificacion_catalogo.html", {"clase": clase, "registros": modelo.objects.all(), "formulario": formulario})
