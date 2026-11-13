"""Libro de recepciones y ajustes, acumulados contra lo ordenado."""
from decimal import Decimal, InvalidOperation, localcontext
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone
from cuentas.models import Rol
from cuentas.permisos import es_admin
from bitacora.servicios import registrar
from compras.models import Recepcion, RecepcionLinea
from compras.numeracion_ordenes import _bloquear_orden
from compras.aprobacion_orden_servicios import guardar_estado, revisar_revision
from compras.operacion_archivos import transaccion, adjuntar
from parametros.catalogo import EXCESO_RECEPCION, COORDINADOR_RECEPCION
from parametros.servicios import obtener
from proveedores.servicios import _exigir_motivo


def exigir_receptor(orden, actor):
    if es_admin(actor):
        return
    if (getattr(actor, "is_authenticated", False) and getattr(actor, "is_active", False)
            and actor.rol == Rol.COORDINADOR and obtener(COORDINADOR_RECEPCION) is True and actor.area_id == orden.cotizacion.area_id):
        return
    raise PermissionDenied


def decimal_con_signo(valor):
    try:
        if isinstance(valor, (float, bool)):
            raise ValueError
        valor = Decimal(str(valor))
        if not valor.is_finite():
            raise ValueError
        return valor
    except (InvalidOperation, ValueError):
        raise ValidationError("Use cantidades decimales finitas, sin flotantes binarios.") from None


def acumulados(orden):
    with localcontext() as contexto:
        contexto.prec = 50
        datos = {l.pk: {"linea": l, "ordenado": l.cantidad, "recibido": Decimal(0), "rechazado": Decimal(0), "devuelto": Decimal(0)} for l in orden.lineas.all()}
        for movimiento in RecepcionLinea.objects.filter(recepcion__orden=orden).order_by("pk"):
            fila = datos[movimiento.linea_id]
            fila["recibido"] += movimiento.cantidad
            fila["rechazado"] += movimiento.rechazada
            fila["devuelto"] += movimiento.devuelta
        for fila in datos.values():
            fila["pendiente"] = max(Decimal(0), fila["ordenado"] - fila["recibido"])
            fila["exceso"] = max(Decimal(0), fila["recibido"] - fila["ordenado"])
            fila["estado"] = "completa" if fila["recibido"] >= fila["ordenado"] else "parcial" if fila["recibido"] > 0 else "pendiente"
        return list(datos.values())


