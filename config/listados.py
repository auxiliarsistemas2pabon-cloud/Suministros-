"""Filtros compartidos. Siempre aplica alcance antes de parámetros del usuario."""
from io import BytesIO
from datetime import date, datetime
from django import forms
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import HttpResponse
from django.utils import timezone
from areas.models import Area
from proveedores.models import CategoriaProveedor
from proveedores.nit import digitos_para_buscar
from cuentas.models import Rol
from cuentas.permisos import es_admin


def especificaciones(clase):
    from compras.models import OrdenCompra, Cotizacion, ListaElegibles, Necesidad
    from proveedores.models import Proveedor, EvaluacionProveedor
    from proyecciones.models import ProyeccionArea
    from seguimientos.models import Seguimiento
    datos = {
        "ordenes": dict(modelo=OrdenCompra, fecha="fecha_elaboracion", area="cotizacion__area_id", categoria="proveedor__categoria_id", textos=["razon_social", "nit"], nits=["nit"], consecutivo="consecutivo", detalle="compras:orden_detalle"),
        "cotizaciones": dict(modelo=Cotizacion, fecha="fecha", area="area_id", categoria="ofertas__proveedor__categoria_id", textos=["objeto", "ofertas__razon_social"], nits=["ofertas__nit"], consecutivo="consecutivo", detalle="compras:cotizacion_detalle"),
        "necesidades": dict(modelo=Necesidad, fecha="fecha", area="area_id", categoria="listas__participantes__proveedor__categoria_id", textos=["objeto", "listas__participantes__razon_social"], nits=["listas__participantes__nit"], consecutivo="pk", detalle="compras:necesidad_detalle"),
        "elegibles": dict(modelo=ListaElegibles, fecha="fecha", area="necesidad__area_id", categoria="participantes__proveedor__categoria_id", textos=["necesidad__objeto", "participantes__razon_social"], nits=["participantes__nit"], consecutivo="pk", detalle="compras:lista_detalle"),
        "proveedores": dict(modelo=Proveedor, fecha="fecha_creacion", area=None, categoria="categoria_id", textos=["razon_social"], nits=["nit"], consecutivo=None, detalle="proveedores:detalle"),
        "evaluaciones": dict(modelo=EvaluacionProveedor, fecha="fecha", area=None, categoria="categoria_id", textos=["proveedor__razon_social"], nits=["proveedor__nit"], consecutivo="pk", detalle="proveedores:evaluacion_detalle"),
        "proyecciones": dict(modelo=ProyeccionArea, fecha=None, area="area_id", categoria=None, textos=["area__nombre"], nits=[], consecutivo="pk", detalle="proyecciones:revision_detalle"),
        "seguimientos": dict(modelo=Seguimiento, fecha="fecha", area="area_id", categoria="proveedor__categoria_id", textos=["razon_social", "objeto"], nits=["nit"], consecutivo="orden__consecutivo", detalle="seguimientos:detalle"),
    }
    return datos[clase]


def aplicar_alcance(consulta, actor, campo_area=None):
    if es_admin(actor):
        return consulta
    if (campo_area and getattr(actor, "is_authenticated", False) and actor.is_active and actor.rol == Rol.COORDINADOR):
        return consulta.filter(**{campo_area: actor.area_id})
    raise PermissionDenied


class FiltroListado(forms.Form):
    periodo = forms.IntegerField(label="Año / periodo", min_value=1, max_value=9999, required=False)
    area = forms.ModelChoiceField(label="Área", queryset=Area.objects.all(), required=False)
    categoria = forms.ModelChoiceField(label="Categoría", queryset=CategoriaProveedor.objects.all(), required=False)
    q = forms.CharField(label="NIT, proveedor o texto", max_length=200, required=False)
    estado = forms.CharField(label="Estado", max_length=30, required=False)
    consecutivo = forms.CharField(label="Consecutivo / folio", max_length=100, required=False)

    def __init__(self, *args, especificacion, actor, **kwargs):
        super().__init__(*args, **kwargs)
        for campo in ("area", "categoria", "consecutivo"):
            if not especificacion[campo]:
                self.fields.pop(campo)
        if "area" in self.fields and not es_admin(actor):
            self.fields["area"].queryset = Area.objects.filter(pk=actor.area_id)
        if especificacion["modelo"].__name__ == "Seguimiento":
            from seguimientos.estados import ESTADOS
            self.fields["estado"] = forms.ChoiceField(label="Estado", choices=[("", "Todos"), *ESTADOS], required=False)
        else:
            campo = especificacion["modelo"]._meta.get_field("estado")
            opciones = list(campo.choices or [])
            if not opciones:
                opciones = [(v, v.replace("_", " ").capitalize()) for v in ("borrador", "cerrada", "anulada")] if especificacion["modelo"].__name__ == "ListaElegibles" else [(v, v.capitalize()) for v in ("abierta", "cerrada", "anulada")] if especificacion["modelo"].__name__ == "Necesidad" else [(v, v.capitalize()) for v in ("borrador", "finalizada", "anulada")]
            self.fields["estado"] = forms.ChoiceField(label="Estado", choices=[("", "Todos"), *opciones], required=False)


