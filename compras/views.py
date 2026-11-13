from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST, require_http_methods, require_safe

from compras import forms, servicios
from compras import calificacion_servicios, criterios_servicios, decision_servicios, documental_servicios, cierre_servicios
from compras.models import CierreListaElegibles, DesempateElegibles, ListaElegibles, Necesidad, ParticipanteElegible, TipoOrigen, VersionCriterios
from bitacora.servicios import registrar
from configuracion.forms import FormularioMotivo
from config.utilidades import agregar_errores
from cuentas.models import ROLES_ADMIN
from cuentas.permisos import rol_requerido


@rol_requerido(*ROLES_ADMIN)
@require_safe
def necesidades(request):
    from config.listados import preparar, excel
    filtro, consulta = preparar("necesidades", request.GET, request.user)
    consulta = consulta.select_related("area", "responsable").prefetch_related("listas")
    if request.GET.get("formato") == "excel" and filtro.is_valid():
        return excel(consulta, "necesidades")
    return render(request, "compras/necesidades.html", {"filtro": filtro, "pagina": Paginator(consulta, 25).get_page(request.GET.get("pagina"))})


@rol_requerido(*ROLES_ADMIN)
@require_http_methods(["GET", "POST"])
def necesidad_nueva(request):
    datos_filtro = request.GET if request.method == "GET" else {"area": request.POST.get("area"), "periodo": request.POST.get("periodo")}
    filtro = forms.FiltroLineas(datos_filtro)
    lineas = servicios.lineas_disponibles().none()
    inicial, periodo_id = {}, ""
    if filtro.is_valid() and filtro.cleaned_data["area"]:
        inicial["area"] = filtro.cleaned_data["area"]
        periodo = filtro.cleaned_data["periodo"]
        periodo_id = periodo.pk if periodo else ""
        lineas = servicios.lineas_disponibles(area=filtro.cleaned_data["area"], periodo=periodo)
    formulario = forms.FormularioNecesidad(request.POST if request.method == "POST" else None, initial=inicial)
    origenes = forms.OrigenesFormSet(request.POST if request.method == "POST" else None, prefix="origenes", form_kwargs={"lineas": lineas})
    if request.method == "POST" and formulario.is_valid() and origenes.is_valid() and filtro.is_valid():
        seleccion = [(f.cleaned_data["linea"].pk, f.cleaned_data["cantidad"]) for f in origenes if f.cleaned_data.get("linea") and not f.cleaned_data.get("DELETE")]
        try:
            necesidad = servicios.crear_necesidad(actor=request.user, lineas=seleccion, **formulario.cleaned_data)
        except ValidationError as error:
            agregar_errores(formulario, error)
        else:
            return redirect("compras:necesidad_detalle", pk=necesidad.pk)
    return render(request, "compras/necesidad_nueva.html", {"filtro": filtro, "formulario": formulario, "origenes": origenes, "periodo_id": periodo_id})


@rol_requerido(*ROLES_ADMIN)
@require_http_methods(["GET", "POST"])
def necesidad_detalle(request, pk):
    necesidad = get_object_or_404(Necesidad.objects.select_related("area", "responsable", "tipo_origen"), pk=pk)
    formulario = forms.FormularioLista(request.POST if request.method == "POST" else None)
    if request.method == "POST" and formulario.is_valid():
        try:
            lista = servicios.crear_lista(necesidad, actor=request.user, **formulario.cleaned_data)
        except ValidationError as error:
            agregar_errores(formulario, error)
        else:
            return redirect("compras:lista_detalle", pk=lista.pk)
    return render(request, "compras/necesidad_detalle.html", {"necesidad": necesidad, "formulario": formulario, "origenes": necesidad.origenes.select_related("linea__proyeccion"), "base": decision_servicios.cantidad_necesidad(necesidad)})


