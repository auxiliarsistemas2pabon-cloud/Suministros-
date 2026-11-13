from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone
from compras.operacion_models import RegistroInmutable
from compras.models import OfertaProtegidaQuerySet


class Catalogo(models.Model):
    nombre = models.CharField(max_length=150)
    codigo = models.SlugField(max_length=50, unique=True)
    activo = models.BooleanField(default=True)

    class Meta:
        abstract = True
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre

    def clean(self):
        self.nombre = " ".join(self.nombre.split())
        self.codigo = self.codigo.strip().lower()
        if not self.nombre:
            raise ValidationError("El nombre es obligatorio.")


class TipoSeguimiento(Catalogo):
    pass


class TipoEvento(Catalogo):
    funcion = models.CharField(max_length=25, default="informativo", choices=[("informativo", "Informativo"),
        ("solicita_documentos", "Solicita documentos"), ("recibe_documentos", "Recibe documentos"),
        ("recepcion", "Recepción"), ("devolucion", "Devolución"), ("cierre", "Cierre"), ("reapertura", "Reapertura")])


class ResultadoCierre(Catalogo):
    pass


class Seguimiento(models.Model):
    objects = OfertaProtegidaQuerySet.as_manager()
    orden = models.OneToOneField("compras.OrdenCompra", on_delete=models.PROTECT, null=True, blank=True, related_name="seguimiento")
    contrato = models.ForeignKey("compras.Contrato", on_delete=models.PROTECT, null=True, blank=True, related_name="seguimientos")
    tipo = models.ForeignKey(TipoSeguimiento, on_delete=models.PROTECT)
    tipo_nombre = models.CharField(max_length=150)
    area = models.ForeignKey("areas.Area", on_delete=models.PROTECT)
    proveedor = models.ForeignKey("proveedores.Proveedor", on_delete=models.PROTECT)
    nit = models.CharField(max_length=25)
    razon_social = models.CharField(max_length=200)
    objeto = models.TextField()
    valor = models.DecimalField(max_digits=32, decimal_places=2, validators=[MinValueValidator(0)])
    comite = models.CharField(max_length=255, blank=True)
    fecha_comite = models.DateField(null=True, blank=True)
    abierto_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    fecha = models.DateTimeField(default=timezone.now)
    origen_datos = models.JSONField()
    cerrado = models.BooleanField(default=False, editable=False)
    revision = models.PositiveIntegerField(default=1, editable=False)
    version_hitos = models.PositiveIntegerField(default=1, editable=False)

    class Meta:
        ordering = ["-fecha", "-pk"]
        constraints = [models.CheckConstraint(condition=models.Q(orden__isnull=False) | models.Q(contrato__isnull=False), name="seguimiento_tiene_origen"),
            models.CheckConstraint(condition=models.Q(valor__gte=0), name="seguimiento_valor_valido"),
            models.UniqueConstraint(fields=["contrato"], condition=models.Q(orden__isnull=True), name="seguimiento_principal_contrato_unico")]

    def __str__(self):
        return f"Seguimiento {self.pk} · {self.razon_social}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            anterior = type(self).objects.get(pk=self.pk)
            if not getattr(self, "_operacion", False):
                raise ValidationError("Use las acciones de corrección, cierre o reapertura con motivo.")
            for campo in ("orden_id", "contrato_id", "fecha", "abierto_por_id", "origen_datos"):
                if getattr(self, campo) != getattr(anterior, campo):
                    raise ValidationError("El origen y apertura del seguimiento se conservan.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Los seguimientos y su historial se conservan.")


