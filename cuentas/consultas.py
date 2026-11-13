"""Indicadores de lectura para el inicio, separados de vistas y mutaciones."""
from django.db.models import Count, Q
from django.urls import reverse
from cuentas.models import Rol
from cuentas.permisos import es_admin


def resumen_inicio(usuario):
    if not getattr(usuario, "is_authenticated", False) or not usuario.is_active:
        return {"indicadores": [], "ordenes_recientes": [], "configuracion_pendiente": False}
    if es_admin(usuario):
        from compras.models import OrdenCompra
        from proveedores.models import Proveedor, EnvioProveedor
        from seguimientos.models import Seguimiento
        from parametros.servicios import obtener
        from parametros.catalogo import CLIENTE_ORDEN, NIT_CLIENTE_ORDEN
        datos = [
            ("Proveedores registrados", Proveedor.objects.count(), "Fichas disponibles", reverse("proveedores:lista"), "personas"),
            ("Órdenes por aprobar", OrdenCompra.objects.filter(estado="en_aprobacion").count(), "Esperan una decisión", reverse("compras:ordenes")+"?estado=en_aprobacion", "orden"),
            ("Documentos por revisar", EnvioProveedor.objects.filter(estado="pendiente").count(), "Envíos del portal", reverse("proveedores:bandeja"), "documento"),
            ("Seguimientos en curso", Seguimiento.objects.filter(cerrado=False).count(), "Operaciones sin cerrar", reverse("seguimientos:lista"), "seguimiento"),
        ]
        recientes = list(OrdenCompra.objects.order_by("-fecha_creacion", "-pk")[:5])
        pendiente = any(str(obtener(clave)).strip().upper() == "POR CONFIGURAR" for clave in (CLIENTE_ORDEN, NIT_CLIENTE_ORDEN))
    elif usuario.rol == Rol.COORDINADOR and usuario.area_id:
        from proyecciones.models import ProyeccionArea
        resumen = ProyeccionArea.objects.filter(area_id=usuario.area_id).aggregate(total=Count("pk"),
            borradores=Count("pk", filter=Q(estado="borrador")), enviadas=Count("pk", filter=Q(estado="enviada")), aprobadas=Count("pk", filter=Q(estado="aprobada")))
        url = reverse("proyecciones:mi_proyeccion")
        datos = [("Proyecciones de su área", resumen["total"], "Historial de periodos", url, "calendario"),
            ("Borradores", resumen["borradores"], "Pendientes de envío", url, "documento"),
            ("Enviadas", resumen["enviadas"], "Esperan validación", url, "reloj"),
            ("Aprobadas", resumen["aprobadas"], "Disponibles para consulta", url, "grafico")]
        recientes, pendiente = [], False
    else:
        return {"indicadores": [], "ordenes_recientes": [], "configuracion_pendiente": False}
    return {"indicadores": [{"nombre": n, "valor": v, "ayuda": a, "url": u, "icono": i} for n, v, a, u, i in datos],
        "ordenes_recientes": recientes, "configuracion_pendiente": pendiente}
