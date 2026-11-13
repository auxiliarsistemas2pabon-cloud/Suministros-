"""Reglas de negocio de proveedores y de sus documentos. Todo cambio queda en la bitácora.

- Solo administración (administrador y desarrollador) gestiona fichas y documentos.
- Los proveedores no se borran: se pasan a estado «Inactivo».
- Quién puede aprobar un proveedor es la decisión pendiente D-03 (parámetro
  «proveedor.roles_aprobadores»).
- Los PDF se validan y se guardan con proveedores/archivos.py; al borrar o reemplazar un
  documento, el archivo anterior se borra al confirmar la transacción (proveedores/signals.py).
"""

from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.db.models import Exists, Max, OuterRef, Q
from django.utils import timezone

from bitacora.servicios import diferencias, guardar_con_bitacora, instantanea, registrar
from cuentas.models import ROLES_ADMIN, Rol
from parametros import servicios as parametros
from parametros.catalogo import CONSERVAR_PDF_DESCARTADO, DIAS_ALERTA_VENCIMIENTO, ROLES_APROBADORES_PROVEEDOR, lista_de_roles
from proveedores import archivos
from proveedores import nit as utilidades_nit
from proveedores.models import CategoriaProveedor, DocumentoProveedor, EnvioProveedor, Peso, Proveedor, Requisito, TipoDocumento

CAMPOS_AUDITADOS_PROVEEDOR = [
    "nit",
    "digito_verificacion",
    "razon_social",
    "tipo_persona",
    "contacto_nombre",
    "contacto_correo",
    "contacto_telefono",
    "direccion",
    "categoria",
    "estado",
]
CAMPOS_AUDITADOS_DOCUMENTO = [
    "proveedor",
    "tipo",
    "fecha_expedicion",
    "fecha_vencimiento",
    "archivo",
    "nombre_archivo",
    "enlace",
    "cargado_por",
]

MENSAJE_SOLO_ADMIN = "Solo administración puede gestionar proveedores y sus documentos."
MENSAJE_MOTIVO = "El motivo es obligatorio."


def _exigir_admin(actor):
    if not (getattr(actor, "is_authenticated", False) and getattr(actor, "is_active", False) and getattr(actor, "rol", None) in ROLES_ADMIN):
        raise PermissionDenied(MENSAJE_SOLO_ADMIN)


def _exigir_motivo(motivo):
    if not (motivo or "").strip():
        raise ValidationError({"motivo": MENSAJE_MOTIVO})


@transaction.atomic
def guardar_catalogo(instancia, *, actor, motivo, request=None):
    """Catálogos sin borrado; la activación tiene una acción independiente."""
    from proveedores.catalogos import CATALOGOS

    _exigir_admin(actor)
    _exigir_motivo(motivo)
    definicion = next((d for d in CATALOGOS.values() if type(instancia) is d["modelo"]), None)
    if definicion is None:
        raise ValidationError("El catálogo no es válido.")
    previo = type(instancia).objects.select_for_update().get(pk=instancia.pk) if instancia.pk else None
    if hasattr(instancia, "activo"):
        instancia.activo = previo.activo if previo else True
    if isinstance(instancia, Peso):
        if previo and (previo.requisito_id != instancia.requisito_id or previo.categoria_id != instancia.categoria_id):
            raise ValidationError("La categoría y el requisito de un peso existente no se pueden cambiar.")
        if not previo and (not instancia.requisito.activo or not instancia.categoria.activo):
            raise ValidationError("Seleccione un requisito y una categoría activos.")
    if isinstance(instancia, TipoDocumento) and instancia.requiere_vencimiento and previo and not previo.requiere_vencimiento:
        if instancia.documentos.filter(fecha_vencimiento__isnull=True).exists():
            raise ValidationError({"requiere_vencimiento": "Hay documentos sin vencimiento. Complete sus fechas antes de exigirlo."})
    instancia.full_clean()
    guardar_con_bitacora(
        instancia, definicion["campos"], accion_crear=f"{definicion['accion']}.creado",
        accion_modificar=f"{definicion['accion']}.modificado", actor=actor, motivo=motivo, request=request,
    )
    return instancia


