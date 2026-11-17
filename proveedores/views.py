"""Vistas de /proveedores/, solo para administrador y desarrollador.

Las vistas solo coordinan formulario → servicio → mensaje; las reglas están en
proveedores/servicios.py. Los PDF solo se descargan por `documento_descargar`, que valida
permisos; MEDIA_ROOT nunca se publica por URL.
"""

from django.contrib import messages
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_safe

from config.utilidades import agregar_errores
from cuentas.models import ROLES_ADMIN
from cuentas.permisos import rol_requerido
from proveedores import forms, servicios
from proveedores.models import DocumentoProveedor, Proveedor, TipoDocumento
from proveedores.documental import tablero

solo_administradores = rol_requerido(*ROLES_ADMIN)

POR_PAGINA = 25


def _documento(proveedor_pk, pk):
    """El documento solo se busca dentro del proveedor de la URL: otro id da 404."""
    return get_object_or_404(DocumentoProveedor.objects.select_related("proveedor", "tipo"), pk=pk, proveedor_id=proveedor_pk)


def _url_bitacora(objeto):
    tipo = ContentType.objects.get_for_model(objeto)
    return f"{reverse('bitacora:consulta')}?tipo_objeto={tipo.pk}&objeto_id={objeto.pk}"


# --- Proveedores ------------------------------------------------------------------------


@solo_administradores
@require_safe
def lista(request):
    filtro = forms.FiltroProveedores(request.GET or None)
    consulta = Proveedor.objects.select_related("categoria")
    if filtro.is_valid():
        consulta = servicios.buscar(consulta, filtro.cleaned_data["q"])
        if filtro.cleaned_data["estado"]:
            consulta = consulta.filter(estado=filtro.cleaned_data["estado"])
        if filtro.cleaned_data["categoria"]:
            consulta = consulta.filter(categoria=filtro.cleaned_data["categoria"])
    pagina = Paginator(consulta.order_by("razon_social", "nit"), POR_PAGINA).get_page(request.GET.get("pagina"))
    return render(
        request,
        "proveedores/lista.html",
        {"filtro": filtro, "pagina": pagina, "alertas": servicios.resumen_alertas(),
         "alertas_personalizadas": TipoDocumento.objects.filter(usar_alerta_general=False).exists()},
    )


@solo_administradores
@require_http_methods(["GET", "POST"])
def formulario(request, pk=None):
    proveedor = get_object_or_404(Proveedor, pk=pk) if pk else Proveedor()
    es_nuevo = not proveedor.pk
    inicial = {"razon_social": request.GET.get("nombre", "").strip()[:200]} if es_nuevo and request.method == "GET" else {}
    formulario = forms.FormularioProveedor(request.POST or None, instance=proveedor, initial=inicial)
    if request.method == "POST" and formulario.is_valid():
        try:
            servicios.guardar_proveedor(
                formulario.instance, actor=request.user, motivo=formulario.cleaned_data["motivo"], request=request
            )
        except ValidationError as error:
            agregar_errores(formulario, error)
        else:
            messages.success(request, f"Proveedor «{proveedor.razon_social}» guardado.")
            return redirect("proveedores:detalle", pk=proveedor.pk)
    return render(
        request,
        "proveedores/formulario.html",
        {
            "formulario": formulario,
            "titulo": "Nuevo proveedor" if es_nuevo else f"Editar {proveedor.razon_social}",
            "boton": "Crear proveedor" if es_nuevo else "Guardar cambios",
            "volver": reverse("proveedores:lista") if es_nuevo else reverse("proveedores:detalle", args=[proveedor.pk]),
        },
    )


@solo_administradores
@require_safe
def detalle(request, pk):
    proveedor = get_object_or_404(Proveedor.objects.select_related("categoria"), pk=pk)
    documentos = servicios.documentos_de(proveedor)
    alertas = [d for d in documentos if d.es_actual and d.vigencia in (servicios.VIGENCIA_VENCIDO, servicios.VIGENCIA_POR_VENCER)]
    return render(
        request,
        "proveedores/detalle.html",
        {
            "proveedor": proveedor,
            "historial_evaluaciones": proveedor.evaluaciones.select_related("version", "evaluador").order_by("-fecha", "-pk")[:10],
            "control_documental": tablero(proveedor),
            "evaluacion_vigente": proveedor.evaluacion_vigente,
            "documentos": documentos,
            "vencidos": [d for d in alertas if d.vigencia == servicios.VIGENCIA_VENCIDO],
            "por_vencer": [d for d in alertas if d.vigencia == servicios.VIGENCIA_POR_VENCER],
            "dias_alerta": servicios.dias_alerta(),
            "alertas_personalizadas": TipoDocumento.objects.filter(usar_alerta_general=False).exists(),
            "usuarios_portal": proveedor.usuarios.order_by("nombre"),
            "url_bitacora": _url_bitacora(proveedor),
        },
    )


