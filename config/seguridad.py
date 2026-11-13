"""Utilidades de seguridad transversales del proyecto."""

import ipaddress


def _ip_valida(valor):
    try:
        return str(ipaddress.ip_address(valor.strip()))
    except ValueError:
        return None


def ip_cliente_detras_de_proxy(request):
    """IP real del cliente cuando hay UN proxy inverso de confianza delante.

    El proxy agrega la IP de quien se conecta a él al final de
    X-Forwarded-For; las entradas anteriores las puede escribir el propio
    cliente y no son de fiar. Por eso se toma la última entrada. Si el
    encabezado falta o no es una IP válida, se usa REMOTE_ADDR.

    Se usa en django-axes (AXES_CLIENT_IP_CALLABLE) solo con
    DJANGO_DETRAS_DE_PROXY=True.
    """
    reenviado = request.META.get("HTTP_X_FORWARDED_FOR", "")
    partes = [parte for parte in reenviado.split(",") if parte.strip()]
    if partes:
        ip = _ip_valida(partes[-1])
        if ip:
            return ip
    return request.META.get("REMOTE_ADDR")