@transaction.atomic
def cambiar_estado_catalogo(instancia, activo, *, actor, motivo, request=None):
    from proveedores.catalogos import CATALOGOS

    _exigir_admin(actor)
    _exigir_motivo(motivo)
    definicion = next((d for d in CATALOGOS.values() if type(instancia) is d["modelo"]), None)
    if definicion is None or isinstance(instancia, Peso):
        raise ValidationError("Este catálogo no admite cambios de estado.")
    instancia = type(instancia).objects.select_for_update().get(pk=instancia.pk)
    if type(activo) is not bool or activo == instancia.activo:
        raise ValidationError("El estado ya cambió. Recargue la página.")
    instancia.activo = activo
    instancia.full_clean()
    guardar_con_bitacora(
        instancia, definicion["campos"], accion_crear=f"{definicion['accion']}.creado",
        accion_modificar=f"{definicion['accion']}.{'activado' if activo else 'desactivado'}",
        actor=actor, motivo=motivo, request=request,
    )
    return instancia


@transaction.atomic
def cargar_fr14(archivo, *, actor, motivo, version=None):
    """Carga completa o rollback; repetir el mismo CSV no duplica datos ni bitácora."""
    from proveedores.carga_fr14 import leer_csv

    _exigir_admin(actor)
    _exigir_motivo(motivo)
    from proveedores.models import VersionMatriz, exigir_matriz_borrador, version_inicial
    version = version or VersionMatriz.objects.get(pk=version_inicial())
    exigir_matriz_borrador(version.pk)
    filas = leer_csv(archivo)
    categorias = {c.nombre.casefold(): c for c in CategoriaProveedor.objects.select_for_update()}
    requisitos = {}
    resumen = {"categorias_creadas": 0, "requisitos_creados": 0, "pesos_creados": 0, "actualizados": 0}
    for fila in filas:
        clave = fila["categoria"].casefold()
        if clave not in categorias:
            categoria = CategoriaProveedor.objects.filter(nombre__iexact=fila["categoria"]).first()
            if categoria is None:
                categoria = CategoriaProveedor(nombre=fila["categoria"])
                guardar_catalogo(categoria, actor=actor, motivo=motivo)
                resumen["categorias_creadas"] += 1
            categorias[clave] = categoria
        categoria = categorias[clave]
        if fila["numero"] not in requisitos:
            requisito = Requisito.objects.select_for_update().filter(version=version, numero=fila["numero"]).first()
            nuevo = requisito is None
            requisito = requisito or Requisito(version=version, numero=fila["numero"])
            cambiado = nuevo or requisito.texto != fila["texto"] or requisito.grupo != fila["grupo"]
            requisito.texto, requisito.grupo = fila["texto"], fila["grupo"]
            if cambiado:
                guardar_catalogo(requisito, actor=actor, motivo=motivo)
                resumen["requisitos_creados" if nuevo else "actualizados"] += 1
            requisitos[fila["numero"]] = requisito
        requisito = requisitos[fila["numero"]]
        peso = Peso.objects.select_for_update().filter(requisito=requisito, categoria=categoria).first()
        nuevo = peso is None
        if nuevo:
            peso = Peso(requisito=requisito, categoria=categoria)
        if nuevo or peso.valor != fila["valor"]:
            peso.valor = fila["valor"]
            guardar_catalogo(peso, actor=actor, motivo=motivo)
            resumen["pesos_creados" if nuevo else "actualizados"] += 1
    return resumen


# --- Ficha del proveedor --------------------------------------------------------------


def buscar(consulta, texto):
    """Filtra por razón social o por NIT escrito en cualquier formato (con puntos,
    espacios, guiones o dígito de verificación)."""
    texto = (texto or "").strip()
    if not texto:
        return consulta
    condicion = Q(razon_social__icontains=texto)
    digitos = utilidades_nit.digitos_para_buscar(texto)
    if digitos:
        condicion |= Q(nit__contains=digitos)
    return consulta.filter(condicion)


