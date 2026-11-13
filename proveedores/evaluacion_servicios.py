import json

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from bitacora.servicios import registrar
from parametros.catalogo import REGLAS_FR14
from parametros.models import Parametro
from parametros.servicios import obtener
from proveedores.evaluacion import calcular_evaluacion
from proveedores.models import EvaluacionProveedor, Peso
from proveedores.servicios import _exigir_admin, _exigir_motivo


def obtener_resultado(evaluacion, reglas=None):
    if evaluacion.estado in ("finalizada", "anulada"):
        return evaluacion.resultado
    reglas = json.loads(obtener(REGLAS_FR14)) if reglas is None else reglas
    respuestas = {r.requisito_id: r.respuesta for r in evaluacion.respuestas.all()}
    pesos = Peso.objects.filter(requisito__version=evaluacion.version, requisito__activo=True, categoria=evaluacion.categoria).select_related("requisito")
    filas = [{"requisito_id": p.requisito_id, "numero": p.requisito.numero, "texto": p.requisito.texto,
              "grupo": p.requisito.grupo, "peso": p.valor, "respuesta": respuestas.get(p.requisito_id)} for p in pesos]
    return calcular_evaluacion(filas, reglas)


@transaction.atomic
def finalizar_evaluacion(evaluacion, *, actor, motivo, request=None):
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    evaluacion = EvaluacionProveedor.objects.select_for_update().get(pk=evaluacion.pk)
    if evaluacion.estado != "borrador":
        raise ValidationError("La evaluación ya fue finalizada.")
    parametro = Parametro.objects.select_for_update().filter(clave=REGLAS_FR14).first()
    reglas = json.loads(parametro.valor if parametro else obtener(REGLAS_FR14))
    resultado = obtener_resultado(evaluacion, reglas)
    if not resultado["finalizable"]:
        raise ValidationError("Complete todas las respuestas y asegure un máximo aplicable mayor que cero. Todo N/A es no calculable.")
    fecha = timezone.now()
    EvaluacionProveedor.objects.filter(pk=evaluacion.pk)._finalizar(estado="finalizada", resultado=resultado, finalizada_por=actor, fecha_finalizacion=fecha)
    registrar("evaluacion.finalizada", actor=actor, objeto=evaluacion, anterior={"estado": "borrador"},
              nuevo={"estado": "finalizada", "resultado": resultado, "fecha": fecha}, motivo=motivo, request=request)
    evaluacion.refresh_from_db()
    return evaluacion
