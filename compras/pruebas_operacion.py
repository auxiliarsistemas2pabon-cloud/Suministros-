"""Preparación de firmas para pruebas unitarias del motor interno B16/B17."""
from compras.models import AprobacionOrden
from compras.aprobacion_orden_servicios import solicitar, solicitud_actual
from parametros.catalogo import CLIENTE_ORDEN, NIT_CLIENTE_ORDEN, DEFINICIONES
from parametros.models import Parametro


def preparar_numeracion(orden, actor, firmante):
    for clave, valor in ((CLIENTE_ORDEN, "Clínica ficticia de pruebas"), (NIT_CLIENTE_ORDEN, "900000001-1")):
        definicion = DEFINICIONES[clave]
        parametro, _ = Parametro.objects.get_or_create(clave=clave, defaults={"nombre": definicion.nombre, "tipo": definicion.tipo,
            "valor": valor, "valor_por_defecto": definicion.valor_por_defecto})
        if parametro.valor == "POR CONFIGURAR":
            parametro.valor = valor
            parametro.save()
    actual = solicitar(orden, actor=actor, motivo="Solicitud ficticia para comprobar el motor de numeración")
    solicitud = solicitud_actual(actual)
    AprobacionOrden.objects.create(orden=actual, solicitud=solicitud, usuario=firmante, usuario_texto=str(firmante), decision="aprueba", comentario="Firma ficticia preparada antes de probar el motor interno")
    orden.refresh_from_db()
    return orden