@transaction.atomic
def guardar_proveedor(proveedor, *, actor, motivo, request=None):
    """Crea o modifica la ficha. El estado no cambia aquí (use cambiar_estado)."""
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    if proveedor.pk:
        proveedor.estado = Proveedor.objects.values_list("estado", flat=True).get(pk=proveedor.pk)
    else:
        proveedor.estado = Proveedor.Estado.REGISTRADO
    proveedor.full_clean()
    guardar_con_bitacora(
        proveedor,
        CAMPOS_AUDITADOS_PROVEEDOR,
        accion_crear="proveedor.creado",
        accion_modificar="proveedor.modificado",
        actor=actor,
        motivo=motivo,
        request=request,
    )
    return proveedor


def roles_aprobadores():
    """Roles que pueden aprobar proveedores según el parámetro D-03."""
    return lista_de_roles(parametros.obtener(ROLES_APROBADORES_PROVEEDOR))


def puede_aprobar(actor):
    return getattr(actor, "rol", None) in ROLES_ADMIN and actor.rol in roles_aprobadores()


def estados_posibles(proveedor, actor):
    """Estados a los que el actor puede pasar el proveedor (sin el estado actual)."""
    return [
        (valor, etiqueta)
        for valor, etiqueta in Proveedor.Estado.choices
        if valor != proveedor.estado and (valor != Proveedor.Estado.APROBADO or puede_aprobar(actor))
    ]


@transaction.atomic
def cambiar_estado(proveedor, estado, *, actor, motivo, request=None):
    """Cambia el estado (registrado, en revisión, aprobado o inactivo) con motivo.
    Aprobar exige uno de los roles del parámetro D-03."""
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    if estado not in Proveedor.Estado.values:
        raise ValidationError({"estado": "El estado no es válido."})
    proveedor = Proveedor.objects.select_for_update().get(pk=proveedor.pk)
    if estado == proveedor.estado:
        raise ValidationError({"estado": "El proveedor ya está en ese estado."})
    if estado == Proveedor.Estado.APROBADO and not puede_aprobar(actor):
        nombres = ", ".join(roles_aprobadores())
        raise PermissionDenied(f"Según la decisión D-03, solo pueden aprobar proveedores los roles: {nombres}.")
    proveedor.estado = estado
    guardar_con_bitacora(
        proveedor,
        ["estado"],
        accion_crear="proveedor.creado",
        accion_modificar="proveedor.estado_cambiado",
        actor=actor,
        motivo=motivo,
        request=request,
    )
    return proveedor


# --- Documentos -----------------------------------------------------------------------


def _instantanea_documento(documento):
    valores = instantanea(documento, CAMPOS_AUDITADOS_DOCUMENTO)
    valores["archivo"] = documento.archivo.name or ""
    return valores


