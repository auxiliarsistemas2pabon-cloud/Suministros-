"""Formularios y vistas de configuración de los catálogos de proveedores."""

from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_safe

from config.utilidades import agregar_errores
from configuracion.forms import ConMotivo, FiltroCatalogo, FormularioMotivo
from cuentas.models import ROLES_ADMIN
from cuentas.permisos import rol_requerido
from proveedores import servicios
from proveedores.catalogos import CATALOGOS
from proveedores.models import CategoriaProveedor, DocumentoExigido, Peso, Requisito, TipoDocumento, VersionMatriz


class FormularioCategoria(ConMotivo, forms.ModelForm):
    class Meta:
        model = CategoriaProveedor
        fields = ["nombre", "descripcion"]


class FormularioTipoDocumento(ConMotivo, forms.ModelForm):
    class Meta:
        model = TipoDocumento
        fields = ["nombre", "requiere_vencimiento", "usar_alerta_general", "dias_alerta"]


class FormularioRequisito(ConMotivo, forms.ModelForm):
    class Meta:
        model = Requisito
        fields = ["version", "numero", "grupo", "texto"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["version"].queryset = VersionMatriz.objects.filter(estado="borrador")
        self.fields["version"].required = False
        if self.instance.pk:
            self.fields["version"].queryset = VersionMatriz.objects.filter(pk=self.instance.version_id)
            self.fields["version"].disabled = True

    def clean_version(self):
        return self.cleaned_data["version"] or VersionMatriz.objects.get(numero=1)


class FormularioPeso(ConMotivo, forms.ModelForm):
    class Meta:
        model = Peso
        fields = ["requisito", "categoria", "valor"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for nombre, modelo in (("requisito", Requisito), ("categoria", CategoriaProveedor)):
            self.fields[nombre].queryset = modelo.objects.filter(activo=True)
            if nombre == "requisito":
                self.fields[nombre].queryset = self.fields[nombre].queryset.filter(version__estado="borrador").select_related("version")
                self.fields[nombre].label_from_instance = lambda requisito: f"Versión {requisito.version.numero} · {requisito}"
            if self.instance.pk:
                self.fields[nombre].queryset = modelo.objects.filter(pk=getattr(self.instance, f"{nombre}_id"))
                self.fields[nombre].disabled = True


class FormularioDocumentoExigido(ConMotivo, forms.ModelForm):
    class Meta:
        model = DocumentoExigido
        fields = ["categoria", "tipo", "requisito", "obligatorio"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["requisito"].queryset = Requisito.objects.select_related("version").filter(activo=True)
        self.fields["requisito"].label_from_instance = lambda r: f"V{r.version.numero} · {r}"


FORMULARIOS = {
    "documentos-exigidos": FormularioDocumentoExigido,
    "categorias": FormularioCategoria, "tipos-documento": FormularioTipoDocumento,
    "requisitos": FormularioRequisito, "pesos": FormularioPeso,
}
COLUMNAS = {
    "documentos-exigidos": ["Categoría", "Tipo", "Requisito", "Obligatorio"],
    "categorias": ["Nombre", "Descripción"],
    "tipos-documento": ["Nombre", "Requiere vencimiento", "Alerta"],
    "requisitos": ["Versión", "Número", "Grupo", "Texto"],
    "pesos": ["Requisito", "Categoría", "Peso"],
}


class FiltroFR14(FiltroCatalogo):
    version = forms.ModelChoiceField(label="Versión de matriz", queryset=VersionMatriz.objects.all(), required=False)
    grupo = forms.ChoiceField(label="Grupo", required=False, choices=[("", "Todos los grupos"), *Requisito.Grupo.choices])
    categoria = forms.ModelChoiceField(
        label="Categoría", required=False, queryset=CategoriaProveedor.objects.all(), empty_label="Todas las categorías",
    )

    def __init__(self, *args, catalogo, **kwargs):
        super().__init__(*args, **kwargs)
        if catalogo not in ("requisitos", "pesos"):
            self.fields.pop("grupo")
            self.fields.pop("version")
        if catalogo not in ("pesos", "documentos-exigidos"):
            self.fields.pop("categoria")


def _definicion(catalogo):
    if catalogo not in CATALOGOS:
        raise Http404
    return CATALOGOS[catalogo]


def _valores(catalogo, objeto):
    if catalogo == "documentos-exigidos":
        return [objeto.categoria, objeto.tipo, f"V{objeto.requisito.version.numero} · {objeto.requisito}" if objeto.requisito_id else "General de la categoría", "Sí" if objeto.obligatorio else "No"]
    if catalogo == "categorias":
        return [objeto.nombre, objeto.descripcion or "—"]
    if catalogo == "tipos-documento":
        return [objeto.nombre, "Sí" if objeto.requiere_vencimiento else "No",
                "General" if objeto.usar_alerta_general else f"{objeto.dias_alerta} días"]
    if catalogo == "requisitos":
        return [objeto.version.numero, objeto.numero, objeto.get_grupo_display(), objeto.texto]
    return [f"V{objeto.requisito.version.numero} · {objeto.requisito}", str(objeto.categoria), objeto.valor]


@rol_requerido(*ROLES_ADMIN)
@require_safe
def lista(request, catalogo):
    definicion = _definicion(catalogo)
    consulta = definicion["modelo"].objects.all()
    if catalogo == "pesos":
        consulta = consulta.select_related("requisito__version", "categoria")
    if catalogo == "documentos-exigidos":
        consulta = consulta.select_related("requisito__version", "categoria", "tipo")
    filtro = FiltroFR14(request.GET, catalogo=catalogo)
    if filtro.is_valid():
        datos = filtro.cleaned_data
        if datos.get("version"):
            consulta = consulta.filter(**{"requisito__version" if catalogo == "pesos" else "version": datos["version"]})
        texto = datos["q"]
        if texto:
            if catalogo == "documentos-exigidos":
                consulta = consulta.filter(Q(tipo__nombre__icontains=texto) | Q(categoria__nombre__icontains=texto))
            elif catalogo == "pesos":
                consulta = consulta.filter(Q(requisito__texto__icontains=texto) | Q(categoria__nombre__icontains=texto))
            elif catalogo == "requisitos":
                condicion = Q(texto__icontains=texto)
                if texto.isascii() and texto.isdecimal() and len(texto) < 6:
                    condicion |= Q(numero=int(texto))
                consulta = consulta.filter(condicion)
            else:
                consulta = consulta.filter(nombre__icontains=texto)
        if datos["estado"]:
            activos = Q(requisito__activo=True, categoria__activo=True) if catalogo == "pesos" else Q(activo=True)
            consulta = consulta.filter(activos if datos["estado"] == "activos" else ~activos)
        if datos.get("grupo"):
            consulta = consulta.filter(**{"requisito__grupo" if catalogo == "pesos" else "grupo": datos["grupo"]})
        if datos.get("categoria"):
            consulta = consulta.filter(categoria=datos["categoria"])
    else:
        consulta = consulta.none()
    pagina = Paginator(consulta, 25).get_page(request.GET.get("pagina"))
    filas = [{"objeto": objeto, "valores": _valores(catalogo, objeto)} for objeto in pagina]
    return render(request, "configuracion/catalogos_proveedores.html", {
        "catalogo": catalogo, "titulo": definicion["titulo"], "filtro": filtro, "pagina": pagina,
        "columnas": COLUMNAS[catalogo], "filas": filas, "con_estado": catalogo != "pesos",
    })


@rol_requerido(*ROLES_ADMIN)
@require_http_methods(["GET", "POST"])
def formulario(request, catalogo, pk=None):
    definicion = _definicion(catalogo)
    instancia = get_object_or_404(definicion["modelo"], pk=pk) if pk else definicion["modelo"]()
    form = FORMULARIOS[catalogo](request.POST if request.method == "POST" else None, instance=instancia)
    if request.method == "POST" and form.is_valid():
        try:
            servicios.guardar_catalogo(form.instance, actor=request.user, motivo=form.cleaned_data["motivo"], request=request)
        except ValidationError as error:
            agregar_errores(form, error)
        else:
            messages.success(request, "El registro del catálogo se guardó correctamente.")
            return redirect("configuracion:catalogos_proveedores", catalogo=catalogo)
    return render(request, "configuracion/formulario.html", {
        "formulario": form, "titulo": f"{'Editar' if pk else 'Crear'} {definicion['singular']}",
        "volver": reverse("configuracion:catalogos_proveedores", kwargs={"catalogo": catalogo}), "boton": "Guardar",
    })


@rol_requerido(*ROLES_ADMIN)
@require_http_methods(["GET", "POST"])
def estado(request, catalogo, pk):
    definicion = _definicion(catalogo)
    if catalogo == "pesos":
        raise Http404
    instancia = get_object_or_404(definicion["modelo"], pk=pk)
    form = FormularioMotivo(request.POST if request.method == "POST" else None)
    nuevo_estado = not instancia.activo
    if request.method == "POST" and form.is_valid():
        try:
            servicios.cambiar_estado_catalogo(instancia, nuevo_estado, actor=request.user,
                                              motivo=form.cleaned_data["motivo"], request=request)
        except ValidationError as error:
            agregar_errores(form, error)
        else:
            messages.success(request, "El estado se actualizó correctamente.")
            return redirect("configuracion:catalogos_proveedores", catalogo=catalogo)
    return render(request, "configuracion/confirmar_estado.html", {
        "objeto": instancia, "activar": nuevo_estado, "tipo": definicion["singular"], "formulario": form,
        "volver": reverse("configuracion:catalogos_proveedores", kwargs={"catalogo": catalogo}),
        "nota": "Los registros anteriores y los pesos se conservan. Desactivar impide elegirlo en nuevos registros.",
    })