@rol_requerido(*ROLES_ADMIN)
@require_http_methods(["GET", "POST"])
def lista_detalle(request, pk):
    lista = get_object_or_404(ListaElegibles.objects.select_related("necesidad__area"), pk=pk)
    formulario = forms.FormularioParticipante(request.POST if request.method == "POST" else None)
    if request.method == "POST" and formulario.is_valid():
        try:
            servicios.agregar_participante(lista, actor=request.user, **formulario.cleaned_data)
        except ValidationError as error:
            agregar_errores(formulario, error)
        else:
            return redirect("compras:lista_detalle", pk=pk)
    return render(request, "compras/lista_detalle.html", {"lista": lista, "formulario": formulario,
        "participantes": lista.participantes.filter(activo=True),
        "cierre_form": forms.FormularioCierre(prefix="cierre", initial={"justificacion_documental": lista.justificacion_documental}),
        "reapertura_form": FormularioMotivo(prefix="reapertura"), "anulacion_form": FormularioMotivo(prefix="anulacion")})


@rol_requerido(*ROLES_ADMIN)
@require_POST
def participante_quitar(request, pk, participante_pk):
    lista = get_object_or_404(ListaElegibles, pk=pk)
    participante = get_object_or_404(ParticipanteElegible, pk=participante_pk, lista=lista)
    formulario = FormularioMotivo(request.POST)
    if formulario.is_valid():
        try:
            servicios.quitar_participante(lista, participante, actor=request.user, motivo=formulario.cleaned_data["motivo"])
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
    else:
        messages.error(request, "Indique el motivo del retiro.")
    return redirect("compras:lista_detalle", pk=pk)


@rol_requerido(*ROLES_ADMIN)
@require_http_methods(["GET", "POST"])
def origenes(request, pk=None):
    tipo = get_object_or_404(TipoOrigen, pk=pk) if pk else TipoOrigen()
    formulario = forms.FormularioTipoOrigen(request.POST if request.method == "POST" else None, instance=tipo)
    if request.method == "POST" and formulario.is_valid():
        try:
            servicios.guardar_tipo_origen(formulario.instance, actor=request.user, motivo=formulario.cleaned_data["motivo"])
        except ValidationError as error:
            agregar_errores(formulario, error)
        else:
            return redirect("compras:origenes")
    return render(request, "compras/origenes.html", {"tipos": TipoOrigen.objects.all(), "formulario": formulario})


@rol_requerido(*ROLES_ADMIN)
@require_safe
def versiones_criterios(request):
    return render(request, "compras/criterios_versiones.html", {"versiones": VersionCriterios.objects.all()})


def _contexto_version(version, formulario=None, filas=None, publicacion=None):
    return {"version": version,
            "formulario": formulario if formulario is not None else forms.FormularioVersion(prefix="edicion", initial={"notas": version.notas}),
            "filas": filas if filas is not None else forms.CriteriosFormSet(prefix="criterios", initial=list(version.criterios.values("nombre", "peso"))),
            "publicacion": publicacion if publicacion is not None else forms.FormularioPublicacion(prefix="publicacion")}


@rol_requerido(*ROLES_ADMIN)
@require_http_methods(["GET", "POST"])
def version_criterios_detalle(request, pk):
    version = get_object_or_404(VersionCriterios, pk=pk)
    if request.method == "POST":
        formulario = forms.FormularioVersion(request.POST, prefix="edicion")
        filas = forms.CriteriosFormSet(request.POST, prefix="criterios")
        if formulario.is_valid() and filas.is_valid():
            criterios = [{"nombre": f.cleaned_data["nombre"], "peso": f.cleaned_data["peso"]} for f in filas if f.cleaned_data and not f.cleaned_data.get("DELETE")]
            try:
                criterios_servicios.guardar_borrador(version, criterios=criterios, actor=request.user, **formulario.cleaned_data)
            except ValidationError as error:
                agregar_errores(formulario, error)
            else:
                messages.success(request, "Criterios guardados. Los pesos suman 100 %.")
                return redirect("compras:version_criterios_detalle", pk=pk)
        return render(request, "compras/criterios_detalle.html", _contexto_version(version, formulario, filas))
    return render(request, "compras/criterios_detalle.html", _contexto_version(version))


