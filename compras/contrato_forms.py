from django import forms
from django.db.models import Q
from django.utils import timezone

from compras.models import Contrato, Poliza, TipoPoliza
from configuracion.forms import ConMotivo
from cuentas.models import Usuario
from proveedores.archivos import validar_pdf


class FormularioRequiere(ConMotivo, forms.Form):
    requiere_contrato = forms.BooleanField(label="Esta compra requiere contrato", required=False)
    revision_esperada = forms.IntegerField(min_value=0, widget=forms.HiddenInput)


class EvidenciaContractual(ConMotivo, forms.ModelForm):
    archivo = forms.FileField(label="Evidencia PDF (opcional al guardar borrador, máximo 10 MB)", required=False, validators=[validar_pdf])
    quitar_pdf = forms.BooleanField(label="Retirar evidencia actual (se conserva en el historial)", required=False)
    revision_esperada = forms.IntegerField(min_value=0, widget=forms.HiddenInput)


class FormularioContrato(EvidenciaContractual):
    class Meta:
        model = Contrato
        fields = ["numero", "supervisor", "supervisor_texto", "cargo", "fecha_inicio", "fecha_fin", "forma_pago", "valor"]
        labels = {"supervisor": "Supervisor (usuario)", "supervisor_texto": "Supervisor por texto (alternativa al usuario)", "fecha_fin": "Fin de vigencia"}
        widgets = {"fecha_inicio": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"), "fecha_fin": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["supervisor"].queryset = Usuario.objects.filter(activo=True)


class FormularioPoliza(EvidenciaContractual):
    class Meta:
        model = Poliza
        fields = ["tipo", "aseguradora", "numero", "valor_asegurado", "vigencia_desde", "vigencia_hasta", "activo"]
        labels = {"activo": "Póliza activa (desmarque para retirarla del conjunto actual)"}
        widgets = {"vigencia_desde": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"), "vigencia_hasta": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["tipo"].queryset = TipoPoliza.objects.filter(Q(activo=True) | Q(pk=self.instance.tipo_id))


class FormularioTipoPoliza(ConMotivo, forms.ModelForm):
    class Meta:
        model = TipoPoliza
        fields = ["nombre", "orden", "activo", "dias_alerta"]
        help_texts = {"dias_alerta": "Vacío usa los días generales de alertas documentales. 0 avisa el día del vencimiento."}


class FiltroPolizas(forms.Form):
    fecha = forms.DateField(label="Fecha de consulta", initial=timezone.localdate, widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    estado = forms.ChoiceField(label="Estado", required=False, choices=[("", "Todos"), ("vigente", "Vigente"), ("por_vencer", "Próximo a vencer"), ("vencido", "Vencido"), ("faltante", "Sin vigencia acreditada")])
