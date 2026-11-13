from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST, require_safe

from bitacora.servicios import registrar
from compras import oferta_forms as forms, oferta_servicios as servicios
from compras.models import Cotizacion, InvitadoCotizacion, Oferta, PdfOferta, RevisionOferta, TarifaImpuesto
from config.utilidades import agregar_errores
from cuentas.models import ROLES_ADMIN
from cuentas.permisos import rol_requerido


@rol_requerido(*ROLES_ADMIN)
@never_cache
@require_http_methods(["GET", "POST"])
def guardar(request, cotizacion_pk, invitado_pk):
    cotizacion = get_object_or_404(Cotizacion, pk=cotizacion_pk)
    invitado = get_object_or_404(InvitadoCotizacion.objects.select_related("proveedor"), pk=invitado_pk, cotizacion=cotizacion)
    actual = Oferta.objects.filter(cotizacion=cotizacion, proveedor=invitado.proveedor).first()
    if cotizacion.estado not in ("borrador", "en_comparacion"):
        messages.error(request, "La cotización ya no admite cambios de ofertas.")
        return redirect("compras:cotizacion_detalle", pk=cotizacion.pk)
    contacto = invitado.proveedor
    inicial = {"contacto_nombre": contacto.contacto_nombre, "contacto_correo": contacto.contacto_correo, "contacto_telefono": contacto.contacto_telefono}
    if actual:
        inicial.update({c: getattr(actual, c) for c in ("contacto_nombre", "contacto_correo", "contacto_telefono", "fecha", "vigente_hasta", "observacion")})
    inicial["revision_esperada"] = actual.revision if actual else 0
    formulario = forms.FormularioOferta(request.POST if request.method == "POST" else None, request.FILES or None, initial=inicial)
    lineas = list(cotizacion.lineas.all())
    anteriores = {l.linea_id: l for l in actual.lineas.all()} if actual else {}
    precios_iniciales = [{"linea": l.pk, "precio_unitario": anteriores[l.pk].precio_unitario if l.pk in anteriores else None,
                         "tarifa": anteriores[l.pk].tarifa_id if l.pk in anteriores else None} for l in lineas]
    precios = forms.formulario_precios(request.POST if request.method == "POST" else None, inicial=precios_iniciales)
    if request.method == "POST" and formulario.is_valid() and precios.is_valid():
        try:
            oferta = servicios.guardar_oferta(cotizacion, invitado, precios=[f.cleaned_data for f in precios], actor=request.user, **formulario.cleaned_data)
        except ValidationError as error:
            agregar_errores(formulario, error)
        else:
            messages.success(request, "Oferta guardada y totales calculados en el servidor. Se conservó una revisión.")
            return redirect("compras:oferta_detalle", cotizacion_pk=cotizacion.pk, pk=oferta.pk)
    return render(request, "compras/oferta_formulario.html", {"cotizacion": cotizacion, "invitado": invitado,
        "actual": actual, "formulario": formulario, "precios": precios, "filas": list(zip(lineas, precios.forms)), "reglas": servicios.reglas_actuales()})


@rol_requerido(*ROLES_ADMIN)
@never_cache
@require_safe
def detalle(request, cotizacion_pk, pk):
    oferta = get_object_or_404(Oferta.objects.select_related("cotizacion", "proveedor", "pdf", "registrada_por"), pk=pk, cotizacion_id=cotizacion_pk)
    return render(request, "compras/oferta_detalle.html", {"oferta": oferta, "lineas": oferta.lineas.all(), "revisiones": oferta.revisiones.select_related("actor", "pdf")})


@rol_requerido(*ROLES_ADMIN)
@never_cache
@require_safe
def revision(request, cotizacion_pk, pk, revision_pk):
    oferta = get_object_or_404(Oferta, pk=pk, cotizacion_id=cotizacion_pk)
    registro = get_object_or_404(RevisionOferta.objects.select_related("actor", "pdf"), pk=revision_pk, oferta=oferta)
    return render(request, "compras/oferta_revision.html", {"oferta": oferta, "revision": registro, "foto": registro.contenido})


@rol_requerido(*ROLES_ADMIN)
@never_cache
@require_safe
def descargar(request, cotizacion_pk, pk, adjunto_pk):
    oferta = get_object_or_404(Oferta, pk=pk, cotizacion_id=cotizacion_pk)
    adjunto = get_object_or_404(PdfOferta, pk=adjunto_pk, oferta=oferta)
    try:
        archivo = adjunto.archivo.open("rb")
    except FileNotFoundError:
        raise Http404("El PDF no está disponible.") from None
    try:
        registrar("oferta.pdf_descargado", actor=request.user, objeto=adjunto, motivo="Descarga privada de PDF de oferta", request=request)
    except BaseException:
        archivo.close()
        raise
    respuesta = FileResponse(archivo, as_attachment=True, filename=adjunto.nombre_archivo, content_type="application/pdf")
    respuesta["X-Content-Type-Options"] = "nosniff"
    respuesta["Cache-Control"] = "private, no-store"
    return respuesta


@rol_requerido(*ROLES_ADMIN)
@require_http_methods(["GET", "POST"])
def tarifas(request, pk=None):
    tarifa = get_object_or_404(TarifaImpuesto, pk=pk) if pk else TarifaImpuesto()
    formulario = forms.FormularioTarifa(request.POST if request.method == "POST" else None, instance=tarifa)
    if request.method == "POST" and formulario.is_valid():
        try:
            servicios.guardar_tarifa(formulario.instance, actor=request.user, motivo=formulario.cleaned_data["motivo"])
        except ValidationError as error:
            agregar_errores(formulario, error)
        else:
            return redirect("compras:oferta_tarifas")
    return render(request, "compras/oferta_tarifas.html", {"formulario": formulario, "tarifas": TarifaImpuesto.objects.all()})


@rol_requerido(*ROLES_ADMIN)
@require_POST
def invitar(request, cotizacion_pk):
    cotizacion = get_object_or_404(Cotizacion, pk=cotizacion_pk)
    formulario = forms.FormularioInvitado(request.POST, cotizacion=cotizacion)
    if formulario.is_valid():
        try:
            servicios.invitar_proveedor(cotizacion, actor=request.user, **formulario.cleaned_data)
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        else:
            messages.success(request, "Proveedor invitado. Ya puede registrar su oferta.")
    else:
        messages.error(request, "Seleccione un proveedor válido e indique el motivo.")
    return redirect("compras:cotizacion_detalle", pk=cotizacion_pk)