@rol_requerido(*ROLES_ADMIN)
@require_POST
def version_criterios_copiar(request, pk):
    version = get_object_or_404(VersionCriterios, pk=pk)
    formulario = FormularioMotivo(request.POST)
    if formulario.is_valid():
        try:
            nueva = criterios_servicios.copiar_version(version, actor=request.user, motivo=formulario.cleaned_data["motivo"])
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        else:
            return redirect("compras:version_criterios_detalle", pk=nueva.pk)
    else:
        messages.error(request, "Indique el motivo de la copia.")
    return redirect("compras:versiones_criterios")


@rol_requerido(*ROLES_ADMIN)
@require_POST
def version_criterios_publicar(request, pk):
    version = get_object_or_404(VersionCriterios, pk=pk)
    publicacion = forms.FormularioPublicacion(request.POST, prefix="publicacion")
    if publicacion.is_valid():
        try:
            criterios_servicios.publicar_version(version, actor=request.user, **publicacion.cleaned_data)
        except ValidationError as error:
            agregar_errores(publicacion, error)
        else:
            messages.success(request, "Versión publicada. Sus criterios quedan conservados.")
            return redirect("compras:version_criterios_detalle", pk=pk)
    return render(request, "compras/criterios_detalle.html", _contexto_version(version, publicacion=publicacion))


@rol_requerido(*ROLES_ADMIN)
@require_POST
def lista_configurar(request, pk):
    lista = get_object_or_404(ListaElegibles, pk=pk)
    formulario = forms.FormularioVersionLista(request.POST, lista=lista)
    if formulario.is_valid():
        try:
            criterios_servicios.configurar_lista(lista, actor=request.user, **formulario.cleaned_data)
        except ValidationError as error:
            agregar_errores(formulario, error)
        else:
            return redirect("compras:lista_calificar", pk=pk)
    return render(request, "compras/calificar.html", {"lista": lista, "configuracion": formulario})


@rol_requerido(*ROLES_ADMIN)
@require_http_methods(["GET", "POST"])
def lista_calificar(request, pk):
    lista = get_object_or_404(ListaElegibles.objects.select_related("necesidad", "version_criterios"), pk=pk)
    if not lista.version_criterios_id:
        return render(request, "compras/calificar.html", {"lista": lista, "configuracion": forms.FormularioVersionLista(lista=lista)})
    matriz = calificacion_servicios.obtener_matriz(lista)
    formulario = forms.FormularioMatriz(request.POST if request.method == "POST" else None, lista=lista, matriz=matriz)
    if request.method == "POST" and formulario.is_valid():
        try:
            calificacion_servicios.guardar_matriz(lista, formulario.valores(), actor=request.user, motivo=formulario.cleaned_data["motivo"])
        except ValidationError as error:
            agregar_errores(formulario, error)
        else:
            messages.success(request, "Calificaciones guardadas. Los totales se calcularon en el servidor.")
            return redirect("compras:lista_calificar", pk=pk)
    return render(request, "compras/calificar.html", {"lista": lista, "matriz": matriz, "formulario": formulario})


@rol_requerido(*ROLES_ADMIN)
@require_http_methods(["GET", "POST"])
def necesidad_cantidad(request, pk):
    necesidad = get_object_or_404(Necesidad, pk=pk)
    base = decision_servicios.cantidad_necesidad(necesidad)
    formulario = forms.FormularioCantidadBase(request.POST if request.method == "POST" else None,
        initial={"cantidad_base": base["cantidad"], "unidad_base": base["unidad"]})
    if request.method == "POST" and formulario.is_valid():
        try:
            decision_servicios.definir_cantidad(necesidad, actor=request.user, **formulario.cleaned_data)
        except ValidationError as error:
            agregar_errores(formulario, error)
        else:
            return redirect("compras:necesidad_detalle", pk=pk)
    return render(request, "compras/cantidad_base.html", {"necesidad": necesidad, "base": base, "formulario": formulario})


