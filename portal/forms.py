from django import forms
from django.contrib.auth.password_validation import password_validators_help_text_html, validate_password
from django.core.exceptions import ValidationError

from cuentas.models import Rol, Usuario, normalizar_correo
from proveedores.archivos import validar_pdf
from proveedores.models import EnvioProveedor, Proveedor, TipoDocumento
from proveedores.nit import normalizar


class FormularioRegistro(forms.Form):
    nit = Proveedor._meta.get_field("nit").formfield()
    razon_social = Proveedor._meta.get_field("razon_social").formfield()
    tipo_persona = forms.ChoiceField(label="Tipo de persona", choices=Proveedor.TipoPersona.choices)
    contacto_nombre = Proveedor._meta.get_field("contacto_nombre").formfield()
    contacto_telefono = Proveedor._meta.get_field("contacto_telefono").formfield()
    direccion = Proveedor._meta.get_field("direccion").formfield()
    correo = forms.EmailField(label="Correo electrónico", max_length=254)
    clave1 = forms.CharField(label="Contraseña", strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}), help_text=password_validators_help_text_html())
    clave2 = forms.CharField(label="Confirme la contraseña", strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    sitio_web = forms.CharField(label="Deje este campo vacío", required=False, max_length=200, widget=forms.TextInput(attrs={"tabindex": "-1", "autocomplete": "off"}))

    def clean_nit(self):
        nit, _ = normalizar(self.cleaned_data["nit"])
        return nit

    def clean_correo(self):
        return normalizar_correo(self.cleaned_data["correo"])

    def clean(self):
        datos = super().clean()
        if datos.get("clave1") and datos.get("clave2") and datos["clave1"] != datos["clave2"]:
            self.add_error("clave2", "Las contraseñas no coinciden.")
        if datos.get("clave1"):
            try:
                validate_password(datos["clave1"], Usuario(correo=datos.get("correo", ""), nombre=datos.get("contacto_nombre", ""), rol=Rol.PROVEEDOR))
            except ValidationError as error:
                self.add_error("clave1", error)
        return datos


class FormularioEnvio(forms.ModelForm):
    archivo_pdf = forms.FileField(label="Archivo PDF", help_text="Solo PDF, máximo 10 MB.", widget=forms.FileInput(attrs={"accept": ".pdf,application/pdf"}))

    class Meta:
        model = EnvioProveedor
        fields = ["tipo", "fecha_expedicion", "fecha_vencimiento"]
        widgets = {
            "fecha_expedicion": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "fecha_vencimiento": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["tipo"].queryset = TipoDocumento.objects.filter(activo=True)

    def clean_archivo_pdf(self):
        archivo = self.cleaned_data["archivo_pdf"]
        validar_pdf(archivo)
        return archivo
