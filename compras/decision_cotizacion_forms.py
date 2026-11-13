from django import forms
from django.core import signing

from compras.comparativo import huella
from configuracion.forms import ConMotivo


class FormularioDecision(ConMotivo, forms.Form):
    modalidad = forms.ChoiceField(label="Modalidad de adjudicación", choices=[("completa", "Oferta completa"), ("lineas", "Por línea")])
    oferta_id = forms.TypedChoiceField(label="Oferente para la oferta completa", coerce=int, empty_value=None, required=False)
    recomendacion = forms.CharField(label="Recomendación de compra", widget=forms.Textarea)
    motivo_eleccion = forms.CharField(label="Justificación de elección más costosa (si corresponde)", widget=forms.Textarea, required=False)
    justificacion_verificaciones = forms.CharField(label="Justificación de alertas de verificaciones (si corresponde)", widget=forms.Textarea, required=False)
    firma = forms.CharField(widget=forms.HiddenInput)

    def __init__(self, *args, datos, **kwargs):
        super().__init__(*args, **kwargs)
        self.identidad = {"cotizacion": datos["cotizacion_id"], "huella": huella(datos)}
        opciones = [("", "Seleccione un oferente")] + [(o["id"], f"{o['razon_social']} · NIT {o['nit']}") for o in datos["ofertas"]]
        self.fields["oferta_id"].choices = opciones
        for fila in datos["filas"]:
            self.fields[f"seleccion_{fila['id']}"] = forms.TypedChoiceField(label=f"Línea {fila['orden']}: {fila['descripcion']}", choices=opciones, coerce=int, empty_value=None, required=False)
        self.fields["firma"].initial = signing.dumps(self.identidad, salt="decision-cotizacion")

    def clean(self):
        datos = super().clean()
        try:
            if signing.loads(datos.get("firma", ""), salt="decision-cotizacion") != self.identidad:
                raise signing.BadSignature()
        except signing.BadSignature:
            raise forms.ValidationError("Cambió el comparativo o la firma no es válida. Recargue y revise antes de proponer.") from None
        return datos


class FormularioAccion(ConMotivo, forms.Form):
    pass
