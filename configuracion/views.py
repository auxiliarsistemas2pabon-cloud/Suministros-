"""Panel de configuración (/configuracion/), solo para administradores y desarrolladores.

Las vistas solo coordinan formulario → servicio → mensaje; las reglas de
negocio están en areas/servicios.py, proyecciones/servicios.py y
cuentas/servicios.py. Nada se borra: todo se desactiva.
"""

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.html import format_html
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from areas import servicios as servicios_areas
from areas.models import Area
from config.utilidades import agregar_errores
from configuracion import forms
from cuentas import servicios as servicios_cuentas
from cuentas.models import ROLES_ADMIN, Rol, Usuario
from cuentas.permisos import rol_requerido
from parametros import servicios as servicios_parametros
from parametros.models import Parametro
from proyecciones import servicios as servicios_proyecciones
from proyecciones.models import ProductoSugerido, UnidadMedida

solo_administradores = rol_requerido(*ROLES_ADMIN)

POR_PAGINA = 25
CLAVE_SESION_TEMPORAL = "configuracion_clave_temporal"


_agregar_errores = agregar_errores


def _paginar(request, consulta):
    return Paginator(consulta, POR_PAGINA).get_page(request.GET.get("pagina"))


def _filtrar_estado(consulta, estado, campo):
    if estado == "activos":
        return consulta.filter(**{campo: True})
    if estado == "inactivos":
        return consulta.filter(**{campo: False})
    return consulta


def _ofrecer_proyeccion_area(request, area):
    periodos_pendientes = servicios_proyecciones.periodos_abiertos_sin_proyeccion(area)
    if not periodos_pendientes:
        return
    anios = ", ".join(str(periodo.anio) for periodo in periodos_pendientes)
    messages.info(
        request,
        format_html(
            "El área quedó activa, pero no tiene proyección para el periodo abierto {}. "
            '<a href="{}">Crear la proyección</a>.',
            anios,
            reverse("proyecciones:abrir_periodo"),
        ),
    )


def _guardar_clave_para_mostrar(request, usuario, clave):
    """La clave generada se guarda en la sesión solo hasta mostrarla una vez."""
    request.session[CLAVE_SESION_TEMPORAL] = {"usuario": usuario.pk, "clave": clave}


# --- Inicio del panel ------------------------------------------------------------


@solo_administradores
def inicio(request):
    contexto = {
        "areas_activas": Area.objects.filter(activa=True).count(),
        "areas_total": Area.objects.count(),
        "unidades_activas": UnidadMedida.objects.filter(activa=True).count(),
        "productos_activos": ProductoSugerido.objects.filter(activo=True).count(),
        "usuarios_activos": Usuario.objects.filter(activo=True).count(),
        "coordinadores_activos": Usuario.objects.filter(activo=True, rol=Rol.COORDINADOR).count(),
        "areas_sin_coordinador": Area.objects.filter(activa=True)
        .annotate(n=Count("usuarios", filter=Q(usuarios__rol=Rol.COORDINADOR, usuarios__activo=True)))
        .filter(n=0)
        .count(),
    }
    return render(request, "configuracion/inicio.html", contexto)


# --- Áreas ------------------------------------------------------------------------


@solo_administradores
def areas_lista(request):
    filtro = forms.FiltroCatalogo(request.GET or None)
    consulta = Area.objects.annotate(
        coordinadores=Count("usuarios", filter=Q(usuarios__rol=Rol.COORDINADOR, usuarios__activo=True))
    )
    if filtro.is_valid():
        if filtro.cleaned_data["q"]:
            q = filtro.cleaned_data["q"]
            consulta = consulta.filter(Q(nombre__icontains=q) | Q(codigo_area__icontains=q))
        consulta = _filtrar_estado(consulta, filtro.cleaned_data["estado"], "activa")
    return render(
        request,
        "configuracion/areas_lista.html",
        {"filtro": filtro, "pagina": _paginar(request, consulta.order_by("nombre"))},
    )


@solo_administradores
@require_http_methods(["GET", "POST"])
def area_formulario(request, pk=None):
    area = get_object_or_404(Area, pk=pk) if pk else Area()
    es_nueva = not area.pk
    formulario = forms.FormularioArea(request.POST or None, instance=area)
    if request.method == "POST" and formulario.is_valid():
        try:
            servicios_areas.guardar_area(
                formulario.instance, actor=request.user, motivo=formulario.cleaned_data["motivo"], request=request
            )
        except ValidationError as error:
            _agregar_errores(formulario, error)
        else:
            messages.success(request, f"Área «{area.nombre}» guardada.")
            if es_nueva:
                _ofrecer_proyeccion_area(request, area)
            return redirect("configuracion:areas")
    return render(
        request,
        "configuracion/formulario.html",
        {
            "formulario": formulario,
            "titulo": f"Editar área «{area.nombre}»" if pk else "Nueva área",
            "volver": reverse("configuracion:areas"),
            "boton": "Guardar área",
        },
    )


