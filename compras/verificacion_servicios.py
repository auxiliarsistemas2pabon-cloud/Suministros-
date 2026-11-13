"""Verificaciones manuales y propuestas documentales que requieren confirmación."""
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

from bitacora.servicios import guardar_con_bitacora, instantanea, registrar
from compras.models import Cotizacion, EstadoVerificacion, Oferta, PdfVerificacionOferta, RevisionVerificacionOferta, TipoVerificacion, VerificacionOferta
from proveedores import archivos
from proveedores.documental import tablero
from proveedores.models import Proveedor
from proveedores.servicios import _exigir_admin, _exigir_motivo

CAMPOS = ["oferta", "tipo", "estado", "fecha", "verificado_por", "observacion", "tipo_nombre", "tipo_obligatoria", "tipo_origen",
          "estado_nombre", "estado_clasificacion", "oferta_revision", "revision", "propuesta", "pdf", "fecha_registro"]


@transaction.atomic
def guardar_tipo(tipo, *, actor, motivo):
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    tipo.full_clean()
    guardar_con_bitacora(tipo, ["nombre", "orden", "obligatoria", "origen", "activo"], accion_crear="verificacion.tipo_creado", accion_modificar="verificacion.tipo_modificado", actor=actor, motivo=motivo)
    return tipo


@transaction.atomic
def guardar_estado(estado, *, actor, motivo):
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    estado.full_clean()
    guardar_con_bitacora(estado, ["nombre", "clasificacion", "orden", "activo"], accion_crear="verificacion.estado_creado", accion_modificar="verificacion.estado_modificado", actor=actor, motivo=motivo)
    return estado


def proponer_documental(oferta, *, fecha=None):
    fecha = fecha or timezone.localdate()
    proveedor = Proveedor.objects.get(pk=oferta.proveedor_id)
    evaluacion = proveedor.evaluaciones.filter(estado="finalizada", fecha__lte=fecha).order_by("-fecha_finalizacion", "-pk").first()
    filas = tablero(proveedor, categoria=evaluacion.categoria if evaluacion else proveedor.categoria,
                    version=evaluacion.version if evaluacion else None, hoy=fecha)
    documentos = []
    for fila in sorted(filas, key=lambda f: f["exigencia"].pk):
        exigencia, doc = fila["exigencia"], fila["documento"]
        documentos.append({"exigencia_id": exigencia.pk, "tipo": exigencia.tipo.nombre, "obligatorio": exigencia.obligatorio,
            "estado": fila["estado"], "etiqueta": fila["etiqueta"], "documento_id": doc.pk if doc else None,
            "expedicion": doc.fecha_expedicion.isoformat() if doc else None,
            "vencimiento": doc.fecha_vencimiento.isoformat() if doc and doc.fecha_vencimiento else None, "dias_alerta": fila["dias"]})
    pendientes = [d for d in documentos if d["estado"] in ("vencido", "faltante")]
    if any(d["obligatorio"] for d in pendientes):
        clase, razon = "no", "Hay documentos obligatorios vencidos o faltantes a la fecha indicada."
    elif not documentos:
        clase, razon = "pendiente", "No hay exigencias configuradas; no se presume cumplimiento documental."
    elif pendientes:
        clase, razon = "pendiente", "Hay alertas en documentos opcionales; revise antes de confirmar."
    else:
        clase, razon = "si", "Los documentos exigidos están vigentes a la fecha, incluidos los próximos a vencer."
    return {"fecha": fecha.isoformat(), "proveedor_id": oferta.proveedor_id, "evaluacion_id": evaluacion.pk if evaluacion else None,
            "clasificacion": clase, "etiqueta": dict(EstadoVerificacion.CLASES)[clase], "razon": razon, "documentos": documentos}


def matriz_verificaciones(cotizacion):
    referencia = timezone.localdate()
    tipos = list(TipoVerificacion.objects.filter(Q(activo=True) | Q(registros__oferta__cotizacion=cotizacion)).distinct())
    registros = {(v.oferta_id, v.tipo_id): v for v in VerificacionOferta.objects.filter(oferta__cotizacion=cotizacion).select_related("verificado_por", "pdf")}
    filas = []
    for oferta in cotizacion.ofertas.select_related("proveedor").order_by("nit", "pk"):
        celdas = []
        propuesta = proponer_documental(oferta, fecha=referencia) if any(t.activo and t.origen == "documental" for t in tipos) else None
        for tipo in tipos:
            registro = registros.get((oferta.pk, tipo.pk))
            desactualizada = bool(registro and registro.oferta_revision != oferta.revision)
            clase = registro.estado_clasificacion if registro and not desactualizada else "pendiente"
            alerta = tipo.activo and tipo.obligatoria and clase in ("no", "pendiente")
            celdas.append({"tipo": tipo, "registro": registro, "desactualizada": desactualizada, "alerta": alerta,
                "clasificacion": clase, "propuesta": propuesta if tipo.activo and tipo.origen == "documental" else None})
        filas.append({"oferta": oferta, "celdas": celdas, "alertas": sum(c["alerta"] for c in celdas)})
    return {"tipos": tipos, "filas": filas, "alertas": sum(f["alertas"] for f in filas), "referencia": referencia}


