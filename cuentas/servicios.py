"""Reglas de negocio de cuentas: claves, cambios de usuarios y accesos por rol."""

import secrets
from dataclasses import dataclass

from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.urls import NoReverseMatch, reverse

from bitacora.servicios import guardar_con_bitacora, registrar
from cuentas.models import ROLES_ADMIN, Rol, Usuario
from cuentas.permisos import es_admin

# Campos del usuario cuyo cambio queda en la bitácora.
CAMPOS_AUDITADOS_USUARIO = [
    "correo",
    "nombre",
    "rol",
    "area",
    "proveedor",
    "activo",
    "is_staff",
    "is_superuser",
    "debe_cambiar_clave",
]


@transaction.atomic
def cambiar_clave(request, usuario, clave_nueva):
    """El propio usuario cambia su clave: se apaga debe_cambiar_clave y la
    sesión actual sigue abierta."""
    tenia_que_cambiarla = usuario.debe_cambiar_clave
    usuario.set_password(clave_nueva)
    usuario.debe_cambiar_clave = False
    usuario.save(update_fields=["password", "debe_cambiar_clave"])
    update_session_auth_hash(request, usuario)
    registrar(
        "cuenta.cambio_clave",
        actor=usuario,
        objeto=usuario,
        anterior={"debe_cambiar_clave": tenia_que_cambiarla},
        nuevo={"debe_cambiar_clave": False},
        motivo="Cambio obligatorio de clave" if tenia_que_cambiarla else "Cambio de clave por el usuario",
        request=request,
    )


@transaction.atomic
def registrar_restablecimiento_clave(request, usuario, motivo):
    """Un desarrollador asignó (o deshabilitó) la clave de un usuario desde el
    admin técnico. Si se asignó una clave a otra persona, esta deberá cambiarla
    en su próximo ingreso."""
    actor = request.user
    tenia = usuario.debe_cambiar_clave
    clave_habilitada = usuario.has_usable_password()
    if clave_habilitada and usuario.pk != actor.pk and not tenia:
        usuario.debe_cambiar_clave = True
        usuario.save(update_fields=["debe_cambiar_clave"])
    registrar(
        "cuenta.clave_asignada" if clave_habilitada else "cuenta.clave_deshabilitada",
        actor=actor,
        objeto=usuario,
        anterior={"debe_cambiar_clave": tenia},
        nuevo={"debe_cambiar_clave": usuario.debe_cambiar_clave, "clave_habilitada": clave_habilitada},
        motivo=motivo,
        request=request,
    )


@transaction.atomic
def guardar_usuario(usuario, *, actor, motivo, request=None, accion_modificar="usuario.modificado"):
    """Crea o modifica un usuario y deja en la bitácora qué cambió y por qué."""
    usuario.full_clean()
    return guardar_con_bitacora(
        usuario,
        CAMPOS_AUDITADOS_USUARIO,
        accion_crear="usuario.creado",
        accion_modificar=accion_modificar,
        actor=actor,
        motivo=motivo,
        request=request,
    )


# --- Gestión de usuarios desde /configuracion/ ---------------------------------

MENSAJE_SOLO_DESARROLLADOR_GESTIONA = (
    "Solo un desarrollador puede crear o modificar usuarios con rol desarrollador, "
    "o asignar ese rol."
)
LONGITUD_CLAVE_TEMPORAL = 14
# Sin caracteres que se confunden al dictarlos o copiarlos (O/0, l/1/I).
_MAYUSCULAS = "ABCDEFGHJKLMNPQRSTUVWXYZ"
_MINUSCULAS = "abcdefghijkmnpqrstuvwxyz"
_DIGITOS = "23456789"
_SIMBOLOS = "-_.!?#"


def roles_asignables(actor):
    """Roles que el actor puede asignar: un administrador no puede asignar desarrollador."""
    if getattr(actor, "rol", None) == Rol.DESARROLLADOR:
        return list(Rol.values)
    return [rol for rol in Rol.values if rol != Rol.DESARROLLADOR]