@solo_administradores
@require_http_methods(["GET", "POST"])
def area_estado(request, pk):
    area = get_object_or_404(Area, pk=pk)
    nuevo_estado = not area.activa
    bloqueo = None if nuevo_estado else servicios_areas.mensaje_bloqueo_desactivacion(area)
    formulario = forms.FormularioMotivo(request.POST or None)
    if request.method == "POST" and not bloqueo and formulario.is_valid():
        try:
            servicios_areas.cambiar_estado_area(
                area, nuevo_estado, actor=request.user, motivo=formulario.cleaned_data["motivo"], request=request
            )
        except ValidationError as error:
            _agregar_errores(formulario, error)
        else:
            messages.success(request, f"Área «{area.nombre}» {'activada' if nuevo_estado else 'desactivada'}.")
            if nuevo_estado:
                _ofrecer_proyeccion_area(request, area)
            return redirect("configuracion:areas")
    return render(
        request,
        "configuracion/confirmar_estado.html",
        {
            "objeto": area,
            "activar": nuevo_estado,
            "tipo": "el área",
            "formulario": formulario,
            "bloqueo": bloqueo,
            "volver": reverse("configuracion:areas"),
            "nota": "Desactivar no borra el área ni sus usuarios ni su historial; solo deja de ofrecerse para nuevos registros.",
        },
    )


@solo_administradores
@require_http_methods(["GET", "POST"])
def area_coordinadores(request, pk):
    area = get_object_or_404(Area, pk=pk)
    disponibles = servicios_areas.coordinadores_disponibles(area)
    formulario = forms.FormularioCoordinadores(request.POST or None, disponibles=disponibles)
    if request.method == "POST" and area.activa and formulario.is_valid():
        try:
            asignados = servicios_areas.asignar_coordinadores(
                area,
                list(formulario.cleaned_data["coordinadores"]),
                actor=request.user,
                motivo=formulario.cleaned_data["motivo"],
                request=request,
            )
        except ValidationError as error:
            _agregar_errores(formulario, error)
        else:
            messages.success(request, f"Se asignaron {len(asignados)} coordinador(es) al área «{area.nombre}».")
            return redirect("configuracion:area_coordinadores", pk=area.pk)
    crear_url = reverse("configuracion:usuario_nuevo") + f"?rol={Rol.COORDINADOR}&area={area.pk}"
    return render(
        request,
        "configuracion/area_coordinadores.html",
        {
            "area": area,
            "actuales": servicios_areas.coordinadores_activos(area),
            "hay_disponibles": disponibles.exists(),
            "formulario": formulario,
            "crear_url": crear_url,
        },
    )


# --- Unidades de medida ----------------------------------------------------------


@solo_administradores
def unidades_lista(request):
    filtro = forms.FiltroCatalogo(request.GET or None)
    consulta = UnidadMedida.objects.annotate(productos=Count("productos_sugeridos"))
    if filtro.is_valid():
        if filtro.cleaned_data["q"]:
            q = filtro.cleaned_data["q"]
            consulta = consulta.filter(Q(nombre__icontains=q) | Q(abreviatura__icontains=q))
        consulta = _filtrar_estado(consulta, filtro.cleaned_data["estado"], "activa")
    return render(
        request,
        "configuracion/unidades_lista.html",
        {"filtro": filtro, "pagina": _paginar(request, consulta.order_by("nombre"))},
    )


@solo_administradores
@require_http_methods(["GET", "POST"])
def unidad_formulario(request, pk=None):
    unidad = get_object_or_404(UnidadMedida, pk=pk) if pk else UnidadMedida()
    formulario = forms.FormularioUnidad(request.POST or None, instance=unidad)
    if request.method == "POST" and formulario.is_valid():
        try:
            servicios_proyecciones.guardar_unidad(
                formulario.instance, actor=request.user, motivo=formulario.cleaned_data["motivo"], request=request
            )
        except ValidationError as error:
            _agregar_errores(formulario, error)
        else:
            messages.success(request, f"Unidad «{unidad.nombre}» guardada.")
            return redirect("configuracion:unidades")
    return render(
        request,
        "configuracion/formulario.html",
        {
            "formulario": formulario,
            "titulo": f"Editar unidad «{unidad.nombre}»" if pk else "Nueva unidad de medida",
            "volver": reverse("configuracion:unidades"),
            "boton": "Guardar unidad",
        },
    )


