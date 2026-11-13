from django import forms
from django.utils import timezone

from compras.models import EstadoVerificacion, TipoVerificacion
from configuracion.forms import ConMotivo
from proveedores.archivos import validar_pdf


class FormularioTipoVerificacion(ConMotivo, forms.ModelForm):
    class Meta:
        model = TipoVerificacion
        fields = ["nombre", "orden", "obligatoria", "origen", "activo"]
        help_texts = {"obligatoria": "Si está activa y es obligatoria, No, Pendiente o falta de confirmación generan alerta en la matriz."}


class FormularioEstadoVerificacion(ConMotivo, forms.ModelForm):
    class Meta:
        model = EstadoVerificacion
        fields = ["nombre", "clasificacion", "orden", "activo"]
        help_texts = {"clasificacion": "Define el significado del estado y las alertas. Los registros anteriores conservan su clasificación confirmada."}


class FiltroFecha(forms.Form):
    fecha = forms.DateField(label="Fecha documental que desea consultar", initial=timezone.localdate,
        widget=forms.DateInput(attrs={"type": "date", "id": "fecha_consulta"}, format="%Y-%m-%d"))


class FormularioVerificacion(ConMotivo, forms.Form):
    estado = forms.ModelChoiceField(label="Estado confirmado", queryset=EstadoVerificacion.objects.filter(activo=True))
    fecha = forms.DateField(label="Fecha de verificación", initial=timezone.localdate, widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    observacion = forms.CharField(label="Observación", required=False, widget=forms.Textarea)
    confirmar_propuesta = forms.BooleanField(label="Revisé la propuesta documental y confirmo el estado elegido", required=False)
    firma_propuesta = forms.CharField(widget=forms.HiddenInput, required=False)
    archivo = forms.FileField(label="Evidencia PDF (opcional, máximo 10 MB)", required=False, validators=[validar_pdf])
    quitar_pdf = forms.BooleanField(label="Retirar la evidencia actual (se conserva en el historial)", required=False)
    oferta_revision_esperada = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
    revision_esperada = forms.IntegerField(min_value=0, widget=forms.HiddenInput)

    def __init__(self, *args, tipo, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["estado"].label_from_instance = lambda e: f"{e.nombre} · {e.get_clasificacion_display()}"
        if tipo.origen == "documental":
            self.fields["fecha"].disabled = True
            self.fields["firma_propuesta"].required = True
        else:
            del self.fields["confirmar_propuesta"]
            del self.fields["firma_propuesta"]
