from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST, require_safe

from bitacora.servicios import registrar
from compras import comparativo, decision_cotizacion_forms as forms, decision_cotizacion_servicios as servicios
from compras.exportar_cotizacion import exportar
from compras.models import Cotizacion, DecisionCotizacion
from config.utilidades import agregar_errores
from cuentas.models import ROLES_ADMIN
from cuentas.permisos import rol_requerido


@rol_requerido(*ROLES_ADMIN)
@never_cache
@require_http_methods(["GET", "POST"])
def comparar(request, pk):
    cotizacion = get_object_or_404(Cotizacion, pk=pk)
    vigente = cotizacion.decisiones.exclude(estado="anulada").first()
    datos = vigente.contenido["comparativo"] if vigente else comparativo.construir(cotizacion, actor=request.user)
    editable = cotizacion.estado in ("borrador", "en_comparacion") and vigente is None
    formulario = forms.FormularioDecision(request.POST if request.method == "POST" else None, datos=datos, initial={"modalidad": servicios.modalidad_inicial()})
    if request.method == "POST":
        if not editable:
            messages.error(request, "Anule la decisión vigente antes de proponer cambios.")
            return redirect("compras:cotizacion_comparar", pk=pk)
        if formulario.is_valid():
            d = formulario.cleaned_data
            try:
                decision = servicios.proponer_decision(cotizacion, modalidad=d["modalidad"], oferta_id=d["oferta_id"] if d["modalidad"] == "completa" else None,
                    selecciones=[{"linea_id": f["id"], "oferta_id": d[f"seleccion_{f['id']}"]} for f in datos["filas"]] if d["modalidad"] == "lineas" else None,
                    recomendacion=d["recomendacion"], motivo_eleccion=d["motivo_eleccion"], justificacion_verificaciones=d["justificacion_verificaciones"],
                    huella_esperada=formulario.identidad["huella"], actor=request.user, motivo=d["motivo"])
            except ValidationError as error:
                agregar_errores(formulario, error)
            else:
                return redirect("compras:cotizacion_decision", pk=pk, decision_pk=decision.pk)
    return render(request, "compras/cotizacion_comparar.html", {"cotizacion": cotizacion, "datos": datos, "vigente": vigente,
        "editable": editable, "formulario": formulario, "decisiones": cotizacion.decisiones.all()})


@rol_requerido(*ROLES_ADMIN)
@never_cache
@require_safe
def detalle(request, pk, decision_pk):
    decision = get_object_or_404(DecisionCotizacion.objects.select_related("cotizacion", "propuesta_por", "decidido_por", "anulada_por"), pk=decision_pk, cotizacion_id=pk)
    return render(request, "compras/cotizacion_decision.html", {"decision": decision, "datos": decision.contenido["comparativo"],
        "formulario_aprobar": forms.FormularioAccion(auto_id="id_aprobar_%s"),
        "formulario_anular": forms.FormularioAccion(auto_id="id_anular_%s"), "aprobaciones": decision.aprobaciones.select_related("actor")})


@rol_requerido(*ROLES_ADMIN)
@require_POST
def actuar(request, pk, decision_pk, accion):
    from django.http import Http404
    if accion not in ("aprobar", "anular"):
        raise Http404("Acción no encontrada.")
    decision = get_object_or_404(DecisionCotizacion, pk=decision_pk, cotizacion_id=pk)
    formulario = forms.FormularioAccion(request.POST)
    if formulario.is_valid():
        try:
            servicio = servicios.aprobar_decision if accion == "aprobar" else servicios.anular_decision
            servicio(decision, actor=request.user, motivo=formulario.cleaned_data["motivo"])
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        else:
            messages.success(request, "Aprobación registrada." if accion == "aprobar" else "Decisión anulada; la cotización admite cambios con historial conservado.")
    else:
        messages.error(request, "Indique el motivo de la operación.")
    return redirect("compras:cotizacion_decision", pk=pk, decision_pk=decision_pk)


@rol_requerido(*ROLES_ADMIN)
@never_cache
@require_safe
def excel(request, pk, decision_pk=None):
    cotizacion = get_object_or_404(Cotizacion, pk=pk)
    decision = get_object_or_404(DecisionCotizacion, pk=decision_pk, cotizacion=cotizacion) if decision_pk else cotizacion.decisiones.exclude(estado="anulada").first()
    datos = decision.contenido["comparativo"] if decision else comparativo.construir(cotizacion, actor=request.user)
    respuesta = HttpResponse(exportar(datos, decision), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    respuesta["Content-Disposition"] = f'attachment; filename="comparativo-{cotizacion.consecutivo}.xlsx"'
    registrar("cotizacion.comparativo_exportado", actor=request.user, objeto=cotizacion, nuevo={"decision_id": decision.pk if decision else None}, motivo="Exportación del comparativo", request=request)
    return respuesta
