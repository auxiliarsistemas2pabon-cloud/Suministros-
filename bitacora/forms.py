"""Filtro de la consulta de la bitácora."""

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType

from bitacora.models import RegistroBitacora
from bitacora.servicios import nombre_tipo


class FiltroBitacora(forms.Form):
    desde = forms.DateField(label="Desde", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    hasta = forms.DateField(label="Hasta", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    actor = forms.ModelChoiceField(
        label="Actor",
        queryset=get_user_model().objects.none(),
        required=False,
        empty_label="Todos los actores",
    )
    accion = forms.ChoiceField(label="Acción", required=False)
    tipo_objeto = forms.ModelChoiceField(
        label="Tipo de objeto",
        queryset=ContentType.objects.none(),
        required=False,
        empty_label="Todos los tipos",
    )
    objeto_id = forms.CharField(label="Id del objeto", required=False, max_length=64)
    q = forms.CharField(label="Buscar en objeto, actor o motivo", required=False, max_length=100)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        registros = RegistroBitacora.objects.order_by()
        self.fields["actor"].queryset = get_user_model().objects.filter(
            pk__in=registros.exclude(actor=None).values("actor")
        ).order_by("nombre")
        self.fields["actor"].label_from_instance = lambda usuario: f"{usuario.nombre} <{usuario.correo}>"
        acciones = registros.values_list("accion", flat=True).distinct().order_by("accion")
        self.fields["accion"].choices = [("", "Todas las acciones"), *((a, a) for a in acciones)]
        self.fields["tipo_objeto"].queryset = ContentType.objects.filter(
            pk__in=registros.exclude(tipo_objeto=None).values("tipo_objeto")
        )
        self.fields["tipo_objeto"].label_from_instance = nombre_tipo

    def clean(self):
        datos = super().clean()
        desde, hasta = datos.get("desde"), datos.get("hasta")
        if desde and hasta and hasta < desde:
            self.add_error("hasta", "La fecha final debe ser igual o posterior a la inicial.")
        return datos
