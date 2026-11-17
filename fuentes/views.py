from hashlib import sha256
import re

from django.core.paginator import Paginator
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET

from cuentas.models import ROLES_ADMIN
from cuentas.permisos import rol_requerido
from compras.models import ContadorOrdenCompra, OrdenCompra
from fuentes.models import CompraHistorica, ElegibleHistorico, FormatoInstitucional, SerieArea


@rol_requerido(*ROLES_ADMIN)
@require_GET
def inicio(request):
    return render(request, "fuentes/inicio.html", {"formatos": FormatoInstitucional.objects.defer("contenido"),
        "historicas": CompraHistorica.objects.count(), "elegibles": ElegibleHistorico.objects.count(),
        "series": SerieArea.objects.count()})


@rol_requerido(*ROLES_ADMIN)
@require_GET
def descargar(request, pk):
    fuente = get_object_or_404(FormatoInstitucional.objects.defer("contenido"), pk=pk)
    try:
        archivo = fuente.archivo.open("rb")
        if sha256(archivo.read()).hexdigest() != fuente.sha256:
            archivo.close()
            raise Http404("El archivo no coincide con la fuente conservada.")
        archivo.seek(0)
    except (OSError, ValueError):
        raise Http404("No se encontró la copia institucional.") from None
    respuesta = FileResponse(archivo, as_attachment=True, filename=fuente.nombre_original,
                             content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    respuesta["Cache-Control"] = "private, no-store"
    respuesta["X-Content-Type-Options"] = "nosniff"
    return respuesta


@rol_requerido(*ROLES_ADMIN)
@require_GET
def detalle(request, pk):
    fuente = get_object_or_404(FormatoInstitucional, pk=pk)
    hojas = fuente.contenido
    nombre = request.GET.get("hoja", hojas[0]["nombre"] if hojas else "")
    hoja = next((h for h in hojas if h["nombre"] == nombre), None)
    if hoja is None:
        raise Http404("La hoja no pertenece al archivo.")
    busqueda = request.GET.get("q", "").strip()[:200]
    filas = {}
    for celda, valor in hoja["celdas"].items():
        numero = int(re.search(r"\d+", celda)[0])
        filas.setdefault(numero, []).append({"celda": celda, "valor": valor})
    registros = [{"numero": numero, "celdas": valores} for numero, valores in sorted(filas.items())
                 if not busqueda or any(busqueda.casefold() in v["valor"].casefold() for v in valores)]
    pagina = Paginator(registros, 20).get_page(request.GET.get("pagina"))
    return render(request, "fuentes/detalle.html", {"fuente": fuente, "hojas": hojas, "nombre_hoja": nombre,
        "pagina": pagina, "busqueda": busqueda})


@rol_requerido(*ROLES_ADMIN)
@require_GET
def historico(request):
    q = request.GET.get("q", "").strip()[:200]
    consulta = CompraHistorica.objects.select_related("fuente").defer("fuente__contenido")
    if q:
        consulta = consulta.filter(Q(orden_original__icontains=q) | Q(proveedor_original__icontains=q) | Q(objeto__icontains=q))
    hoja = request.GET.get("hoja", "")
    if hoja:
        consulta = consulta.filter(hoja=hoja)
    return render(request, "fuentes/historico.html", {"pagina": Paginator(consulta, 30).get_page(request.GET.get("pagina")),
        "busqueda": q, "hoja": hoja, "hojas": CompraHistorica.objects.values_list("hoja", flat=True).distinct().order_by("hoja")})


@rol_requerido(*ROLES_ADMIN)
@require_GET
def consecutivos(request):
    consulta = SerieArea.objects.select_related("area", "fuente").defer("fuente__contenido")
    busqueda = request.GET.get("q", "").strip()[:100]
    if busqueda:
        consulta = consulta.filter(Q(codigo__icontains=busqueda) | Q(area__nombre__icontains=busqueda))
    contadores = dict(ContadorOrdenCompra.objects.values_list("clave", "ultimo"))
    series = list(consulta)
    for serie in series:
        serie.ultimo_actual = max(serie.ultimo_historico, contadores.get(serie.clave_contador, 0))
        serie.siguiente = serie.formatear(serie.ultimo_actual + 1)
    emitidas = OrdenCompra.objects.exclude(consecutivo__isnull=True).select_related("cotizacion__area", "emitida_por").order_by("-fecha_emision")[:30]
    return render(request, "fuentes/consecutivos.html", {"series": series, "busqueda": busqueda, "emitidas": emitidas})


@rol_requerido(*ROLES_ADMIN)
@require_GET
def elegibles(request):
    consulta = ElegibleHistorico.objects.select_related("fuente").defer("fuente__contenido")
    q = request.GET.get("q", "").strip()[:200]
    if q:
        consulta = consulta.filter(Q(proveedor__icontains=q) | Q(area_original__icontains=q) | Q(observaciones__icontains=q))
    return render(request, "fuentes/elegibles.html", {"pagina": Paginator(consulta, 30).get_page(request.GET.get("pagina")), "busqueda": q})
