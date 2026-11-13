"""Puestos densos, desempates y decisiones FR-GDS-20; no cierra listas."""

from collections import Counter
from decimal import Decimal, InvalidOperation
from datetime import datetime
from types import SimpleNamespace

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from bitacora.servicios import guardar_con_bitacora, registrar
from compras.calificacion_servicios import obtener_matriz
from compras.models import DecisionElegibles, DesempateElegibles, ListaElegibles, Necesidad
from proveedores.servicios import _exigir_admin, _exigir_motivo


def cantidad_necesidad(necesidad):
    if necesidad.cantidad_base is not None:
        return {"cantidad": necesidad.cantidad_base, "unidad": necesidad.unidad_base, "origen": "definida"}
    origenes = list(necesidad.origenes.select_related("linea"))
    if origenes and len({o.linea.unidad_id for o in origenes}) == 1 and len({o.datos_origen["unidad"] for o in origenes}) == 1:
        return {"cantidad": sum((o.cantidad for o in origenes), Decimal(0)), "unidad": origenes[0].datos_origen["unidad"], "origen": "líneas de origen"}
    return {"cantidad": None, "unidad": "", "origen": "pendiente de definir"}


def obtener_puestos(lista):
    matriz = obtener_matriz(lista)
    if matriz.get("historico"):
        return matriz
    completas = [f for f in matriz["filas"] if f["completo"]]
    pendientes = [f for f in matriz["filas"] if not f["completo"]]
    grupos = Counter(f["total"] for f in completas)
    desempates = {d.total: d for d in lista.desempates.filter(activo=True)}
    filas, grupos_empate, puesto = [], [], 1
    for denso, total in enumerate(sorted(grupos, reverse=True), 1):
        grupo = sorted([f for f in completas if f["total"] == total], key=lambda f: f["participante"].nit)
        empate = len(grupo) > 1
        desempate = desempates.get(total)
        aplicado = bool(empate and desempate and len(desempate.orden) == len(grupo) and set(desempate.orden) == {f["participante"].pk for f in grupo})
        if aplicado:
            orden = {pk: n for n, pk in enumerate(desempate.orden)}
            grupo.sort(key=lambda f: orden[f["participante"].pk])
        if empate:
            grupos_empate.append({"total": total, "filas": grupo, "desempate": desempate if aplicado else None})
        for n, fila in enumerate(grupo):
            fila.update(puesto=puesto + n if aplicado else puesto, puesto_calculado=denso, empate=empate,
                        desempate=desempate if aplicado else None)
        filas.extend(grupo)
        puesto += len(grupo) if aplicado else 1
    for fila in pendientes:
        fila.update(puesto=None, puesto_calculado=None, empate=False, desempate=None)
    matriz.update(filas=filas + pendientes, empates=grupos_empate, base=cantidad_necesidad(lista.necesidad))
    return matriz


def _contexto(lista, resultado):
    return {"version": lista.version_criterios_id, "reglas": lista.reglas_calculo,
        "base": {"cantidad": str(resultado["base"]["cantidad"]), "unidad": resultado["base"]["unidad"]},
        "filas": [{"participante": f["participante"].pk, "total": str(f["total"]), "puesto": f["puesto"],
                   "cantidad": str(f["participante"].cantidad_autorizada), "observacion": f["participante"].observacion,
                   "justificacion": f["participante"].justificacion_eleccion} for f in resultado["filas"]]}


def estado_decision(lista, resultado=None):
    resultado = resultado if resultado is not None else obtener_puestos(lista)
    if resultado.get("historico"):
        dato = lista.resultado_cierre["decision"]
        return {"registro": SimpleNamespace(**{**dato, "fecha": datetime.fromisoformat(dato["fecha"])}),
                "vigente": True, "total_autorizado": sum((f["participante"].cantidad_autorizada for f in resultado["filas"]), Decimal(0))}
    decision = DecisionElegibles.objects.filter(lista=lista).first()
    vigente = bool(decision and decision.vigente and decision.contexto == _contexto(lista, resultado))
    return {"registro": decision, "vigente": vigente,
            "total_autorizado": sum((f["participante"].cantidad_autorizada for f in resultado["filas"]), Decimal(0))}


