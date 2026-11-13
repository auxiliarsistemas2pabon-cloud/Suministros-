"""Borradores contractuales, historial privado y validación antes de cada firma."""
from contextlib import contextmanager
from decimal import Decimal
import json

from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import connection, transaction
from django.utils import timezone

from bitacora.servicios import guardar_con_bitacora, instantanea, registrar
from compras.models import Contrato, Cotizacion, DecisionCotizacion, PdfContractual, Poliza, RevisionContrato, TipoPoliza, _contrato_editable
from config.utilidades import normalizar_espacios
from cuentas.models import Usuario
from parametros.catalogo import CAMPOS_CONTRATO, CAMPOS_POLIZA, EXIGIR_POLIZA, validar_campos_contrato, validar_campos_poliza
from parametros.models import Parametro
from parametros.servicios import obtener
from proveedores import archivos
from proveedores.documental import ETIQUETAS, clasificar
from proveedores.servicios import _exigir_admin, _exigir_motivo, dias_alerta, dias_alerta_tipo

CAMPOS = ["numero", "supervisor", "supervisor_texto", "supervisor_nombre", "cargo", "fecha_inicio", "fecha_fin", "forma_pago", "valor", "pdf", "revision"]
CAMPOS_P = ["tipo", "tipo_nombre", "aseguradora", "numero", "valor_asegurado", "vigencia_desde", "vigencia_hasta", "pdf", "activo"]


def reglas_actuales():
    contrato = json.loads(validar_campos_contrato(obtener(CAMPOS_CONTRATO)))
    poliza = json.loads(validar_campos_poliza(obtener(CAMPOS_POLIZA)))
    exigir = obtener(EXIGIR_POLIZA)
    if type(exigir) is not bool:
        raise ValidationError("Configure Sí/No para exigir al menos una póliza.")
    return {"contrato": contrato, "poliza": poliza, "exigir_poliza": exigir}


@transaction.atomic
def guardar_requiere(cotizacion, *, requiere_contrato, revision_esperada=None, actor, motivo):
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    if type(requiere_contrato) is not bool:
        raise ValidationError("Indique Sí o No para requiere contrato.")
    cotizacion = Cotizacion.objects.select_for_update().get(pk=cotizacion.pk)
    if cotizacion.estado not in ("borrador", "en_comparacion") or cotizacion.decisiones.exclude(estado="anulada").exists():
        raise ValidationError("Indique si requiere contrato antes de proponer la decisión. Anule la propuesta vigente para cambiarlo.")
    if revision_esperada is not None and revision_esperada != cotizacion.revision_requiere_contrato:
        raise ValidationError("La selección de contrato cambió. Recargue antes de guardar.")
    anterior = cotizacion.requiere_contrato
    cotizacion.requiere_contrato = requiere_contrato
    cotizacion.revision_requiere_contrato += 1
    cotizacion.save(update_fields=["requiere_contrato", "revision_requiere_contrato"])
    registrar("contrato.requerimiento_modificado", actor=actor, objeto=cotizacion, anterior={"requiere_contrato": anterior}, nuevo={"requiere_contrato": requiere_contrato}, motivo=motivo)
    return cotizacion


@transaction.atomic
def guardar_tipo(tipo, *, actor, motivo):
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    tipo.full_clean()
    guardar_con_bitacora(tipo, ["nombre", "orden", "activo", "dias_alerta"], accion_crear="poliza.tipo_creado", accion_modificar="poliza.tipo_modificado", actor=actor, motivo=motivo)
    return tipo


@contextmanager
def _transaccion_pdf(archivo, quitar_pdf):
    if archivo is not None:
        archivos.validar_pdf(archivo)
        if quitar_pdf:
            raise ValidationError("No cargue y retire evidencia en la misma operación.")
        if any(not getattr(b, "_from_testcase", False) for b in connection.atomic_blocks):
            raise ValidationError("Cargue el PDF fuera de una transacción externa.")
    rutas = []
    try:
        with transaction.atomic(durable=archivo is not None):
            yield rutas
    except BaseException:
        for ruta in rutas:
            archivos.borrar_ahora(ruta)
        raise


