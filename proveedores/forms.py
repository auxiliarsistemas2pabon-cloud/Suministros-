"""Formularios de proveedores. Las reglas viven en proveedores/servicios.py; aquí solo se
validan los datos y se anticipan los errores para el usuario."""

from django import forms

from configuracion.forms import ConMotivo, FormularioMotivo

__all__ = ["FiltroProveedores", "FormularioDocumento", "FormularioEstado", "FormularioMotivo", "FormularioProveedor"]
from proveedores import archivos
from proveedores.models import CategoriaProveedor, DocumentoProveedor, Proveedor, TipoDocumento


def _activos_y_actual(modelo, actual_id):
    """Registros activos del catálogo más el que ya tenía el objeto (aunque esté inactivo)."""
    consulta = modelo.objects.filter(activo=True)
    if actual_id:
        consulta = consulta | modelo.objects.filter(pk=actual_id)
    return consulta.order_by("nombre")


class FormularioProveedor(ConMotivo, forms.ModelForm):
    class Meta:
        model = Proveedor
        fields = [
            "nit",
            "razon_social",
            "tipo_persona",
            "contacto_nombre",
            "contacto_correo",
            "contacto_telefono",
            "direccion",
            "categoria",
        ]
        widgets = {"nit": forms.TextInput(attrs={"inputmode": "numeric", "autocomplete": "off"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and not self.is_bound:
            self.initial["nit"] = self.instance.nit_formateado
        self.fields["tipo_persona"].choices = [("", "Seleccione el tipo de persona")] + list(
            Proveedor.TipoPersona.choices
        )
        categoria = self.fields["categoria"]
        categoria.queryset = _activos_y_actual(CategoriaProveedor, self.instance.categoria_id)
        categoria.empty_label = "Sin categoría"


class FiltroProveedores(forms.Form):
    q = forms.CharField(
        label="Buscar por NIT o nombre",
        required=False,
        max_length=200,
        widget=forms.TextInput(attrs={"placeholder": "900.123.456-8 o razón social"}),
    )
    estado = forms.ChoiceField(
        label="Estado", required=False, choices=[("", "Todos")] + list(Proveedor.Estado.choices)
    )
    categoria = forms.ModelChoiceField(
        label="Categoría", required=False, queryset=CategoriaProveedor.objects.order_by("nombre"), empty_label="Todas"
    )


class FiltroVencimientos(FiltroProveedores):
    tipo = forms.ModelChoiceField(label="Tipo de documento", queryset=TipoDocumento.objects.all(), required=False)
    estado = forms.ChoiceField(label="Estado documental", required=False, choices=[("", "Vencidos y próximos"), ("vencido", "Vencido"), ("por_vencer", "Próximo a vencer")])


class FormularioEstado(ConMotivo, forms.Form):
    estado = forms.ChoiceField(label="Nuevo estado", choices=())

    def __init__(self, *args, opciones, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["estado"].choices = [("", "Seleccione el nuevo estado")] + list(opciones)
        self.order_fields(["estado", "motivo"])


class FormularioDocumento(ConMotivo, forms.ModelForm):
    """Datos del documento y su contenido: un PDF (máximo 10 MB) o un enlace."""

    archivo_pdf = forms.FileField(
        label="Archivo PDF",
        required=False,
        widget=forms.FileInput(attrs={"accept": "application/pdf,.pdf"}),
        help_text="Solo PDF, máximo 10 MB. Si adjunta un PDF, deje vacío el enlace.",
    )

    class Meta:
        model = DocumentoProveedor
        fields = ["tipo", "fecha_expedicion", "fecha_vencimiento", "enlace"]
        widgets = {
            "fecha_expedicion": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "fecha_vencimiento": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "enlace": forms.URLInput(attrs={"placeholder": "https://"}),
        }
        help_texts = {
            "fecha_vencimiento": "Obligatoria si el tipo de documento la requiere.",
            "enlace": "Use un enlace solo si el documento no se adjunta como PDF.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        tipo = self.fields["tipo"]
        tipo.queryset = _activos_y_actual(TipoDocumento, self.instance.tipo_id)
        tipo.empty_label = "Seleccione el tipo de documento"
        tipo.label_from_instance = lambda t: f"{t.nombre}{' (vence)' if t.requiere_vencimiento else ''}"
        if self.instance.tiene_pdf:
            self.fields["archivo_pdf"].help_text = (
                f"Archivo actual: {self.instance.nombre_archivo or 'documento.pdf'}. Adjunte otro solo si quiere "
                "reemplazarlo (el anterior se borra). Solo PDF, máximo 10 MB."
            )
        self.order_fields(["tipo", "fecha_expedicion", "fecha_vencimiento", "archivo_pdf", "enlace", "motivo"])

    def clean_archivo_pdf(self):
        archivo = self.cleaned_data.get("archivo_pdf")
        if archivo:
            archivos.validar_pdf(archivo)
        return archivo

    def clean(self):
        datos = super().clean()
        archivo = datos.get("archivo_pdf")
        enlace = datos.get("enlace")
        if "archivo_pdf" in self.errors:
            return datos
        if archivo and enlace:
            self.add_error(None, "Adjunte un PDF o escriba un enlace, no ambos.")
        elif not archivo and not enlace and not self.instance.tiene_pdf and "enlace" not in self.errors:
            self.add_error(None, "Adjunte el PDF del documento o escriba su enlace.")
        return datos