def registrar_recepcion(orden, *, fecha, lineas, actor, motivo, tipo="recepcion", ajusta_id=None, autorizar_exceso=False, archivo=None, revision_esperada=None):
    exigir_receptor(orden, actor)
    _exigir_motivo(motivo)
    if type(autorizar_exceso) is not bool:
        raise ValidationError("Indique Sí/No para autorizar el exceso.")
    with transaccion(archivo) as rutas, localcontext() as contexto:
        contexto.prec = 50
        orden = _bloquear_orden(orden)
        exigir_receptor(orden, actor)
        revisar_revision(orden, revision_esperada)
        if orden.numero is None or orden.estado not in ("emitida", "recibida_parcial", "recibida_total"):
            raise ValidationError("Solo se reciben órdenes emitidas vigentes, sin cierre.")
        if fecha > timezone.localdate() or fecha < timezone.localdate(orden.fecha_emision):
            raise ValidationError("La recepción no puede preceder a la emisión ni estar en el futuro.")
        if tipo not in ("recepcion", "ajuste", "devolucion"):
            raise ValidationError("Indique recepción, ajuste o devolución.")
        if not isinstance(lineas, (list, tuple)) or not lineas or any(not isinstance(l, dict) or type(l.get("id")) is not int for l in lineas):
            raise ValidationError("Indique líneas y cantidades de esta orden.")
        anteriores = {f["linea"].pk: f for f in acumulados(orden)}
        ids = [l["id"] for l in lineas]
        if len(set(ids)) != len(ids) or not set(ids) <= set(anteriores) or any(set(l)-{"id", "cantidad", "rechazada", "devuelta", "observacion"} for l in lineas):
            raise ValidationError("Cada línea debe pertenecer a la orden y aparecer una sola vez.")
        permite = obtener(EXCESO_RECEPCION) is True
        from seguimientos.models import Seguimiento
        from seguimientos.servicios import lineas as lineas_seguimiento
        seguimiento = Seguimiento.objects.filter(orden=orden).first()
        cerradas = {f["linea"].pk for f in lineas_seguimiento(seguimiento) if f["cerrada"]} if seguimiento else set()
        movimientos, aumenta_exceso = [], False
        for datos in lineas:
            cantidad, rechazada = decimal_con_signo(datos.get("cantidad", 0)), decimal_con_signo(datos.get("rechazada", 0))
            devuelta = decimal_con_signo(datos.get("devuelta", 0))
            if tipo == "devolucion":
                if cantidad != 0 or rechazada != 0 or devuelta < 0:
                    raise ValidationError("En devolución indique solo cantidades devueltas positivas; se descuentan automáticamente de lo aceptado.")
                cantidad = -devuelta
            elif tipo == "recepcion" and devuelta != 0:
                raise ValidationError("Use Devolución para registrar cantidades devueltas.")
            elif tipo == "ajuste" and devuelta != 0 and cantidad != -devuelta:
                raise ValidationError("Ajustar una devolución exige cantidades aceptadas y devueltas opuestas.")
            if tipo == "recepcion" and (cantidad < 0 or rechazada < 0):
                raise ValidationError("Las cantidades negativas requieren un ajuste con referencia y motivo.")
            if cantidad == 0 and rechazada == 0 and devuelta == 0:
                continue
            if datos["id"] in cerradas:
                raise ValidationError("La línea está cerrada; reábrala con motivo antes de registrar movimientos.")
            anterior = anteriores[datos["id"]]
            recibido, rechazado = anterior["recibido"]+cantidad, anterior["rechazado"]+rechazada
            if recibido < 0 or rechazado < 0 or anterior["devuelto"]+devuelta < 0:
                raise ValidationError("Un ajuste no puede dejar acumulados recibidos o rechazados negativos.")
            aumenta_exceso |= cantidad > 0 and recibido > anterior["ordenado"]
            movimientos.append(RecepcionLinea(linea=anterior["linea"], cantidad=cantidad, rechazada=rechazada, devuelta=devuelta, observacion=datos.get("observacion", "").strip()))
        if not movimientos:
            raise ValidationError("Registre al menos una cantidad recibida, rechazada o de ajuste distinta de cero.")
        if aumenta_exceso and not (permite and autorizar_exceso and es_admin(actor)):
            raise ValidationError("El exceso requiere parámetro habilitado, autorización administrativa explícita y motivo.")
        recepcion = Recepcion(orden=orden, fecha=fecha, recibido_por=actor, observacion=motivo.strip(), tipo=tipo, ajusta_id=ajusta_id,
            exceso_autorizado=aumenta_exceso, reglas={"permite_exceso": permite, "coordinador": obtener(COORDINADOR_RECEPCION) is True})
        adjuntar(recepcion, archivo, rutas, "recepciones")
        recepcion.full_clean()
        recepcion.save()
        for movimiento in movimientos:
            movimiento.recepcion = recepcion
            movimiento.full_clean()
            movimiento.save()
        filas = acumulados(orden)
        orden.estado = "recibida_total" if all(f["pendiente"] == 0 for f in filas) else "recibida_parcial" if any(f["recibido"] > 0 for f in filas) else "emitida"
        guardar_estado(orden, actor, motivo, "orden.recepcion_registrada")
        from seguimientos.servicios import evento_recepcion
        evento_recepcion(recepcion, actor, motivo)
        registrar("recepcion.registrada", actor=actor, objeto=recepcion,
            nuevo={"orden_id": orden.pk, "tipo": tipo, "ajusta_id": ajusta_id, "exceso_autorizado": aumenta_exceso,
                "lineas": [{"linea_id": m.linea_id, "cantidad": str(m.cantidad), "rechazada": str(m.rechazada), "devuelta": str(m.devuelta)} for m in movimientos]}, motivo=motivo)
    return recepcion