def _adjuntar(contrato, poliza, archivo, rutas, actor, motivo):
    ruta = archivos.guardar_pdf(archivo, carpeta="polizas" if poliza else "contratos")
    rutas.append(ruta)
    adjunto = PdfContractual(contrato=contrato, poliza=poliza, archivo=ruta, nombre_archivo=archivos.nombre_original(archivo), cargado_por=actor)
    adjunto.full_clean()
    adjunto.save()
    registrar("contrato.pdf_cargado", actor=actor, objeto=adjunto, nuevo=instantanea(adjunto, ["contrato", "poliza", "nombre_archivo", "cargado_por", "fecha"]), motivo=motivo)
    return adjunto


def _revisar_revision(contrato, esperada):
    if esperada is not None and esperada != contrato.revision:
        raise ValidationError("El contrato o sus pólizas cambiaron. Recargue antes de guardar.")


def _valor(valor):
    if isinstance(valor, (float, bool)):
        raise ValidationError("Use un valor monetario Decimal, sin flotantes binarios.")
    return valor


def foto(contrato):
    datos = {"id": contrato.pk, "decision_id": contrato.decision_id, "revision": contrato.revision,
        "numero": contrato.numero, "supervisor_id": contrato.supervisor_id, "supervisor": contrato.supervisor_nombre,
        "cargo": contrato.cargo, "fecha_inicio": contrato.fecha_inicio, "fecha_fin": contrato.fecha_fin,
        "forma_pago": contrato.forma_pago, "valor": contrato.valor, "pdf_id": contrato.pdf_id,
        "polizas": [{"id": p.pk, "tipo_id": p.tipo_id, "tipo": p.tipo_nombre, "aseguradora": p.aseguradora, "numero": p.numero,
            "valor_asegurado": p.valor_asegurado, "vigencia_desde": p.vigencia_desde, "vigencia_hasta": p.vigencia_hasta,
            "pdf_id": p.pdf_id, "activo": p.activo} for p in contrato.polizas.order_by("pk")]}
    return json.loads(json.dumps(datos, cls=DjangoJSONEncoder))


def _revision(contrato, actor, motivo, accion):
    contrato.revision += 1
    contrato.save(update_fields=["revision"])
    contenido = {"contrato": foto(contrato), "reglas": reglas_actuales()}
    revision = RevisionContrato(contrato=contrato, numero=contrato.revision, contenido=contenido, actor=actor, motivo=motivo.strip())
    revision.full_clean()
    revision.save()
    registrar(accion, actor=actor, objeto=contrato, nuevo=contenido, motivo=motivo)


def guardar_contrato(decision, *, numero="", supervisor=None, supervisor_texto="", cargo="", fecha_inicio=None, fecha_fin=None,
                     forma_pago="", valor=None, archivo=None, quitar_pdf=False, revision_esperada=None, actor, motivo):
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    with _transaccion_pdf(archivo, quitar_pdf) as rutas:
        decision = _contrato_editable(decision.pk)
        contrato = Contrato.objects.filter(decision=decision).first() or Contrato(decision=decision)
        _revisar_revision(contrato, revision_esperada)
        if supervisor is not None:
            supervisor = Usuario.objects.filter(pk=supervisor.pk, activo=True).first()
            if supervisor is None:
                raise ValidationError({"supervisor": "Seleccione un usuario activo o indique el supervisor por texto."})
        contrato.numero, contrato.supervisor, contrato.supervisor_texto = normalizar_espacios(numero), supervisor, normalizar_espacios(supervisor_texto)
        contrato.supervisor_nombre = str(supervisor) if supervisor else contrato.supervisor_texto
        contrato.cargo, contrato.fecha_inicio, contrato.fecha_fin = normalizar_espacios(cargo), fecha_inicio, fecha_fin
        contrato.forma_pago, contrato.valor = forma_pago.strip(), _valor(valor)
        if quitar_pdf:
            contrato.pdf = None
        contrato.full_clean()
        contrato.save()
        if archivo is not None:
            contrato.pdf = _adjuntar(contrato, None, archivo, rutas, actor, motivo)
            contrato.full_clean()
            contrato.save(update_fields=["pdf"])
        _revision(contrato, actor, motivo, "contrato.guardado")
    return contrato