def _validar(resultado, justificacion_unico, justificacion_cantidad):
    if not resultado["completa"]:
        raise ValidationError("Complete la calificación de todos los participantes activos antes de registrar la decisión.")
    base = resultado["base"]["cantidad"]
    if base is None:
        raise ValidationError("Defina la cantidad base y su unidad para esta necesidad.")
    elegidos = [f for f in resultado["filas"] if f["participante"].cantidad_autorizada > 0]
    if not elegidos:
        raise ValidationError("Autorice una cantidad positiva al menos a un participante.")
    if len(resultado["filas"]) == 1 and not justificacion_unico.strip():
        raise ValidationError("Justifique la decisión con proveedor único antes de validarla o cerrar la lista.")
    if sum((f["participante"].cantidad_autorizada for f in elegidos), Decimal(0)) > base and not justificacion_cantidad.strip():
        raise ValidationError("La suma autorizada supera la cantidad de la necesidad. Justifique la excepción.")
    if any(f["puesto"] != 1 and not f["participante"].justificacion_eleccion.strip() for f in elegidos):
        raise ValidationError("Justifique cada elección de un participante que no ocupa el primer puesto.")


def validar_para_cierre(lista):
    """Validación reutilizable por B8; no cambia el estado ni crea otros documentos."""
    resultado = obtener_puestos(lista)
    decision = estado_decision(lista, resultado)
    if not decision["vigente"]:
        raise ValidationError("Registre o revise la decisión vigente antes de cerrar la lista.")
    registro = decision["registro"]
    _validar(resultado, registro.justificacion_unico, registro.justificacion_cantidad)
    return resultado


def invalidar_decisiones(lista, *, actor, motivo, desempates=True):
    """El llamador ya bloqueó la lista dentro de su transacción."""
    decision = DecisionElegibles.objects.filter(lista=lista, vigente=True).first()
    if decision:
        decision.vigente = False
        guardar_con_bitacora(decision, ["vigente"], accion_crear="elegibles.decision_invalidada",
                            accion_modificar="elegibles.decision_invalidada", actor=actor, motivo=motivo)
    if desempates:
        for desempate in lista.desempates.filter(activo=True):
            desempate.activo = False
            guardar_con_bitacora(desempate, ["activo"], accion_crear="elegibles.desempate_invalidado",
                                accion_modificar="elegibles.desempate_invalidado", actor=actor, motivo=motivo)


@transaction.atomic
def definir_cantidad(necesidad, *, cantidad_base, unidad_base, actor, motivo):
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    necesidad = Necesidad.objects.select_for_update().get(pk=necesidad.pk)
    listas = list(necesidad.listas.select_for_update().order_by("pk"))
    if necesidad.estado != "abierta" or any(l.estado != "borrador" for l in listas):
        raise ValidationError("La cantidad base se conserva si la necesidad o alguna de sus listas ya está cerrada o anulada.")
    if cantidad_base is None or isinstance(cantidad_base, (float, bool)):
        raise ValidationError("Indique una cantidad decimal positiva.")
    necesidad.cantidad_base, necesidad.unidad_base = cantidad_base, unidad_base
    necesidad.full_clean()
    registro = guardar_con_bitacora(necesidad, ["cantidad_base", "unidad_base"], accion_crear="necesidad.cantidad_definida",
                                  accion_modificar="necesidad.cantidad_definida", actor=actor, motivo=motivo)
    if registro:
        for lista in listas:
            invalidar_decisiones(lista, actor=actor, motivo=motivo, desempates=False)
    return necesidad


