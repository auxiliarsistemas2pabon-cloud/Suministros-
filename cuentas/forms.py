from django import forms
from django.contrib.auth.forms import (
    AdminPasswordChangeForm,
    AuthenticationForm,
    BaseUserCreationForm,
    PasswordChangeForm,
    UserChangeForm,
)

from cuentas.models import Usuario
from cuentas.servicios import CAMPOS_AUDITADOS_USUARIO

MENSAJE_MOTIVO = "Indique el motivo del cambio; queda registrado en la bitácora."


def campo_motivo():
    return forms.CharField(
        label="Motivo del cambio",
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text="Obligatorio. Se guarda en la bitácora junto con los valores anterior y nuevo.",
    )


def exigir_motivo(formulario):
    if not (formulario.cleaned_data.get("motivo") or "").strip():
        formulario.add_error("motivo", MENSAJE_MOTIVO)


class FormularioIngreso(AuthenticationForm):
    username = forms.EmailField(
        label="Correo electrónico",
        widget=forms.EmailInput(attrs={
            "autofocus": True,
            "autocomplete": "email",
            "placeholder": "nombre@organizacion.com",
            "inputmode": "email",
            "autocapitalize": "none",
            "spellcheck": "false",
        }),
    )
    password = forms.CharField(
        label="Clave",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password", "placeholder": "Escriba su clave"}),
    )

    # El mismo mensaje para correo inexistente, clave errada o cuenta inactiva:
    # no revela si el correo está registrado.
    error_messages = {
        "invalid_login": "El correo o la clave no son correctos. Revise los datos e intente de nuevo.",
        "inactive": "El correo o la clave no son correctos. Revise los datos e intente de nuevo.",
    }


class FormularioCambioClave(PasswordChangeForm):
    error_messages = {
        **PasswordChangeForm.error_messages,
        "password_incorrect": "La clave actual no es correcta. Escríbala de nuevo.",
        "password_mismatch": "Las dos claves nuevas no coinciden.",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["old_password"].label = "Clave actual"
        self.fields["new_password1"].label = "Clave nueva"
        self.fields["new_password2"].label = "Confirme la clave nueva"
        self.fields["new_password2"].help_text = "Escriba de nuevo la clave nueva."

    def clean(self):
        datos = super().clean()
        nueva = datos.get("new_password1")
        if nueva and self.user.check_password(nueva):
            self.add_error("new_password1", "La clave nueva debe ser distinta de la actual.")
        return datos


class FormularioCreacionUsuario(BaseUserCreationForm):
    """Alta de usuarios en el admin técnico (clave con confirmación)."""

    motivo = campo_motivo()

    class Meta:
        model = Usuario
        fields = ["correo", "nombre", "rol", "area", "proveedor", "debe_cambiar_clave"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Quien recibe una clave asignada por otra persona debe cambiarla al ingresar.
        self.fields["debe_cambiar_clave"].initial = True

    def clean(self):
        datos = super().clean()
        exigir_motivo(self)
        return datos


class FormularioCambioUsuario(UserChangeForm):
    motivo = campo_motivo()

    class Meta:
        model = Usuario
        fields = "__all__"

    def clean(self):
        datos = super().clean()
        if set(self.changed_data) & set(CAMPOS_AUDITADOS_USUARIO):
            exigir_motivo(self)
        return datos


class FormularioClaveAdmin(AdminPasswordChangeForm):
    """Asignación de clave por un desarrollador desde el admin técnico."""

    motivo = campo_motivo()

    def clean(self):
        datos = super().clean()
        exigir_motivo(self)
        return datos
