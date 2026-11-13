from django import forms

from configuracion.forms import ConMotivo
from portal.forms import FormularioEnvio
from proveedores.models import EnvioProveedor, Proveedor, TipoDocumento


class FiltroEnvios(forms.Form):
    q = forms.CharField(label="Buscar proveedor por NIT o nombre", required=False, max_length=200)
    proveedor = forms.ModelChoiceField(label="Proveedor", queryset=Proveedor.objects.all(), required=False, empty_label="Todos los proveedores")
    tipo = forms.ModelChoiceField(label="Tipo de documento", queryset=TipoDocumento.objects.all(), required=False, empty_label="Todos los tipos")
    estado = forms.ChoiceField(label="Estado", required=False, choices=[("", "Todos los estados"), *EnvioProveedor.Estado.choices])
    desde = forms.DateField(label="Enviado desde", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    hasta = forms.DateField(label="Enviado hasta", required=False, widget=forms.DateInput(attrs={"type": "date"}))

    def clean(self):
        datos = super().clean()
        if datos.get("desde") and datos.get("hasta") and datos["desde"] > datos["hasta"]:
            raise forms.ValidationError("La fecha inicial no puede ser posterior a la final.")
        return datos


class FormularioEnvioManual(ConMotivo, FormularioEnvio):
    proveedor = forms.ModelChoiceField(label="Proveedor", queryset=Proveedor.objects.exclude(estado=Proveedor.Estado.INACTIVO))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.order_fields(["proveedor", "tipo", "fecha_expedicion", "fecha_vencimiento", "archivo_pdf", "motivo"])
