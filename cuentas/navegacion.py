"""Presentación del menú; los permisos siguen definidos por cuentas.servicios."""
from cuentas.models import ROLES_ADMIN
from cuentas.servicios import Acceso, accesos_para

GRUPOS = {"operacion": "Operación", "planeacion": "Planeación", "administracion": "Administración"}
UBICACION = {
    "fuentes:inicio": ("operacion", "documento"),
    "compras:necesidades": ("operacion", "compras"), "compras:cotizaciones": ("operacion", "documento"),
    "compras:ordenes": ("operacion", "orden"), "proveedores:lista": ("operacion", "personas"),
    "seguimientos:lista": ("operacion", "seguimiento"), "portal:inicio": ("operacion", "documento"),
    "proyecciones:mi_proyeccion": ("planeacion", "calendario"), "proyecciones:revision": ("planeacion", "documento"),
    "proyecciones:abrir_periodo": ("planeacion", "calendario"), "proyecciones:consolidado": ("planeacion", "grafico"),
    "configuracion:listados": ("administracion", "lista"), "bitacora:consulta": ("administracion", "reloj"),
    "configuracion:inicio": ("administracion", "ajustes"), "admin:index": ("administracion", "ajustes"),
}


def _seccion(request):
    coincidencia = getattr(request, "resolver_match", None)
    if not coincidencia:
        return "inicio" if getattr(request, "path", "/") == "/" else ""
    espacio, nombre = coincidencia.namespace, coincidencia.url_name or ""
    if espacio == "compras":
        if nombre.startswith(("orden", "recepcion", "retencion")):
            return "compras:ordenes"
        if nombre.startswith(("cotizacion", "oferta", "verificacion", "proveedor_unico", "contrato", "poliza")):
            return "compras:cotizaciones"
        return "compras:necesidades"
    if espacio == "proyecciones":
        if nombre.startswith("mi_proyeccion"):
            return "proyecciones:mi_proyeccion"
        if nombre.startswith("consolidado"):
            return "proyecciones:consolidado"
        if nombre in ("abrir_periodo", "periodo_estado", "crear_proyeccion_area"):
            return "proyecciones:abrir_periodo"
        if nombre in ("plantilla_excel", "importar_excel") and request.user.rol == "coordinador":
            return "proyecciones:mi_proyeccion"
        return "proyecciones:revision"
    if espacio == "configuracion":
        return "configuracion:listados" if nombre in ("buscar", "listados", "listado_global") else "configuracion:inicio"
    return {"fuentes": "fuentes:inicio", "proveedores": "proveedores:lista", "seguimientos": "seguimientos:lista", "bitacora": "bitacora:consulta",
        "portal": "portal:inicio", "admin": "admin:index"}.get(espacio, "inicio" if getattr(request, "path", "") == "/" else "")


def menu_para(usuario, request):
    accesos = [a for a in accesos_para(usuario) if a.url]
    if not accesos:
        return {"grupos_menu": [], "seccion_actual": "Gestión de suministros", "seccion_menu": "", "inicio_activo": False}
    if usuario.rol in ROLES_ADMIN:
        accesos += [Acceso("Cotizaciones", "Comparación y adjudicación de ofertas.", "compras:cotizaciones"),
            Acceso("Órdenes de compra", "Aprobaciones, emisión y recepciones.", "compras:ordenes")]
    actual = _seccion(request)
    agrupados = {clave: [] for clave in GRUPOS}
    titulo = "Inicio"
    orden = list(UBICACION)
    for acceso in sorted(accesos, key=lambda a: orden.index(a.url_name) if a.url_name in orden else len(orden)):
        grupo, icono = UBICACION.get(acceso.url_name, ("administracion", "lista"))
        activo = acceso.url_name == actual
        agrupados[grupo].append({"nombre": acceso.nombre, "url": acceso.url, "descripcion": acceso.descripcion, "icono": icono, "activo": activo})
        if activo:
            titulo = acceso.nombre
    return {"grupos_menu": [{"nombre": GRUPOS[clave], "enlaces": enlaces} for clave, enlaces in agrupados.items() if enlaces],
        "seccion_actual": titulo, "seccion_menu": actual, "inicio_activo": actual == "inicio"}