def puede_gestionar(actor, rol_actual=None, rol_nuevo=None):
    """True si el actor puede crear o modificar un usuario que tiene `rol_actual`
    (None si es nuevo) y que quedará con `rol_nuevo`."""
    if not es_admin(actor):
        return False
    if actor.rol == Rol.DESARROLLADOR:
        return True
    return Rol.DESARROLLADOR not in (rol_actual, rol_nuevo)


def verificar_gestion(actor, usuario, rol_nuevo=None):
    """Lanza PermissionDenied si el actor no puede gestionar a este usuario.
    El rol actual se lee de la base de datos, no del objeto en memoria."""
    rol_actual = None
    if usuario.pk:
        rol_actual = Usuario.objects.filter(pk=usuario.pk).values_list("rol", flat=True).first()
    if not puede_gestionar(actor, rol_actual, rol_nuevo if rol_nuevo is not None else rol_actual):
        raise PermissionDenied(MENSAJE_SOLO_DESARROLLADOR_GESTIONA)


def generar_clave_temporal(usuario=None):
    """Clave aleatoria que cumple los validadores del proyecto."""
    todos = _MAYUSCULAS + _MINUSCULAS + _DIGITOS + _SIMBOLOS
    azar = secrets.SystemRandom()
    while True:
        caracteres = [secrets.choice(grupo) for grupo in (_MAYUSCULAS, _MINUSCULAS, _DIGITOS, _SIMBOLOS)]
        caracteres += [secrets.choice(todos) for _ in range(LONGITUD_CLAVE_TEMPORAL - len(caracteres))]
        azar.shuffle(caracteres)
        clave = "".join(caracteres)
        try:
            validate_password(clave, usuario)
        except ValidationError:
            continue
        return clave


def _clave_para(usuario, clave):
    """(clave, generada). Valida la clave escrita por el administrador o genera una."""
    if clave:
        validate_password(clave, usuario)
        return clave, False
    return generar_clave_temporal(usuario), True


@transaction.atomic
def crear_usuario(usuario, *, actor, motivo, clave=None, request=None):
    """Crea un usuario desde el panel. Queda con debe_cambiar_clave=True.
    Devuelve (clave, generada): si la generó el sistema, se muestra una sola vez."""
    verificar_gestion(actor, usuario, usuario.rol)
    usuario.is_staff = False
    usuario.is_superuser = False
    usuario.debe_cambiar_clave = True
    clave, generada = _clave_para(usuario, clave)
    usuario.set_password(clave)
    guardar_usuario(usuario, actor=actor, motivo=motivo, request=request)
    return clave, generada


@transaction.atomic
def editar_usuario(usuario, *, actor, motivo, request=None):
    """Guarda los cambios de datos, rol o área hechos desde el panel."""
    previo = Usuario.objects.select_for_update().get(pk=usuario.pk)
    # Primero: nadie cambia su propio rol (también evita evaluar permisos con un
    # rol que el actor se está intentando dar a sí mismo).
    if usuario.pk == actor.pk and usuario.rol != previo.rol:
        raise ValidationError({"rol": "No puede cambiar su propio rol."})
    verificar_gestion(actor, usuario, usuario.rol)
    # El estado y los privilegios técnicos no se cambian desde la edición.
    usuario.activo = previo.activo
    usuario.is_staff = previo.is_staff
    usuario.is_superuser = previo.is_superuser
    return guardar_usuario(usuario, actor=actor, motivo=motivo, request=request)


@transaction.atomic
def cambiar_estado_usuario(usuario, activo, *, actor, motivo, request=None):
    """Activa o desactiva un usuario (nunca se borra). Un usuario desactivado
    pierde su sesión en la siguiente petición."""
    verificar_gestion(actor, usuario)
    if usuario.pk == actor.pk and not activo:
        raise ValidationError("No puede desactivar su propia cuenta.")
    usuario.activo = activo
    return guardar_usuario(
        usuario,
        actor=actor,
        motivo=motivo,
        request=request,
        accion_modificar="usuario.activado" if activo else "usuario.desactivado",
    )


