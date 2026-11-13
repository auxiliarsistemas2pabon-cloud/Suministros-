from django import forms
from django.contrib import admin

from areas import servicios
from areas.models import Area
from cuentas.forms import campo_motivo, exigir_motivo


class FormularioArea(forms.ModelForm):
    motivo = campo_motivo()

    class Meta:
        model = Area
        fields = ["nombre", "codigo_area", "activa"]

    def clean(self):
        datos = super().clean()
        if self.instance._state.adding or set(self.changed_data) & set(servicios.CAMPOS_AUDITADOS_AREA):
            exigir_motivo(self)
        if self.instance.pk and self.instance.activa and datos.get("activa") is False:
            mensaje = servicios.mensaje_bloqueo_desactivacion(self.instance)
            if mensaje:
                self.add_error("activa", mensaje)
        return datos


@admin.register(Area)
class AreaAdmin(admin.ModelAdmin):
    form = FormularioArea
    fields = ["nombre", "codigo_area", "activa", "fecha_creacion", "motivo"]
    list_display = ["nombre", "codigo_area", "activa", "fecha_creacion"]
    list_filter = ["activa"]
    search_fields = ["nombre", "codigo_area"]
    readonly_fields = ["fecha_creacion"]

    def save_model(self, request, obj, form, change):
        servicios.guardar_area(obj, actor=request.user, motivo=form.cleaned_data.get("motivo", ""), request=request)

    def has_delete_permission(self, request, obj=None):
        # Los catálogos se desactivan, no se borran.
        return False
