"""Registro de cambios en la bitácora. Úselo desde los servicios de cada app."""

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import FieldDoesNotExist
from django.db import models

from bitacora.models import RegistroBitacora


def _ip(request):
    if request is None:
        return None
    # Respeta AXES_CLIENT_IP_CALLABLE (IP real detrás de proxy en producción).
    from axes.helpers import get_client_ip_address

    return get_client_ip_address(request) or None


def registrar(accion, *, actor=None, objeto=None, anterior=None, nuevo=None, motivo="", request=None):
    """Inserta un registro. `anterior` y `nuevo` deben ser serializables a JSON
    (se aceptan Decimal, fechas y UUID; Decimal se guarda como texto exacto)."""
    if actor is not None and not getattr(actor, "is_authenticated", False):
        actor = None
    registro = RegistroBitacora(
        accion=accion,
        actor=actor,
        actor_texto=actor.get_username() if actor else "",
        valor_anterior=anterior,
        valor_nuevo=nuevo,
        motivo=(motivo or "").strip(),
        ip=_ip(request),
    )
    if objeto is not None:
        registro.tipo_objeto = ContentType.objects.get_for_model(objeto, for_concrete_model=False)
        registro.objeto_id = str(objeto.pk)
        registro.objeto_texto = str(objeto)[:255]
    registro.save()
    return registro


def instantanea(objeto, campos):
    """Valores actuales de los campos indicados, listos para la bitácora.
    Las claves foráneas se guardan con su id y su texto."""
    valores = {}
    for nombre in campos:
        campo = objeto._meta.get_field(nombre)
        if isinstance(campo, models.ForeignKey):
            relacionado = getattr(objeto, nombre)
            valores[nombre] = {"id": relacionado.pk, "texto": str(relacionado)} if relacionado else None
        else:
            valores[nombre] = getattr(objeto, nombre)
    return valores


def diferencias(anterior, nuevo):
    """(valores_anteriores, valores_nuevos) solo con los campos que cambiaron."""
    cambiados = [clave for clave in nuevo if anterior.get(clave) != nuevo[clave]]
    return {c: anterior.get(c) for c in cambiados}, {c: nuevo[c] for c in cambiados}


def guardar_con_bitacora(instancia, campos, *, accion_crear, accion_modificar, actor, motivo, request=None):
    """Guarda `instancia` y registra la creación o los campos que cambiaron.
    Debe llamarse dentro de transaction.atomic()."""
    es_nueva = instancia._state.adding
    previo = None
    if not es_nueva:
        previo = instantanea(type(instancia)._default_manager.select_for_update().get(pk=instancia.pk), campos)
    instancia.save()
    actual = instantanea(instancia, campos)
    if es_nueva:
        return registrar(accion_crear, actor=actor, objeto=instancia, nuevo=actual, motivo=motivo, request=request)
    anterior, nuevo = diferencias(previo, actual)
    if nuevo:
        return registrar(
            accion_modificar,
            actor=actor,
            objeto=instancia,
            anterior=anterior,
            nuevo=nuevo,
            motivo=motivo,
            request=request,
        )
    return None


# --- Consulta para administración -------------------------------------------------------


def filtrar_registros(*, desde=None, hasta=None, actor=None, accion="", tipo_objeto=None, objeto_id="", texto=""):
    """Registros de la bitácora según los filtros; las fechas se comparan en la hora de Bogotá."""
    consulta = RegistroBitacora.objects.select_related("actor", "tipo_objeto")
    if desde:
        consulta = consulta.filter(fecha__date__gte=desde)
    if hasta:
        consulta = consulta.filter(fecha__date__lte=hasta)
    if actor is not None:
        consulta = consulta.filter(actor=actor)
    if accion:
        consulta = consulta.filter(accion=accion)
    if tipo_objeto is not None:
        consulta = consulta.filter(tipo_objeto=tipo_objeto)
    if objeto_id:
        consulta = consulta.filter(objeto_id=str(objeto_id).strip())
    if texto:
        consulta = consulta.filter(
            models.Q(motivo__icontains=texto)
            | models.Q(objeto_texto__icontains=texto)
            | models.Q(actor_texto__icontains=texto)
        )
    return consulta.order_by("-fecha", "-id")


def nombre_tipo(tipo_objeto):
    """Nombre legible de un ContentType, p. ej. «Línea de proyección»."""
    modelo = tipo_objeto.model_class() if tipo_objeto else None
    if modelo is None:
        return tipo_objeto.model if tipo_objeto else "—"
    nombre = str(modelo._meta.verbose_name)
    return nombre[:1].upper() + nombre[1:]


def _texto_valor(valor):
    if valor is None or valor == "":
        return "(vacío)"
    if isinstance(valor, bool):
        return "Sí" if valor else "No"
    if isinstance(valor, dict) and "texto" in valor:
        return str(valor["texto"])
    return str(valor)


def _etiqueta_campo(modelo, nombre):
    if modelo is not None:
        try:
            etiqueta = str(modelo._meta.get_field(nombre).verbose_name)
            return etiqueta[:1].upper() + etiqueta[1:]
        except FieldDoesNotExist:  # campo que ya no existe en el modelo
            pass
    return nombre


def detalle_cambios(registro):
    """Lista de {campo, anterior, nuevo} legible para mostrar un registro."""
    anterior, nuevo = registro.valor_anterior, registro.valor_nuevo
    if not isinstance(anterior, dict) and not isinstance(nuevo, dict):
        if anterior is None and nuevo is None:
            return []
        return [{"campo": "Valor", "anterior": _texto_valor(anterior), "nuevo": _texto_valor(nuevo)}]
    anterior = anterior if isinstance(anterior, dict) else {}
    nuevo = nuevo if isinstance(nuevo, dict) else {}
    modelo = registro.tipo_objeto.model_class() if registro.tipo_objeto_id else None
    filas = []
    for campo in dict.fromkeys([*anterior, *nuevo]):
        filas.append(
            {
                "campo": _etiqueta_campo(modelo, campo),
                "anterior": _texto_valor(anterior.get(campo)) if campo in anterior else "—",
                "nuevo": _texto_valor(nuevo.get(campo)) if campo in nuevo else "—",
            }
        )
    return filas