def preparar(clase, parametros, actor):
    especificacion = especificaciones(clase)
    consulta = aplicar_alcance(especificacion["modelo"].objects.all(), actor, especificacion["area"])
    filtro = FiltroListado(parametros, especificacion=especificacion, actor=actor)
    if not filtro.is_valid():
        return filtro, consulta.none()
    datos = filtro.cleaned_data
    if datos.get("periodo"):
        campo = f'{especificacion["fecha"]}__year' if especificacion["fecha"] else "periodo__anio"
        consulta = consulta.filter(**{campo: datos["periodo"]})
    for campo in ("area", "categoria", "estado"):
        if datos.get(campo):
            if campo == "estado" and clase == "seguimientos":
                continue
            ruta = "estado" if campo == "estado" else especificacion[campo]
            valor = datos[campo].pk if hasattr(datos[campo], "pk") else datos[campo]
            consulta = consulta.filter(**{ruta: valor})
    if datos.get("consecutivo"):
        campo, texto = especificacion["consecutivo"], datos["consecutivo"].strip()
        if campo == "pk":
            consulta = consulta.filter(pk=int(texto)) if texto.isdigit() else consulta.none()
        else:
            consulta = consulta.filter(**{campo+"__icontains": texto})
    if datos.get("q"):
        condicion = Q()
        texto = datos["q"].strip()
        for campo in especificacion["textos"]:
            condicion |= Q(**{campo+"__icontains": texto})
        nit = digitos_para_buscar(texto)
        if nit:
            for campo in especificacion["nits"]:
                condicion |= Q(**{campo+"__contains": nit})
        consulta = consulta.filter(condicion)
    consulta = consulta.distinct()
    if clase == "seguimientos" and datos.get("estado"):
        from seguimientos.servicios import tablero
        ids = [s.pk for s in consulta if tablero(s)["estado"] == datos["estado"]]
        consulta = consulta.filter(pk__in=ids)
    return filtro, consulta


def excel(consulta, titulo):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    libro = Workbook()
    hoja = libro.active
    hoja.title = "Resultados"
    campos = [f for f in consulta.model._meta.fields if f.name not in ("password", "archivo") and f.get_internal_type() not in ("JSONField", "FileField")]
    seguimiento = consulta.model._meta.label_lower == "seguimientos.seguimiento"
    hoja.append([str(f.verbose_name) for f in campos]+(["Estado operativo"] if seguimiento else []))
    for objeto in consulta.iterator():
        fila = []
        for campo in campos:
            valor = getattr(objeto, campo.name)
            if campo.is_relation:
                valor = str(valor) if valor is not None else ""
            if isinstance(valor, datetime) and timezone.is_aware(valor):
                valor = timezone.localtime(valor).replace(tzinfo=None)
            fila.append(valor)
        if seguimiento:
            from seguimientos.servicios import tablero
            fila.append(tablero(objeto)["estado_texto"])
        hoja.append(fila)
        for celda in hoja[hoja.max_row]:
            if isinstance(celda.value, str):
                celda.data_type = "s"
    for celda in hoja[1]:
        celda.fill, celda.font = PatternFill("solid", fgColor="172554"), Font(color="FFFFFF", bold=True)
    hoja.freeze_panes = "A2"
    hoja.auto_filter.ref = hoja.dimensions
    for columna in hoja.columns:
        hoja.column_dimensions[columna[0].column_letter].width = 24
    salida = BytesIO()
    libro.save(salida)
    respuesta = HttpResponse(salida.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    respuesta["Content-Disposition"] = f'attachment; filename="{titulo}.xlsx"'
    respuesta["Cache-Control"] = "private, no-store"
    return respuesta