@transaction.atomic
def guardar_desempate(lista, *, orden, justificacion, actor, motivo, total_esperado=None):
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    if not justificacion.strip():
        raise ValidationError("Justifique el desempate manual.")
    if any(type(pk) is not int or pk <= 0 for pk in orden):
        raise ValidationError("Seleccione participantes válidos para el desempate.")
    lista = ListaElegibles.objects.select_for_update().get(pk=lista.pk)
    if lista.estado != "borrador":
        raise ValidationError("Solo se desempata una lista en borrador.")
    resultado = obtener_puestos(lista)
    grupos = [g for g in resultado["empates"] if len(orden) == len(g["filas"]) and set(orden) == {f["participante"].pk for f in g["filas"]}]
    if len(grupos) != 1 or len(orden) != len(set(orden)):
        raise ValidationError("Ordene una sola vez a todos los participantes de un mismo empate actual.")
    total = grupos[0]["total"]
    if total_esperado is not None and total != total_esperado:
        raise ValidationError("El puntaje empatado cambió. Recargue la decisión.")
    desempate = lista.desempates.filter(total=total).first() or DesempateElegibles(lista=lista, total=total)
    desempate.orden, desempate.justificacion = list(orden), justificacion.strip()
    desempate.registrado_por, desempate.fecha, desempate.activo = actor, timezone.now(), True
    desempate.full_clean()
    guardar_con_bitacora(desempate, ["orden", "justificacion", "registrado_por", "fecha", "activo"],
                        accion_crear="elegibles.desempate_registrado", accion_modificar="elegibles.desempate_modificado", actor=actor, motivo=motivo)
    invalidar_decisiones(lista, actor=actor, motivo=motivo, desempates=False)
    return desempate


@transaction.atomic
def restablecer_empate(lista, desempate, *, actor, motivo):
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    lista = ListaElegibles.objects.select_for_update().get(pk=lista.pk)
    desempate = DesempateElegibles.objects.get(pk=desempate.pk, lista=lista)
    if lista.estado != "borrador" or not desempate.activo:
        raise ValidationError("Solo se restablece un desempate activo en borrador.")
    desempate.activo = False
    guardar_con_bitacora(desempate, ["activo"], accion_crear="elegibles.desempate_restablecido",
                        accion_modificar="elegibles.desempate_restablecido", actor=actor, motivo=motivo)
    invalidar_decisiones(lista, actor=actor, motivo=motivo, desempates=False)


@transaction.atomic
def guardar_decision(lista, asignaciones, *, justificacion_unico="", justificacion_cantidad="", actor, motivo):
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    # Orden común con la edición de cantidad: necesidad, después lista.
    necesidad_id = ListaElegibles.objects.values_list("necesidad_id", flat=True).get(pk=lista.pk)
    Necesidad.objects.select_for_update().get(pk=necesidad_id)
    lista = ListaElegibles.objects.select_for_update().get(pk=lista.pk)
    if lista.estado != "borrador":
        raise ValidationError("Solo se decide una lista en borrador.")
    participantes = {p.pk: p for p in lista.participantes.filter(activo=True)}
    recibidos = [d["participante"] for d in asignaciones]
    if len(recibidos) != len(set(recibidos)) or set(recibidos) != set(participantes):
        raise ValidationError("Los participantes cambiaron. Recargue la decisión.")
    fecha = timezone.now()
    for dato in asignaciones:
        p = participantes[dato["participante"]]
        valor = dato["cantidad_autorizada"]
        try:
            if isinstance(valor, (bool, float)):
                raise ValueError
            valor = Decimal(str(valor))
            if not valor.is_finite() or valor < 0:
                raise ValueError
        except (InvalidOperation, ValueError):
            raise ValidationError("Use cantidades decimales válidas mayores o iguales a cero.") from None
        p.cantidad_autorizada = valor
        p.observacion = dato.get("observacion", "").strip()
        p.justificacion_eleccion = dato.get("justificacion_eleccion", "").strip()
        p.decision_por, p.decision_fecha = actor, fecha
        p.full_clean()
        guardar_con_bitacora(p, ["cantidad_autorizada", "observacion", "justificacion_eleccion", "decision_por", "decision_fecha"],
                            accion_crear="elegibles.asignacion_creada", accion_modificar="elegibles.asignacion_modificada", actor=actor, motivo=motivo)
    resultado = obtener_puestos(lista)
    _validar(resultado, justificacion_unico, justificacion_cantidad)
    decision = DecisionElegibles.objects.filter(lista=lista).first() or DecisionElegibles(lista=lista)
    decision.justificacion_unico, decision.justificacion_cantidad = justificacion_unico.strip(), justificacion_cantidad.strip()
    decision.registrada_por, decision.fecha = actor, fecha
    decision.contexto, decision.vigente = _contexto(lista, resultado), True
    decision.full_clean()
    guardar_con_bitacora(decision, ["justificacion_unico", "justificacion_cantidad", "registrada_por", "fecha", "contexto", "vigente"],
                        accion_crear="elegibles.decision_registrada", accion_modificar="elegibles.decision_modificada", actor=actor, motivo=motivo)
    return decision