@solo_administradores
@require_http_methods(["GET", "POST"])
def unidad_estado(request, pk):
    unidad = get_object_or_404(UnidadMedida, pk=pk)
    nuevo_estado = not unidad.activa
    formulario = forms.FormularioMotivo(request.POST or None)
    if request.method == "POST" and formulario.is_valid():
        servicios_proyecciones.cambiar_estado_unidad(
            unidad, nuevo_estado, actor=request.user, motivo=formulario.cleaned_data["motivo"], request=request
        )
        messages.success(request, f"Unidad «{unidad.nombre}» {'activada' if nuevo_estado else 'desactivada'}.")
        return redirect("configuracion:unidades")
    return render(
        request,
        "configuracion/confirmar_estado.html",
        {
            "objeto": unidad,
            "activar": nuevo_estado,
            "tipo": "la unidad de medida",
            "formulario": formulario,
            "volver": reverse("configuracion:unidades"),
            "nota": "Los productos que ya usan esta unidad la conservan; solo deja de ofrecerse para nuevos productos.",
        },
    )


# --- Productos sugeridos ----------------------------------------------------------


@solo_administradores
def productos_lista(request):
    filtro = forms.FiltroCatalogo(request.GET or None)
    consulta = ProductoSugerido.objects.select_related("unidad_por_defecto")
    if filtro.is_valid():
        if filtro.cleaned_data["q"]:
            consulta = consulta.filter(nombre__icontains=filtro.cleaned_data["q"])
        consulta = _filtrar_estado(consulta, filtro.cleaned_data["estado"], "activo")
    return render(
        request,
        "configuracion/productos_lista.html",
        {
            "filtro": filtro,
            "pagina": _paginar(request, consulta.order_by("nombre")),
            "hay_unidades": UnidadMedida.objects.filter(activa=True).exists(),
        },
    )


@solo_administradores
@require_http_methods(["GET", "POST"])
def producto_formulario(request, pk=None):
    producto = get_object_or_404(ProductoSugerido, pk=pk) if pk else ProductoSugerido()
    formulario = forms.FormularioProducto(request.POST or None, instance=producto)
    if request.method == "POST" and formulario.is_valid():
        try:
            servicios_proyecciones.guardar_producto(
                formulario.instance, actor=request.user, motivo=formulario.cleaned_data["motivo"], request=request
            )
        except ValidationError as error:
            _agregar_errores(formulario, error)
        else:
            messages.success(request, f"Producto «{producto.nombre}» guardado.")
            return redirect("configuracion:productos")
    aviso = None
    if not UnidadMedida.objects.filter(activa=True).exists():
        aviso = {
            "texto": "No hay unidades de medida activas. Cree una antes de registrar productos.",
            "enlace": reverse("configuracion:unidad_nueva"),
            "enlace_texto": "Crear unidad de medida",
        }
    return render(
        request,
        "configuracion/formulario.html",
        {
            "formulario": formulario,
            "titulo": f"Editar producto «{producto.nombre}»" if pk else "Nuevo producto sugerido",
            "volver": reverse("configuracion:productos"),
            "boton": "Guardar producto",
            "aviso": aviso,
        },
    )


@solo_administradores
@require_http_methods(["GET", "POST"])
def producto_estado(request, pk):
    producto = get_object_or_404(ProductoSugerido, pk=pk)
    nuevo_estado = not producto.activo
    formulario = forms.FormularioMotivo(request.POST or None)
    if request.method == "POST" and formulario.is_valid():
        servicios_proyecciones.cambiar_estado_producto(
            producto, nuevo_estado, actor=request.user, motivo=formulario.cleaned_data["motivo"], request=request
        )
        messages.success(request, f"Producto «{producto.nombre}» {'activado' if nuevo_estado else 'desactivado'}.")
        return redirect("configuracion:productos")
    return render(
        request,
        "configuracion/confirmar_estado.html",
        {
            "objeto": producto,
            "activar": nuevo_estado,
            "tipo": "el producto sugerido",
            "formulario": formulario,
            "volver": reverse("configuracion:productos"),
            "nota": "Desactivar no borra el producto; solo deja de sugerirse en nuevas proyecciones.",
        },
    )