@solo_administradores
@require_http_methods(["GET", "POST"])
def estado(request, pk):
    proveedor = get_object_or_404(Proveedor, pk=pk)
    formulario = forms.FormularioEstado(request.POST or None, opciones=servicios.estados_posibles(proveedor, request.user))
    if request.method == "POST" and formulario.is_valid():
        try:
            servicios.cambiar_estado(
                proveedor,
                formulario.cleaned_data["estado"],
                actor=request.user,
                motivo=formulario.cleaned_data["motivo"],
                request=request,
            )
        except PermissionDenied as error:
            formulario.add_error("estado", str(error))
        except ValidationError as error:
            agregar_errores(formulario, error)
        else:
            proveedor.refresh_from_db()
            messages.success(request, f"El proveedor quedó en estado «{proveedor.get_estado_display()}».")
            return redirect("proveedores:detalle", pk=proveedor.pk)
    return render(
        request,
        "proveedores/formulario.html",
        {
            "formulario": formulario,
            "titulo": f"Cambiar estado de {proveedor.razon_social}",
            "nota": f"Estado actual: {proveedor.get_estado_display()}.",
            "boton": "Cambiar estado",
            "volver": reverse("proveedores:detalle", args=[proveedor.pk]),
        },
    )


# --- Documentos -------------------------------------------------------------------------


@solo_administradores
@require_http_methods(["GET", "POST"])
def documento_formulario(request, proveedor_pk, pk=None):
    proveedor = get_object_or_404(Proveedor, pk=proveedor_pk)
    documento = _documento(proveedor_pk, pk) if pk else DocumentoProveedor(proveedor=proveedor)
    es_nuevo = not documento.pk
    formulario = forms.FormularioDocumento(request.POST or None, request.FILES or None, instance=documento)
    if request.method == "POST" and formulario.is_valid():
        try:
            servicios.guardar_documento(
                formulario.instance,
                actor=request.user,
                motivo=formulario.cleaned_data["motivo"],
                archivo_subido=formulario.cleaned_data.get("archivo_pdf"),
                request=request,
            )
        except ValidationError as error:
            if hasattr(error, "error_dict") and "archivo" in error.error_dict:
                formulario.add_error("archivo_pdf", error.error_dict.pop("archivo"))
            agregar_errores(formulario, error)
        else:
            messages.success(request, f"Documento «{documento.tipo}» guardado.")
            return redirect("proveedores:detalle", pk=proveedor.pk)
    return render(
        request,
        "proveedores/formulario.html",
        {
            "formulario": formulario,
            "con_archivo": True,
            "titulo": f"{'Agregar' if es_nuevo else 'Editar'} documento de {proveedor.razon_social}",
            "boton": "Agregar documento" if es_nuevo else "Guardar cambios",
            "volver": reverse("proveedores:detalle", args=[proveedor.pk]),
        },
    )


@solo_administradores
@require_http_methods(["GET", "POST"])
def documento_eliminar(request, proveedor_pk, pk):
    documento = _documento(proveedor_pk, pk)
    formulario = forms.FormularioMotivo(request.POST or None)
    if request.method == "POST" and formulario.is_valid():
        try:
            servicios.eliminar_documento(
                documento, actor=request.user, motivo=formulario.cleaned_data["motivo"], request=request
            )
        except ValidationError as error:
            agregar_errores(formulario, error)
        else:
            messages.success(request, f"Documento «{documento.tipo}» eliminado. Sus datos quedan en la bitácora.")
            return redirect("proveedores:detalle", pk=proveedor_pk)
    return render(
        request,
        "proveedores/formulario.html",
        {
            "formulario": formulario,
            "titulo": f"Eliminar documento «{documento.tipo}»",
            "nota": (
                f"Proveedor: {documento.proveedor.razon_social}. Se borrará el documento"
                f"{' y su archivo PDF' if documento.tiene_pdf else ''}; sus datos quedan en la bitácora."
            ),
            "boton": "Eliminar documento",
            "peligro": True,
            "volver": reverse("proveedores:detalle", args=[proveedor_pk]),
        },
    )


@solo_administradores
@require_safe
def documento_descargar(request, proveedor_pk, pk):
    documento = _documento(proveedor_pk, pk)
    if not documento.tiene_pdf:
        raise Http404("El documento no tiene archivo PDF.")
    try:
        archivo = documento.archivo.open("rb")
    except FileNotFoundError:
        raise Http404("El archivo no está disponible.") from None
    respuesta = FileResponse(
        archivo,
        as_attachment=True,
        filename=documento.nombre_archivo or f"documento-{documento.pk}.pdf",
        content_type="application/pdf",
    )
    respuesta["X-Content-Type-Options"] = "nosniff"
    respuesta["Cache-Control"] = "private, no-store"
    return respuesta


@solo_administradores
@require_safe
def vencimientos(request):
    filtro = forms.FiltroVencimientos(request.GET)
    documentos = []
    if filtro.is_valid():
        datos = filtro.cleaned_data
        proveedores = servicios.buscar(Proveedor.objects.all(), datos["q"])
        if datos["categoria"]:
            proveedores = proveedores.filter(categoria=datos["categoria"])
        ids = set(proveedores.values_list("pk", flat=True))
        documentos = [d for d in servicios.alertas_vencimiento() if d.proveedor_id in ids
            and (not datos["tipo"] or d.tipo_id == datos["tipo"].pk)
            and (not datos["estado"] or d.vigencia == datos["estado"])]
    return render(
        request,
        "proveedores/vencimientos.html",
        {
            "filtro": filtro,
            "vencidos": [d for d in documentos if d.vigencia == servicios.VIGENCIA_VENCIDO],
            "por_vencer": [d for d in documentos if d.vigencia == servicios.VIGENCIA_POR_VENCER],
            "dias_alerta": servicios.dias_alerta(),
            "alertas_personalizadas": TipoDocumento.objects.filter(usar_alerta_general=False).exists(),
        },
    )
