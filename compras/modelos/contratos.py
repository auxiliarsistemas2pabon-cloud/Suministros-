"""Modelos del área: contratos."""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone
from config.utilidades import normalizar_espacios
from compras.modelos.comunes import OfertaProtegidaQuerySet
from compras.modelos.cotizaciones import Cotizacion
from compras.modelos.decisiones import DecisionCotizacion


def _contrato_editable(decision_id):
    """El llamador mantiene una transacción; se comparte el bloqueo de decisión B13."""
    cotizacion_id = DecisionCotizacion.objects.values_list("cotizacion_id", flat=True).get(pk=decision_id)
    cotizacion = Cotizacion.objects.select_for_update().get(pk=cotizacion_id)
    decision = DecisionCotizacion.objects.get(pk=decision_id)
    if decision.estado != "pendiente" or cotizacion.estado != "en_comparacion" or decision.aprobaciones.exists():
        raise ValidationError("El contrato y sus pólizas solo se modifican antes de la primera aprobación. Anule la decisión para registrar cambios.")
    if not decision.contenido["comparativo"].get("requiere_contrato", False):
        raise ValidationError("La propuesta no requiere contrato.")
    return decision


class TipoPoliza(models.Model):
    nombre = models.CharField(max_length=120)
    orden = models.PositiveSmallIntegerField(default=1)
    activo = models.BooleanField(default=True)
    dias_alerta = models.PositiveSmallIntegerField("días de alerta particulares", null=True, blank=True)

    class Meta:
        ordering = ["orden", "nombre", "pk"]
        constraints = [models.UniqueConstraint(Lower("nombre"), name="poliza_tipo_nombre_unico")]

    def __str__(self):
        return self.nombre

    @property
    def usar_alerta_general(self):
        return self.dias_alerta is None

    def clean(self):
        self.nombre = normalizar_espacios(self.nombre)
        if not self.nombre:
            raise ValidationError({"nombre": "El nombre es obligatorio."})
        if any(n.casefold() == self.nombre.casefold() for n in type(self).objects.exclude(pk=self.pk).values_list("nombre", flat=True)):
            raise ValidationError({"nombre": "Ya existe un tipo con este nombre."})


class Contrato(models.Model):
    objects = OfertaProtegidaQuerySet.as_manager()
    decision = models.OneToOneField(DecisionCotizacion, on_delete=models.PROTECT, related_name="contrato")
    numero = models.CharField("número", max_length=120, blank=True)
    supervisor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True)
    supervisor_texto = models.CharField("supervisor por texto", max_length=255, blank=True)
    supervisor_nombre = models.CharField(max_length=450, blank=True, editable=False)
    cargo = models.CharField(max_length=150, blank=True)
    fecha_inicio = models.DateField(null=True, blank=True)
    fecha_fin = models.DateField(null=True, blank=True)
    forma_pago = models.TextField("forma de pago", blank=True)
    valor = models.DecimalField(max_digits=32, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)])
    pdf = models.ForeignKey("PdfContractual", on_delete=models.PROTECT, null=True, blank=True, related_name="contratos_actuales", editable=False)
    revision = models.PositiveIntegerField(default=0, editable=False)

    def clean(self):
        if self.supervisor_id and self.supervisor_texto.strip():
            raise ValidationError("Indique supervisor por usuario o por texto, sin mezclar ambas opciones.")
        if self.fecha_inicio and self.fecha_fin and self.fecha_fin < self.fecha_inicio:
            raise ValidationError({"fecha_fin": "El fin no puede ser anterior al inicio."})
        if self.pdf_id and (self.pdf.contrato_id != self.pk or self.pdf.poliza_id is not None):
            raise ValidationError("La evidencia no pertenece al contrato.")

    def save(self, *args, **kwargs):
        from django.db import transaction
        with transaction.atomic():
            _contrato_editable(self.decision_id)
            if self.pk and type(self).objects.get(pk=self.pk).decision_id != self.decision_id:
                raise ValidationError("No traslade contratos entre decisiones.")
            self.clean()
            super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Los contratos y sus evidencias se conservan.")


class Poliza(models.Model):
    objects = OfertaProtegidaQuerySet.as_manager()
    contrato = models.ForeignKey(Contrato, on_delete=models.PROTECT, related_name="polizas")
    tipo = models.ForeignKey(TipoPoliza, on_delete=models.PROTECT, null=True, blank=True)
    tipo_nombre = models.CharField(max_length=120, blank=True, editable=False)
    aseguradora = models.CharField(max_length=200, blank=True)
    numero = models.CharField("número", max_length=120, blank=True)
    valor_asegurado = models.DecimalField(max_digits=32, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)])
    vigencia_desde = models.DateField(null=True, blank=True)
    vigencia_hasta = models.DateField(null=True, blank=True)
    pdf = models.ForeignKey("PdfContractual", on_delete=models.PROTECT, null=True, blank=True, related_name="polizas_actuales", editable=False)
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ["pk"]

    def clean(self):
        if self.vigencia_desde and self.vigencia_hasta and self.vigencia_hasta < self.vigencia_desde:
            raise ValidationError({"vigencia_hasta": "El vencimiento no puede ser anterior al inicio."})
        if self.pdf_id and (self.pdf.poliza_id != self.pk or self.pdf.contrato_id != self.contrato_id):
            raise ValidationError("La evidencia no pertenece a esta póliza y contrato.")

    def save(self, *args, **kwargs):
        from django.db import transaction
        with transaction.atomic():
            _contrato_editable(self.contrato.decision_id)
            if self.pk and type(self).objects.get(pk=self.pk).contrato_id != self.contrato_id:
                raise ValidationError("No traslade pólizas entre contratos.")
            self.clean()
            super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Desactive la póliza con motivo; su historial se conserva.")


class PdfContractual(models.Model):
    objects = OfertaProtegidaQuerySet.as_manager()
    contrato = models.ForeignKey(Contrato, on_delete=models.PROTECT, related_name="adjuntos")
    poliza = models.ForeignKey(Poliza, on_delete=models.PROTECT, null=True, blank=True, related_name="adjuntos")
    archivo = models.FileField(max_length=255)
    nombre_archivo = models.CharField(max_length=255)
    cargado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    fecha = models.DateTimeField(default=timezone.now)

    def clean(self):
        if self.poliza_id and self.poliza.contrato_id != self.contrato_id:
            raise ValidationError("La póliza no pertenece al contrato indicado.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Las evidencias contractuales se conservan.")
        self.clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Las evidencias contractuales se conservan.")


class RevisionContrato(models.Model):
    objects = OfertaProtegidaQuerySet.as_manager()
    contrato = models.ForeignKey(Contrato, on_delete=models.PROTECT, related_name="revisiones")
    numero = models.PositiveIntegerField()
    contenido = models.JSONField()
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    motivo = models.TextField()
    fecha = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-numero"]
        constraints = [models.UniqueConstraint(fields=["contrato", "numero"], name="contrato_revision_unica")]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Las revisiones del contrato se conservan.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Las revisiones del contrato se conservan.")
