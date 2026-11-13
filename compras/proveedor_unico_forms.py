from django import forms

from compras.models import CausalProveedorUnico
from configuracion.forms import ConMotivo
from proveedores.archivos import validar_pdf


class FormularioCausal(ConMotivo, forms.ModelForm):
    class Meta:
        model = CausalProveedorUnico
        fields = ["nombre", "descripcion", "orden", "activo"]


class FormularioCaso(ConMotivo, forms.Form):
    proveedor_unico = forms.BooleanField(label="Confirmar caso de proveedor único", required=False)
    causal = forms.ModelChoiceField(label="Causal", queryset=CausalProveedorUnico.objects.filter(activo=True), required=False)
    justificacion = forms.CharField(label="Especificación y justificación del caso", required=False, widget=forms.Textarea)
    archivo = forms.FileField(label="Evidencia PDF (máximo 10 MB)", required=False, validators=[validar_pdf])
    quitar_pdf = forms.BooleanField(label="Retirar evidencia actual (se conserva en el historial)", required=False)
    revision_esperada = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
