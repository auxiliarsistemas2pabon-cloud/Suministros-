from decimal import Decimal

from django import forms
from django.core import signing
from django.utils import timezone

from areas.models import Area
from compras.models import TipoOrigen
from compras.criterios_servicios import versiones_en_fecha
from configuracion.forms import ConMotivo
from proveedores.models import Proveedor
from proyecciones.models import Linea, Periodo


class FiltroLineas(forms.Form):
    area = forms.ModelChoiceField(label="Área de origen", queryset=Area.objects.filter(activa=True), required=False, widget=forms.Select(attrs={"id": "filtro_area"}))
    periodo = forms.ModelChoiceField(label="Periodo", queryset=Periodo.objects.all(), required=False, widget=forms.Select(attrs={"id": "filtro_periodo"}))


class FormularioNecesidad(ConMotivo, forms.Form):
    objeto = forms.CharField(label="Objeto o descripción", widget=forms.Textarea)
    area = forms.ModelChoiceField(label="Área", queryset=Area.objects.filter(activa=True))
    fecha = forms.DateField(label="Fecha", initial=timezone.localdate, widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    tipo_origen = forms.ModelChoiceField(label="Tipo de origen (opcional)", queryset=TipoOrigen.objects.filter(activo=True), required=False)
    origen_texto = forms.CharField(label="Detalle del origen", required=False, widget=forms.Textarea,
                                 help_text="Si no usa líneas aprobadas, indique un tipo o describa el origen.")
    cantidad_base = forms.DecimalField(label="Cantidad base (opcional)", max_digits=14, decimal_places=3, min_value=Decimal("0.001"), required=False)
    unidad_base = forms.CharField(label="Unidad de la cantidad base", max_length=120, required=False,
        help_text="Indíquela junto con la cantidad para necesidades manuales o de unidades mixtas. Las líneas de una misma unidad pueden sumarse automáticamente.")


class OrigenForm(forms.Form):
    linea = forms.ModelChoiceField(label="Línea aprobada", queryset=Linea.objects.none(), required=False)
    cantidad = forms.DecimalField(label="Cantidad tomada", max_digits=14, decimal_places=3, min_value=Decimal("0.001"), required=False)

    def __init__(self, *args, lineas, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["linea"].queryset = lineas
        self.fields["linea"].label_from_instance = lambda l: f"{l.proyeccion.periodo.anio} · {l.producto_servicio} · {l.unidad}"

    def clean(self):
        datos = super().clean()
        if bool(datos.get("linea")) != (datos.get("cantidad") is not None):
            raise forms.ValidationError("Seleccione la línea y su cantidad, o deje ambos vacíos.")
        return datos


OrigenesFormSet = forms.formset_factory(OrigenForm, extra=1, can_delete=True, max_num=100, validate_max=True, absolute_max=100)


class FormularioLista(ConMotivo, forms.Form):
    fecha = forms.DateField(label="Fecha de la lista", initial=timezone.localdate, widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))


class FormularioParticipante(ConMotivo, forms.Form):
    proveedor = forms.ModelChoiceField(label="Proveedor", queryset=Proveedor.objects.exclude(estado=Proveedor.Estado.INACTIVO))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["proveedor"].label_from_instance = lambda p: f"{p.razon_social} · NIT {p.nit_formateado}"


class FormularioTipoOrigen(ConMotivo, forms.ModelForm):
    class Meta:
        model = TipoOrigen
        fields = ["nombre", "activo"]


class FormularioVersion(ConMotivo, forms.Form):
    notas = forms.CharField(label="Notas de la versión", required=False, widget=forms.Textarea)


class FormularioPublicacion(ConMotivo, forms.Form):
    desde = forms.DateField(label="Vigente desde", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    hasta = forms.DateField(label="Vigente hasta (opcional)", required=False, widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))


class FormularioCriterio(forms.Form):
    nombre = forms.CharField(label="Criterio", max_length=120)
    peso = forms.DecimalField(label="Peso %", max_digits=5, decimal_places=2, min_value=Decimal("0.01"), max_value=Decimal(100))


CriteriosFormSet = forms.formset_factory(FormularioCriterio, extra=2, can_delete=True, max_num=20, validate_max=True, absolute_max=20)


class FormularioVersionLista(ConMotivo, forms.Form):
    def __init__(self, *args, lista, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["version"] = forms.ModelChoiceField(label="Versión de criterios", queryset=versiones_en_fecha(lista.fecha))


class FormularioMatriz(ConMotivo, forms.Form):
    revision = forms.CharField(widget=forms.HiddenInput)

    def __init__(self, *args, lista, matriz, **kwargs):
        super().__init__(*args, **kwargs)
        self.identidad = {"lista": lista.pk, "version": lista.version_criterios_id,
            "participantes": [f["participante"].pk for f in matriz["filas"]], "criterios": [c["id"] for c in matriz["criterios"]]}
        self.fields["revision"].initial = signing.dumps(self.identidad, salt="matriz-elegibles")
        self.celdas = []
        for fila in matriz["filas"]:
            participante = fila["participante"]
            for celda in fila["celdas"]:
                clave = f"p{participante.pk}_c{celda['id']}"
                self.fields[clave] = forms.TypedChoiceField(label=f"{participante.razon_social} · {celda['nombre']} · Cumplimiento",
                    choices=[("", "Sin calificar")] + [(v, v) for v in matriz["reglas"]["escala"]],
                    coerce=Decimal, empty_value=None, required=False,
                    initial=str(celda["cumplimiento"].normalize()) if celda["cumplimiento"] is not None else "")
                # Los valores de ChoiceField y su initial usan la misma representación decimal.
                self.fields[clave].choices = [("", "Sin calificar")] + [(str(Decimal(v).normalize()), v) for v in matriz["reglas"]["escala"]]
                observacion = clave + "_observacion"
                self.fields[observacion] = forms.CharField(label=f"{participante.razon_social} · {celda['nombre']} · Observación",
                    required=False, max_length=2000, initial=celda["observacion"], widget=forms.Textarea(attrs={"rows": 2}))
                celda["campo_cumplimiento"], celda["campo_observacion"] = self[clave], self[observacion]
                self.celdas.append((participante.pk, celda["id"], clave, observacion))

    def clean(self):
        datos = super().clean()
        try:
            identidad = signing.loads(datos.get("revision", ""), salt="matriz-elegibles")
            if identidad != self.identidad:
                raise signing.BadSignature()
        except signing.BadSignature:
            raise forms.ValidationError("Los participantes o criterios cambiaron. Recargue la matriz antes de guardar.") from None
        return datos

    def valores(self):
        return [{"participante": p, "criterio": c, "cumplimiento": self.cleaned_data[clave],
                 "observacion": self.cleaned_data[obs]} for p, c, clave, obs in self.celdas]


class FormularioCantidadBase(ConMotivo, forms.Form):
    cantidad_base = forms.DecimalField(label="Cantidad base de la necesidad", max_digits=14, decimal_places=3, min_value=Decimal("0.001"))
    unidad_base = forms.CharField(label="Unidad base", max_length=120)


class FormularioRevisionDocumental(ConMotivo, forms.Form):
    justificacion = forms.CharField(label="Justificación para continuar con advertencias documentales", required=False,
        max_length=3000, widget=forms.Textarea,
        help_text="Obligatoria si un proveedor elegido tiene advertencias y el modo permite continuar. No permite omitir un bloqueo.")


class FormularioCierre(ConMotivo, forms.Form):
    justificacion_documental = forms.CharField(label="Justificación documental para continuar con advertencias", required=False,
        max_length=3000, widget=forms.Textarea,
        help_text="Se volverán a comprobar las condiciones actuales. Una justificación no evita los bloqueos configurados.")


class FormularioDesempate(ConMotivo, forms.Form):
    total = forms.DecimalField(widget=forms.HiddenInput, max_digits=8, decimal_places=4)
    justificacion = forms.CharField(label="Justificación del desempate", widget=forms.Textarea, max_length=2000)

    def __init__(self, *args, grupo, **kwargs):
        kwargs.setdefault("auto_id", f"desempate_{grupo['total']}_%s")
        super().__init__(*args, **kwargs)
        self.grupo = grupo
        self.fields["total"].initial = grupo["total"]
        opciones = [(f["participante"].pk, f"{f['participante'].razon_social} · NIT {f['participante'].nit}") for f in grupo["filas"]]
        for n in range(1, len(opciones) + 1):
            self.fields[f"puesto_{n}"] = forms.TypedChoiceField(label=f"Orden dentro del empate: {n}", choices=[("", "Seleccione un participante"), *opciones], coerce=int)

    def clean(self):
        datos = super().clean()
        orden = [datos.get(f"puesto_{n}") for n in range(1, len(self.grupo["filas"]) + 1)]
        if datos.get("total") != self.grupo["total"] or len(set(orden)) != len(orden):
            raise forms.ValidationError("Ordene una sola vez a cada participante del empate actual.")
        return datos

    def orden(self):
        return [self.cleaned_data[f"puesto_{n}"] for n in range(1, len(self.grupo["filas"]) + 1)]


def firma_decision(lista, resultado):
    return {"lista": lista.pk, "version": lista.version_criterios_id, "reglas": lista.reglas_calculo,
        "base": {"cantidad": str(resultado["base"]["cantidad"]), "unidad": resultado["base"]["unidad"]},
        "filas": [{"id": f["participante"].pk, "total": str(f["total"]), "puesto": f["puesto"],
                   "cantidad": str(f["participante"].cantidad_autorizada), "observacion": f["participante"].observacion,
                   "justificacion": f["participante"].justificacion_eleccion} for f in resultado["filas"]]}


class FormularioDecision(ConMotivo, forms.Form):
    revision = forms.CharField(widget=forms.HiddenInput)
    justificacion_unico = forms.CharField(label="Justificación de proveedor único", required=False, widget=forms.Textarea, max_length=2000)
    justificacion_cantidad = forms.CharField(label="Justificación para superar la cantidad base", required=False, widget=forms.Textarea, max_length=2000)

    def __init__(self, *args, lista, resultado, decision, **kwargs):
        super().__init__(*args, **kwargs)
        self.identidad = firma_decision(lista, resultado)
        self.fields["revision"].initial = signing.dumps(self.identidad, salt="decision-elegibles")
        registro = decision["registro"]
        if registro:
            self.fields["justificacion_unico"].initial = registro.justificacion_unico
            self.fields["justificacion_cantidad"].initial = registro.justificacion_cantidad
        self.asignaciones = []
        for fila in resultado["filas"]:
            p = fila["participante"]
            clave = f"p{p.pk}"
            self.fields[clave + "_cantidad"] = forms.DecimalField(label=f"{p.razon_social} · Cantidad autorizada",
                max_digits=14, decimal_places=3, min_value=0, initial=p.cantidad_autorizada)
            self.fields[clave + "_observacion"] = forms.CharField(label=f"{p.razon_social} · Observación", required=False,
                initial=p.observacion, max_length=2000, widget=forms.Textarea(attrs={"rows": 2}))
            self.fields[clave + "_justificacion"] = forms.CharField(label=f"{p.razon_social} · Justificación si no ocupa el primer puesto",
                required=False, initial=p.justificacion_eleccion, max_length=2000, widget=forms.Textarea(attrs={"rows": 2}))
            fila["campo_cantidad"], fila["campo_observacion"], fila["campo_justificacion"] = [self[clave + sufijo] for sufijo in ("_cantidad", "_observacion", "_justificacion")]
            self.asignaciones.append((p.pk, clave))

    def clean(self):
        datos = super().clean()
        try:
            if signing.loads(datos.get("revision", ""), salt="decision-elegibles") != self.identidad:
                raise signing.BadSignature()
        except signing.BadSignature:
            raise forms.ValidationError("La lista o sus cantidades cambiaron. Recargue la decisión antes de guardar.") from None
        return datos

    def valores(self):
        return [{"participante": pk, "cantidad_autorizada": self.cleaned_data[clave + "_cantidad"],
                 "observacion": self.cleaned_data[clave + "_observacion"],
                 "justificacion_eleccion": self.cleaned_data[clave + "_justificacion"]} for pk, clave in self.asignaciones]
