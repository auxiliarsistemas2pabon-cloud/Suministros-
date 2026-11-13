"""Caso de proveedor único y validación reutilizable antes de decidir (B12)."""
from copy import deepcopy

from django.core.exceptions import ValidationError
from django.db import connection, transaction

from bitacora.servicios import guardar_con_bitacora, instantanea, registrar
from compras.models import CausalProveedorUnico, Cotizacion, PdfProveedorUnico, RevisionProveedorUnico
from config.utilidades import normalizar_espacios
from parametros.catalogo import EVIDENCIA_UNICO_OBLIGATORIA, MIN_JUSTIFICACION_UNICO
from parametros.models import Parametro
from parametros.servicios import obtener
from proveedores import archivos
from proveedores.servicios import _exigir_admin, _exigir_motivo

CAMPOS = ["proveedor_unico", "causal_proveedor_unico", "causal_unico_nombre", "justificacion_proveedor_unico",
          "pdf_proveedor_unico", "revision_proveedor_unico", "reglas_proveedor_unico", "oferta_unica_datos"]


def reglas_actuales():
    reglas = {"min_caracteres": obtener(MIN_JUSTIFICACION_UNICO), "evidencia_obligatoria": obtener(EVIDENCIA_UNICO_OBLIGATORIA)}
    if type(reglas["min_caracteres"]) is not int or reglas["min_caracteres"] < 1 or type(reglas["evidencia_obligatoria"]) is not bool:
        raise ValidationError("Configure un mínimo entero positivo y una regla Sí/No para la evidencia de proveedor único.")
    return reglas


def _bloquear_reglas():
    list(Parametro.objects.select_for_update().filter(clave__in=[MIN_JUSTIFICACION_UNICO, EVIDENCIA_UNICO_OBLIGATORIA]).order_by("pk"))
    return reglas_actuales()


@transaction.atomic
def guardar_causal(causal, *, actor, motivo):
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    causal.full_clean()
    guardar_con_bitacora(causal, ["nombre", "descripcion", "orden", "activo"], accion_crear="unico.causal_creada",
        accion_modificar="unico.causal_modificada", actor=actor, motivo=motivo)
    return causal


def _validar_caso(cotizacion, reglas, numero_ofertas):
    if not cotizacion.proveedor_unico:
        raise ValidationError("Confirme y justifique el caso de proveedor único antes de decidir con una sola oferta.")
    if numero_ofertas != 1:
        raise ValidationError("El caso de proveedor único requiere exactamente una oferta registrada. Revise las ofertas y el caso.")
    if not cotizacion.causal_proveedor_unico_id or not cotizacion.causal_unico_nombre:
        raise ValidationError({"causal": "Seleccione una causal para proveedor único."})
    texto = normalizar_espacios(cotizacion.justificacion_proveedor_unico)
    if not texto or len(texto) < reglas["min_caracteres"]:
        raise ValidationError({"justificacion": f"Escriba una justificación de al menos {reglas['min_caracteres']} caracteres, sin contar espacios repetidos."})
    if reglas["evidencia_obligatoria"] and not cotizacion.pdf_proveedor_unico_id:
        raise ValidationError({"archivo": "Adjunte la evidencia PDF obligatoria para proveedor único."})
    if cotizacion.pdf_proveedor_unico_id and cotizacion.pdf_proveedor_unico.cotizacion_id != cotizacion.pk:
        raise ValidationError("La evidencia pertenece a otra cotización.")


def _validar_para_decidir(cotizacion):
    """Se invoca con bloqueo de la cotización; no cambia su estado ni decide B13."""
    reglas = _bloquear_reglas()
    ofertas = list(cotizacion.ofertas.order_by("pk"))
    if not ofertas:
        raise ValidationError("Registre al menos una oferta antes de decidir.")
    if cotizacion.proveedor_unico or len(ofertas) == 1:
        _validar_caso(cotizacion, reglas, len(ofertas))
        oferta = ofertas[0]
        if cotizacion.oferta_unica_datos.get("proveedor_id") != oferta.proveedor_id:
            raise ValidationError("El proveedor no corresponde al caso confirmado. Revíselo nuevamente.")
    return {"proveedor_unico": cotizacion.proveedor_unico, "numero_ofertas": len(ofertas),
        "causal_id": cotizacion.causal_proveedor_unico_id, "causal": cotizacion.causal_unico_nombre,
        "justificacion": cotizacion.justificacion_proveedor_unico, "pdf_id": cotizacion.pdf_proveedor_unico_id,
        "revision": cotizacion.revision_proveedor_unico, "oferta": deepcopy(cotizacion.oferta_unica_datos), "reglas": reglas}


