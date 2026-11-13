from django.core.paginator import Paginator
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe
from cuentas.models import ROLES_ADMIN
from cuentas.permisos import rol_requerido
from config import listados
from proveedores.models import Proveedor
from proveedores.servicios import buscar
from compras.models import OrdenCompra, Cotizacion
from django.db.models import Q

CLASES = ("proyecciones", "proveedores", "evaluaciones", "necesidades", "elegibles", "cotizaciones", "ordenes", "seguimientos")


@rol_requerido(*ROLES_ADMIN)
@never_cache
@require_safe
def listado(request, clase):
    if clase not in CLASES:
        raise Http404
    filtro, consulta = listados.preparar(clase, request.GET, request.user)
    if request.GET.get("formato") == "excel":
        if not filtro.is_valid():
            return HttpResponse("Corrija los filtros.", status=400)
        return listados.excel(consulta, clase)
    pagina = Paginator(consulta, 25).get_page(request.GET.get("pagina"))
    if clase == "seguimientos":
        from seguimientos.servicios import tablero
        estado = lambda o: tablero(o)["estado_texto"]
    else:
        estado = lambda o: o.get_estado_display() if hasattr(o, "get_estado_display") else getattr(o, "estado", "")
    filas = [{"objeto": o, "url": reverse(listados.especificaciones(clase)["detalle"], args=[o.pk]), "estado": estado(o)} for o in pagina]
    parametros = request.GET.copy()
    parametros["formato"] = "excel"
    return render(request, "configuracion/listado_global.html", {"clase": clase, "clases": CLASES, "filtro": filtro, "pagina": pagina, "filas": filas, "url_excel": "?"+parametros.urlencode()})


@rol_requerido(*ROLES_ADMIN)
@never_cache
@require_safe
def global_(request):
    texto = request.GET.get("q", "").strip()[:200]
    resultados = []
    if texto:
        proveedores = buscar(Proveedor.objects.all(), texto)[:25]
        resultados.extend({"tipo": "Proveedor", "texto": f'{p.razon_social} · {p.nit_formateado}', "url": reverse("proveedores:detalle", args=[p.pk])} for p in proveedores)
        for clase in ("ordenes", "cotizaciones"):
            especificacion = listados.especificaciones(clase)
            condicion = Q(consecutivo__icontains=texto)
            from proveedores.nit import digitos_para_buscar
            nit = digitos_para_buscar(texto)
            if nit:
                campo = "nit" if clase == "ordenes" else "ofertas__nit"
                condicion |= Q(**{campo+"__contains": nit})
            objetos = listados.aplicar_alcance(especificacion["modelo"].objects.all(), request.user, especificacion["area"]).filter(condicion).distinct()[:25]
            resultados.extend({"tipo": clase.capitalize(), "texto": str(o), "url": reverse(especificacion["detalle"], args=[o.pk])} for o in objetos)
    return render(request, "configuracion/busqueda.html", {"q": texto, "resultados": resultados})