# --- Usuarios ---------------------------------------------------------------------


def _usuario_gestionable(request, pk):
    """Usuario a modificar, o 403 si el actor no puede gestionarlo (p. ej. un
    administrador frente a un desarrollador)."""
    usuario = get_object_or_404(Usuario.objects.select_related("area"), pk=pk)
    if not servicios_cuentas.puede_gestionar(request.user, usuario.rol, usuario.rol):
        raise PermissionDenied(servicios_cuentas.MENSAJE_SOLO_DESARROLLADOR_GESTIONA)
    return usuario


@solo_administradores
def usuarios_lista(request):
    filtro = forms.FiltroUsuarios(request.GET or None)
    consulta = Usuario.objects.select_related("area")
    if filtro.is_valid():
        datos = filtro.cleaned_data
        if datos["q"]:
            consulta = consulta.filter(Q(nombre__icontains=datos["q"]) | Q(correo__icontains=datos["q"]))
        if datos["rol"]:
            consulta = consulta.filter(rol=datos["rol"])
        if datos["area"]:
            consulta = consulta.filter(area=datos["area"])
        consulta = _filtrar_estado(consulta, datos["estado"], "activo")
    pagina = _paginar(request, consulta.order_by("nombre", "correo"))
    for usuario in pagina:
        usuario.gestionable = servicios_cuentas.puede_gestionar(request.user, usuario.rol, usuario.rol)
    return render(request, "configuracion/usuarios_lista.html", {"filtro": filtro, "pagina": pagina})


@solo_administradores
@require_http_methods(["GET", "POST"])
def usuario_nuevo(request):
    inicial = {}
    if request.method == "GET":
        if request.GET.get("rol") in servicios_cuentas.roles_asignables(request.user):
            inicial["rol"] = request.GET["rol"]
        if request.GET.get("area", "").isdigit():
            inicial["area"] = request.GET["area"]
    formulario = forms.FormularioCrearUsuario(request.POST or None, actor=request.user, initial=inicial)
    if request.method == "POST" and formulario.is_valid():
        try:
            clave, generada = servicios_cuentas.crear_usuario(
                formulario.instance,
                actor=request.user,
                motivo=formulario.cleaned_data["motivo"],
                clave=formulario.clave_elegida(),
                request=request,
            )
        except ValidationError as error:
            _agregar_errores(formulario, error)
        else:
            usuario = formulario.instance
            messages.success(request, f"Usuario «{usuario.correo}» creado. Deberá cambiar la clave al ingresar.")
            if generada:
                _guardar_clave_para_mostrar(request, usuario, clave)
                return redirect("configuracion:usuario_clave_temporal", pk=usuario.pk)
            return redirect("configuracion:usuarios")
    return render(
        request,
        "configuracion/formulario.html",
        {
            "formulario": formulario,
            "titulo": "Nuevo usuario",
            "volver": reverse("configuracion:usuarios"),
            "boton": "Crear usuario",
            "con_clave": True,
        },
    )


@solo_administradores
@require_http_methods(["GET", "POST"])
def usuario_editar(request, pk):
    usuario = _usuario_gestionable(request, pk)
    formulario = forms.FormularioEditarUsuario(request.POST or None, instance=usuario, actor=request.user)
    if request.method == "POST" and formulario.is_valid():
        try:
            servicios_cuentas.editar_usuario(
                formulario.instance, actor=request.user, motivo=formulario.cleaned_data["motivo"], request=request
            )
        except ValidationError as error:
            _agregar_errores(formulario, error)
        else:
            messages.success(request, f"Usuario «{usuario.correo}» guardado.")
            return redirect("configuracion:usuarios")
    return render(
        request,
        "configuracion/formulario.html",
        {
            "formulario": formulario,
            "titulo": f"Editar usuario «{usuario.correo}»",
            "volver": reverse("configuracion:usuarios"),
            "boton": "Guardar usuario",
        },
    )