@rol_requerido(*ROLES_ADMIN)
@require_http_methods(["GET", "POST"])
def lista_decision(request, pk):
    lista = get_object_or_404(ListaElegibles.objects.select_related("necesidad", "version_criterios"), pk=pk)
    resultado = decision_servicios.obtener_puestos(lista)
    decision = decision_servicios.estado_decision(lista, resultado)
    formulario = forms.FormularioDecision(request.POST if request.method == "POST" else None, lista=lista, resultado=resultado, decision=decision)
    if request.method == "POST" and formulario.is_valid():
        try:
            decision_servicios.guardar_decision(lista, formulario.valores(), justificacion_unico=formulario.cleaned_data["justificacion_unico"],
                justificacion_cantidad=formulario.cleaned_data["justificacion_cantidad"], actor=request.user, motivo=formulario.cleaned_data["motivo"])
        except ValidationError as error:
            agregar_errores(formulario, error)
        else:
            messages.success(request, "Decisión registrada con cantidades, justificaciones y responsable.")
            return redirect("compras:lista_decision", pk=pk)
    for grupo in resultado["empates"]:
        grupo["formulario"] = forms.FormularioDesempate(grupo=grupo)
    return render(request, "compras/decision.html", {"lista": lista, "resultado": resultado, "decision": decision, "formulario": formulario})


@rol_requerido(*ROLES_ADMIN)
@require_POST
def lista_desempatar(request, pk):
    lista = get_object_or_404(ListaElegibles, pk=pk)
    try:
        total = Decimal(request.POST.get("total", ""))
        if not total.is_finite():
            raise ValueError
    except (InvalidOperation, ValueError):
        total = None
    grupo = next((g for g in decision_servicios.obtener_puestos(lista)["empates"] if g["total"] == total), None)
    if grupo is None:
        messages.error(request, "El empate cambió. Recargue la decisión.")
        return redirect("compras:lista_decision", pk=pk)
    formulario = forms.FormularioDesempate(request.POST, grupo=grupo)
    if formulario.is_valid():
        try:
            decision_servicios.guardar_desempate(lista, orden=formulario.orden(), justificacion=formulario.cleaned_data["justificacion"],
                actor=request.user, motivo=formulario.cleaned_data["motivo"], total_esperado=total)
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        else:
            messages.success(request, "Desempate registrado. Revise y guarde la decisión.")
    else:
        messages.error(request, "Revise el orden, la justificación y el motivo del desempate.")
    return redirect("compras:lista_decision", pk=pk)


@rol_requerido(*ROLES_ADMIN)
@require_POST
def lista_restablecer_empate(request, pk, desempate_pk):
    lista = get_object_or_404(ListaElegibles, pk=pk)
    desempate = get_object_or_404(DesempateElegibles, pk=desempate_pk, lista=lista)
    formulario = FormularioMotivo(request.POST)
    if formulario.is_valid():
        try:
            decision_servicios.restablecer_empate(lista, desempate, actor=request.user, motivo=formulario.cleaned_data["motivo"])
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
    else:
        messages.error(request, "Indique el motivo para restablecer el empate.")
    return redirect("compras:lista_decision", pk=pk)


