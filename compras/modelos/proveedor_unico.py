"""Modelos del área: proveedor unico."""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone
from config.utilidades import normalizar_espacios
from compras.modelos.comunes import OfertaProtegidaQuerySet
from compras.modelos.cotizaciones import Cotizacion


class CausalProveedorUnico(models.Model):
    nombre = models.CharField(max_length=120)
    descripcion = models.TextField("descripción", blank=True)
    orden = models.PositiveSmallIntegerField(default=1)
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ["orden", "nombre", "pk"]
        verbose_name = "causal de proveedor único"
        verbose_name_plural = "causales de proveedor único"
        constraints = [models.UniqueConstraint(Lower("nombre"), name="unico_causal_nombre_unico")]

    def __str__(self):
        return self.nombre

    def clean(self):
        self.nombre = normalizar_espacios(self.nombre)
        if not self.nombre:
            raise ValidationError({"nombre": "El nombre es obligatorio."})
        if any(n.casefold() == self.nombre.casefold() for n in type(self).objects.exclude(pk=self.pk).values_list("nombre", flat=True)):
            raise ValidationError({"nombre": "Ya existe una causal con este nombre."})


class PdfProveedorUnico(models.Model):
    objects = OfertaProtegidaQuerySet.as_manager()
    cotizacion = models.ForeignKey(Cotizacion, on_delete=models.PROTECT, related_name="evidencias_proveedor_unico")
    archivo = models.FileField(max_length=255)
    nombre_archivo = models.CharField(max_length=255)
    cargado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    fecha = models.DateTimeField(default=timezone.now)

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("La evidencia se conserva. Cargue otro PDF.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Las evidencias de proveedor único se conservan.")


class RevisionProveedorUnico(models.Model):
    objects = OfertaProtegidaQuerySet.as_manager()
    cotizacion = models.ForeignKey(Cotizacion, on_delete=models.PROTECT, related_name="revisiones_proveedor_unico")
    numero = models.PositiveIntegerField()
    contenido = models.JSONField()
    pdf = models.ForeignKey(PdfProveedorUnico, on_delete=models.PROTECT, null=True, blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    motivo = models.TextField()
    fecha = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-numero"]
        constraints = [models.UniqueConstraint(fields=["cotizacion", "numero"], name="unico_revision_unica")]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("El historial de proveedor único se conserva.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("El historial de proveedor único se conserva.")