@transaction.atomic
def validar_para_decidir(cotizacion, *, actor):
    """Validador B12 que B13 debe ejecutar dentro de su transacción de decisión."""
    _exigir_admin(actor)
    cotizacion = Cotizacion.objects.select_for_update().get(pk=cotizacion.pk)
    return _validar_para_decidir(cotizacion)


def guardar_caso(cotizacion, *, proveedor_unico, causal=None, justificacion="", archivo=None, quitar_pdf=False,
                 revision_esperada=None, actor, motivo):
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    if type(proveedor_unico) is not bool:
        raise ValidationError("Indique Sí o No para proveedor único.")
    if archivo is not None:
        archivos.validar_pdf(archivo)
        if any(not getattr(b, "_from_testcase", False) for b in connection.atomic_blocks):
            raise ValidationError("Cargue la evidencia fuera de una transacción externa.")
    if archivo is not None and (quitar_pdf or not proveedor_unico):
        raise ValidationError("Cargue evidencia únicamente al confirmar el caso y sin marcar Retirar.")
    ruta = ""
    try:
        with transaction.atomic(durable=archivo is not None):
            cotizacion = Cotizacion.objects.select_for_update().get(pk=cotizacion.pk)
            if cotizacion.estado not in ("borrador", "en_comparacion"):
                raise ValidationError("La cotización ya no admite cambios de proveedor único.")
            if revision_esperada is not None and revision_esperada != cotizacion.revision_proveedor_unico:
                raise ValidationError("El caso de proveedor único cambió. Recargue antes de guardar.")
            anterior = instantanea(cotizacion, CAMPOS)
            reglas = _bloquear_reglas()
            cotizacion.proveedor_unico = proveedor_unico
            cotizacion.reglas_proveedor_unico = reglas
            cotizacion.revision_proveedor_unico += 1
            if quitar_pdf or not proveedor_unico:
                cotizacion.pdf_proveedor_unico = None
            if proveedor_unico:
                causal = CausalProveedorUnico.objects.select_for_update().filter(pk=causal.pk if causal else None, activo=True).first()
                if causal is None:
                    raise ValidationError({"causal": "Seleccione una causal activa."})
                cotizacion.causal_proveedor_unico = causal
                cotizacion.causal_unico_nombre = causal.nombre
                cotizacion.justificacion_proveedor_unico = normalizar_espacios(justificacion)
                ofertas = list(cotizacion.ofertas.order_by("pk"))
                # La evidencia nueva se valida y adjunta antes de comprobar la obligatoriedad.
                if archivo is not None:
                    ruta = archivos.guardar_pdf(archivo, carpeta="proveedor_unico")
                    adjunto = PdfProveedorUnico(cotizacion=cotizacion, archivo=ruta, nombre_archivo=archivos.nombre_original(archivo), cargado_por=actor)
                    adjunto.full_clean()
                    adjunto.save()
                    cotizacion.pdf_proveedor_unico = adjunto
                    registrar("unico.evidencia_cargada", actor=actor, objeto=adjunto,
                        nuevo=instantanea(adjunto, ["cotizacion", "nombre_archivo", "cargado_por", "fecha"]), motivo=motivo)
                _validar_caso(cotizacion, reglas, len(ofertas))
                oferta = ofertas[0]
                cotizacion.oferta_unica_datos = {"id": oferta.pk, "revision": oferta.revision,
                    "proveedor_id": oferta.proveedor_id, "nit": oferta.nit, "razon_social": oferta.razon_social}
            else:
                cotizacion.causal_proveedor_unico = None
                cotizacion.causal_unico_nombre = ""
                cotizacion.justificacion_proveedor_unico = ""
                cotizacion.oferta_unica_datos = {}
            # No se revalida aquí el origen B9: una lista puede haberse reabierto desde entonces.
            cotizacion.save(update_fields=CAMPOS)
            contenido = {"proveedor_unico": proveedor_unico, "causal_id": cotizacion.causal_proveedor_unico_id,
                "causal": cotizacion.causal_unico_nombre, "justificacion": cotizacion.justificacion_proveedor_unico,
                "oferta": deepcopy(cotizacion.oferta_unica_datos), "reglas": reglas}
            revision = RevisionProveedorUnico(cotizacion=cotizacion, numero=cotizacion.revision_proveedor_unico,
                contenido=contenido, pdf=cotizacion.pdf_proveedor_unico, actor=actor, motivo=motivo.strip())
            revision.full_clean()
            revision.save()
            accion = "unico.marcado" if proveedor_unico and not anterior["proveedor_unico"] else "unico.desmarcado" if not proveedor_unico and anterior["proveedor_unico"] else "unico.modificado"
            registrar(accion, actor=actor, objeto=cotizacion, anterior=anterior, nuevo=instantanea(cotizacion, CAMPOS), motivo=motivo)
    except BaseException:
        archivos.borrar_ahora(ruta)
        raise
    return cotizacion
