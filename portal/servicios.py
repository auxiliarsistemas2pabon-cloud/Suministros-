"""Registro público y envíos del proveedor, sin modelos propios en la app portal."""

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils.crypto import salted_hmac

from bitacora.servicios import instantanea, registrar
from cuentas.models import Rol, Usuario, normalizar_correo
from parametros import servicios as parametros
from parametros.catalogo import ACTIVAR_REGISTRO_PORTAL
from proveedores.models import Proveedor
from proveedores.nit import normalizar
from proveedores.servicios import CAMPOS_AUDITADOS_PROVEEDOR

MENSAJE_REGISTRO = "Si los datos permiten el registro, su cuenta quedó creada. Puede intentar ingresar con la clave elegida; si la cuenta requiere revisión o ya existe un registro con su NIT o correo, comuníquese con la clínica."


def admitir_intento_registro(request):
    """Ventana fija por IP, compartida entre sesiones; no guarda la IP en texto claro."""
    from config.seguridad import ip_cliente_detras_de_proxy

    ventana = getattr(settings, "PORTAL_REGISTRO_VENTANA", 900)
    limite = getattr(settings, "PORTAL_REGISTRO_INTENTOS", 5)
    ip = str((ip_cliente_detras_de_proxy(request) if getattr(settings, "SECURE_PROXY_SSL_HEADER", None)
              else request.META.get("REMOTE_ADDR")) or "sin-ip")
    clave = "portal-registro:" + salted_hmac("portal.registro", ip).hexdigest()
    for _ in range(3):
        if cache.add(clave, 1, timeout=ventana):
            return True
        try:
            return cache.incr(clave) <= limite
        except ValueError:
            continue  # La clave pudo vencer entre add e incr.
    return False


def registrar_proveedor(datos, *, request=None):
    """No devuelve información sobre NIT/correos duplicados ni permite elegir privilegios."""
    nit, _ = normalizar(datos["nit"])
    correo = normalizar_correo(datos["correo"])
    proveedor = Proveedor(
        nit=nit, razon_social=datos["razon_social"], tipo_persona=datos["tipo_persona"],
        contacto_nombre=datos["contacto_nombre"], contacto_correo=correo,
        contacto_telefono=datos["contacto_telefono"], direccion=datos["direccion"],
        estado=Proveedor.Estado.REGISTRADO,
    )
    usuario = Usuario(correo=correo, nombre=datos["contacto_nombre"], rol=Rol.PROVEEDOR,
                      activo=parametros.obtener(ACTIVAR_REGISTRO_PORTAL), debe_cambiar_clave=False)
    validate_password(datos["clave1"], usuario)
    # Hash también cuando hay duplicados, para evitar una diferencia obvia de tiempo.
    usuario.set_password(datos["clave1"])
    proveedor.full_clean(validate_unique=False, validate_constraints=False)
    if Proveedor.objects.filter(nit=nit).exists() or Usuario.objects.filter(correo=correo).exists():
        return None
    try:
        with transaction.atomic():
            proveedor.save()
            usuario.proveedor = proveedor
            usuario.full_clean(validate_unique=False, validate_constraints=False)
            usuario.save()
            motivo = "Registro solicitado desde el portal público por el proveedor."
            registrar("proveedor.registrado_portal", actor=usuario, objeto=proveedor,
                      nuevo=instantanea(proveedor, CAMPOS_AUDITADOS_PROVEEDOR), motivo=motivo, request=request)
            registrar("usuario.registrado_portal", actor=usuario, objeto=usuario,
                      nuevo={"correo": usuario.correo, "rol": usuario.rol, "activo": usuario.activo,
                             "proveedor": proveedor.pk}, motivo=motivo, request=request)
    except IntegrityError:
        # Incluye dos altas simultáneas del mismo NIT/correo, sin dejar fichas sueltas.
        if Proveedor.objects.filter(nit=nit).exists() or Usuario.objects.filter(correo=correo).exists():
            return None
        raise
    return usuario


def ficha_de(actor):
    if not (getattr(actor, "is_authenticated", False) and getattr(actor, "is_active", False)
            and actor.rol == Rol.PROVEEDOR and actor.proveedor_id):
        raise PermissionDenied
    return Proveedor.objects.select_related("categoria").get(pk=actor.proveedor_id)


def enviar_documento(*, actor, tipo, fecha_expedicion, fecha_vencimiento, archivo, request=None):
    from proveedores.servicios import crear_envio

    proveedor = ficha_de(actor)
    return crear_envio(proveedor=proveedor, actor=actor, tipo=tipo, fecha_expedicion=fecha_expedicion,
                       fecha_vencimiento=fecha_vencimiento, archivo=archivo,
                       motivo="Documento presentado por el proveedor desde su portal.", request=request)
