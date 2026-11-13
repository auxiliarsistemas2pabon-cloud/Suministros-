"""Versiones de FR14 y creación de evaluaciones con origen fijo."""
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max, Q
from django.utils import timezone

from bitacora.servicios import registrar
from proveedores.models import CategoriaProveedor, EvaluacionProveedor, Peso, Requisito, VersionMatriz
from proveedores.servicios import _exigir_admin, _exigir_motivo


@transaction.atomic
def copiar_version(origen, *, actor, motivo):
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    # La fila inicial es el cerrojo común de publicaciones y numeración.
    VersionMatriz.objects.select_for_update().get(numero=1)
    origen = VersionMatriz.objects.select_for_update().get(pk=origen.pk)
    numero = (VersionMatriz.objects.aggregate(n=Max("numero"))["n"] or 0) + 1
    nueva = VersionMatriz.objects.create(numero=numero, notas=motivo.strip())
    for anterior in origen.requisitos.all():
        requisito = Requisito.objects.create(version=nueva, numero=anterior.numero, grupo=anterior.grupo, texto=anterior.texto, activo=anterior.activo)
        for peso in anterior.pesos.all():
            Peso.objects.create(requisito=requisito, categoria=peso.categoria, valor=peso.valor)
    registrar("matriz.copiada", actor=actor, objeto=nueva, anterior={"version_origen": origen.numero}, nuevo={"numero": numero}, motivo=motivo)
    return nueva


@transaction.atomic
def publicar_version(version, *, desde, hasta=None, actor, motivo):
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    VersionMatriz.objects.select_for_update().get(numero=1)
    version = VersionMatriz.objects.select_for_update().get(pk=version.pk)
    if version.estado != "borrador":
        raise ValidationError("Solo se publica una matriz en borrador.")
    if not desde or (hasta and hasta < desde):
        raise ValidationError("Indique fechas de vigencia coherentes.")
    requisitos = version.requisitos.filter(activo=True)
    categorias = CategoriaProveedor.objects.filter(activo=True, pesos__requisito__version=version).distinct()
    if not requisitos.exists() or not categorias.exists():
        raise ValidationError("La matriz requiere requisitos activos y pesos por categoría.")
    for categoria in categorias:
        if requisitos.exclude(pesos__categoria=categoria).exists():
            raise ValidationError(f"Complete los pesos de todos los requisitos para {categoria}.")
    otras = VersionMatriz.objects.exclude(pk=version.pk).exclude(estado="borrador")
    # Una sucesora cierra la versión abierta anterior el día previo; conserva su histórico.
    anterior = otras.filter(hasta__isnull=True, desde__lt=desde).order_by("-desde").first()
    limite = hasta or timezone.datetime.max.date()
    solapadas = otras.filter(desde__lte=limite).filter(Q(hasta__isnull=True) | Q(hasta__gte=desde))
    if anterior:
        solapadas = solapadas.exclude(pk=anterior.pk)
    if solapadas.exists():
        raise ValidationError("Las fechas se superponen con otra versión publicada.")
    if anterior:
        fin = desde - timedelta(days=1)
        VersionMatriz.objects.filter(pk=anterior.pk)._transicion(hasta=fin, estado="retirada")
        registrar("matriz.retirada", actor=actor, objeto=anterior, anterior={"hasta": anterior.hasta, "estado": anterior.estado}, nuevo={"hasta": fin, "estado": "retirada"}, motivo=motivo)
    VersionMatriz.objects.filter(pk=version.pk)._transicion(desde=desde, hasta=hasta, estado="vigente")
    registrar("matriz.publicada", actor=actor, objeto=version, anterior={"estado": "borrador"}, nuevo={"estado": "vigente", "desde": desde, "hasta": hasta}, motivo=motivo)
    version.refresh_from_db()
    return version


def matriz_en_fecha(fecha):
    consulta = VersionMatriz.objects.exclude(estado="borrador").filter(desde__lte=fecha).filter(Q(hasta__isnull=True) | Q(hasta__gte=fecha))
    if consulta.count() != 1:
        raise ValidationError("No hay una única matriz publicada aplicable a la fecha elegida.")
    return consulta.get()


@transaction.atomic
def crear_evaluacion(proveedor, categoria, fecha, *, actor, motivo):
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    VersionMatriz.objects.select_for_update().get(numero=1)
    categoria = CategoriaProveedor.objects.get(pk=categoria.pk)
    if not categoria.activo:
        raise ValidationError("Seleccione una categoría activa.")
    version = matriz_en_fecha(fecha)
    requisitos = version.requisitos.filter(activo=True)
    if not requisitos.exists() or requisitos.exclude(pesos__categoria=categoria).exists():
        raise ValidationError("La matriz no tiene pesos completos para esta categoría.")
    evaluacion = EvaluacionProveedor(proveedor=proveedor, categoria=categoria, categoria_nombre=categoria.nombre, version=version, fecha=fecha, evaluador=actor)
    evaluacion.full_clean()
    evaluacion.save()
    registrar("evaluacion.creada", actor=actor, objeto=evaluacion, nuevo={"proveedor": proveedor.pk, "categoria": categoria.pk, "categoria_nombre": categoria.nombre, "version": version.numero, "fecha": fecha}, motivo=motivo)
    return evaluacion
