from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_safe, require_POST

from compras import orden_forms as forms, orden_servicios as servicios
from compras.models import DecisionCotizacion, OrdenCompra, RevisionOrdenCompra
from config.utilidades import agregar_errores
from cuentas.models import ROLES_ADMIN
from cuentas.permisos import rol_requerido


@rol_requerido(*ROLES_ADMIN)
@never_cache
@require_safe
def lista(request):
    from config.listados import preparar, excel
    filtro, consulta = preparar("ordenes", request.GET, request.user)
    consulta = consulta.select_related("decision", "cotizacion", "elaborada_por")
    if request.GET.get("formato") == "excel" and filtro.is_valid():
        return excel(consulta, "ordenes")
    return render(request, "compras/ordenes.html", {"filtro": filtro, "pagina": Paginator(consulta, 25).get_page(request.GET.get("pagina"))})


@rol_requerido(*ROLES_ADMIN)
@never_cache
@require_http_methods(["GET", "POST"])
def crear(request, pk, decision_pk):
    decision = get_object_or_404(DecisionCotizacion.objects.select_related("cotizacion"), pk=decision_pk, cotizacion_id=pk)
    try:
        grupos = servicios.preparar_ordenes(decision, actor=request.user)
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
        return redirect("compras:cotizacion_decision", pk=pk, decision_pk=decision_pk)
    existentes = list(decision.ordenes.all())
    formulario = forms.FormularioCrearOrden(request.POST if request.method == "POST" else None,
        initial={"condiciones_pago": grupos[0]["condiciones_pago"] if grupos else ""})
    if request.method == "POST" and formulario.is_valid():
        try:
            ordenes = servicios.crear_orden_desde_decision(decision, actor=request.user, **formulario.cleaned_data)
        except ValidationError as error:
            agregar_errores(formulario, error)
        else:
            messages.success(request, f"Órdenes disponibles: {len(ordenes)}. Las ya creadas conservan sus datos.")
            if len(ordenes) == 1:
                return redirect("compras:orden_detalle", pk=ordenes[0].pk)
            return redirect("compras:cotizacion_decision", pk=pk, decision_pk=decision_pk)
    return render(request, "compras/orden_crear.html", {"decision": decision, "grupos": grupos, "existentes": existentes, "formulario": formulario})


@rol_requerido(*ROLES_ADMIN)
@never_cache
@require_safe
def detalle(request, pk):
    from compras.recepcion_servicios import acumulados
    orden = get_object_or_404(OrdenCompra.objects.select_related("decision", "cotizacion__necesidad", "cotizacion__lista_elegibles", "elaborada_por", "evaluacion_origen"), pk=pk)
    return render(request, "compras/orden_detalle.html", {"orden": orden, "foto": servicios.foto(orden),
        "traza": orden.origen_datos["trazabilidad"], "revisiones": orden.revisiones.select_related("actor"),
        "solicitudes": orden.solicitudes_aprobacion.prefetch_related("firmas"), "envios": orden.envios.select_related("registrado_por"),
        "recepciones": orden.recepciones.select_related("recibido_por"), "recibido": acumulados(orden),
        "formulario_anular": forms.FormularioAnularOrden(initial={"revision_esperada": orden.revision})})


@rol_requerido(*ROLES_ADMIN)
@never_cache
@require_http_methods(["GET", "POST"])
def editar(request, pk):
    orden = get_object_or_404(OrdenCompra.objects.select_related("decision", "cotizacion"), pk=pk)
    if orden.estado != "borrador" or orden.decision.estado != "aprobada" or orden.cotizacion.estado != "decidida":
        messages.error(request, "Esta orden solo permite consulta.")
        return redirect("compras:orden_detalle", pk=pk)
    inicial = [{"id": l.pk, **{c: getattr(l, c) for c in ("referencia", "descripcion", "especificacion", "unidad", "cantidad", "precio_unitario", "descuento")}} for l in orden.lineas.all()]
    formulario = forms.FormularioOrden(request.POST if request.method == "POST" else None, orden=orden,
        initial={"fecha_elaboracion": orden.fecha_elaboracion, "condiciones_pago": orden.condiciones_pago, "fecha_vencimiento": orden.fecha_vencimiento, "fecha_esperada_entrega": orden.fecha_esperada_entrega, "revision_esperada": orden.revision})
    filas = forms.formulario_lineas(request.POST if request.method == "POST" else None, inicial=inicial)
    if request.method == "POST" and formulario.is_valid() and filas.is_valid():
        try:
            servicios.guardar_borrador(orden, lineas=[f.cleaned_data for f in filas], actor=request.user, **formulario.cleaned_data)
        except ValidationError as error:
            agregar_errores(formulario, error)
        else:
            return redirect("compras:orden_detalle", pk=pk)
    return render(request, "compras/orden_editar.html", {"orden": orden, "formulario": formulario, "filas": filas})


@rol_requerido(*ROLES_ADMIN)
@never_cache
@require_safe
def revision(request, pk, revision_pk):
    orden = get_object_or_404(OrdenCompra, pk=pk)
    registro = get_object_or_404(RevisionOrdenCompra.objects.select_related("actor"), pk=revision_pk, orden=orden)
    return render(request, "compras/orden_revision.html", {"orden": orden, "revision": registro, "foto": registro.contenido})


@rol_requerido(*ROLES_ADMIN)
@require_POST
def anular(request, pk):
    from compras.numeracion_ordenes import anular_orden
    orden = get_object_or_404(OrdenCompra, pk=pk)
    formulario = forms.FormularioAnularOrden(request.POST)
    if formulario.is_valid():
        try:
            anular_orden(orden, actor=request.user, **formulario.cleaned_data)
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        else:
            messages.success(request, "Orden anulada; se conservan número, datos e historial.")
    else:
        messages.error(request, "Indique el motivo y la revisión de la orden que desea anular.")
    return redirect("compras:orden_detalle", pk=pk)
