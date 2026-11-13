"""Aprobación y movimientos operativos con historial conservado."""
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone

from compras.models import OfertaProtegidaQuerySet


class RegistroInmutable(models.Model):
    objects = OfertaProtegidaQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("El historial no se edita; registre una corrección con motivo.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("El historial y sus evidencias se conservan.")


class ReglaAprobacionOrden(models.Model):
    nombre = models.CharField(max_length=120)
    monto_desde = models.DecimalField(max_digits=32, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    monto_hasta = models.DecimalField(max_digits=32, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)])
    categoria = models.ForeignKey("proveedores.CategoriaProveedor", null=True, blank=True, on_delete=models.PROTECT)
    aprobaciones = models.PositiveSmallIntegerField(default=1, validators=[MinValueValidator(1)])
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ["monto_desde", "pk"]
        constraints = [models.UniqueConstraint(Lower("nombre"), name="regla_orden_nombre_unico"),
            models.CheckConstraint(condition=models.Q(monto_desde__gte=0, aprobaciones__gte=1), name="regla_orden_positiva"),
            models.CheckConstraint(condition=models.Q(monto_hasta__isnull=True) | models.Q(monto_hasta__gt=models.F("monto_desde")), name="regla_orden_rango")]

    def __str__(self):
        return self.nombre

    def clean(self):
        self.nombre = " ".join(self.nombre.split())
        if self.monto_hasta is not None and self.monto_hasta <= self.monto_desde:
            raise ValidationError("El límite superior debe ser mayor al inferior; se aplica desde inclusive, hasta exclusivo.")


class SolicitudAprobacionOrden(RegistroInmutable):
    orden = models.ForeignKey("compras.OrdenCompra", on_delete=models.PROTECT, related_name="solicitudes_aprobacion")
    ciclo = models.PositiveIntegerField()
    revision_borrador = models.PositiveIntegerField()
    reglas = models.JSONField()
    contenido = models.JSONField()
    cliente = models.JSONField()
    solicitada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    fecha = models.DateTimeField(default=timezone.now)
    motivo = models.TextField()

    class Meta:
        ordering = ["-ciclo"]
        constraints = [models.UniqueConstraint(fields=["orden", "ciclo"], name="solicitud_orden_ciclo_unico")]


class AprobacionOrden(RegistroInmutable):
    solicitud = models.ForeignKey(SolicitudAprobacionOrden, on_delete=models.PROTECT, related_name="firmas")
    orden = models.ForeignKey("compras.OrdenCompra", on_delete=models.PROTECT, related_name="aprobaciones")
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    usuario_texto = models.CharField(max_length=350)
    fecha = models.DateTimeField(default=timezone.now)
    decision = models.CharField(max_length=10, choices=[("aprueba", "Aprueba"), ("rechaza", "Rechaza")])
    comentario = models.TextField()

    class Meta:
        ordering = ["fecha", "pk"]
        constraints = [models.UniqueConstraint(fields=["solicitud", "usuario"], name="firma_orden_usuario_unico"),
            models.CheckConstraint(condition=models.Q(decision__in=["aprueba", "rechaza"]), name="firma_orden_decision_valida")]

    def clean(self):
        if self.solicitud.orden_id != self.orden_id:
            raise ValidationError("La firma no corresponde a la orden solicitada.")


class EvidenciaEnvioOrden(RegistroInmutable):
    orden = models.ForeignKey("compras.OrdenCompra", on_delete=models.PROTECT, related_name="envios")
    fecha_envio = models.DateTimeField()
    registrado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    fecha = models.DateTimeField(default=timezone.now)
    observacion = models.TextField()
    archivo = models.FileField(max_length=255, blank=True)
    nombre_archivo = models.CharField(max_length=255, blank=True)
    corrige = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT)

    class Meta:
        ordering = ["-fecha", "-pk"]

    def clean(self):
        if self.corrige_id and not type(self).objects.filter(pk=self.corrige_id, orden_id=self.orden_id).exists():
            raise ValidationError("La evidencia corregida debe pertenecer a la misma orden.")


class Recepcion(RegistroInmutable):
    orden = models.ForeignKey("compras.OrdenCompra", on_delete=models.PROTECT, related_name="recepciones")
    fecha = models.DateField(default=timezone.localdate)
    recibido_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    fecha_registro = models.DateTimeField(default=timezone.now)
    observacion = models.TextField()
    tipo = models.CharField(max_length=12, default="recepcion", choices=[("recepcion", "Recepción"), ("ajuste", "Ajuste"), ("devolucion", "Devolución")])
    ajusta = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT)
    exceso_autorizado = models.BooleanField(default=False)
    reglas = models.JSONField(default=dict)
    archivo = models.FileField(max_length=255, blank=True)
    nombre_archivo = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["fecha", "pk"]
        constraints = [models.CheckConstraint(condition=models.Q(tipo__in=["recepcion", "ajuste", "devolucion"]), name="recepcion_tipo_valido")]

    def clean(self):
        if self.ajusta_id and not type(self).objects.filter(pk=self.ajusta_id, orden_id=self.orden_id).exists():
            raise ValidationError("El ajuste debe referir una recepción de la misma orden.")
        if (self.tipo == "ajuste") != bool(self.ajusta_id):
            raise ValidationError("Un ajuste debe indicar la recepción que corrige; una recepción nueva no indica ajuste.")


class RecepcionLinea(RegistroInmutable):
    recepcion = models.ForeignKey(Recepcion, on_delete=models.PROTECT, related_name="lineas")
    linea = models.ForeignKey("compras.OrdenLinea", on_delete=models.PROTECT, related_name="recepciones")
    cantidad = models.DecimalField(max_digits=18, decimal_places=3, default=0)
    rechazada = models.DecimalField(max_digits=18, decimal_places=3, default=0)
    devuelta = models.DecimalField(max_digits=18, decimal_places=3, default=0)
    observacion = models.TextField(blank=True)

    class Meta:
        ordering = ["linea__posicion", "pk"]
        constraints = [models.UniqueConstraint(fields=["recepcion", "linea"], name="recepcion_linea_unica")]

    def clean(self):
        if self.linea.orden_id != self.recepcion.orden_id:
            raise ValidationError("La línea recibida pertenece a otra orden.")
