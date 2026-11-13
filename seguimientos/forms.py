from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from configuracion.forms import ConMotivo
from areas.models import Area
from compras.models import OrdenCompra, Contrato
from proveedores.models import Proveedor
from proveedores.models import CategoriaProveedor
from seguimientos.models import Seguimiento, TipoSeguimiento, TipoEvento, ResultadoCierre, PlantillaHito
from seguimientos.estados import ESTADOS


class Crear(ConMotivo, forms.Form):
    orden = forms.ModelChoiceField(queryset=OrdenCompra.objects.filter(estado__in=["emitida", "recibida_parcial", "recibida_total"]), required=False)
    contrato = forms.ModelChoiceField(queryset=Contrato.objects.filter(decision__estado="aprobada"), required=False)
    tipo = forms.ModelChoiceField(queryset=TipoSeguimiento.objects.filter(activo=True), required=False)
    comite = forms.CharField(label="Comité", max_length=255, required=False)
    fecha_comite = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))

    def clean(self):
        datos = super().clean()
        if not datos.get("orden") and not datos.get("contrato"):
            raise ValidationError("Seleccione una orden o un contrato.")
        return datos


class ConRevision(ConMotivo, forms.Form):
    revision_esperada = forms.IntegerField(min_value=1, widget=forms.HiddenInput)


class Corregir(ConMotivo, forms.ModelForm):
    revision_esperada = forms.IntegerField(min_value=1, widget=forms.HiddenInput)

    class Meta:
        model = Seguimiento
        fields = ["proveedor", "objeto", "valor", "tipo", "comite", "fecha_comite"]
        widgets = {"fecha_comite": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}


class Evento(ConRevision):
    tipo = forms.ModelChoiceField(queryset=TipoEvento.objects.filter(activo=True))
    fecha = forms.DateTimeField(label="Fecha y hora del evento", initial=timezone.now, widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"))
    nota = forms.CharField(label="Nota", widget=forms.Textarea)
    corrige_id = forms.IntegerField(label="ID del evento que corrige", min_value=1, required=False)
    archivo = forms.FileField(label="Soporte PDF opcional (máximo 10 MB)", required=False)


class Cierre(ConRevision):
    resultado = forms.ModelChoiceField(queryset=ResultadoCierre.objects.filter(activo=True))
    fecha = forms.DateField(initial=timezone.localdate, widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))


class Filtro(forms.Form):
    periodo = forms.IntegerField(label="Año de apertura", min_value=1, max_value=9999, required=False)
    desde = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    hasta = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    area = forms.ModelChoiceField(label="Área", queryset=Area.objects.all(), required=False)
    proveedor = forms.CharField(label="NIT o nombre del proveedor", required=False, max_length=200)
    categoria = forms.ModelChoiceField(label="Categoría", queryset=CategoriaProveedor.objects.all(), required=False)
    consecutivo = forms.CharField(label="Consecutivo de la orden", required=False, max_length=100)
    tipo = forms.ModelChoiceField(queryset=TipoSeguimiento.objects.all(), required=False)
    estado = forms.ChoiceField(choices=[("", "Todos"), *ESTADOS], required=False)

    def clean(self):
        datos = super().clean()
        if datos.get("desde") and datos.get("hasta") and datos["desde"] > datos["hasta"]:
            raise ValidationError("La fecha inicial no puede ser posterior a la final.")
        return datos


class CatalogoTipo(ConMotivo, forms.ModelForm):
    class Meta:
        model = TipoSeguimiento
        fields = ["nombre", "codigo", "activo"]


class CatalogoEvento(ConMotivo, forms.ModelForm):
    class Meta:
        model = TipoEvento
        fields = ["nombre", "codigo", "funcion", "activo"]


class CatalogoResultado(ConMotivo, forms.ModelForm):
    class Meta:
        model = ResultadoCierre
        fields = ["nombre", "codigo", "activo"]


class CatalogoHito(ConMotivo, forms.ModelForm):
    class Meta:
        model = PlantillaHito
        fields = ["tipo_seguimiento", "nombre", "referencia", "cumple", "plazo_dias", "activo"]
