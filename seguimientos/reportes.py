"""Un mismo filtro y los mismos agregados para pantalla y Excel."""
from decimal import Decimal
from io import BytesIO
from django.db.models import Q, Sum, Count, F, Value, DecimalField, OuterRef, Subquery, Case, When
from django.db.models.functions import Coalesce
from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from compras.models import OrdenLinea, RecepcionLinea
from seguimientos.models import Seguimiento
from seguimientos.servicios import alcance, tablero


def consulta(filtros, actor, hoy=None):
    hoy = hoy or timezone.localdate()
    registros = alcance(Seguimiento.objects.select_related("orden", "contrato", "area", "tipo"), actor)
    if filtros.get("periodo"):
        registros = registros.filter(fecha__year=filtros["periodo"])
    if filtros.get("desde"):
        registros = registros.filter(fecha__date__gte=filtros["desde"])
    if filtros.get("hasta"):
        registros = registros.filter(fecha__date__lte=filtros["hasta"])
    if filtros.get("area"):
        registros = registros.filter(area=filtros["area"])
    if filtros.get("tipo"):
        registros = registros.filter(tipo=filtros["tipo"])
    if filtros.get("categoria"):
        registros = registros.filter(proveedor__categoria=filtros["categoria"])
    if filtros.get("consecutivo"):
        registros = registros.filter(orden__consecutivo__icontains=filtros["consecutivo"])
    if filtros.get("proveedor"):
        from proveedores.nit import digitos_para_buscar
        texto = filtros["proveedor"]
        condicion = Q(razon_social__icontains=texto)
        nit = digitos_para_buscar(texto)
        if nit:
            condicion |= Q(nit__contains=nit)
        registros = registros.filter(condicion)
    filas = [{"seguimiento": s, **tablero(s, hoy=hoy)} for s in registros]
    if filtros.get("estado"):
        filas = [f for f in filas if f["estado"] == filtros["estado"]]
    ids = [f["seguimiento"].pk for f in filas]
    totales = registros.filter(pk__in=ids).aggregate(cantidad=Count("pk"),
        valor=Coalesce(Sum("valor"), Value(Decimal(0)), output_field=DecimalField(max_digits=38, decimal_places=2)),
        valor_ordenes=Coalesce(Sum("orden__total"), Value(Decimal(0)), output_field=DecimalField(max_digits=38, decimal_places=2)))
    decimales = DecimalField(max_digits=38, decimal_places=3)
    def acumulado(campo):
        suma = RecepcionLinea.objects.filter(linea_id=OuterRef("pk")).values("linea_id").annotate(valor=Sum(campo)).values("valor")[:1]
        return Coalesce(Subquery(suma, output_field=decimales), Value(Decimal(0)), output_field=decimales)
    lineas = OrdenLinea.objects.filter(orden__seguimiento__pk__in=ids).annotate(aceptado=acumulado("cantidad"), rechazado=acumulado("rechazada"), devuelto=acumulado("devuelta"))
    cantidades = list(lineas.values("unidad").annotate(ordenado=Sum("cantidad"), recibido=Sum("aceptado"), rechazado_total=Sum("rechazado"), devuelto_total=Sum("devuelto"),
        pendiente=Sum(Case(When(aceptado__lt=F("cantidad"), then=F("cantidad")-F("aceptado")), default=Value(Decimal(0)), output_field=decimales))).order_by("unidad"))
    return {"filas": filas, "totales": totales, "cantidades": cantidades}


def exportar(datos):
    libro = Workbook()
    hoja = libro.active
    hoja.title = "Seguimientos"
    hoja.append(["ID", "Fecha de apertura", "Área", "NIT", "Proveedor", "Tipo", "Estado", "Valor", "Orden", "Contrato"])
    for fila in datos["filas"]:
        s = fila["seguimiento"]
        hoja.append([s.pk, timezone.localtime(s.fecha).replace(tzinfo=None), s.area.nombre, s.nit, s.razon_social,
            s.tipo_nombre, fila["estado_texto"], s.valor, s.orden.consecutivo if s.orden_id else "", s.contrato.numero if s.contrato_id else ""])
    hoja.append(["TOTAL", datos["totales"]["cantidad"], "", "", "", "", "", datos["totales"]["valor"]])
    hoja.append(["ÓRDENES INCLUIDAS", "", "", "", "", "", "", datos["totales"]["valor_ordenes"]])
    cantidades = libro.create_sheet("Cantidades por unidad")
    cantidades.append(["Unidad", "Ordenado", "Aceptado", "Rechazado", "Devuelto", "Pendiente"])
    for fila in datos["cantidades"]:
        cantidades.append([fila[k] for k in ("unidad", "ordenado", "recibido", "rechazado_total", "devuelto_total", "pendiente")])
    for tabla in libro:
        tabla.freeze_panes = "A2"
        tabla.auto_filter.ref = tabla.dimensions
        for celda in tabla[1]:
            celda.fill, celda.font = PatternFill("solid", fgColor="172554"), Font(color="FFFFFF", bold=True)
        for fila in tabla.iter_rows(min_row=2):
            for celda in fila:
                if isinstance(celda.value, str):
                    celda.data_type = "s"
                celda.alignment = Alignment(vertical="top", wrap_text=True)
        for columna in tabla.columns:
            tabla.column_dimensions[columna[0].column_letter].width = 23
    for celda in hoja["H"][1:]:
        celda.number_format = '#,##0.00'
    salida = BytesIO()
    libro.save(salida)
    return salida.getvalue()
