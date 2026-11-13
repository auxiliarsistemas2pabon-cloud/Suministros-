from django import forms
from django.utils import timezone

from compras.models import TarifaImpuesto
from configuracion.forms import ConMotivo
from proveedores.archivos import validar_pdf
from proveedores.models import Proveedor


class FormularioOferta(ConMotivo, forms.Form):
    contacto_nombre = forms.CharField(label="Contacto", max_length=120)
    contacto_correo = forms.EmailField(label="Correo de contacto", max_length=254)
    contacto_telefono = forms.CharField(label="Teléfono de contacto", max_length=50)
    fecha = forms.DateField(label="Fecha de la oferta", initial=timezone.localdate, widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    vigente_hasta = forms.DateField(label="Vigente hasta (opcional)", required=False, widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    observacion = forms.CharField(label="Observación", required=False, widget=forms.Textarea)
    archivo = forms.FileField(label="PDF de la oferta (opcional, máximo 10 MB)", required=False, validators=[validar_pdf])
    quitar_pdf = forms.BooleanField(label="Retirar el PDF actual (las revisiones anteriores lo conservan)", required=False)
    revision_esperada = forms.IntegerField(min_value=0, widget=forms.HiddenInput)


class FormularioPrecio(forms.Form):
    linea = forms.IntegerField(widget=forms.HiddenInput, disabled=True)
    precio_unitario = forms.DecimalField(label="Precio unitario", max_digits=18, decimal_places=4, min_value=0)
    tarifa = forms.ModelChoiceField(label="Tarifa de impuesto", queryset=TarifaImpuesto.objects.filter(activo=True))


def formulario_precios(*args, inicial, **kwargs):
    clase = forms.formset_factory(FormularioPrecio, extra=0, min_num=len(inicial), max_num=len(inicial),
        validate_min=True, validate_max=True, absolute_max=max(2000, len(inicial)))
    return clase(*args, initial=inicial, prefix="precios", **kwargs)


class FormularioTarifa(ConMotivo, forms.ModelForm):
    class Meta:
        model = TarifaImpuesto
        fields = ["nombre", "porcentaje", "activo"]


class FormularioInvitado(ConMotivo, forms.Form):
    proveedor = forms.ModelChoiceField(label="Proveedor registrado", queryset=Proveedor.objects.exclude(estado="inactivo"))

    def __init__(self, *args, cotizacion, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["proveedor"].queryset = self.fields["proveedor"].queryset.exclude(pk__in=cotizacion.invitados.values("proveedor_id"))
