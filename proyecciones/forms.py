"""Formularios de periodos y de las líneas de la proyección del coordinador."""

from django import forms
from django.core.exceptions import ValidationError

from areas.models import Area
from cuentas.forms import campo_motivo, exigir_motivo
from proyecciones.models import (
    CAMPOS_AJUSTABLES,
    CAMPOS_CANTIDADES_MENSUALES,
    Linea,
    Periodo,
    ProyeccionArea,
    UnidadMedida,
)


class ConMotivo:
    """Agrega un motivo obligatorio para dejar trazabilidad del cambio."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["motivo"] = campo_motivo()

    def clean(self):
        datos = super().clean()
        exigir_motivo(self)
        return datos


class FormularioAbrirPeriodo(ConMotivo, forms.Form):
    anio = forms.IntegerField(label="Año", min_value=1)
    fecha_limite = forms.DateField(
        label="Fecha límite de diligenciamiento",
        widget=forms.DateInput(attrs={"type": "date"}),
    )


class FormularioMotivo(ConMotivo, forms.Form):
    """Motivo para cerrar, reabrir o completar una proyección faltante."""


class FormularioImportacion(forms.Form):
    archivo = forms.FileField(
        label="Archivo Excel", widget=forms.ClearableFileInput(attrs={"accept": ".xlsx"}),
        help_text="Use la plantilla del sistema. Máximo 10 MB y 1000 líneas.",
    )


class FormularioConfirmarImportacion(ConMotivo, forms.Form):
    token = forms.CharField(widget=forms.HiddenInput)
    modo = forms.ChoiceField(
        label="Cómo guardar las filas válidas",
        choices=[("agregar", "Agregar a las líneas existentes"), ("reemplazar", "Reemplazar todas las líneas existentes")],
    )


class FormularioLinea(forms.ModelForm):
    """Línea editable del formset de la proyección del coordinador."""

    class Meta:
        model = Linea
        fields = [
            "producto_servicio",
            "dependencia",
            "unidad",
            *CAMPOS_CANTIDADES_MENSUALES,
            "precio_estimado",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["producto_servicio"].widget.attrs["list"] = "productos-sugeridos"
        self.fields["producto_servicio"].widget.attrs["autocomplete"] = "off"
        for nombre in CAMPOS_CANTIDADES_MENSUALES:
            self.fields[nombre].widget.attrs.update(
                {"data-cantidad": "", "inputmode": "numeric", "min": "0", "step": "1"}
            )
        self.fields["precio_estimado"].widget.attrs.update(
            {"data-precio": "", "inputmode": "decimal", "min": "0", "step": "0.01"}
        )
        unidades = UnidadMedida.objects.filter(activa=True)
        if self.instance.pk and self.instance.unidad_id:
            unidades = unidades | UnidadMedida.objects.filter(pk=self.instance.unidad_id)
        self.fields["unidad"].queryset = unidades.order_by("nombre")
        self.fields["unidad"].empty_label = "Seleccione una unidad"
        self._etiquetar_campos()

    def _etiquetar_campos(self):
        """Da a cada casilla de la tabla un nombre accesible, p. ej. «Cantidad de enero, línea 2»."""
        if self.prefix is None:
            return  # Formulario suelto (no en tabla): cada campo ya tiene su etiqueta visible.
        indice = (self.prefix or "").rsplit("-", 1)[-1]
        fila = f"línea {int(indice) + 1}" if indice.isdigit() else "línea nueva"
        for nombre, campo in self.fields.items():
            if nombre in ("id", "DELETE"):
                continue
            etiqueta = str(campo.label or nombre)
            campo.widget.attrs["aria-label"] = f"{etiqueta[:1].upper()}{etiqueta[1:]}, {fila}"


class BaseFormularioLineas(forms.BaseModelFormSet):
    """Formset que solo acepta líneas de la proyección indicada.

    El campo oculto «id» de Django valida contra todas las líneas de la base; si alguien
    cambia ese valor por el de una línea de otra área, se rechaza con un error claro en
    lugar de ignorarlo en silencio.
    """

    MENSAJE_LINEA_AJENA = (
        "Una de las líneas enviadas no pertenece a esta proyección. Recargue la página e intente de nuevo."
    )

    def __init__(self, *args, proyeccion=None, **kwargs):
        self.proyeccion = proyeccion
        super().__init__(*args, **kwargs)

    def clean(self):
        super().clean()
        for indice, formulario in enumerate(self.forms):
            linea = getattr(formulario, "cleaned_data", {}).get("id")
            if linea is None:
                continue
            es_fila_nueva = indice >= self.initial_form_count()
            if es_fila_nueva or self.proyeccion is None or linea.proyeccion_id != self.proyeccion.pk:
                raise ValidationError(self.MENSAJE_LINEA_AJENA, code="linea_ajena")


FormularioLineas = forms.modelformset_factory(
    Linea,
    form=FormularioLinea,
    formset=BaseFormularioLineas,
    extra=1,
    can_delete=True,
)


def formulario_lineas(proyeccion, data=None):
    """Formset limitado a una sola proyección del área del usuario."""
    return FormularioLineas(
        data=data,
        queryset=Linea.objects.filter(proyeccion=proyeccion).order_by("id"),
        prefix="lineas",
        proyeccion=proyeccion,
    )


# --- Revisión por administración ---------------------------------------------------


class FiltroRevision(forms.Form):
    periodo = forms.ModelChoiceField(
        label="Periodo",
        queryset=Periodo.objects.order_by("-anio"),
        required=False,
        empty_label="Todos los periodos",
    )
    area = forms.ModelChoiceField(
        label="Área",
        queryset=Area.objects.order_by("nombre"),
        required=False,
        empty_label="Todas las áreas",
    )
    estado = forms.ChoiceField(
        label="Estado",
        choices=[("", "Todos los estados"), *ProyeccionArea.Estado.choices],
        required=False,
    )


class FormularioCorreccionLinea(ConMotivo, FormularioLinea):
    """Corrección de una línea por administración: cualquier campo diligenciado por el área."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["motivo"].label = "Motivo de la corrección (justificación)"