@transaction.atomic
def restablecer_clave(usuario, *, actor, motivo, clave=None, request=None):
    """Asigna una clave temporal a otro usuario, que deberá cambiarla al ingresar.
    Sus otras sesiones abiertas se cierran. Devuelve (clave, generada)."""
    verificar_gestion(actor, usuario)
    if usuario.pk == actor.pk:
        raise ValidationError("Para cambiar su propia clave use la opción «Cambiar clave».")
    clave, generada = _clave_para(usuario, clave)
    tenia = usuario.debe_cambiar_clave
    usuario.set_password(clave)
    usuario.debe_cambiar_clave = True
    usuario.save(update_fields=["password", "debe_cambiar_clave"])
    registrar(
        "cuenta.clave_restablecida",
        actor=actor,
        objeto=usuario,
        anterior={"debe_cambiar_clave": tenia},
        nuevo={"debe_cambiar_clave": True, "clave_generada": generada},
        motivo=motivo,
        request=request,
    )
    return clave, generada


@dataclass(frozen=True)
class Acceso:
    nombre: str
    descripcion: str
    url_name: str

    @property
    def url(self):
        """URL del acceso, o None si esa pantalla todavía no existe."""
        try:
            return reverse(self.url_name)
        except NoReverseMatch:
            return None


ACCESOS_COORDINADOR = [
    Acceso("Mi proyección", "Registre y consulte la proyección anual de su área.", "proyecciones:mi_proyeccion"),
]

ACCESOS_ADMIN = [
    Acceso("Información institucional", "Formatos originales, histórico y consecutivos de las áreas.", "fuentes:inicio"),
    Acceso("Listados", "Filtros por módulo, NIT, periodo y exportación con el mismo alcance.", "configuracion:listados"),
    Acceso("Seguimientos", "Entregas, eventos, pendientes y reportes FR-GDS-27.", "seguimientos:lista"),
    Acceso("Compras", "Necesidades y listas de elegibles.", "compras:necesidades"),
    Acceso("Revisión", "Revise y apruebe las proyecciones de las áreas.", "proyecciones:revision"),
    Acceso(
        "Periodos de proyección",
        "Abra, cierre y reabra los periodos de diligenciamiento.",
        "proyecciones:abrir_periodo",
    ),
    Acceso(
        "Consolidado",
        "Totales por año y área, con cantidades autorizadas y ajustadas, y exportación a Excel.",
        "proyecciones:consolidado",
    ),
    Acceso("Bitácora","Consulte quién cambió qué, cuándo y por qué.", "bitacora:consulta"),
    Acceso("Configuración", "Áreas, parámetros y catálogos del sistema.", "configuracion:inicio"),
    Acceso("Proveedores", "Fichas, requisitos y documentos de los proveedores.", "proveedores:lista"),
]

ACCESOS_DESARROLLADOR = [
    Acceso("Administración técnica", "Usuarios, bitácora y datos técnicos.", "admin:index"),
]

ACCESOS_PROVEEDOR = [
    Acceso("Portal", "Su ficha y sus documentos como proveedor.", "portal:inicio"),
]


def accesos_para(usuario):
    """Accesos que el inicio y el menú muestran según el rol del usuario."""
    if not getattr(usuario, "is_authenticated", False) or not usuario.is_active:
        return []
    if usuario.rol == Rol.COORDINADOR:
        return list(ACCESOS_COORDINADOR)
    if usuario.rol in ROLES_ADMIN:
        accesos = list(ACCESOS_ADMIN)
        if usuario.puede_usar_admin_tecnico:
            accesos += ACCESOS_DESARROLLADOR
        return accesos
    if usuario.rol == Rol.PROVEEDOR:
        return list(ACCESOS_PROVEEDOR)
    return []
