from django import forms
from django.core.files.storage import default_storage
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_safe

from config.utilidades import agregar_errores
from configuracion.forms import ConMotivo
from cuentas.models import ROLES_ADMIN
from cuentas.permisos import rol_requerido
from proveedores import archivos
from proveedores.models import DocumentoProveedor, EvaluacionProveedor, EvidenciaEvaluacion, Peso, RespuestaEvaluacion
from proveedores.respuestas_servicios import guardar_respuesta


class FormularioRespuesta(ConMotivo, forms.Form):
    respuesta = forms.ChoiceField(label="Respuesta", choices=[("", "Seleccione una respuesta"), *RespuestaEvaluacion.Valor.choices])
    observacion = forms.CharField(label="Observación", required=False, widget=forms.Textarea)
    confirma_na = forms.BooleanField(label="Confirmo que este requisito no aplica", required=False)
    documento = forms.ModelChoiceField(label="Documento del proveedor", queryset=DocumentoProveedor.objects.none(), required=False)
    archivo = forms.FileField(label="PDF de evidencia (opcional)", required=False, widget=forms.FileInput(attrs={"accept": ".pdf"}))
    quitar_pdf = forms.BooleanField(label="Desvincular el PDF actual (se conserva en el historial)", required=False)

    def __init__(self, *args, evaluacion, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["documento"].queryset = DocumentoProveedor.objects.filter(proveedor=evaluacion.proveedor).select_related("tipo")
        from proveedores.documental import clasificar, ETIQUETAS
        from proveedores.servicios import dias_alerta, dias_alerta_tipo
        general = dias_alerta()
        def etiqueta_documento(doc):
            estado = clasificar(expedicion=doc.fecha_expedicion, vencimiento=doc.fecha_vencimiento,
                                referencia=evaluacion.fecha, dias=dias_alerta_tipo(doc.tipo, general),
                                requiere_vencimiento=doc.tipo.requiere_vencimiento)
            return f"{doc} · {ETIQUETAS[estado]} al {evaluacion.fecha:%d/%m/%Y}"
        self.fields["documento"].label_from_instance = etiqueta_documento

    def clean_archivo(self):
        archivo = self.cleaned_data.get("archivo")
        if archivo:
            archivos.validar_pdf(archivo)
        return archivo

    def clean(self):
        datos = super().clean()
        if datos.get("respuesta") == "na" and (not datos.get("confirma_na") or not datos.get("observacion", "").strip()):
            self.add_error("confirma_na", "Confirme que no aplica y escriba una observación.")
        return datos


@rol_requerido(*ROLES_ADMIN)
@never_cache
@require_http_methods(["GET", "POST"])
def responder(request, pk, requisito_pk):
    evaluacion = get_object_or_404(EvaluacionProveedor.objects.select_related("proveedor", "version"), pk=pk)
    if evaluacion.estado != "borrador":
        raise PermissionDenied("Esta evaluación es de solo lectura. Cree una copia para corregirla.")
    peso = get_object_or_404(Peso.objects.select_related("requisito"), requisito_id=requisito_pk,
                             requisito__version=evaluacion.version, requisito__activo=True, categoria=evaluacion.categoria)
    actual = evaluacion.respuestas.filter(requisito=peso.requisito).first()
    inicial = {c: getattr(actual, c) for c in ("respuesta", "observacion", "confirma_na", "documento")} if actual else {}
    formulario = FormularioRespuesta(request.POST if request.method == "POST" else None, request.FILES or None,
                                      evaluacion=evaluacion, initial=inicial)
    if request.method == "POST" and formulario.is_valid():
        try:
            registro = guardar_respuesta(evaluacion, peso.requisito, actor=request.user, request=request, **formulario.cleaned_data)
        except ValidationError as error:
            agregar_errores(formulario, error)
        else:
            from django.contrib import messages
            for advertencia in registro.control_documental.get("advertencias", []):
                messages.warning(request, advertencia)
            return redirect("proveedores:evaluacion_detalle", pk=pk)
    return render(request, "proveedores/respuesta.html", {"evaluacion": evaluacion, "peso": peso, "actual": actual, "formulario": formulario})


@rol_requerido(*ROLES_ADMIN)
@never_cache
@require_safe
def descargar(request, pk, adjunto_pk):
    adjunto = get_object_or_404(EvidenciaEvaluacion, pk=adjunto_pk, evaluacion_id=pk)
    try:
        archivo = adjunto.archivo.open("rb")
    except FileNotFoundError:
        raise Http404("La evidencia no está disponible.") from None
    respuesta = FileResponse(archivo, as_attachment=True, filename=adjunto.nombre_archivo, content_type="application/pdf")
    respuesta["X-Content-Type-Options"] = "nosniff"
    respuesta["Cache-Control"] = "private, no-store"
    return respuesta


@rol_requerido(*ROLES_ADMIN)
@never_cache
@require_safe
def documento_descargar(request, pk, respuesta_pk):
    registro = get_object_or_404(RespuestaEvaluacion, pk=respuesta_pk, evaluacion_id=pk)
    nombre = registro.documento_datos.get("archivo")
    if not nombre:
        raise Http404("La evidencia documental no tiene PDF.")
    try:
        archivo = default_storage.open(nombre, "rb")
    except FileNotFoundError:
        raise Http404("La evidencia no está disponible.") from None
    respuesta = FileResponse(archivo, as_attachment=True, filename="evidencia-documental.pdf", content_type="application/pdf")
    respuesta["X-Content-Type-Options"] = "nosniff"
    respuesta["Cache-Control"] = "private, no-store"
    return respuesta