def guardar_documento(documento, *, actor, motivo, archivo_subido=None, request=None):
    """Crea o modifica un documento.

    - Con `archivo_subido`: se valida (extensión, %PDF-, 10 MB), se guarda con nombre uuid y
      reemplaza el PDF o el enlace anterior.
    - Sin archivo y con enlace: el documento queda con el enlace (si tenía PDF, se borra).
    - El archivo reemplazado se borra al confirmar; si algo falla, el nuevo se borra y el
      anterior se conserva.
    """
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    if archivo_subido is not None:
        try:
            archivos.validar_pdf(archivo_subido)
        except ValidationError as error:
            raise ValidationError({"archivo": error.messages}) from None
        if any(not getattr(bloque, "_from_testcase", False) for bloque in connection.atomic_blocks):
            raise ValidationError("La carga de un PDF debe ejecutarse fuera de otra transacción para evitar archivos huérfanos.")
    nuevo_archivo = ""
    previo = None
    try:
        with transaction.atomic(durable=archivo_subido is not None):
            if documento.pk:
                previo = _instantanea_documento(DocumentoProveedor.objects.select_for_update().get(pk=documento.pk))
                proveedor_original = previo["proveedor"]["id"]
                if documento.proveedor_id != proveedor_original:
                    raise ValidationError("Un documento no se puede pasar a otro proveedor.")
            if archivo_subido is not None:
                nuevo_archivo = archivos.guardar_pdf(archivo_subido)
                documento.archivo.name = nuevo_archivo
                documento.nombre_archivo = archivos.nombre_original(archivo_subido)
                documento.enlace = ""
            elif documento.enlace:
                documento.archivo.name = ""
                documento.nombre_archivo = ""
            if previo is None or archivo_subido is not None or documento.enlace != previo["enlace"]:
                # Quien carga el contenido nuevo queda como responsable de la carga.
                documento.cargado_por = actor
                documento.fecha_carga = timezone.now()
            documento.full_clean()
            documento.save()
            actual = _instantanea_documento(documento)
            if previo is None:
                registrar(
                    "documento_proveedor.creado",
                    actor=actor,
                    objeto=documento,
                    nuevo=actual,
                    motivo=motivo,
                    request=request,
                )
            else:
                anterior, nuevo = diferencias(previo, actual)
                if not nuevo:
                    raise ValidationError("No hay cambios para guardar.")
                registrar(
                    "documento_proveedor.modificado",
                    actor=actor,
                    objeto=documento,
                    anterior=anterior,
                    nuevo=nuevo,
                    motivo=motivo,
                    request=request,
                )
    except BaseException:
        # La transacción se revirtió: el PDF recién guardado quedaría huérfano.
        archivos.borrar_ahora(nuevo_archivo)
        if previo is not None:
            documento.archivo.name = previo["archivo"]
        raise
    return documento


@transaction.atomic
def eliminar_documento(documento, *, actor, motivo, request=None):
    """Borra el documento y, al confirmar, su PDF. La bitácora conserva sus datos."""
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    documento = DocumentoProveedor.objects.select_for_update().select_related("proveedor", "tipo").get(pk=documento.pk)
    from proveedores.models import RespuestaEvaluacion
    if RespuestaEvaluacion.objects.filter(documento=documento).exists():
        raise ValidationError("Este documento respalda respuestas de una evaluación y debe conservarse.")
    if EnvioProveedor.objects.filter(documento=documento).exists():
        raise ValidationError("Este documento proviene de un envío aceptado. Conserve el historial y cargue otro documento para renovarlo.")
    registrar(
        "documento_proveedor.eliminado",
        actor=actor,
        objeto=documento,
        anterior=_instantanea_documento(documento),
        motivo=motivo,
        request=request,
    )
    documento.delete()


CAMPOS_AUDITADOS_ENVIO = [
    "proveedor", "tipo", "fecha_expedicion", "fecha_vencimiento", "archivo", "nombre_archivo",
    "enviado_por", "fecha_envio", "estado", "motivo", "revisado_por", "fecha_revision", "documento",
]


def _instantanea_envio(envio):
    valores = instantanea(envio, CAMPOS_AUDITADOS_ENVIO)
    valores["archivo"] = envio.archivo.name or ""
    return valores


