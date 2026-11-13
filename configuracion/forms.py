"""Formularios del panel de configuración. Las reglas viven en los servicios;
aquí solo se validan los datos y se anticipan los errores para el usuario."""

from django import forms
from django.contrib.auth.password_validation import password_validators_help_text_html, validate_password
from django.core.exceptions import ValidationError

from areas.models import Area
from cuentas.forms import campo_motivo, exigir_motivo
from cuentas.models import Rol, Usuario
from cuentas.servicios import MENSAJE_SOLO_DESARROLLADOR_GESTIONA, roles_asignables
from parametros.catalogo import DEFINICIONES
from parametros.models import Parametro
from proveedores.models import Proveedor
from proyecciones.models import ProductoSugerido, UnidadMedida
from proyecciones.servicios import unidades_para_producto


class ConMotivo:
    """Agrega el campo motivo (obligatorio) a un formulario."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["motivo"] = campo_motivo()

    def clean(self):
        datos = super().clean()
        exigir_motivo(self)
        return datos


class FormularioMotivo(ConMotivo, forms.Form):
    """Confirmación de una acción (activar, desactivar) con su motivo."""


# --- Áreas ----------------------------------------------------------------------


class FormularioArea(ConMotivo, forms.ModelForm):
    class Meta:
        model = Area
        fields = ["nombre", "codigo_area"]
        help_texts = {"codigo_area": "Se guarda en mayúsculas. Ejemplo: FAR."}


class FormularioCoordinadores(ConMotivo, forms.Form):
    coordinadores = forms.ModelMultipleChoiceField(
        label="Coordinadores que pasarán a esta área",
        queryset=Usuario.objects.none(),
        widget=forms.CheckboxSelectMultiple,
        error_messages={"required": "Seleccione al menos un coordinador."},
    )

    def __init__(self, *args, disponibles, **kwargs):
        super().__init__(*args, **kwargs)
        campo = self.fields["coordinadores"]
        campo.queryset = disponibles
        campo.label_from_instance = lambda u: f"{u.nombre} <{u.correo}> · hoy en {u.area.nombre if u.area else 'sin área'}"


# --- Catálogos de la proyección ----------------------------------------------------


class FormularioUnidad(ConMotivo, forms.ModelForm):
    class Meta:
        model = UnidadMedida
        fields = ["nombre", "abreviatura"]
        help_texts = {"abreviatura": "Ejemplo: und, caja, ml."}


class FormularioProducto(ConMotivo, forms.ModelForm):
    class Meta:
        model = ProductoSugerido
        fields = ["nombre", "unidad_por_defecto"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["unidad_por_defecto"].queryset = unidades_para_producto(
            self.instance if self.instance.pk else None
        )
        self.fields["unidad_por_defecto"].empty_label = "Seleccione una unidad"


# --- Usuarios ---------------------------------------------------------------------

MODO_GENERAR = "generar"
MODO_MANUAL = "manual"


class CamposClaveTemporal(forms.Form):
    """Clave temporal: la genera el sistema (por defecto) o la escribe el administrador."""

    modo_clave = forms.ChoiceField(
        label="Clave temporal",
        choices=[
            (MODO_GENERAR, "Generarla automáticamente (se le mostrará una sola vez)"),
            (MODO_MANUAL, "Escribirla yo"),
        ],
        initial=MODO_GENERAR,
        widget=forms.RadioSelect,
    )
    clave1 = forms.CharField(
        label="Clave temporal",
        required=False,
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text=password_validators_help_text_html(),
    )
    clave2 = forms.CharField(
        label="Confirme la clave temporal",
        required=False,
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    def usuario_para_validar(self):
        return None

    def validar_clave(self):
        if self.cleaned_data.get("modo_clave") != MODO_MANUAL:
            return
        clave1 = self.cleaned_data.get("clave1")
        clave2 = self.cleaned_data.get("clave2")
        if not clave1:
            self.add_error("clave1", "Escriba la clave temporal o elija generarla automáticamente.")
            return
        if clave1 != clave2:
            self.add_error("clave2", "Las dos claves no coinciden.")
            return
        try:
            validate_password(clave1, self.usuario_para_validar())
        except ValidationError as error:
            self.add_error("clave1", error)

    def clave_elegida(self):
        """La clave escrita, o None para que el servicio la genere."""
        if self.cleaned_data.get("modo_clave") == MODO_MANUAL:
            return self.cleaned_data.get("clave1")
        return None


def _ajustar_campos_usuario(formulario, actor):
    roles = roles_asignables(actor)
    formulario.fields["rol"].choices = [("", "Seleccione un rol")] + [
        (valor, etiqueta) for valor, etiqueta in Rol.choices if valor in roles
    ]
    instancia_area = formulario.instance.area_id if formulario.instance.pk else None
    areas = Area.objects.filter(activa=True)
    if instancia_area:
        areas = areas | Area.objects.filter(pk=instancia_area)
    formulario.fields["area"].queryset = areas.order_by("nombre")
    formulario.fields["area"].empty_label = "Sin área"
    formulario.fields["area"].help_text = "Obligatoria para coordinadores; vacía para proveedores."
    # Proveedores no inactivos, más el que el usuario ya tenía (aunque esté inactivo).
    proveedor_actual = formulario.instance.proveedor_id if formulario.instance.pk else None
    proveedores = Proveedor.objects.exclude(estado=Proveedor.Estado.INACTIVO)
    if proveedor_actual:
        proveedores = proveedores | Proveedor.objects.filter(pk=proveedor_actual)
    formulario.fields["proveedor"].queryset = proveedores.order_by("razon_social")
    formulario.fields["proveedor"].empty_label = "Sin proveedor"
    formulario.fields["proveedor"].help_text = "Obligatorio para el rol proveedor; vacío para los demás roles."


def _validar_rol_desarrollador(formulario, actor):
    rol = formulario.cleaned_data.get("rol")
    if rol and rol not in roles_asignables(actor):
        formulario.add_error("rol", MENSAJE_SOLO_DESARROLLADOR_GESTIONA)


class FormularioCrearUsuario(ConMotivo, CamposClaveTemporal, forms.ModelForm):
    class Meta:
        model = Usuario
        fields = ["correo", "nombre", "rol", "area", "proveedor"]

    def __init__(self, *args, actor, **kwargs):
        self.actor = actor
        super().__init__(*args, **kwargs)
        _ajustar_campos_usuario(self, actor)
        # Ordena los campos: datos, clave y motivo al final.
        self.order_fields(["correo", "nombre", "rol", "area", "proveedor", "modo_clave", "clave1", "clave2", "motivo"])

    def usuario_para_validar(self):
        return Usuario(correo=self.cleaned_data.get("correo", ""), nombre=self.cleaned_data.get("nombre", ""))

    def clean(self):
        datos = super().clean()
        _validar_rol_desarrollador(self, self.actor)
        self.validar_clave()
        return datos


class FormularioEditarUsuario(ConMotivo, forms.ModelForm):
    class Meta:
        model = Usuario
        fields = ["correo", "nombre", "rol", "area", "proveedor"]

    def __init__(self, *args, actor, **kwargs):
        self.actor = actor
        super().__init__(*args, **kwargs)
        _ajustar_campos_usuario(self, actor)
        if self.instance.pk == actor.pk:
            self.fields["rol"].disabled = True
            self.fields["rol"].help_text = "No puede cambiar su propio rol."

    def clean(self):
        datos = super().clean()
        _validar_rol_desarrollador(self, self.actor)
        return datos


class FormularioRestablecerClave(ConMotivo, CamposClaveTemporal):
    def __init__(self, *args, usuario, **kwargs):
        self.usuario = usuario
        super().__init__(*args, **kwargs)

    def usuario_para_validar(self):
        return self.usuario

    def clean(self):
        datos = super().clean()
        self.validar_clave()
        return datos


class FiltroUsuarios(forms.Form):
    q = forms.CharField(label="Buscar", required=False, widget=forms.TextInput(attrs={"placeholder": "Nombre o correo"}))
    rol = forms.ChoiceField(label="Rol", required=False, choices=[("", "Todos los roles")] + Rol.choices)
    area = forms.ModelChoiceField(
        label="Área", required=False, queryset=Area.objects.order_by("nombre"), empty_label="Todas las áreas"
    )
    estado = forms.ChoiceField(
        label="Estado",
        required=False,
        choices=[("", "Todos"), ("activos", "Activos"), ("inactivos", "Inactivos")],
    )


class FiltroCatalogo(forms.Form):
    q = forms.CharField(label="Buscar", required=False)
    estado = forms.ChoiceField(
        label="Estado",
        required=False,
        choices=[("", "Todos"), ("activos", "Activos"), ("inactivos", "Inactivos")],
    )


# --- Parámetros ---------------------------------------------------------------------


class FormularioParametro(ConMotivo, forms.Form):
    """Nuevo valor de un parámetro; el campo depende de su tipo."""

    def __init__(self, *args, parametro, **kwargs):
        super().__init__(*args, **kwargs)
        self.parametro = parametro
        definicion = DEFINICIONES.get(parametro.clave)
        minimo = definicion.minimo if definicion else None
        ayuda = f"Valor por defecto documentado: {parametro.valor_por_defecto}."
        if parametro.tipo == Parametro.Tipo.BOOLEANO:
            campo = forms.TypedChoiceField(
                choices=[("true", "Sí"), ("false", "No")],
                coerce=lambda valor: valor == "true",
                widget=forms.RadioSelect,
                initial="true" if parametro.valor_tipado else "false",
            )
            ayuda = f"Valor por defecto documentado: {'Sí' if parametro.valor_por_defecto_tipado else 'No'}."
        elif parametro.tipo == Parametro.Tipo.ENTERO:
            campo = forms.IntegerField(initial=parametro.valor_tipado, min_value=minimo)
        elif parametro.tipo == Parametro.Tipo.DECIMAL:
            campo = forms.DecimalField(initial=parametro.valor_tipado, min_value=minimo)
        else:
            campo = forms.CharField(max_length=255, initial=parametro.valor)
        campo.label = "Valor"
        campo.help_text = ayuda
        self.fields = {"valor": campo, **{k: v for k, v in self.fields.items() if k != "valor"}}