@solo_administradores
@require_http_methods(["GET", "POST"])
def usuario_estado(request, pk):
    usuario = _usuario_gestionable(request, pk)
    nuevo_estado = not usuario.activo
    bloqueo = "No puede desactivar su propia cuenta." if usuario.pk == request.user.pk and not nuevo_estado else None
    formulario = forms.FormularioMotivo(request.POST or None)
    if request.method == "POST" and not bloqueo and formulario.is_valid():
        try:
            servicios_cuentas.cambiar_estado_usuario(
                usuario, nuevo_estado, actor=request.user, motivo=formulario.cleaned_data["motivo"], request=request
            )
        except ValidationError as error:
            _agregar_errores(formulario, error)
        else:
            messages.success(request, f"Usuario «{usuario.correo}» {'activado' if nuevo_estado else 'desactivado'}.")
            return redirect("configuracion:usuarios")
    return render(
        request,
        "configuracion/confirmar_estado.html",
        {
            "objeto": usuario,
            "activar": nuevo_estado,
            "tipo": "el usuario",
            "formulario": formulario,
            "bloqueo": bloqueo,
            "volver": reverse("configuracion:usuarios"),
            "nota": "Desactivar no borra el usuario ni su historial; pierde el acceso de inmediato.",
        },
    )


@solo_administradores
@require_http_methods(["GET", "POST"])
def usuario_restablecer_clave(request, pk):
    usuario = _usuario_gestionable(request, pk)
    if usuario.pk == request.user.pk:
        messages.warning(request, "Para cambiar su propia clave use la opción «Cambiar clave».")
        return redirect("cuentas:cambiar_clave")
    formulario = forms.FormularioRestablecerClave(request.POST or None, usuario=usuario)
    if request.method == "POST" and formulario.is_valid():
        try:
            clave, generada = servicios_cuentas.restablecer_clave(
                usuario,
                actor=request.user,
                motivo=formulario.cleaned_data["motivo"],
                clave=formulario.clave_elegida(),
                request=request,
            )
        except ValidationError as error:
            _agregar_errores(formulario, error)
        else:
            messages.success(request, f"Clave de «{usuario.correo}» restablecida. Deberá cambiarla al ingresar.")
            if generada:
                _guardar_clave_para_mostrar(request, usuario, clave)
                return redirect("configuracion:usuario_clave_temporal", pk=usuario.pk)
            return redirect("configuracion:usuarios")
    return render(
        request,
        "configuracion/formulario.html",
        {
            "formulario": formulario,
            "titulo": f"Restablecer clave de «{usuario.correo}»",
            "volver": reverse("configuracion:usuarios"),
            "boton": "Restablecer clave",
            "con_clave": True,
            "nota": "Se cerrarán las sesiones abiertas del usuario y deberá cambiar la clave en su próximo ingreso.",
        },
    )


@never_cache
@solo_administradores
def usuario_clave_temporal(request, pk):
    """Muestra la clave generada UNA sola vez: se retira de la sesión al leerla."""
    usuario = get_object_or_404(Usuario, pk=pk)
    datos = request.session.pop(CLAVE_SESION_TEMPORAL, None)
    if not datos or datos.get("usuario") != usuario.pk:
        messages.warning(request, "La clave temporal ya se mostró y no se puede volver a ver. Si la perdió, restablézcala.")
        return redirect("configuracion:usuarios")
    # never_cache agrega Cache-Control: no-store (ni el navegador ni un proxy la guardan).
    return render(request, "configuracion/clave_temporal.html", {"usuario": usuario, "clave": datos["clave"]})


# --- Parámetros (reglas pendientes de decisión) -------------------------------------


@solo_administradores
def parametros_lista(request):
    return render(
        request,
        "configuracion/parametros_lista.html",
        {"parametros": Parametro.objects.order_by("decision", "clave")},
    )


@solo_administradores
@require_http_methods(["GET", "POST"])
def parametro_editar(request, pk):
    parametro = get_object_or_404(Parametro, pk=pk)
    formulario = forms.FormularioParametro(request.POST or None, parametro=parametro)
    if request.method == "POST" and formulario.is_valid():
        try:
            servicios_parametros.cambiar_valor(
                parametro,
                Parametro.a_texto(parametro.tipo, formulario.cleaned_data["valor"]),
                actor=request.user,
                motivo=formulario.cleaned_data["motivo"],
                request=request,
            )
        except ValidationError as error:
            _agregar_errores(formulario, error)
        else:
            messages.success(request, f"Parámetro «{parametro.nombre}» actualizado.")
            return redirect("configuracion:parametros")
    return render(
        request,
        "configuracion/formulario.html",
        {
            "formulario": formulario,
            "titulo": f"Editar parámetro «{parametro.nombre}»",
            "nota": parametro.descripcion,
            "volver": reverse("configuracion:parametros"),
            "boton": "Guardar parámetro",
        },
    )