class EventoSeguimiento(RegistroInmutable):
    seguimiento = models.ForeignKey(Seguimiento, on_delete=models.PROTECT, related_name="eventos")
    tipo = models.ForeignKey(TipoEvento, on_delete=models.PROTECT)
    tipo_nombre = models.CharField(max_length=150)
    funcion = models.CharField(max_length=25)
    fecha = models.DateTimeField()
    registrado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    fecha_registro = models.DateTimeField(default=timezone.now)
    nota = models.TextField()
    archivo = models.FileField(max_length=255, blank=True)
    nombre_archivo = models.CharField(max_length=255, blank=True)
    corrige = models.OneToOneField("self", null=True, blank=True, on_delete=models.PROTECT, related_name="correccion")
    recepcion = models.OneToOneField("compras.Recepcion", null=True, blank=True, on_delete=models.PROTECT, related_name="evento")

    class Meta:
        ordering = ["fecha", "pk"]

    def clean(self):
        if self.corrige_id and not type(self).objects.filter(pk=self.corrige_id, seguimiento_id=self.seguimiento_id).exists():
            raise ValidationError("El evento corregido pertenece a otro seguimiento o no existe.")
        if self.recepcion_id and self.recepcion.orden_id != self.seguimiento.orden_id:
            raise ValidationError("La recepción no corresponde al seguimiento.")


class PlantillaHito(models.Model):
    tipo_seguimiento = models.ForeignKey(TipoSeguimiento, on_delete=models.PROTECT)
    nombre = models.CharField(max_length=150)
    referencia = models.ForeignKey(TipoEvento, on_delete=models.PROTECT, null=True, blank=True, related_name="hitos_referencia")
    cumple = models.ForeignKey(TipoEvento, on_delete=models.PROTECT, related_name="hitos_cumplimiento")
    plazo_dias = models.PositiveIntegerField(default=0)
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ["nombre", "pk"]

    def __str__(self):
        return self.nombre


class HitoSeguimiento(RegistroInmutable):
    seguimiento = models.ForeignKey(Seguimiento, on_delete=models.PROTECT, related_name="hitos")
    version = models.PositiveIntegerField()
    plantilla = models.ForeignKey(PlantillaHito, on_delete=models.PROTECT)
    nombre = models.CharField(max_length=150)
    referencia_id_guardada = models.PositiveBigIntegerField(null=True, blank=True)
    cumple_id_guardada = models.PositiveBigIntegerField()
    plazo_dias = models.PositiveIntegerField()
    fecha_registro = models.DateTimeField(default=timezone.now)


class MovimientoLinea(RegistroInmutable):
    seguimiento = models.ForeignKey(Seguimiento, on_delete=models.PROTECT, related_name="movimientos_linea")
    linea = models.ForeignKey("compras.OrdenLinea", on_delete=models.PROTECT)
    accion = models.CharField(max_length=8, choices=[("cerrar", "Cerrar"), ("reabrir", "Reabrir")])
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    fecha = models.DateTimeField(default=timezone.now)
    motivo = models.TextField()
    saldo = models.DecimalField(max_digits=32, decimal_places=3)

    class Meta:
        ordering = ["fecha", "pk"]
        constraints = [models.CheckConstraint(condition=models.Q(accion__in=["cerrar", "reabrir"]), name="movimiento_linea_accion_valida")]


class CierreSeguimiento(RegistroInmutable):
    seguimiento = models.ForeignKey(Seguimiento, on_delete=models.PROTECT, related_name="cierres")
    accion = models.CharField(max_length=10, choices=[("cierre", "Cierre"), ("reapertura", "Reapertura")])
    resultado = models.ForeignKey(ResultadoCierre, on_delete=models.PROTECT, null=True, blank=True)
    resultado_nombre = models.CharField(max_length=150, blank=True)
    fecha = models.DateField(default=timezone.localdate)
    registrado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    fecha_registro = models.DateTimeField(default=timezone.now)
    observacion = models.TextField()
    reglas = models.JSONField(default=dict)

    class Meta:
        ordering = ["fecha_registro", "pk"]
        constraints = [models.CheckConstraint(condition=models.Q(accion__in=["cierre", "reapertura"]), name="cierre_seguimiento_accion_valida")]