# --- Aprobación y ajustes --------------------------------------------------------------


class FormularioAutorizacion(ConMotivo, forms.Form):
    """Cantidad autorizada por línea (por defecto, su total anual) y motivo de la aprobación."""

    def __init__(self, *args, lineas, **kwargs):
        super().__init__(*args, **kwargs)
        self.lineas = list(lineas)
        campos = {}
        for numero, linea in enumerate(self.lineas, start=1):
            inicial = linea.total_anual if linea.cantidad_autorizada is None else linea.cantidad_autorizada
            campos[self.nombre_campo(linea)] = forms.IntegerField(
                label=f"Cantidad autorizada de {linea.producto_servicio}",
                min_value=0,
                required=False,
                initial=inicial,
                widget=forms.NumberInput(
                    attrs={
                        "min": "0",
                        "step": "1",
                        "inputmode": "numeric",
                        "aria-label": f"Cantidad autorizada, línea {numero}: {linea.producto_servicio}",
                    }
                ),
            )
        self.fields["motivo"].label = "Motivo (se guarda con la autorización o la aprobación)"
        self.fields = {**campos, "motivo": self.fields["motivo"]}

    @staticmethod
    def nombre_campo(linea):
        return f"autorizada_{linea.pk}"

    def filas(self):
        return [(linea, self[self.nombre_campo(linea)]) for linea in self.lineas]

    def cantidades(self):
        """{id_linea: entero o None}; None (casilla vacía) toma el total anual."""
        return {linea.pk: self.cleaned_data.get(self.nombre_campo(linea)) for linea in self.lineas}


class FormularioAjuste(forms.Form):
    campo = forms.ChoiceField(label="Campo a ajustar")
    valor_nuevo = forms.CharField(
        label="Valor nuevo",
        max_length=30,
        help_text="Cantidades: número entero no negativo. Precio: hasta dos decimales, con punto.",
    )
    justificacion = forms.CharField(
        label="Justificación",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Obligatoria. Se guarda con el ajuste y en la bitácora.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        opciones = []
        for campo in CAMPOS_AJUSTABLES:
            etiqueta = str(Linea._meta.get_field(campo).verbose_name)
            opciones.append((campo, etiqueta[:1].upper() + etiqueta[1:]))
        self.fields["campo"].choices = [("", "Seleccione el campo"), *opciones]

    def clean(self):
        datos = super().clean()
        datos["justificacion"] = (datos.get("justificacion") or "").strip()
        if not datos["justificacion"]:
            self.add_error("justificacion", "La justificación es obligatoria.")
        return datos