def crear_envio(*, proveedor, actor, tipo, fecha_expedicion, fecha_vencimiento, archivo, motivo, request=None):
    """Entrada común del portal y de las cargas administrativas, siempre pendiente."""
    if getattr(actor, "rol", None) == Rol.PROVEEDOR:
        if not actor.is_active or actor.proveedor_id != proveedor.pk:
            raise PermissionDenied
    else:
        _exigir_admin(actor)
    _exigir_motivo(motivo)
    archivos.validar_pdf(archivo)
    if any(not getattr(b, "_from_testcase", False) for b in connection.atomic_blocks):
        raise ValidationError("La carga del PDF debe ejecutarse fuera de otra transacción.")
    ruta = ""
    try:
        with transaction.atomic(durable=True):
            proveedor = Proveedor.objects.select_for_update().get(pk=proveedor.pk)
            if not proveedor.activo:
                raise PermissionDenied("Un proveedor inactivo no admite nuevos envíos.")
            ruta = archivos.guardar_pdf(archivo, carpeta="envios")
            envio = EnvioProveedor(proveedor=proveedor, tipo=tipo, fecha_expedicion=fecha_expedicion,
                                   fecha_vencimiento=fecha_vencimiento, archivo=ruta,
                                   nombre_archivo=archivos.nombre_original(archivo), enviado_por=actor)
            envio.full_clean()
            envio.save()
            registrar("envio_proveedor.creado", actor=actor, objeto=envio, nuevo=_instantanea_envio(envio),
                      motivo=motivo, request=request)
    except BaseException:
        archivos.borrar_ahora(ruta)
        raise
    return envio


def filtrar_envios(*, proveedor=None, texto="", tipo=None, estado="pendiente", desde=None, hasta=None):
    consulta = EnvioProveedor.objects.select_related("proveedor", "tipo", "enviado_por")
    if proveedor:
        consulta = consulta.filter(proveedor=proveedor)
    if texto:
        consulta = consulta.filter(proveedor__in=buscar(Proveedor.objects.all(), texto))
    if tipo:
        consulta = consulta.filter(tipo=tipo)
    if estado:
        consulta = consulta.filter(estado=estado)
    if desde:
        consulta = consulta.filter(fecha_envio__date__gte=desde)
    if hasta:
        consulta = consulta.filter(fecha_envio__date__lte=hasta)
    return consulta.order_by("-fecha_envio", "-pk")


@transaction.atomic
def revisar_envio(envio, *, aceptar, actor, motivo, request=None):
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    if type(aceptar) is not bool:
        raise ValidationError("Seleccione aceptar o descartar.")
    envio = EnvioProveedor.objects.select_for_update().select_related("proveedor", "tipo").get(pk=envio.pk)
    if envio.estado != EnvioProveedor.Estado.PENDIENTE:
        raise ValidationError("Este envío ya fue revisado. Recargue la bandeja.")
    anterior = _instantanea_envio(envio)
    if aceptar:
        if not envio.archivo:
            raise ValidationError("El envío no tiene un PDF disponible.")
        try:
            with envio.archivo.open("rb") as contenido:
                archivos.validar_pdf(contenido)
        except FileNotFoundError:
            raise ValidationError("El PDF del envío no está disponible.") from None
        documento = DocumentoProveedor(
            proveedor=envio.proveedor, tipo=envio.tipo, fecha_expedicion=envio.fecha_expedicion,
            fecha_vencimiento=envio.fecha_vencimiento, archivo=envio.archivo.name,
            nombre_archivo=envio.nombre_archivo, cargado_por=actor,
        )
        guardar_documento(documento, actor=actor, motivo=motivo, request=request)
        envio.documento = documento
        envio.estado = EnvioProveedor.Estado.ACEPTADO
    else:
        envio.estado = EnvioProveedor.Estado.DESCARTADO
        if not parametros.obtener(CONSERVAR_PDF_DESCARTADO):
            ruta = envio.archivo.name
            envio.archivo = ""
            archivos.borrar_al_confirmar(ruta)
    envio.revisado_por, envio.fecha_revision, envio.motivo = actor, timezone.now(), motivo.strip()
    envio.full_clean()
    envio.save()
    registrar("envio_proveedor.aceptado" if aceptar else "envio_proveedor.descartado",
              actor=actor, objeto=envio, anterior=anterior, nuevo=_instantanea_envio(envio), motivo=motivo, request=request)
    return envio


# --- Vencimientos -----------------------------------------------------------------------

VIGENCIA_VENCIDO = "vencido"
VIGENCIA_POR_VENCER = "por_vencer"
VIGENCIA_VIGENTE = "vigente"
VIGENCIA_SIN_VENCIMIENTO = "sin_vencimiento"