def guardar_poliza(contrato, *, poliza=None, tipo=None, aseguradora="", numero="", valor_asegurado=None, vigencia_desde=None,
                   vigencia_hasta=None, activo=True, archivo=None, quitar_pdf=False, revision_esperada=None, actor, motivo):
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    with _transaccion_pdf(archivo, quitar_pdf) as rutas:
        contrato = Contrato.objects.get(pk=contrato.pk)
        _contrato_editable(contrato.decision_id)
        contrato.refresh_from_db()
        _revisar_revision(contrato, revision_esperada)
        if poliza is not None:
            poliza = Poliza.objects.filter(pk=poliza.pk, contrato=contrato).first()
            if poliza is None:
                raise ValidationError("La póliza pertenece a otro contrato.")
        poliza = poliza or Poliza(contrato=contrato)
        nombre_tipo = ""
        if tipo is not None:
            tipo = TipoPoliza.objects.select_for_update().filter(pk=tipo.pk).first()
            retiro_historico = bool(tipo and poliza.pk and poliza.tipo_id == tipo.pk and activo is False)
            if tipo is None or (not tipo.activo and not retiro_historico):
                raise ValidationError({"tipo": "Seleccione un tipo de póliza activo."})
            nombre_tipo = poliza.tipo_nombre if not tipo.activo and retiro_historico else tipo.nombre
        poliza.tipo, poliza.tipo_nombre = tipo, nombre_tipo
        poliza.aseguradora, poliza.numero = normalizar_espacios(aseguradora), normalizar_espacios(numero)
        poliza.valor_asegurado = _valor(valor_asegurado)
        poliza.vigencia_desde, poliza.vigencia_hasta, poliza.activo = vigencia_desde, vigencia_hasta, activo
        if quitar_pdf:
            poliza.pdf = None
        poliza.full_clean()
        poliza.save()
        if archivo is not None:
            poliza.pdf = _adjuntar(contrato, poliza, archivo, rutas, actor, motivo)
            poliza.full_clean()
            poliza.save(update_fields=["pdf"])
        _revision(contrato, actor, motivo, "poliza.guardada")
    return poliza


@transaction.atomic
def validar_para_aprobar(decision, *, actor):
    _exigir_admin(actor)
    cotizacion_id = DecisionCotizacion.objects.values_list("cotizacion_id", flat=True).get(pk=decision.pk)
    Cotizacion.objects.select_for_update().get(pk=cotizacion_id)
    decision = DecisionCotizacion.objects.get(pk=decision.pk)
    if not decision.contenido["comparativo"].get("requiere_contrato", False):
        return {"requiere_contrato": False}
    list(Parametro.objects.select_for_update().filter(clave__in=[CAMPOS_CONTRATO, CAMPOS_POLIZA, EXIGIR_POLIZA]).order_by("pk"))
    reglas = reglas_actuales()
    contrato = Contrato.objects.filter(decision=decision).first()
    if contrato is None:
        raise ValidationError("La decisión requiere contrato. Regístrelo antes de aprobar.")
    datos = foto(contrato)
    campos = {**datos, "pdf": datos["pdf_id"]}
    faltantes = [k for k, obligatorio in reglas["contrato"].items() if obligatorio and (campos.get(k) is None or campos.get(k) == "")]
    if faltantes:
        raise ValidationError("Complete los campos obligatorios del contrato: " + ", ".join(faltantes))
    polizas = [p for p in datos["polizas"] if p["activo"]]
    if reglas["exigir_poliza"] and not polizas:
        raise ValidationError("Registre al menos una póliza activa para el contrato.")
    for poliza in polizas:
        campos_p = {**poliza, "pdf": poliza["pdf_id"]}
        faltantes = [k for k, obligatorio in reglas["poliza"].items() if obligatorio and (campos_p.get(k) is None or campos_p.get(k) == "")]
        if faltantes:
            raise ValidationError(f"Complete los campos obligatorios de la póliza {poliza['id']}: " + ", ".join(faltantes))
    return {"requiere_contrato": True, "contrato": datos, "reglas": reglas}


def tablero_polizas(contrato=None, *, referencia=None):
    referencia = referencia or timezone.localdate()
    consulta = Poliza.objects.filter(activo=True).select_related("tipo", "contrato__decision__cotizacion")
    consulta = consulta.filter(contrato=contrato) if contrato else consulta.exclude(contrato__decision__estado="anulada")
    general, filas = dias_alerta(), []
    for poliza in consulta:
        dias = dias_alerta_tipo(poliza.tipo, general) if poliza.tipo_id else general
        estado = clasificar(expedicion=poliza.vigencia_desde, vencimiento=poliza.vigencia_hasta, referencia=referencia, dias=dias, requiere_vencimiento=True)
        etiqueta = "Sin vigencia acreditada a la fecha" if estado == "faltante" else ETIQUETAS[estado]
        filas.append({"poliza": poliza, "estado": estado, "etiqueta": etiqueta, "dias": dias, "referencia": referencia})
    return filas