@rol_requerido(*ROLES_ADMIN)
@require_safe
@transaction.atomic
def lista_exportar(request, pk):
    from compras.exportar_elegibles import exportar_lista
    lista = get_object_or_404(ListaElegibles, pk=pk)
    Necesidad.objects.select_for_update().get(pk=lista.necesidad_id)
    lista = ListaElegibles.objects.select_for_update().get(pk=pk)
    resultado = decision_servicios.obtener_puestos(lista)
    decision = decision_servicios.estado_decision(lista, resultado)
    contenido = exportar_lista(lista, resultado, decision, documental_servicios.obtener_control(lista))
    registrar("elegibles.exportados", actor=request.user, objeto=lista,
        nuevo={"participantes": len(resultado["filas"]), "decision_vigente": decision["vigente"]}, motivo="Exportación de lista a Excel", request=request)
    respuesta = HttpResponse(contenido, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    respuesta["Content-Disposition"] = f'attachment; filename="lista-elegibles-{lista.pk}.xlsx"'
    respuesta["Cache-Control"] = "private, no-store"
    return respuesta


@rol_requerido(*ROLES_ADMIN)
@require_http_methods(["GET", "POST"])
def lista_documental(request, pk):
    lista = get_object_or_404(ListaElegibles, pk=pk)
    formulario = forms.FormularioRevisionDocumental(request.POST if request.method == "POST" else None,
        initial={"justificacion": lista.justificacion_documental})
    if request.method == "POST" and formulario.is_valid():
        try:
            documental_servicios.guardar_justificacion(lista, actor=request.user, **formulario.cleaned_data)
        except ValidationError as error:
            agregar_errores(formulario, error)
        else:
            messages.success(request, "Revisión documental comprobada y justificación guardada. Se volverá a comprobar al cerrar.")
            return redirect("compras:lista_documental", pk=pk)
    control = documental_servicios.obtener_control(lista)
    return render(request, "compras/documental.html", {"lista": lista, "control": control, "formulario": formulario})


@rol_requerido(*ROLES_ADMIN)
@require_POST
def lista_cerrar(request, pk):
    lista = get_object_or_404(ListaElegibles, pk=pk)
    formulario = forms.FormularioCierre(request.POST, prefix="cierre")
    if formulario.is_valid():
        try:
            cierre_servicios.cerrar_lista(lista, actor=request.user, **formulario.cleaned_data)
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        else:
            messages.success(request, "Lista cerrada. Se conservaron resultados, decisión y estado documental.")
    else:
        messages.error(request, "Revise la justificación documental y el motivo del cierre.")
    return redirect("compras:lista_detalle", pk=pk)


@rol_requerido(*ROLES_ADMIN)
@require_POST
def lista_reabrir(request, pk):
    lista = get_object_or_404(ListaElegibles, pk=pk)
    formulario = FormularioMotivo(request.POST, prefix="reapertura")
    if formulario.is_valid():
        try:
            cierre_servicios.reabrir_lista(lista, actor=request.user, motivo=formulario.cleaned_data["motivo"])
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        else:
            messages.success(request, "Lista reabierta. Revise la decisión y los documentos antes de cerrarla otra vez.")
    else:
        messages.error(request, "Indique el motivo de la reapertura.")
    return redirect("compras:lista_detalle", pk=pk)


@rol_requerido(*ROLES_ADMIN)
@require_POST
def lista_anular(request, pk):
    lista = get_object_or_404(ListaElegibles, pk=pk)
    formulario = FormularioMotivo(request.POST, prefix="anulacion")
    if formulario.is_valid():
        try:
            cierre_servicios.anular_lista(lista, actor=request.user, motivo=formulario.cleaned_data["motivo"])
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
        else:
            messages.success(request, "Lista anulada. Sus datos y cierres históricos se conservan.")
    else:
        messages.error(request, "Indique el motivo de la anulación.")
    return redirect("compras:lista_detalle", pk=pk)


@rol_requerido(*ROLES_ADMIN)
@require_safe
def cotizacion_iniciar(request, pk):
    from compras.cotizacion_views import nueva
    return nueva(request, lista_pk=pk)


@rol_requerido(*ROLES_ADMIN)
@require_safe
def lista_cierre_detalle(request, pk, cierre_pk):
    lista = get_object_or_404(ListaElegibles, pk=pk)
    cierre = get_object_or_404(CierreListaElegibles.objects.select_related("actor"), lista=lista, pk=cierre_pk)
    return render(request, "compras/cierre_detalle.html", {"lista": lista, "cierre": cierre, "foto": cierre.contenido["resultado"], "documental": cierre.contenido["documental"]})
