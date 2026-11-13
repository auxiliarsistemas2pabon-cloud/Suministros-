"""Modelos del área: verificaciones."""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone
from config.utilidades import normalizar_espacios
from compras.modelos.comunes import OfertaProtegidaQuerySet
from compras.modelos.cotizaciones import Cotizacion
from compras.modelos.ofertas import Oferta


class TipoVerificacion(models.Model):
    nombre = models.CharField(max_length=120)
    orden = models.PositiveSmallIntegerField(default=1)
    obligatoria = models.BooleanField(default=False)
    origen = models.CharField(max_length=12, choices=[("manual", "Revisión manual"), ("documental", "Propuesta de vigencia documental")], default="manual")
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ["orden", "nombre", "pk"]
        verbose_name = "tipo de verificación"
        verbose_name_plural = "tipos de verificación"
        constraints = [
            models.UniqueConstraint(Lower("nombre"), name="verificacion_tipo_nombre_unico"),
            models.CheckConstraint(condition=models.Q(origen__in=["manual", "documental"]), name="verificacion_origen_valido"),
        ]

    def __str__(self):
        return self.nombre

    def clean(self):
        self.nombre = normalizar_espacios(self.nombre)
        if not self.nombre:
            raise ValidationError({"nombre": "El nombre es obligatorio."})
        if any(n.casefold() == self.nombre.casefold() for n in type(self).objects.exclude(pk=self.pk).values_list("nombre", flat=True)):
            raise ValidationError({"nombre": "Ya existe un tipo con este nombre."})


class EstadoVerificacion(models.Model):
    CLASES = [("si", "Sí / cumple"), ("no", "No / no cumple"), ("pendiente", "Pendiente de verificar"), ("na", "No aplica")]
    nombre = models.CharField(max_length=80)
    clasificacion = models.CharField(max_length=12, choices=CLASES)
    orden = models.PositiveSmallIntegerField(default=1)
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ["orden", "nombre", "pk"]
        verbose_name = "estado de verificación"
        verbose_name_plural = "estados de verificación"
        constraints = [
            models.UniqueConstraint(Lower("nombre"), name="verificacion_estado_nombre_unico"),
            models.CheckConstraint(condition=models.Q(clasificacion__in=["si", "no", "pendiente", "na"]), name="verificacion_estado_clase_valida"),
        ]

    def __str__(self):
        return self.nombre

    def clean(self):
        self.nombre = normalizar_espacios(self.nombre)
        if not self.nombre:
            raise ValidationError({"nombre": "El nombre es obligatorio."})
        if any(n.casefold() == self.nombre.casefold() for n in type(self).objects.exclude(pk=self.pk).values_list("nombre", flat=True)):
            raise ValidationError({"nombre": "Ya existe un estado con este nombre."})


class VerificacionOferta(models.Model):
    objects = OfertaProtegidaQuerySet.as_manager()
    oferta = models.ForeignKey(Oferta, on_delete=models.PROTECT, related_name="verificaciones")
    tipo = models.ForeignKey(TipoVerificacion, on_delete=models.PROTECT, related_name="registros")
    estado = models.ForeignKey(EstadoVerificacion, on_delete=models.PROTECT)
    fecha = models.DateField(default=timezone.localdate)
    verificado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    observacion = models.TextField(blank=True)
    tipo_nombre = models.CharField(max_length=120, editable=False)
    tipo_obligatoria = models.BooleanField(default=False, editable=False)
    tipo_origen = models.CharField(max_length=12, editable=False)
    estado_nombre = models.CharField(max_length=80, editable=False)
    estado_clasificacion = models.CharField(max_length=12, editable=False)
    oferta_revision = models.PositiveIntegerField(editable=False)
    revision = models.PositiveIntegerField(default=0, editable=False)
    propuesta = models.JSONField(default=dict, blank=True, editable=False)
    pdf = models.ForeignKey("PdfVerificacionOferta", on_delete=models.PROTECT, null=True, blank=True, related_name="verificaciones_actuales", editable=False)
    fecha_registro = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["oferta", "tipo"], name="verificacion_oferta_tipo_unico"),
            models.CheckConstraint(condition=models.Q(estado_clasificacion__in=["si", "no", "pendiente", "na"]), name="verificacion_foto_clase_valida"),
        ]

    def clean(self):
        if self.pdf_id and self.pdf.verificacion_id != self.pk:
            raise ValidationError("La evidencia pertenece a otra verificación.")

    def save(self, *args, **kwargs):
        from django.db import transaction
        with transaction.atomic():
            oferta = Oferta.objects.get(pk=self.oferta_id)
            if Cotizacion.objects.select_for_update().get(pk=oferta.cotizacion_id).estado not in ("borrador", "en_comparacion"):
                raise ValidationError("La cotización ya no admite cambios de verificaciones.")
            if self.pk:
                original = type(self).objects.get(pk=self.pk)
                if (original.oferta_id, original.tipo_id) != (self.oferta_id, self.tipo_id):
                    raise ValidationError("No traslade una verificación a otro oferente o tipo.")
            self.clean()
            super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Las verificaciones y sus evidencias se conservan.")


class PdfVerificacionOferta(models.Model):
    objects = OfertaProtegidaQuerySet.as_manager()
    verificacion = models.ForeignKey(VerificacionOferta, on_delete=models.PROTECT, related_name="adjuntos")
    archivo = models.FileField(max_length=255)
    nombre_archivo = models.CharField(max_length=255)
    cargado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    fecha = models.DateTimeField(default=timezone.now)

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("La evidencia se conserva. Cargue otro PDF.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Las evidencias de verificaciones se conservan.")


class RevisionVerificacionOferta(models.Model):
    objects = OfertaProtegidaQuerySet.as_manager()
    verificacion = models.ForeignKey(VerificacionOferta, on_delete=models.PROTECT, related_name="revisiones")
    numero = models.PositiveIntegerField()
    contenido = models.JSONField()
    pdf = models.ForeignKey(PdfVerificacionOferta, on_delete=models.PROTECT, null=True, blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    fecha = models.DateTimeField(default=timezone.now)
    motivo = models.TextField()

    class Meta:
        ordering = ["-numero"]
        constraints = [models.UniqueConstraint(fields=["verificacion", "numero"], name="verificacion_revision_unica")]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("El historial de verificaciones se conserva.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("El historial de verificaciones se conserva.")
