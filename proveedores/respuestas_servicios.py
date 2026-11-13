"""Respuestas y evidencias auditadas de evaluaciones en borrador."""
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.utils import timezone

from bitacora.servicios import instantanea, registrar
from proveedores import archivos
from proveedores.models import DocumentoProveedor, EvaluacionProveedor, EvidenciaEvaluacion, Peso, RespuestaEvaluacion
from proveedores.servicios import _exigir_admin, _exigir_motivo

CAMPOS = ["evaluacion", "requisito", "respuesta", "observacion", "confirma_na", "documento", "documento_datos", "control_documental", "evidencia_pdf", "respondido_por", "fecha"]


def guardar_respuesta(evaluacion, requisito, *, respuesta, observacion, confirma_na, documento=None,
                      archivo=None, quitar_pdf=False, actor, motivo, request=None):
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    if archivo is not None:
        archivos.validar_pdf(archivo)
        if any(not getattr(b, "_from_testcase", False) for b in connection.atomic_blocks):
            raise ValidationError("Cargue el PDF fuera de una transacción externa.")
    ruta = ""
    try:
        with transaction.atomic(durable=archivo is not None):
            evaluacion = EvaluacionProveedor.objects.select_for_update().get(pk=evaluacion.pk)
            if evaluacion.estado != "borrador":
                raise ValidationError("Solo se responden evaluaciones en borrador.")
            if not Peso.objects.filter(requisito=requisito, requisito__version=evaluacion.version,
                                       requisito__activo=True, categoria=evaluacion.categoria).exists():
                raise ValidationError("El requisito no pertenece a esta evaluación y categoría.")
            registro = RespuestaEvaluacion.objects.filter(evaluacion=evaluacion, requisito=requisito).first()
            anterior = instantanea(registro, CAMPOS) if registro else None
            registro = registro or RespuestaEvaluacion(evaluacion=evaluacion, requisito=requisito)
            registro.respuesta, registro.observacion = respuesta, observacion.strip()
            registro.confirma_na = confirma_na is True if respuesta == "na" else False
            registro.documento = DocumentoProveedor.objects.select_for_update().get(pk=documento.pk) if documento else None
            registro.documento_datos = {}
            if registro.documento:
                if registro.documento.proveedor_id != evaluacion.proveedor_id:
                    raise ValidationError("La evidencia documental pertenece a otro proveedor.")
                doc = registro.documento
                registro.documento_datos = {"id": doc.pk, "tipo": str(doc.tipo), "archivo": doc.archivo.name or "",
                                           "requiere_vencimiento": doc.tipo.requiere_vencimiento,
                                           "enlace": doc.enlace, "expedicion": doc.fecha_expedicion.isoformat(),
                                           "vencimiento": doc.fecha_vencimiento.isoformat() if doc.fecha_vencimiento else None}
            from proveedores.documental import control_respuesta
            registro.control_documental = control_respuesta(evaluacion, requisito, respuesta, registro.documento)
            if quitar_pdf:
                registro.evidencia_pdf = None
            if archivo is not None:
                ruta = archivos.guardar_pdf(archivo, carpeta="evidencias")
                adjunto = EvidenciaEvaluacion.objects.create(evaluacion=evaluacion, archivo=ruta,
                          nombre_archivo=archivos.nombre_original(archivo), cargado_por=actor)
                registro.evidencia_pdf = adjunto
            registro.respondido_por, registro.fecha = actor, timezone.now()
            registro.full_clean()
            registro.save()
            registrar("respuesta.creada" if anterior is None else "respuesta.modificada", actor=actor, objeto=registro,
                      anterior=anterior, nuevo=instantanea(registro, CAMPOS), motivo=motivo, request=request)
    except BaseException:
        archivos.borrar_ahora(ruta)
        raise
    return registro