def dias_alerta():
    return parametros.obtener(DIAS_ALERTA_VENCIMIENTO)


def dias_alerta_tipo(tipo, general=None):
    if not tipo.usar_alerta_general:
        return tipo.dias_alerta
    return dias_alerta() if general is None else general


def vigencia(fecha_vencimiento, hoy=None, dias=None):
    """Clasifica una fecha de vencimiento. Un documento vence al terminar su fecha de
    vencimiento: ese día todavía está vigente (por vencer)."""
    if fecha_vencimiento is None:
        return VIGENCIA_SIN_VENCIMIENTO
    hoy = hoy or timezone.localdate()
    dias = dias_alerta() if dias is None else dias
    if fecha_vencimiento < hoy:
        return VIGENCIA_VENCIDO
    if fecha_vencimiento <= hoy + timedelta(days=dias):
        return VIGENCIA_POR_VENCER
    return VIGENCIA_VIGENTE


def documentos_actuales(consulta=None):
    """Documentos que no han sido sustituidos por otro más reciente del mismo tipo para el
    mismo proveedor (por fecha de expedición y, a igual fecha, el último cargado)."""
    consulta = DocumentoProveedor.objects.all() if consulta is None else consulta
    mas_reciente = DocumentoProveedor.objects.filter(proveedor=OuterRef("proveedor"), tipo=OuterRef("tipo")).filter(
        Q(fecha_expedicion__gt=OuterRef("fecha_expedicion"))
        | Q(fecha_expedicion=OuterRef("fecha_expedicion"), pk__gt=OuterRef("pk"))
    )
    return consulta.filter(~Exists(mas_reciente))


def alertas_vencimiento(hoy=None, dias=None, proveedor=None):
    """Documentos actuales de proveedores no inactivos que ya vencieron o vencen en los
    próximos `dias` (parámetro, 30 por defecto). Cada uno trae el atributo `vigencia`."""
    hoy = hoy or timezone.localdate()
    general = dias_alerta() if dias is None else dias
    maximo = max(general, TipoDocumento.objects.filter(usar_alerta_general=False).aggregate(maximo=Max("dias_alerta"))["maximo"] or 0) if dias is None else dias
    consulta = DocumentoProveedor.objects.exclude(proveedor__estado=Proveedor.Estado.INACTIVO)
    if proveedor is not None:
        consulta = consulta.filter(proveedor=proveedor)
    consulta = documentos_actuales(consulta).filter(fecha_vencimiento__lte=hoy + timedelta(days=maximo))
    documentos = list(
        consulta.select_related("proveedor", "tipo").order_by("fecha_vencimiento", "proveedor__razon_social")
    )
    for documento in documentos:
        documento.dias_alerta = dias_alerta_tipo(documento.tipo, general) if dias is None else dias
        documento.vigencia = vigencia(documento.fecha_vencimiento, hoy, documento.dias_alerta)
    return [d for d in documentos if d.vigencia in (VIGENCIA_VENCIDO, VIGENCIA_POR_VENCER)]


def resumen_alertas(hoy=None, dias=None):
    documentos = alertas_vencimiento(hoy, dias)
    vencidos = sum(1 for documento in documentos if documento.vigencia == VIGENCIA_VENCIDO)
    return {"vencidos": vencidos, "por_vencer": len(documentos) - vencidos, "dias": dias_alerta() if dias is None else dias}


def documentos_de(proveedor, hoy=None):
    """Documentos del proveedor con su vigencia y si son el actual de su tipo."""
    hoy = hoy or timezone.localdate()
    dias = dias_alerta()
    actuales = set(documentos_actuales(proveedor.documentos.all()).values_list("pk", flat=True))
    documentos = list(proveedor.documentos.select_related("tipo", "cargado_por"))
    for documento in documentos:
        documento.dias_alerta = dias_alerta_tipo(documento.tipo, dias)
        documento.vigencia = vigencia(documento.fecha_vencimiento, hoy, documento.dias_alerta)
        documento.es_actual = documento.pk in actuales
    return documentos
