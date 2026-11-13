from collections import Counter
from datetime import timedelta
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.http import Http404, HttpResponse, FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe, require_http_methods, require_POST
from bitacora.servicios import registrar
from config.utilidades import agregar_errores
from cuentas.models import Rol, ROLES_ADMIN
from cuentas.permisos import rol_requerido, es_admin
from parametros.catalogo import DIAS_SEGUIMIENTO
from parametros.servicios import obtener
from seguimientos.models import Seguimiento, EventoSeguimiento
from seguimientos import servicios, forms, reportes
from seguimientos.estados import ESTADOS


def _obtener(request, pk):
    return get_object_or_404(servicios.alcance(Seguimiento.objects.select_related("orden", "contrato", "area", "tipo"), request.user), pk=pk)


@rol_requerido(*ROLES_ADMIN, Rol.COORDINADOR)
@never_cache
@require_safe
def lista(request):
    filtro = forms.Filtro(request.GET)
    if not es_admin(request.user):
        filtro.fields["area"].queryset = filtro.fields["area"].queryset.filter(pk=request.user.area_id)
    # Valida alcance incluso cuando se envían filtros inválidos.
    servicios.alcance(Seguimiento.objects.all(), request.user)
    valido = filtro.is_valid()
    datos = reportes.consulta(filtro.cleaned_data if valido else {}, request.user)
    if not valido:
        datos = {"filas": [], "totales": {"cantidad": 0, "valor": 0}, "cantidades": []}
    if request.GET.get("formato") == "excel":
        if not valido:
            return HttpResponse("Corrija los filtros antes de exportar.", status=400)
        respuesta = HttpResponse(reportes.exportar(datos), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        respuesta["Content-Disposition"] = 'attachment; filename="seguimientos.xlsx"'
        respuesta["Cache-Control"] = "private, no-store"
        registrar("seguimiento.reporte_exportado", actor=request.user, nuevo={"cantidad": datos["totales"]["cantidad"]})
        return respuesta
    hoy = timezone.localdate()
    dias = obtener(DIAS_SEGUIMIENTO)
    contadores = Counter(f["estado"] for f in datos["filas"])
    proximos = [{"seguimiento": f["seguimiento"], **h} for f in datos["filas"] if not f["seguimiento"].cerrado for h in f["hitos"]
        if h["fecha_limite"] and not h["cumplido"] and hoy <= h["fecha_limite"] <= hoy+timedelta(days=dias)]
    parametros = request.GET.copy()
    parametros["formato"] = "excel"
    return render(request, "seguimientos/lista.html", {**datos, "filtro": filtro, "pagina": Paginator(datos["filas"], 25).get_page(request.GET.get("pagina")),
        "contadores": [(nombre, contadores.get(codigo, 0)) for codigo, nombre in ESTADOS], "proximos": sorted(proximos, key=lambda h: h["fecha_limite"]), "dias": dias,
        "url_excel": "?"+parametros.urlencode()})


@rol_requerido(*ROLES_ADMIN)
@never_cache
@require_http_methods(["GET", "POST"])
def crear(request):
    formulario = forms.Crear(request.POST if request.method == "POST" else None, initial={"orden": request.GET.get("orden"), "contrato": request.GET.get("contrato")})
    if request.method == "POST" and formulario.is_valid():
        try:
            seguimiento = servicios.crear(actor=request.user, **formulario.cleaned_data)
        except ValidationError as error:
            agregar_errores(formulario, error)
        else:
            return redirect("seguimientos:detalle", pk=seguimiento.pk)
    return render(request, "seguimientos/formulario.html", {"titulo": "Iniciar seguimiento", "formulario": formulario})


@rol_requerido(*ROLES_ADMIN, Rol.COORDINADOR)
@never_cache
@require_safe
def detalle(request, pk):
    seguimiento = _obtener(request, pk)
    return render(request, "seguimientos/detalle.html", {"seguimiento": seguimiento, **servicios.tablero(seguimiento),
        "eventos": seguimiento.eventos.select_related("registrado_por", "recepcion"), "cierres": seguimiento.cierres.select_related("registrado_por"),
        "movimientos": seguimiento.movimientos_linea.select_related("actor", "linea"),
        "accion": forms.ConRevision(initial={"revision_esperada": seguimiento.revision}), "puede_editar": es_admin(request.user)})


@rol_requerido(*ROLES_ADMIN)
@never_cache
@require_http_methods(["GET", "POST"])
def corregir(request, pk):
    seguimiento = _obtener(request, pk)
    formulario = forms.Corregir(request.POST if request.method == "POST" else None, instance=seguimiento, initial={"revision_esperada": seguimiento.revision})
    if request.method == "POST" and formulario.is_valid():
        try:
            servicios.corregir(seguimiento, actor=request.user, **formulario.cleaned_data)
        except ValidationError as error:
            agregar_errores(formulario, error)
        else:
            return redirect("seguimientos:detalle", pk=pk)
    return render(request, "seguimientos/formulario.html", {"titulo": "Corregir seguimiento con motivo", "formulario": formulario})


@rol_requerido(*ROLES_ADMIN)
@never_cache
@require_http_methods(["GET", "POST"])
def evento(request, pk):
    seguimiento = _obtener(request, pk)
    formulario = forms.Evento(request.POST if request.method == "POST" else None, request.FILES or None,
        initial={"revision_esperada": seguimiento.revision, "corrige_id": request.GET.get("corrige")})
    if request.method == "POST" and formulario.is_valid():
        try:
            servicios.agregar_evento(seguimiento, actor=request.user, **formulario.cleaned_data)
        except ValidationError as error:
            agregar_errores(formulario, error)
        else:
            return redirect("seguimientos:detalle", pk=pk)
    return render(request, "seguimientos/formulario.html", {"titulo": "Agregar evento o corrección", "formulario": formulario})


@rol_requerido(*ROLES_ADMIN, Rol.COORDINADOR)
@never_cache
@require_safe
def descargar(request, pk, evento_pk):
    seguimiento = _obtener(request, pk)
    registro = get_object_or_404(EventoSeguimiento, pk=evento_pk, seguimiento=seguimiento)
    if not registro.archivo:
        raise Http404
    try:
        archivo = registro.archivo.open("rb")
    except (OSError, ValueError):
        raise Http404("El archivo no está disponible.") from None
    registrar("seguimiento.evento_pdf_descargado", actor=request.user, objeto=registro)
    respuesta = FileResponse(archivo, as_attachment=True, filename=registro.nombre_archivo, content_type="application/pdf")
    respuesta["Cache-Control"] = "private, no-store"
    return respuesta


@rol_requerido(*ROLES_ADMIN)
@never_cache
@require_http_methods(["GET", "POST"])
def cerrar(request, pk):
    seguimiento = _obtener(request, pk)
    formulario = forms.Cierre(request.POST if request.method == "POST" else None, initial={"revision_esperada": seguimiento.revision})
    pendientes = [f for f in servicios.lineas(seguimiento) if f["pendiente"] > 0 and not f["cerrada"]]
    if request.method == "POST" and formulario.is_valid():
        try:
            servicios.cerrar(seguimiento, actor=request.user, **formulario.cleaned_data)
        except ValidationError as error:
            agregar_errores(formulario, error)
        else:
            return redirect("seguimientos:detalle", pk=pk)
    return render(request, "seguimientos/formulario.html", {"titulo": "Cerrar seguimiento", "formulario": formulario,
        "advertencia": "Hay líneas con saldo sin cierre justificado. Según el parámetro, el cierre se bloqueará o conservará esta advertencia." if pendientes else ""})


@rol_requerido(*ROLES_ADMIN)
@require_POST
def actuar(request, pk, accion):
    seguimiento = _obtener(request, pk)
    formulario = forms.ConRevision(request.POST)
    if formulario.is_valid():
        try:
            if accion == "reabrir":
                servicios.reabrir(seguimiento, actor=request.user, **formulario.cleaned_data)
            elif accion == "hitos":
                servicios.actualizar_hitos(seguimiento, actor=request.user, **formulario.cleaned_data)
            else:
                raise Http404
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
    else:
        messages.error(request, "Indique motivo y revisión actual.")
    return redirect("seguimientos:detalle", pk=pk)


@rol_requerido(*ROLES_ADMIN)
@require_POST
def mover_linea(request, pk, linea_pk, accion):
    seguimiento = _obtener(request, pk)
    formulario = forms.ConRevision(request.POST)
    if formulario.is_valid():
        try:
            servicios.mover_linea(seguimiento, linea_id=linea_pk, accion=accion, actor=request.user, **formulario.cleaned_data)
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
    else:
        messages.error(request, "Indique motivo y revisión actual.")
    return redirect("seguimientos:detalle", pk=pk)


@rol_requerido(*ROLES_ADMIN)
@never_cache
@require_http_methods(["GET", "POST"])
def catalogo(request, clase, pk=None):
    clases = {"tipos": forms.CatalogoTipo, "eventos": forms.CatalogoEvento, "resultados": forms.CatalogoResultado, "hitos": forms.CatalogoHito}
    if clase not in clases:
        raise Http404
    formulario_clase = clases[clase]
    modelo = formulario_clase._meta.model
    registro = get_object_or_404(modelo, pk=pk) if pk else modelo()
    formulario = formulario_clase(request.POST if request.method == "POST" else None, instance=registro)
    if request.method == "POST" and formulario.is_valid():
        try:
            servicios.guardar_catalogo(formulario.instance, actor=request.user, motivo=formulario.cleaned_data["motivo"])
        except ValidationError as error:
            agregar_errores(formulario, error)
        else:
            return redirect("seguimientos:catalogo", clase=clase)
    return render(request, "seguimientos/catalogo.html", {"clase": clase, "registros": modelo.objects.all(), "formulario": formulario})