def guardar_verificacion(oferta, tipo, *, estado, fecha, observacion="", confirmar_propuesta=False, firma_propuesta="",
                         archivo=None, quitar_pdf=False, oferta_revision_esperada=None, revision_esperada=None, actor, motivo):
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    if archivo is not None:
        archivos.validar_pdf(archivo)
        if any(not getattr(b, "_from_testcase", False) for b in connection.atomic_blocks):
            raise ValidationError("Cargue la evidencia fuera de una transacción externa.")
    if archivo is not None and quitar_pdf:
        raise ValidationError("No cargue y retire la evidencia en la misma operación.")
    ruta = ""
    try:
        with transaction.atomic(durable=archivo is not None):
            cotizacion_id = Oferta.objects.values_list("cotizacion_id", flat=True).get(pk=oferta.pk)
            cotizacion = Cotizacion.objects.select_for_update().get(pk=cotizacion_id)
            if cotizacion.estado not in ("borrador", "en_comparacion"):
                raise ValidationError("La cotización ya no admite cambios de verificaciones.")
            oferta = Oferta.objects.select_for_update().get(pk=oferta.pk)
            if oferta_revision_esperada is not None and oferta_revision_esperada != oferta.revision:
                raise ValidationError("La oferta cambió. Revise su nueva revisión antes de verificarla.")
            tipo = TipoVerificacion.objects.select_for_update().get(pk=tipo.pk)
            estado = EstadoVerificacion.objects.select_for_update().get(pk=estado.pk)
            if not tipo.activo or not estado.activo:
                raise ValidationError("Seleccione un tipo y estado activos.")
            registro = VerificacionOferta.objects.filter(oferta=oferta, tipo=tipo).first()
            if revision_esperada is not None and revision_esperada != (registro.revision if registro else 0):
                raise ValidationError("La verificación cambió. Recargue antes de guardar.")
            propuesta = {}
            if tipo.origen == "documental":
                if confirmar_propuesta is not True:
                    raise ValidationError("Revise y confirme expresamente la propuesta documental.")
                propuesta = proponer_documental(oferta, fecha=fecha)
                try:
                    if signing.loads(firma_propuesta, salt="propuesta-verificacion") != propuesta:
                        raise signing.BadSignature()
                except signing.BadSignature:
                    raise ValidationError("La propuesta documental cambió o no corresponde a la fecha. Consúltela nuevamente antes de confirmar.") from None
                if estado.clasificacion != propuesta["clasificacion"] and not observacion.strip():
                    raise ValidationError("Explique en la observación por qué confirma un estado distinto de la propuesta.")
            registro = registro or VerificacionOferta(oferta=oferta, tipo=tipo)
            anterior = instantanea(registro, CAMPOS) if registro.pk else None
            registro.estado, registro.fecha, registro.verificado_por = estado, fecha, actor
            registro.observacion = observacion.strip()
            registro.tipo_nombre, registro.tipo_obligatoria, registro.tipo_origen = tipo.nombre, tipo.obligatoria, tipo.origen
            registro.estado_nombre, registro.estado_clasificacion = estado.nombre, estado.clasificacion
            registro.oferta_revision, registro.propuesta = oferta.revision, propuesta
            registro.revision += 1
            registro.fecha_registro = timezone.now()
            if quitar_pdf:
                registro.pdf = None
            registro.full_clean()
            registro.save()
            if archivo is not None:
                ruta = archivos.guardar_pdf(archivo, carpeta="verificaciones")
                adjunto = PdfVerificacionOferta(verificacion=registro, archivo=ruta, nombre_archivo=archivos.nombre_original(archivo), cargado_por=actor)
                adjunto.full_clean()
                adjunto.save()
                registro.pdf = adjunto
                registro.full_clean()
                registro.save()
                registrar("verificacion.evidencia_cargada", actor=actor, objeto=adjunto,
                    nuevo=instantanea(adjunto, ["verificacion", "nombre_archivo", "cargado_por", "fecha"]), motivo=motivo)
            contenido = {"oferta_id": oferta.pk, "oferta_revision": oferta.revision, "proveedor_id": oferta.proveedor_id,
                "nit": oferta.nit, "razon_social": oferta.razon_social, "tipo": tipo.nombre, "obligatoria": tipo.obligatoria,
                "estado": estado.nombre, "clasificacion": estado.clasificacion, "fecha": fecha.isoformat(),
                "verificado_por": str(actor), "observacion": registro.observacion, "propuesta": propuesta}
            revision = RevisionVerificacionOferta(verificacion=registro, numero=registro.revision, contenido=contenido,
                pdf=registro.pdf, actor=actor, motivo=motivo.strip())
            revision.full_clean()
            revision.save()
            registrar("verificacion.confirmada" if anterior is None else "verificacion.modificada", actor=actor, objeto=registro,
                anterior=anterior, nuevo=instantanea(registro, CAMPOS), motivo=motivo)
    except BaseException:
        archivos.borrar_ahora(ruta)
        raise
    return registro
