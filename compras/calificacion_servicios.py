from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction

from bitacora.servicios import guardar_con_bitacora
from compras.calificacion import calcular_puntaje
from compras.models import CalificacionElegible, ListaElegibles
from compras.historico import matriz_cierre
from proveedores.servicios import _exigir_admin, _exigir_motivo


def obtener_matriz(lista):
    conservada = matriz_cierre(lista)
    if conservada is not None:
        return conservada
    if not lista.version_criterios_id:
        return {"criterios": [], "filas": [], "reglas": {}, "completa": False}
    criterios = list(lista.version_criterios.criterios.values("id", "nombre", "peso", "orden"))
    participantes = list(lista.participantes.filter(activo=True))
    respuestas = {}
    for respuesta in CalificacionElegible.objects.filter(participante__lista=lista, participante__activo=True):
        respuestas.setdefault(respuesta.participante_id, {})[respuesta.criterio_id] = {
            "cumplimiento": respuesta.cumplimiento, "observacion": respuesta.observacion}
    filas = [{"participante": p, **calcular_puntaje(criterios, respuestas.get(p.pk, {}), lista.reglas_calculo)} for p in participantes]
    return {"criterios": criterios, "filas": filas, "reglas": lista.reglas_calculo,
            "completa": bool(filas) and all(f["completo"] for f in filas)}


@transaction.atomic
def guardar_matriz(lista, celdas, *, actor, motivo):
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    lista = ListaElegibles.objects.select_for_update().get(pk=lista.pk)
    if lista.estado != "borrador" or not lista.version_criterios_id:
        raise ValidationError("Solo se califica una lista en borrador con versión asignada.")
    participantes = {p.pk: p for p in lista.participantes.filter(activo=True)}
    criterios = {c.pk: c for c in lista.version_criterios.criterios.all()}
    esperadas = {(p, c) for p in participantes for c in criterios}
    recibidas = [(d["participante"], d["criterio"]) for d in celdas]
    if len(recibidas) != len(set(recibidas)) or set(recibidas) != esperadas:
        raise ValidationError("Los participantes o criterios cambiaron. Recargue la matriz antes de guardar.")
    escala = {Decimal(v) for v in lista.reglas_calculo["escala"]}
    anteriores = {(r.participante_id, r.criterio_id): r for r in CalificacionElegible.objects.filter(participante__lista=lista)}
    cambios = False
    for dato in celdas:
        valor = dato["cumplimiento"]
        if valor is not None:
            try:
                if isinstance(valor, (float, bool)):
                    raise ValueError
                valor = Decimal(str(valor))
                if not valor.is_finite() or valor not in escala:
                    raise ValueError
            except (ValueError, InvalidOperation):
                raise ValidationError("Seleccione un cumplimiento de la escala de la lista.") from None
        clave = (dato["participante"], dato["criterio"])
        respuesta = anteriores.get(clave)
        observacion = dato.get("observacion", "").strip()
        if respuesta is None and valor is None and not observacion:
            continue
        respuesta = respuesta or CalificacionElegible(participante=participantes[clave[0]], criterio=criterios[clave[1]])
        respuesta.cumplimiento, respuesta.observacion = valor, observacion
        respuesta.full_clean()
        registro = guardar_con_bitacora(respuesta, ["participante", "criterio", "cumplimiento", "observacion"],
                            accion_crear="elegible.calificado", accion_modificar="elegible.calificacion_modificada", actor=actor, motivo=motivo)
        cambios = cambios or registro is not None
    if cambios:
        from compras.decision_servicios import invalidar_decisiones
        invalidar_decisiones(lista, actor=actor, motivo=motivo)
    return lista
