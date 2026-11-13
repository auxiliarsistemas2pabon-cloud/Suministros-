from decimal import Decimal

from django import forms
from django.core import signing
from django.utils import timezone

from compras.models import Necesidad, OrigenNecesidad, TipoCotizacion
from configuracion.forms import ConMotivo
from proveedores.models import Proveedor
from proyecciones.models import UnidadMedida


class SeleccionNecesidad(forms.Form):
    necesidad = forms.ModelChoiceField(label="Precargar necesidad", queryset=Necesidad.objects.filter(estado="abierta", area__activa=True), required=False,
        widget=forms.Select(attrs={"id": "seleccion_necesidad"}))


class FormularioCotizacion(ConMotivo, forms.Form):
    necesidad = forms.ModelChoiceField(label="Necesidad de origen", queryset=Necesidad.objects.filter(estado="abierta", area__activa=True))
    objeto = forms.CharField(label="Objeto", widget=forms.Textarea)
    fecha = forms.DateField(label="Fecha", initial=timezone.localdate, widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    tipo = forms.ModelChoiceField(label="Tipo de cotización", queryset=TipoCotizacion.objects.filter(activo=True))
    invitados = forms.ModelMultipleChoiceField(label="Proveedores invitados (opcional)", queryset=Proveedor.objects.exclude(estado="inactivo"), required=False)
    revision_origen = forms.CharField(widget=forms.HiddenInput, required=False)

    def __init__(self, *args, lista=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.identidad = None
        if lista:
            self.fields["necesidad"].disabled = True
            del self.fields["invitados"]
            cierre = lista.cierres.first()
            self.identidad = {"lista": lista.pk, "cierre": cierre.pk if cierre else None}
            self.fields["revision_origen"].required = True
            self.fields["revision_origen"].initial = signing.dumps(self.identidad, salt="cotizacion-origen")

    def clean(self):
        datos = super().clean()
        if self.identidad:
            try:
                if signing.loads(datos.get("revision_origen", ""), salt="cotizacion-origen") != self.identidad:
                    raise signing.BadSignature()
            except signing.BadSignature:
                raise forms.ValidationError("El cierre de origen cambió. Recargue la precarga antes de guardar.") from None
        return datos


class FormularioLineaCotizacion(forms.Form):
    descripcion = forms.CharField(label="Descripción", max_length=255)
    unidad = forms.ModelChoiceField(label="Unidad", queryset=UnidadMedida.objects.filter(activa=True))
    cantidad = forms.DecimalField(label="Cantidad", max_digits=14, decimal_places=3, min_value=Decimal("0.001"))
    especificacion = forms.CharField(label="Especificación técnica", required=False, widget=forms.Textarea(attrs={"rows": 2}))
    origen = forms.ModelChoiceField(label="Línea de la necesidad (opcional)", queryset=OrigenNecesidad.objects.none(), required=False)

    def __init__(self, *args, origenes, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["origen"].queryset = origenes
        self.fields["origen"].label_from_instance = lambda o: f"{o.datos_origen['producto']} · {o.datos_origen['unidad']} · {o.datos_origen['periodo']}"


def formulario_lineas(*args, limite, origenes, **kwargs):
    clase = forms.formset_factory(FormularioLineaCotizacion, extra=1, can_delete=True,
        max_num=limite or 1000, validate_max=bool(limite), absolute_max=max(2000, limite))
    return clase(*args, prefix="lineas", form_kwargs={"origenes": origenes}, **kwargs)


class FormularioTipoCotizacion(ConMotivo, forms.ModelForm):
    class Meta:
        model = TipoCotizacion
        fields = ["nombre", "descripcion", "activo"]
