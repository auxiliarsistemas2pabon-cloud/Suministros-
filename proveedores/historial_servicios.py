"""Anulación y copias de evaluaciones sin sobrescribir el origen."""
from copy import deepcopy

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from bitacora.servicios import instantanea, registrar
from proveedores.evaluacion_servicios import obtener_resultado
from proveedores.models import EvaluacionProveedor, EvidenciaEvaluacion, RespuestaEvaluacion
from proveedores.respuestas_servicios import CAMPOS
from proveedores.servicios import _exigir_admin, _exigir_motivo


@transaction.atomic
def anular_evaluacion(evaluacion, *, actor, motivo, request=None):
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    evaluacion = EvaluacionProveedor.objects.select_for_update().get(pk=evaluacion.pk)
    if evaluacion.estado == "anulada":
        raise ValidationError("La evaluación ya está anulada.")
    anterior = evaluacion.estado
    # Un borrador anulado conserva también una foto de lo que tenía respondido.
    resultado = evaluacion.resultado or obtener_resultado(evaluacion)
    fecha = timezone.now()
    EvaluacionProveedor.objects.filter(pk=evaluacion.pk)._finalizar(
        estado="anulada", resultado=resultado, anulada_por=actor, fecha_anulacion=fecha,
        motivo_anulacion=motivo.strip(),
    )
    registrar("evaluacion.anulada", actor=actor, objeto=evaluacion, anterior={"estado": anterior},
              nuevo={"estado": "anulada", "resultado": resultado, "fecha_anulacion": fecha}, motivo=motivo, request=request)
    evaluacion.refresh_from_db()
    return evaluacion


@transaction.atomic
def copiar_evaluacion(evaluacion, *, actor, motivo, copiar_respuestas=True, request=None):
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    if type(copiar_respuestas) is not bool:
        raise ValidationError("Indique si desea copiar las respuestas.")
    origen = EvaluacionProveedor.objects.select_for_update().get(pk=evaluacion.pk)
    nueva = EvaluacionProveedor(proveedor=origen.proveedor, categoria=origen.categoria,
        categoria_nombre=origen.categoria_nombre, version=origen.version, fecha=origen.fecha,
        evaluador=actor, origen=origen)
    nueva.full_clean()
    nueva.save()
    registrar("evaluacion.creada", actor=actor, objeto=nueva, nuevo={"origen": origen.pk,
        "version": origen.version.numero, "categoria": origen.categoria_id, "fecha": nueva.fecha}, motivo=motivo, request=request)
    cantidad, adjuntos = 0, {}
    if copiar_respuestas:
        from parametros.catalogo import BLOQUEAR_SI_VENCIDO
        from parametros.servicios import obtener
        from proveedores.documental import estado_guardado
        bloquear = obtener(BLOQUEAR_SI_VENCIDO)
        for anterior in origen.respuestas.select_related("evidencia_pdf", "documento", "requisito"):
            if bloquear and anterior.respuesta == "si" and estado_guardado(anterior, nueva.fecha).get("estado_evidencia") in ("vencido", "faltante"):
                raise ValidationError("D-05 bloquea copiar respuestas Sí con evidencia vencida o no expedida. Cree la copia sin respuestas para corregirla.")
            adjunto = None
            if anterior.evidencia_pdf_id:
                if anterior.evidencia_pdf_id not in adjuntos:
                    fuente = anterior.evidencia_pdf
                    adjuntos[fuente.pk] = EvidenciaEvaluacion.objects.create(evaluacion=nueva,
                        archivo=fuente.archivo.name, nombre_archivo=fuente.nombre_archivo, cargado_por=actor)
                adjunto = adjuntos[anterior.evidencia_pdf_id]
            respuesta = RespuestaEvaluacion(evaluacion=nueva, requisito=anterior.requisito,
                respuesta=anterior.respuesta, observacion=anterior.observacion, confirma_na=anterior.confirma_na,
                documento=anterior.documento, documento_datos=deepcopy(anterior.documento_datos),
                control_documental=deepcopy(anterior.control_documental),
                evidencia_pdf=adjunto, respondido_por=actor)
            respuesta.full_clean()
            respuesta.save()
            registrar("respuesta.creada", actor=actor, objeto=respuesta, nuevo=instantanea(respuesta, CAMPOS), motivo=motivo, request=request)
            cantidad += 1
    registrar("evaluacion.copiada", actor=actor, objeto=nueva, anterior={"evaluacion_origen": origen.pk},
              nuevo={"evaluacion_nueva": nueva.pk, "respuestas_copiadas": cantidad}, motivo=motivo, request=request)
    return nueva
