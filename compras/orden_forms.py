from decimal import Decimal

from django import forms
from django.utils import timezone

from configuracion.forms import ConMotivo
from compras.orden_servicios import etiqueta_validez
from compras.models import TarifaImpuesto, TipoRetencion
from django.db.models import Q


class FormularioCrearOrden(ConMotivo, forms.Form):
    fecha_elaboracion = forms.DateField(label="Fecha de elaboración", initial=timezone.localdate, widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    condiciones_pago = forms.CharField(label="Condiciones de pago", required=False, widget=forms.Textarea)
    fecha_vencimiento = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    fecha_esperada_entrega = forms.DateField(label="Fecha esperada de entrega", required=False, widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["fecha_vencimiento"].label = etiqueta_validez()


class FormularioOrden(FormularioCrearOrden):
    revision_esperada = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
    retenciones = forms.ModelMultipleChoiceField(label="Retenciones de la orden", queryset=TipoRetencion.objects.none(), required=False)
    actualizar_reglas = forms.BooleanField(label="Aplicar parámetros actuales de importes y actualizar las retenciones seleccionadas", required=False,
        help_text="Si no marca esta opción, conserva las reglas y porcentajes ya guardados. Una retención nueva utiliza el catálogo actual.")

    def __init__(self, *args, orden=None, **kwargs):
        super().__init__(*args, **kwargs)
        guardadas = {r["id"]: r for r in orden.retenciones_aplicadas} if orden else {}
        self.fields["retenciones"].queryset = TipoRetencion.objects.filter(Q(activo=True) | Q(pk__in=guardadas))
        self.fields["retenciones"].label_from_instance = lambda r: f'{guardadas[r.pk]["nombre"]} · {guardadas[r.pk]["porcentaje"]} % (guardada)' if r.pk in guardadas else str(r)
        self.initial.setdefault("retenciones", list(guardadas))

    def clean_retenciones(self):
        return list(self.cleaned_data["retenciones"].values_list("pk", flat=True))


class FormularioAnularOrden(ConMotivo, forms.Form):
    revision_esperada = forms.IntegerField(min_value=1, widget=forms.HiddenInput)


class FormularioOrdenLinea(forms.Form):
    id = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
    referencia = forms.CharField(label="Referencia", max_length=120, required=False)
    descripcion = forms.CharField(label="Descripción", max_length=255)
    especificacion = forms.CharField(label="Especificación", required=False, widget=forms.Textarea(attrs={"rows": 2}))
    unidad = forms.CharField(label="Unidad", max_length=120)
    cantidad = forms.DecimalField(label="Cantidad", max_digits=14, decimal_places=3, min_value=Decimal("0.001"))
    precio_unitario = forms.DecimalField(label="Precio unitario", max_digits=18, decimal_places=4, min_value=Decimal(0))
    descuento = forms.DecimalField(label="Descuento en dinero (antes del redondeo)", max_digits=32, decimal_places=2, min_value=Decimal(0), required=False)
    tarifa_id = forms.ModelChoiceField(label="Cambiar tarifa", queryset=TarifaImpuesto.objects.filter(activo=True), required=False, empty_label="Conservar tarifa guardada")

    def clean_descuento(self):
        return self.cleaned_data["descuento"] or Decimal(0)

    def clean_tarifa_id(self):
        tarifa = self.cleaned_data["tarifa_id"]
        return tarifa.pk if tarifa else None


class FormularioRetencion(ConMotivo, forms.ModelForm):
    class Meta:
        model = TipoRetencion
        fields = ["nombre", "porcentaje", "base_minima", "base_calculo", "activo"]


class FormularioEnvioOrden(ConMotivo, forms.Form):
    fecha_envio = forms.DateTimeField(label="Fecha y hora de envío", initial=timezone.now, widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"))
    archivo = forms.FileField(label="Soporte PDF opcional (máximo 10 MB)", required=False)
    corrige_id = forms.IntegerField(label="ID de evidencia que corrige", min_value=1, required=False)


class FormularioReglaAprobacion(ConMotivo, forms.ModelForm):
    class Meta:
        from compras.models import ReglaAprobacionOrden
        model = ReglaAprobacionOrden
        fields = ["nombre", "monto_desde", "monto_hasta", "categoria", "aprobaciones", "activo"]


class FormularioRecepcion(ConMotivo, forms.Form):
    fecha = forms.DateField(initial=timezone.localdate, widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    tipo = forms.ChoiceField(choices=[("recepcion", "Recepción"), ("ajuste", "Ajuste con cantidades firmadas"), ("devolucion", "Devolución de cantidades aceptadas")])
    ajusta_id = forms.ModelChoiceField(label="Recepción que corrige", queryset=TipoRetencion.objects.none(), required=False)
    autorizar_exceso = forms.BooleanField(label="Autorizar exceso de recepción (requiere parámetro habilitado y rol administrador)", required=False)
    archivo = forms.FileField(label="Soporte PDF opcional (máximo 10 MB)", required=False)
    revision_esperada = forms.IntegerField(min_value=1, widget=forms.HiddenInput)

    def __init__(self, *args, orden, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["ajusta_id"].queryset = orden.recepciones.all()
        self.fields["ajusta_id"].label_from_instance = lambda r: f'{r.pk} · {r.fecha} · {r.get_tipo_display()}'

    def clean_ajusta_id(self):
        registro = self.cleaned_data["ajusta_id"]
        return registro.pk if registro else None


class FormularioRecepcionLinea(forms.Form):
    id = forms.IntegerField(widget=forms.HiddenInput)
    cantidad = forms.DecimalField(label="Cantidad aceptada (negativa solo en ajuste)", max_digits=18, decimal_places=3, required=False)
    rechazada = forms.DecimalField(label="Cantidad rechazada (negativa solo en ajuste)", max_digits=18, decimal_places=3, required=False)
    devuelta = forms.DecimalField(label="Cantidad devuelta (positiva en devolución; su ajuste requiere cantidad aceptada opuesta)", max_digits=18, decimal_places=3, required=False)
    observacion = forms.CharField(label="Observación de la línea", required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def clean(self):
        datos = super().clean()
        for campo in ("cantidad", "rechazada", "devuelta"):
            datos[campo] = datos.get(campo) or Decimal(0)
        return datos


def formulario_recepcion_lineas(*args, inicial, **kwargs):
    clase = forms.formset_factory(FormularioRecepcionLinea, extra=0, min_num=len(inicial), max_num=len(inicial), validate_min=True, validate_max=True,
        absolute_max=max(2000, len(inicial)))
    return clase(*args, prefix="lineas", initial=inicial, **kwargs)


def formulario_lineas(*args, inicial, **kwargs):
    clase = forms.formset_factory(FormularioOrdenLinea, extra=0, max_num=len(inicial), validate_max=True,
        min_num=len(inicial), validate_min=True, absolute_max=max(2000, len(inicial)))
    return clase(*args, prefix="lineas", initial=inicial, **kwargs)
