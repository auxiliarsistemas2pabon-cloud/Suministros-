from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_safe

from compras import cotizacion_forms as forms, cotizacion_servicios as servicios
from compras.cotizacion_origen import preparar_cotizacion
from compras.decision_servicios import cantidad_necesidad
from compras.models import Cotizacion, ListaElegibles, Necesidad, OrigenNecesidad, TipoCotizacion
from config.utilidades import agregar_errores
from cuentas.models import ROLES_ADMIN
from cuentas.permisos import rol_requerido
from proyecciones.models import UnidadMedida


@rol_requerido(*ROLES_ADMIN)
@require_safe
def lista(request):
    from config.listados import preparar, excel
    filtro, consulta = preparar("cotizaciones", request.GET, request.user)
    consulta = consulta.select_related("necesidad", "lista_elegibles", "tipo", "area", "responsable")
    if request.GET.get("formato") == "excel" and filtro.is_valid():
        return excel(consulta, "cotizaciones")
    return render(request, "compras/cotizaciones.html", {"filtro": filtro, "pagina": Paginator(consulta, 25).get_page(request.GET.get("pagina"))})


def _iniciales(necesidad, origenes, datos):
    unidades = list(UnidadMedida.objects.filter(activa=True))
    por_linea = {o.linea_id: o for o in origenes.select_related("linea__unidad")}
    def unidad_para(texto, origen=None):
        if origen and origen.linea.unidad.activa:
            return origen.linea.unidad_id
        candidatas = [u for u in unidades if texto.casefold() in {str(u).casefold(), u.nombre.casefold(), u.abreviatura.casefold()}]
        return candidatas[0].pk if len(candidatas) == 1 else None
    lineas = datos.get("lineas") if datos else [{"linea_origen_id": o.linea_id, "cantidad": str(o.cantidad), **o.datos_origen} for o in por_linea.values()]
    filas = []
    for dato in lineas:
        origen = por_linea.get(dato["linea_origen_id"])
        filas.append({"descripcion": dato["producto"], "unidad": unidad_para(dato["unidad"], origen), "cantidad": dato["cantidad"], "origen": origen.pk if origen else None})
    if not filas and necesidad:
        base = datos["base"] if datos else cantidad_necesidad(necesidad)
        filas.append({"descripcion": datos["necesidad"]["objeto"] if datos else necesidad.objeto,
            "cantidad": base["cantidad"], "unidad": unidad_para(base["unidad"])})
    return filas


@rol_requerido(*ROLES_ADMIN)
@require_http_methods(["GET", "POST"])
def nueva(request, lista_pk=None):
    lista_origen, datos, necesidad = None, {}, None
    seleccion = forms.SeleccionNecesidad(request.GET)
    if lista_pk:
        lista_origen = get_object_or_404(ListaElegibles, pk=lista_pk)
        try:
            datos = preparar_cotizacion(lista_origen, actor=request.user)
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
            return redirect("compras:lista_detalle", pk=lista_pk)
        necesidad = lista_origen.necesidad
    elif request.method == "POST":
        try:
            necesidad = Necesidad.objects.filter(pk=request.POST.get("necesidad")).first()
        except (ValueError, TypeError, ValidationError):
            necesidad = None
    elif seleccion.is_valid():
        necesidad = seleccion.cleaned_data["necesidad"]
    origenes = OrigenNecesidad.objects.filter(necesidad=necesidad) if necesidad else OrigenNecesidad.objects.none()
    if lista_origen:
        origenes = origenes.filter(linea_id__in=[d["linea_origen_id"] for d in datos["lineas"]])
    limites = servicios.limites_actuales()
    inicial = {"necesidad": necesidad, "objeto": datos["necesidad"]["objeto"] if datos else (necesidad.objeto if necesidad else "")}
    formulario = forms.FormularioCotizacion(request.POST if request.method == "POST" else None, lista=lista_origen, initial=inicial)
    filas = forms.formulario_lineas(request.POST if request.method == "POST" else None, limite=limites["lineas"], origenes=origenes,
        initial=_iniciales(necesidad, origenes, datos) if request.method == "GET" else None)
    if request.method == "POST" and formulario.is_valid() and filas.is_valid():
        cabecera = formulario.cleaned_data.copy()
        cabecera.pop("revision_origen")
        cabecera["lista_elegibles"] = lista_origen
        if lista_origen:
            cabecera["cierre_esperado_id"] = formulario.identidad["cierre"]
        lineas = [{k: v for k, v in f.cleaned_data.items() if k != "DELETE"} for f in filas if f.cleaned_data and not f.cleaned_data.get("DELETE")]
        try:
            cotizacion = servicios.crear_cotizacion(lineas=lineas, actor=request.user, **cabecera)
        except ValidationError as error:
            agregar_errores(formulario, error)
        else:
            messages.success(request, f"Cotización {cotizacion.consecutivo} creada en borrador.")
            return redirect("compras:cotizacion_detalle", pk=cotizacion.pk)
    accion = reverse("compras:cotizacion_desde_lista", args=[lista_pk]) if lista_pk else reverse("compras:cotizacion_nueva")
    return render(request, "compras/cotizacion_preparar.html", {"lista": lista_origen, "necesidad": necesidad,
        "datos": datos, "seleccion": seleccion, "formulario": formulario, "filas": filas, "limites": limites, "accion": accion})


@rol_requerido(*ROLES_ADMIN)
@require_safe
def detalle(request, pk):
    from compras.oferta_forms import FormularioInvitado
    cotizacion = get_object_or_404(Cotizacion.objects.select_related("necesidad", "lista_elegibles", "cierre_origen", "tipo", "area", "responsable"), pk=pk)
    return render(request, "compras/cotizacion_detalle.html", {"cotizacion": cotizacion,
        "lineas": cotizacion.lineas.select_related("origen__linea__proyeccion"), "invitados": cotizacion.invitados.select_related("proveedor"),
        "ofertas": cotizacion.ofertas.all(), "invitacion_form": FormularioInvitado(cotizacion=cotizacion)})


@rol_requerido(*ROLES_ADMIN)
@require_http_methods(["GET", "POST"])
def tipos(request, pk=None):
    tipo = get_object_or_404(TipoCotizacion, pk=pk) if pk else TipoCotizacion()
    formulario = forms.FormularioTipoCotizacion(request.POST if request.method == "POST" else None, instance=tipo)
    if request.method == "POST" and formulario.is_valid():
        try:
            servicios.guardar_tipo(formulario.instance, actor=request.user, motivo=formulario.cleaned_data["motivo"])
        except ValidationError as error:
            agregar_errores(formulario, error)
        else:
            return redirect("compras:cotizacion_tipos")
    return render(request, "compras/cotizacion_tipos.html", {"formulario": formulario, "tipos": TipoCotizacion.objects.all()})
