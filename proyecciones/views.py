"""Vistas de periodos, proyección del coordinador y revisión por administración."""

from decimal import Decimal

from django.contrib import messages
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST, require_http_methods, require_safe

from areas.models import Area
from config.utilidades import agregar_errores
from cuentas.models import ROLES_ADMIN, Rol
from cuentas.permisos import rol_requerido
from proyecciones import consolidado, exportar, forms, servicios
from proyecciones.models import CAMPOS_AJUSTABLES, Ajuste, Linea, Periodo, ProductoSugerido, ProyeccionArea, UnidadMedida

CLAVE_IMPORTACION = "proyecciones_importacion"


@rol_requerido(*ROLES_ADMIN, Rol.COORDINADOR)
@require_safe
def plantilla_excel(request):
    from proyecciones.importar import plantilla_excel as generar_plantilla

    respuesta = HttpResponse(
        generar_plantilla(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    respuesta["Content-Disposition"] = 'attachment; filename="plantilla-proyecciones.xlsx"'
    respuesta["Cache-Control"] = "private, no-store"
    respuesta["X-Content-Type-Options"] = "nosniff"
    return respuesta


@rol_requerido(*ROLES_ADMIN, Rol.COORDINADOR)
@require_http_methods(["GET", "POST"])
def importar_excel(request, pk):
    proyeccion = get_object_or_404(ProyeccionArea.objects.select_related("periodo", "area"), pk=pk)
    volver = reverse(
        "proyecciones:mi_proyeccion_detalle" if request.user.rol == Rol.COORDINADOR
        else "proyecciones:revision_detalle", args=[pk],
    )
    try:
        servicios.validar_importacion(proyeccion, request.user)
    except ValidationError as error:
        messages.error(request, _texto_error(error))
        return redirect(volver)
    previa = request.session.get(CLAVE_IMPORTACION)
    if previa and (previa["proyeccion"] != pk or previa["actor"] != request.user.pk):
        previa = None
    formulario = forms.FormularioImportacion()
    confirmar = forms.FormularioConfirmarImportacion(initial={"token": previa["token"]}) if previa else None
    if request.method == "POST":
        if request.POST.get("accion") == "confirmar":
            confirmar = forms.FormularioConfirmarImportacion(request.POST)
            if confirmar.is_valid():
                if not previa or confirmar.cleaned_data["token"] != previa["token"]:
                    raise PermissionDenied("La vista previa no corresponde a esta carga.")
                try:
                    cantidad = servicios.confirmar_importacion(
                        proyeccion, previa, actor=request.user, modo=confirmar.cleaned_data["modo"],
                        motivo=confirmar.cleaned_data["motivo"], request=request,
                    )
                except ValidationError as error:
                    confirmar.add_error(None, _texto_error(error))
                else:
                    request.session.pop(CLAVE_IMPORTACION, None)
                    messages.success(request, f"Se importaron {cantidad} líneas correctamente.")
                    return redirect(volver)
        else:
            # Una carga nueva invalida la vista previa anterior, aunque el archivo resulte inválido.
            request.session.pop(CLAVE_IMPORTACION, None)
            previa, confirmar = None, None
            formulario = forms.FormularioImportacion(request.POST, request.FILES)
            if formulario.is_valid():
                try:
                    previa = servicios.preparar_importacion(proyeccion, formulario.cleaned_data["archivo"], actor=request.user)
                except ValidationError as error:
                    formulario.add_error("archivo", _texto_error(error))
                else:
                    request.session[CLAVE_IMPORTACION] = previa
                    confirmar = forms.FormularioConfirmarImportacion(initial={"token": previa["token"]})
    filas = []
    if previa:
        unidades = dict(UnidadMedida.objects.values_list("pk", "abreviatura"))
        for fila in previa["filas"]:
            datos = fila["datos"]
            total = sum(datos[c] for c in servicios.CAMPOS_CANTIDADES_MENSUALES)
            filas.append({**fila, "unidad": unidades.get(datos["unidad_id"], "Unidad inactiva o eliminada"),
                          "cantidades": [datos[c] for c in servicios.CAMPOS_CANTIDADES_MENSUALES],
                          "total": total, "costo": Decimal(datos["costo_proyectado_total"]) if datos.get("costo_proyectado_total") is not None else total * Decimal(datos["precio_estimado"])})
    return render(request, "proyecciones/importar.html", {
        "proyeccion": proyeccion, "volver": volver, "formulario": formulario,
        "confirmar": confirmar, "previa": previa, "filas": filas,
    })


solo_administradores = rol_requerido(*ROLES_ADMIN)
solo_coordinadores = rol_requerido(Rol.COORDINADOR)


_agregar_errores = agregar_errores


def _texto_error(error):
    if hasattr(error, "message_dict"):
        return " ".join(str(mensaje) for mensajes in error.message_dict.values() for mensaje in mensajes)
    return " ".join(error.messages)


def _contexto_periodos(formulario=None):
    periodos = list(Periodo.objects.select_related("creado_por").order_by("-anio"))
    for periodo in periodos:
        periodo.areas_sin_proyeccion = servicios.areas_sin_proyeccion(periodo)
        periodo.proyecciones_creadas = ProyeccionArea.objects.filter(periodo=periodo).count()
    return {
        "formulario": formulario or forms.FormularioAbrirPeriodo(),
        "periodos": periodos,
    }


@solo_administradores
@require_http_methods(["GET", "POST"])
def abrir_periodo(request):
    """Abre un periodo y crea sus proyecciones borrador."""
    formulario = forms.FormularioAbrirPeriodo(request.POST or None)
    if request.method == "POST" and formulario.is_valid():
        try:
            periodo = servicios.abrir_periodo(
                formulario.cleaned_data["anio"],
                formulario.cleaned_data["fecha_limite"],
                actor=request.user,
                motivo=formulario.cleaned_data["motivo"],
                request=request,
            )
        except ValidationError as error:
            _agregar_errores(formulario, error)
        else:
            cantidad = ProyeccionArea.objects.filter(periodo=periodo).count()
            messages.success(
                request,
                f"Periodo {periodo.anio} abierto. Se crearon {cantidad} proyección(es) en borrador.",
            )
            return redirect("proyecciones:abrir_periodo")
    return render(request, "proyecciones/abrir_periodo.html", _contexto_periodos(formulario))


@solo_administradores
@require_POST
def periodo_estado(request, pk):
    """Cierra un periodo abierto o reabre uno cerrado desde la sección de periodos."""
    periodo = get_object_or_404(Periodo, pk=pk)
    formulario = forms.FormularioMotivo(request.POST)
    if not formulario.is_valid():
        messages.error(request, "Indique el motivo del cambio para continuar.")
        return redirect("proyecciones:abrir_periodo")
    try:
        if periodo.estado == Periodo.Estado.ABIERTO:
            periodo = servicios.cerrar_periodo(
                periodo,
                actor=request.user,
                motivo=formulario.cleaned_data["motivo"],
                request=request,
            )
            accion = "cerrado"
        else:
            periodo = servicios.reabrir_periodo(
                periodo,
                actor=request.user,
                motivo=formulario.cleaned_data["motivo"],
                request=request,
            )
            accion = "reabierto"
    except ValidationError as error:
        messages.error(request, _texto_error(error))
    else:
        messages.success(request, f"Periodo {periodo.anio} {accion} correctamente.")
    return redirect("proyecciones:abrir_periodo")


@solo_administradores
@require_POST
def crear_proyeccion_area(request, periodo_pk, area_pk):
    """Completa, con confirmación del administrador, una proyección faltante."""
    periodo = get_object_or_404(Periodo, pk=periodo_pk)
    area = get_object_or_404(Area, pk=area_pk)
    formulario = forms.FormularioMotivo(request.POST)
    if not formulario.is_valid():
        messages.error(request, "Indique el motivo para crear la proyección.")
        return redirect("proyecciones:abrir_periodo")
    try:
        servicios.crear_proyeccion_area(
            periodo,
            area,
            actor=request.user,
            motivo=formulario.cleaned_data["motivo"],
            request=request,
        )
    except ValidationError as error:
        messages.error(request, _texto_error(error))
    else:
        messages.success(request, f"Se creó la proyección en borrador para «{area.nombre}».")
    return redirect("proyecciones:abrir_periodo")


def _proyeccion_para_coordinador(usuario, pk=None):
    consulta = (
        ProyeccionArea.objects.filter(area_id=usuario.area_id)
        .select_related("periodo", "area")
        .prefetch_related("lineas__unidad")
        .order_by("-periodo__anio")
    )
    if pk is not None:
        return get_object_or_404(consulta, pk=pk)
    return consulta.filter(periodo__estado=Periodo.Estado.ABIERTO).first() or consulta.first()


def _error_formset(formset, error):
    mensajes = error.messages if not hasattr(error, "message_dict") else [
        mensaje for mensajes in error.message_dict.values() for mensaje in mensajes
    ]
    formset._non_form_errors = formset.error_class(mensajes)


@solo_coordinadores
@require_http_methods(["GET", "POST"])
def mi_proyeccion(request, pk=None):
    """Edita o consulta únicamente la proyección propia del coordinador."""
    proyeccion = _proyeccion_para_coordinador(request.user, pk)
    area = request.user.area
    proyecciones = list(
        ProyeccionArea.objects.filter(area_id=request.user.area_id)
        .select_related("periodo", "area")
        .prefetch_related("lineas__unidad")
        .order_by("-periodo__anio")
    )
    editable = bool(
        proyeccion
        and proyeccion.periodo.estado == Periodo.Estado.ABIERTO
        and proyeccion.estado == ProyeccionArea.Estado.BORRADOR
    )
    formset = forms.formulario_lineas(proyeccion) if proyeccion and request.method == "GET" and editable else None
    motivo_form = forms.FormularioMotivo()

    if request.method == "POST":
        if proyeccion is None:
            return render(
                request,
                "proyecciones/mi_proyeccion.html",
                {
                    "area": area,
                    "proyecciones": proyecciones,
                    "periodos_sin_proyeccion": servicios.periodos_abiertos_sin_proyeccion(area),
                    "editable": False,
                },
            )
        formset = forms.formulario_lineas(proyeccion, data=request.POST)
        motivo_form = forms.FormularioMotivo(request.POST)
        accion = request.POST.get("accion")
        if accion not in ("guardar", "enviar"):
            formset._non_form_errors = formset.error_class(["Seleccione guardar borrador o enviar."])
        elif formset.is_valid() and motivo_form.is_valid():
            try:
                proyeccion = servicios.guardar_lineas_borrador(
                    proyeccion,
                    formset,
                    actor=request.user,
                    motivo=motivo_form.cleaned_data["motivo"],
                    request=request,
                    enviar=accion == "enviar",
                )
            except ValidationError as error:
                _error_formset(formset, error)
            else:
                messages.success(
                    request,
                    "La proyección fue enviada correctamente."
                    if accion == "enviar"
                    else "El borrador de la proyección se guardó correctamente.",
                )
                return redirect("proyecciones:mi_proyeccion_detalle", pk=proyeccion.pk)

    lineas_lectura = []
    if proyeccion and not editable:
        lineas_lectura = list(
            proyeccion.lineas.select_related("unidad").prefetch_related("ajustes").order_by("producto_servicio", "id")
        )
        if proyeccion.estado == ProyeccionArea.Estado.APROBADA:
            lineas_lectura = servicios.anotar_vigentes(lineas_lectura)

    return render(
        request,
        "proyecciones/mi_proyeccion.html",
        {
            "area": area,
            "proyeccion": proyeccion,
            "proyecciones": proyecciones,
            "periodos_sin_proyeccion": servicios.periodos_abiertos_sin_proyeccion(area),
            "editable": editable,
            "lineas_lectura": lineas_lectura,
            "formset": formset,
            "motivo_form": motivo_form,
            "devolucion": (
                servicios.ultima_devolucion(proyeccion)
                if proyeccion and proyeccion.estado == ProyeccionArea.Estado.BORRADOR
                else None
            ),
            "productos_sugeridos": ProductoSugerido.objects.filter(activo=True).order_by("nombre"),
        },
    )


# --- Revisión por administración (GDS-PRY-04) ----------------------------------------

POR_PAGINA_REVISION = 25


def _filtrar_por_periodo_area_estado(request):
    """Filtro de revisión y consolidado: (formulario, consulta de proyecciones).

    Sin filtros, se usa el periodo más reciente (abierto si lo hay). Elegir «Todos los
    periodos» envía periodo vacío y sí muestra todos.
    """
    datos = request.GET
    if not any(campo in request.GET for campo in ("periodo", "area", "estado")):
        reciente = (
            Periodo.objects.filter(estado=Periodo.Estado.ABIERTO).order_by("-anio").first()
            or Periodo.objects.order_by("-anio").first()
        )
        datos = {"periodo": reciente.pk if reciente else ""}
    filtro = forms.FiltroRevision(datos)
    consulta = ProyeccionArea.objects.none()
    if filtro.is_valid():
        consulta = servicios.filtrar_proyecciones(
            periodo=filtro.cleaned_data["periodo"],
            area=filtro.cleaned_data["area"],
            estado=filtro.cleaned_data["estado"],
        )
    return filtro, consulta


def _descripcion_filtro(filtro):
    if not filtro.is_valid():
        return "Filtro no válido"
    datos = filtro.cleaned_data
    estado = dict(ProyeccionArea.Estado.choices).get(datos["estado"], "Todos")
    return (
        f"Periodo: {datos['periodo'] or 'Todos'} · Área: {datos['area'].nombre if datos['area'] else 'Todas'}"
        f" · Estado: {estado}"
    )


@solo_administradores
def revision_lista(request):
    """Todas las áreas del periodo con estado, número de líneas y costo total."""
    filtro, consulta = _filtrar_por_periodo_area_estado(request)
    pagina = Paginator(servicios.resumen_revision(consulta), POR_PAGINA_REVISION).get_page(request.GET.get("pagina"))
    servicios.anotar_costos_vigentes(pagina.object_list)
    totales = consolidado.totales(consulta)
    return render(
        request,
        "proyecciones/revision_lista.html",
        {"filtro": filtro, "pagina": pagina, "costo_total": totales["costo"], "costo_vigente": totales["costo_ajustado"]},
    )


# --- Consolidado y exportación (GDS-PRY-06) ----------------------------------------------


@solo_administradores
@require_safe
def consolidado_vista(request):
    filtro, consulta = _filtrar_por_periodo_area_estado(request)
    return render(
        request,
        "proyecciones/consolidado.html",
        {
            "filtro": filtro,
            "filas": consolidado.filas_por_area(consulta),
            "total": consolidado.totales(consulta),
            "descripcion_filtro": _descripcion_filtro(filtro),
        },
    )


@solo_administradores
@require_safe
def consolidado_exportar(request):
    filtro, consulta = _filtrar_por_periodo_area_estado(request)
    contenido = exportar.exportar_consolidado(consulta, _descripcion_filtro(filtro))
    periodo = filtro.cleaned_data.get("periodo") if filtro.is_valid() else None
    nombre = f"consolidado-proyecciones-{periodo.anio if periodo else 'todos'}.xlsx"
    respuesta = HttpResponse(
        contenido,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    respuesta["Content-Disposition"] = f'attachment; filename="{nombre}"'
    respuesta["Cache-Control"] = "no-store"
    respuesta["X-Content-Type-Options"] = "nosniff"
    return respuesta


def _proyeccion_para_revision(pk):
    return get_object_or_404(
        ProyeccionArea.objects.select_related("periodo", "area", "enviado_por", "aprobado_por"),
        pk=pk,
    )


def _contexto_detalle(proyeccion, formulario_autorizacion=None):
    enviada = proyeccion.estado == ProyeccionArea.Estado.ENVIADA
    aprobada = proyeccion.estado == ProyeccionArea.Estado.APROBADA
    lineas = list(proyeccion.lineas.select_related("unidad").prefetch_related("ajustes").order_by("id"))
    if aprobada:
        lineas = servicios.anotar_vigentes(lineas)
    if enviada and formulario_autorizacion is None:
        formulario_autorizacion = forms.FormularioAutorizacion(lineas=lineas)
    return {
        "proyeccion": proyeccion,
        "lineas": lineas,
        "costo_total": servicios.costo_total(ProyeccionArea.objects.filter(pk=proyeccion.pk)),
        "costo_vigente": sum((linea.costo_vigente for linea in lineas), Decimal("0")) if aprobada else None,
        "corregible": enviada,
        "aprobada": aprobada,
        "formulario_autorizacion": formulario_autorizacion if enviada else None,
        "aprobaciones": servicios.aprobaciones_vigentes(proyeccion),
        "aprobaciones_requeridas": servicios.aprobaciones_requeridas(),
        "ajustes": (
            Ajuste.objects.filter(linea__proyeccion=proyeccion).select_related("linea", "usuario")
            if aprobada
            else Ajuste.objects.none()
        ),
        "devolucion_habilitada": servicios.devolucion_habilitada(),
        "periodo_abierto": proyeccion.periodo.estado == Periodo.Estado.ABIERTO,
        "formulario_devolucion": forms.FormularioMotivo(),
        "historial": servicios.historial_proyeccion(proyeccion)[:100],
        "tipo_proyeccion": ContentType.objects.get_for_model(ProyeccionArea).pk,
    }


@solo_administradores
def revision_detalle(request, pk):
    proyeccion = _proyeccion_para_revision(pk)
    return render(request, "proyecciones/revision_detalle.html", _contexto_detalle(proyeccion))


@solo_administradores
@require_POST
def revision_aprobar(request, pk):
    """Guarda las cantidades autorizadas y, si se pide, registra la aprobación."""
    proyeccion = _proyeccion_para_revision(pk)
    volver = reverse("proyecciones:revision_detalle", args=[proyeccion.pk])
    if proyeccion.estado != ProyeccionArea.Estado.ENVIADA:
        messages.error(request, "Solo se puede autorizar y aprobar una proyección enviada.")
        return redirect(volver)
    lineas = list(proyeccion.lineas.order_by("id"))
    formulario = forms.FormularioAutorizacion(request.POST, lineas=lineas)
    accion = request.POST.get("accion")
    if accion not in ("guardar", "aprobar"):
        formulario.add_error(None, "Seleccione guardar las cantidades o aprobar.")
    elif formulario.is_valid():
        argumentos = {"actor": request.user, "motivo": formulario.cleaned_data["motivo"], "request": request}
        try:
            if accion == "guardar":
                cambios = servicios.guardar_cantidades_autorizadas(
                    proyeccion, formulario.cantidades(), **argumentos
                )
                mensaje = f"Cantidades autorizadas guardadas ({cambios} línea(s) cambiaron)."
            else:
                _, aprobada = servicios.aprobar_proyeccion(
                    proyeccion, cantidades=formulario.cantidades(), **argumentos
                )
                mensaje = (
                    f"La proyección de «{proyeccion.area.nombre}» quedó aprobada."
                    if aprobada
                    else "Su aprobación quedó registrada; faltan aprobaciones de otros administradores."
                )
        except ValidationError as error:
            _agregar_errores(formulario, error)
        else:
            messages.success(request, mensaje)
            return redirect(volver)
    return render(
        request,
        "proyecciones/revision_detalle.html",
        _contexto_detalle(proyeccion, formulario_autorizacion=formulario),
    )


@solo_administradores
@require_http_methods(["GET", "POST"])
def revision_ajustar_linea(request, pk, linea_pk):
    """Ajuste justificado de una línea de una proyección aprobada."""
    proyeccion = _proyeccion_para_revision(pk)
    linea = get_object_or_404(
        Linea.objects.select_related("unidad").prefetch_related("ajustes__usuario"),
        pk=linea_pk,
        proyeccion=proyeccion,
    )
    volver = reverse("proyecciones:revision_detalle", args=[proyeccion.pk])
    if proyeccion.estado != ProyeccionArea.Estado.APROBADA:
        messages.error(request, "Solo se pueden ajustar líneas de una proyección aprobada.")
        return redirect(volver)
    formulario = forms.FormularioAjuste(request.POST or None)
    if request.method == "POST" and formulario.is_valid():
        try:
            servicios.registrar_ajuste(
                linea,
                formulario.cleaned_data["campo"],
                formulario.cleaned_data["valor_nuevo"],
                actor=request.user,
                justificacion=formulario.cleaned_data["justificacion"],
                request=request,
            )
        except ValidationError as error:
            _agregar_errores(formulario, error)
        else:
            messages.success(request, f"Ajuste registrado en «{linea.producto_servicio}».")
            return redirect(volver)
    linea = servicios.anotar_vigentes([linea])[0]
    filas = [
        {
            "campo": str(Linea._meta.get_field(campo).verbose_name),
            "aprobado": getattr(linea, campo),
            "vigente": linea.vigente[campo],
            "ajustado": campo in linea.campos_ajustados,
        }
        for campo in CAMPOS_AJUSTABLES
    ]
    return render(
        request,
        "proyecciones/revision_ajustar_linea.html",
        {
            "proyeccion": proyeccion,
            "linea": linea,
            "filas": filas,
            "ajustes": linea.ajustes.all(),
            "formulario": formulario,
            "volver": volver,
        },
    )


@solo_administradores
@require_http_methods(["GET", "POST"])
def revision_corregir_linea(request, pk, linea_pk):
    proyeccion = _proyeccion_para_revision(pk)
    # La línea se busca dentro de la proyección de la URL: otro id da 404.
    linea = get_object_or_404(Linea.objects.select_related("unidad"), pk=linea_pk, proyeccion=proyeccion)
    volver = reverse("proyecciones:revision_detalle", args=[proyeccion.pk])
    if proyeccion.estado != ProyeccionArea.Estado.ENVIADA:
        messages.error(request, "Solo se pueden corregir líneas de una proyección enviada.")
        return redirect(volver)
    formulario = forms.FormularioCorreccionLinea(request.POST or None, instance=linea)
    if request.method == "POST" and formulario.is_valid():
        try:
            servicios.corregir_linea(
                formulario.instance,
                actor=request.user,
                motivo=formulario.cleaned_data["motivo"],
                request=request,
            )
        except ValidationError as error:
            _agregar_errores(formulario, error)
        else:
            messages.success(request, f"Línea «{formulario.instance.producto_servicio}» corregida.")
            return redirect(volver)
    return render(
        request,
        "proyecciones/revision_corregir_linea.html",
        {
            "proyeccion": proyeccion,
            "linea": linea,
            "formulario": formulario,
            "volver": volver,
            "productos_sugeridos": ProductoSugerido.objects.filter(activo=True).order_by("nombre"),
        },
    )


@solo_administradores
@require_POST
def revision_devolver(request, pk):
    proyeccion = _proyeccion_para_revision(pk)
    volver = reverse("proyecciones:revision_detalle", args=[proyeccion.pk])
    formulario = forms.FormularioMotivo(request.POST)
    if not formulario.is_valid():
        messages.error(request, "Indique el motivo de la devolución para continuar.")
        return redirect(volver)
    try:
        servicios.devolver_proyeccion(
            proyeccion,
            actor=request.user,
            motivo=formulario.cleaned_data["motivo"],
            request=request,
        )
    except ValidationError as error:
        messages.error(request, _texto_error(error))
    else:
        messages.success(request, f"La proyección de «{proyeccion.area.nombre}» se devolvió al área.")
    return redirect(volver)
