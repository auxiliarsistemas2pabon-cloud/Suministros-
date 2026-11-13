"""Vigencias documentales con fecha de referencia explícita y control D-05."""
from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone

from parametros.catalogo import BLOQUEAR_SI_VENCIDO
from parametros.servicios import obtener
from proveedores.models import DocumentoExigido, DocumentoProveedor, VersionMatriz
from proveedores.servicios import dias_alerta, dias_alerta_tipo

ETIQUETAS = {"vigente": "Vigente", "por_vencer": "Próximo a vencer", "vencido": "Vencido", "faltante": "Faltante"}


def clasificar(*, expedicion, vencimiento, referencia, dias=30, requiere_vencimiento=False):
    if expedicion is None or expedicion > referencia:
        return "faltante"
    if vencimiento is None:
        return "faltante" if requiere_vencimiento else "vigente"
    if vencimiento < referencia:
        return "vencido"
    return "por_vencer" if vencimiento <= referencia + timedelta(days=dias) else "vigente"


def tablero(proveedor, *, categoria=None, version=None, hoy=None):
    referencia = hoy or timezone.localdate()
    categoria = categoria or proveedor.categoria
    exigencias = DocumentoExigido.objects.filter(activo=True, categoria=categoria).select_related("tipo", "requisito__version", "categoria")
    if version is None:
        version = VersionMatriz.objects.exclude(estado="borrador").filter(desde__lte=referencia).filter(Q(hasta__isnull=True) | Q(hasta__gte=referencia)).first()
    exigencias = exigencias.filter(Q(requisito__isnull=True) | Q(requisito__version=version, requisito__activo=True))
    documentos = DocumentoProveedor.objects.filter(proveedor=proveedor, fecha_expedicion__lte=referencia).select_related("tipo").order_by("tipo_id", "-fecha_expedicion", "-pk")
    actuales = {}
    for documento in documentos:
        actuales.setdefault(documento.tipo_id, documento)
    general, filas = dias_alerta(), []
    for exigencia in exigencias:
        documento = actuales.get(exigencia.tipo_id)
        dias = dias_alerta_tipo(exigencia.tipo, general)
        estado = clasificar(expedicion=documento.fecha_expedicion if documento else None,
                            vencimiento=documento.fecha_vencimiento if documento else None, referencia=referencia, dias=dias, requiere_vencimiento=exigencia.tipo.requiere_vencimiento)
        filas.append({"exigencia": exigencia, "documento": documento, "estado": estado,
                      "etiqueta": ETIQUETAS[estado], "dias": dias, "referencia": referencia})
    return filas


def control_respuesta(evaluacion, requisito, respuesta, documento):
    filas = tablero(evaluacion.proveedor, categoria=evaluacion.categoria, version=evaluacion.version, hoy=evaluacion.fecha)
    asociadas = [f for f in filas if f["exigencia"].requisito_id == requisito.pk]
    advertencias = []
    estado = None
    dias = dias_alerta_tipo(documento.tipo) if documento else dias_alerta()
    if documento:
        estado = clasificar(expedicion=documento.fecha_expedicion, vencimiento=documento.fecha_vencimiento, referencia=evaluacion.fecha, dias=dias, requiere_vencimiento=documento.tipo.requiere_vencimiento)
    if asociadas and respuesta == "si":
        if not documento:
            advertencias.append("El requisito tiene documentos asociados y no se seleccionó evidencia documental fechada.")
        elif documento.tipo_id not in {f["exigencia"].tipo_id for f in asociadas}:
            raise ValidationError({"documento": "El tipo de documento no respalda este requisito según la configuración."})
        for fila in asociadas:
            if fila["estado"] in ("vencido", "faltante"):
                advertencias.append(f"{fila['exigencia'].tipo.nombre}: {fila['etiqueta']} a la fecha de evaluación.")
    bloquear = obtener(BLOQUEAR_SI_VENCIDO)
    if respuesta == "si" and documento and estado in ("vencido", "faltante"):
        if bloquear:
            raise ValidationError({"documento": "La evidencia está vencida, no estaba expedida o carece de vencimiento obligatorio a la fecha de evaluación; D-05 bloquea responder Sí."})
        advertencias.append("La evidencia seleccionada está vencida, no estaba expedida o carece de vencimiento obligatorio a la fecha de evaluación. Se permite con advertencia (D-05).")
    return {"referencia": evaluacion.fecha.isoformat(), "estado_evidencia": estado,
            "etiqueta_evidencia": ETIQUETAS.get(estado, "Sin documento seleccionado"), "dias": dias,
            "bloquear_si_vencido": bloquear, "advertencias": advertencias,
            "exigencias": [{"id": f["exigencia"].pk, "tipo": f["exigencia"].tipo.nombre,
                            "obligatorio": f["exigencia"].obligatorio, "estado": f["estado"]} for f in asociadas]}


def estado_guardado(respuesta, referencia):
    if respuesta.control_documental:
        return respuesta.control_documental
    datos = respuesta.documento_datos
    if not datos:
        return {"etiqueta_evidencia": "Sin documento seleccionado"}
    # Registros previos a B3 no guardaban el umbral; la fecha de vencimiento sí se conservó.
    estado = clasificar(expedicion=date.fromisoformat(datos["expedicion"]),
        vencimiento=date.fromisoformat(datos["vencimiento"]) if datos.get("vencimiento") else None,
        referencia=referencia, dias=dias_alerta())
    return {"referencia": referencia.isoformat(), "etiqueta_evidencia": ETIQUETAS[estado], "estado_evidencia": estado,
            "advertencias": ["Respuesta anterior a B3: plazo de alerta general actual; fechas documentales conservadas."]}
