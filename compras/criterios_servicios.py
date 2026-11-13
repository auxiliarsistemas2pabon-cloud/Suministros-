"""Catálogo versionado de criterios y asignación fija a las listas de elegibles."""

import json
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max, Q

from bitacora.servicios import guardar_con_bitacora, registrar
from compras.models import CriterioElegible, ListaElegibles, VersionCriterios
from config.utilidades import normalizar_espacios
from parametros.catalogo import REGLAS_ELEGIBLES, validar_reglas_elegibles
from parametros.models import Parametro
from parametros.servicios import obtener
from proveedores.servicios import _exigir_admin, _exigir_motivo


def _cerrojo():
    return VersionCriterios.objects.select_for_update().get(numero=1)


def _datos_criterios(version):
    return [{"nombre": c.nombre, "peso": str(c.peso), "orden": c.orden} for c in version.criterios.all()]


def validar_criterios(datos):
    if not 1 <= len(datos) <= 20:
        raise ValidationError("Registre entre uno y veinte criterios.")
    filas, nombres = [], set()
    for orden, dato in enumerate(datos, 1):
        nombre = normalizar_espacios(dato["nombre"])
        if not nombre or len(nombre) > 120 or nombre.casefold() in nombres:
            raise ValidationError("Indique nombres distintos, de uno a 120 caracteres.")
        nombres.add(nombre.casefold())
        try:
            if isinstance(dato["peso"], (float, bool)):
                raise ValueError
            peso = Decimal(str(dato["peso"]))
            if not peso.is_finite() or not 0 < peso <= 100 or peso.as_tuple().exponent < -2:
                raise ValueError
        except (ValueError, InvalidOperation):
            raise ValidationError("Los pesos deben ser decimales positivos con hasta dos decimales.") from None
        filas.append({"nombre": nombre, "peso": peso, "orden": orden})
    if sum((c["peso"] for c in filas), Decimal(0)) != 100:
        raise ValidationError("Los pesos de la versión deben sumar exactamente 100 %.")
    return filas


@transaction.atomic
def copiar_version(origen, *, actor, motivo):
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    _cerrojo()
    origen = VersionCriterios.objects.get(pk=origen.pk)
    numero = VersionCriterios.objects.aggregate(n=Max("numero"))["n"] + 1
    nueva = VersionCriterios.objects.create(numero=numero, notas=motivo.strip())
    for anterior in origen.criterios.all():
        CriterioElegible.objects.create(version=nueva, nombre=anterior.nombre, peso=anterior.peso, orden=anterior.orden)
    registrar("criterios.copiados", actor=actor, objeto=nueva,
              nuevo={"numero": numero, "origen": origen.numero, "criterios": _datos_criterios(nueva)}, motivo=motivo)
    return nueva


@transaction.atomic
def guardar_borrador(version, *, criterios, notas, actor, motivo):
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    _cerrojo()
    version = VersionCriterios.objects.select_for_update().get(pk=version.pk)
    if version.estado != "borrador":
        raise ValidationError("Solo se edita una versión en borrador. Copie otra versión.")
    filas = validar_criterios(criterios)
    anterior = {"criterios": _datos_criterios(version), "notas": version.notas}
    version.criterios.all()._reemplazar()
    for fila in filas:
        criterio = CriterioElegible(version=version, **fila)
        criterio.full_clean()
        criterio.save()
    version.notas = notas.strip()
    version.full_clean()
    version.save()
    registrar("criterios.editados", actor=actor, objeto=version, anterior=anterior,
              nuevo={"criterios": _datos_criterios(version), "notas": version.notas}, motivo=motivo)
    return version


@transaction.atomic
def publicar_version(version, *, desde, hasta=None, actor, motivo):
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    _cerrojo()
    version = VersionCriterios.objects.select_for_update().get(pk=version.pk)
    if version.estado != "borrador":
        raise ValidationError("Solo se publica una versión en borrador.")
    if not desde or (hasta and hasta < desde):
        raise ValidationError("Indique fechas de vigencia coherentes.")
    validar_criterios(_datos_criterios(version))
    otras = VersionCriterios.objects.exclude(pk=version.pk).exclude(estado="borrador")
    anterior = otras.filter(hasta__isnull=True, desde__lt=desde).order_by("-desde").first()
    solapadas = otras.filter(desde__lte=hasta or desde.max).filter(Q(hasta__isnull=True) | Q(hasta__gte=desde))
    if anterior:
        solapadas = solapadas.exclude(pk=anterior.pk)
    if solapadas.exists():
        raise ValidationError("La vigencia se superpone con otra versión publicada.")
    if anterior:
        fin = desde - timedelta(days=1)
        VersionCriterios.objects.filter(pk=anterior.pk)._transicion(hasta=fin, estado="retirada")
        registrar("criterios.retirados", actor=actor, objeto=anterior,
                  anterior={"hasta": anterior.hasta, "estado": anterior.estado}, nuevo={"hasta": fin, "estado": "retirada"}, motivo=motivo)
    VersionCriterios.objects.filter(pk=version.pk)._transicion(desde=desde, hasta=hasta, estado="publicada")
    registrar("criterios.publicados", actor=actor, objeto=version, anterior={"estado": "borrador"},
              nuevo={"estado": "publicada", "desde": desde, "hasta": hasta, "criterios": _datos_criterios(version)}, motivo=motivo)
    version.refresh_from_db()
    return version


def versiones_en_fecha(fecha):
    return VersionCriterios.objects.exclude(estado="borrador").filter(desde__lte=fecha).filter(Q(hasta__isnull=True) | Q(hasta__gte=fecha))


def preparar_lista(lista, version=None):
    """Dentro de la transacción de creación/asignación; conserva las reglas actuales."""
    _cerrojo()
    versiones = versiones_en_fecha(lista.fecha)
    if version is not None:
        versiones = versiones.filter(pk=version.pk)
    if not versiones.exists() and version is None:
        return False
    if versiones.count() != 1:
        raise ValidationError("Seleccione una única versión publicada aplicable a la fecha de la lista.")
    version = versiones.get()
    validar_criterios(_datos_criterios(version))
    parametro = Parametro.objects.select_for_update().filter(clave=REGLAS_ELEGIBLES).first()
    reglas = json.loads(validar_reglas_elegibles(parametro.valor if parametro else obtener(REGLAS_ELEGIBLES)))
    lista.version_criterios, lista.reglas_calculo = version, reglas
    return True


@transaction.atomic
def configurar_lista(lista, version, *, actor, motivo):
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    if version is None:
        raise ValidationError("Seleccione una versión publicada.")
    lista = ListaElegibles.objects.select_for_update().get(pk=lista.pk)
    if lista.estado != "borrador" or lista.version_criterios_id:
        raise ValidationError("Solo se configura una lista en borrador que aún no tiene versión.")
    preparar_lista(lista, version)
    lista.full_clean()
    guardar_con_bitacora(lista, ["version_criterios", "reglas_calculo"], accion_crear="lista_elegibles.configurada",
                        accion_modificar="lista_elegibles.configurada", actor=actor, motivo=motivo)
    return lista
