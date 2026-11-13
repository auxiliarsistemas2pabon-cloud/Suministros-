"""Modelos del área: decisiones."""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from compras.modelos.comunes import OfertaProtegidaQuerySet
from compras.modelos.cotizaciones import Cotizacion, LineaCotizacion
from compras.modelos.ofertas import Oferta, OfertaLinea


class DecisionCotizacion(models.Model):
    objects = OfertaProtegidaQuerySet.as_manager()
    cotizacion = models.ForeignKey(Cotizacion, on_delete=models.PROTECT, related_name="decisiones")
    modalidad = models.CharField(max_length=12, choices=[("completa", "Oferta completa"), ("lineas", "Por línea")])
    recomendacion = models.TextField()
    motivo_eleccion = models.TextField(blank=True)
    justificacion_verificaciones = models.TextField(blank=True)
    reglas = models.JSONField()
    contenido = models.JSONField()
    huella = models.CharField(max_length=64)
    propuesta_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="decisiones_cotizacion_propuestas")
    fecha_propuesta = models.DateTimeField(default=timezone.now)
    estado = models.CharField(max_length=12, default="pendiente", choices=[("pendiente", "Pendiente"), ("aprobada", "Aprobada"), ("anulada", "Anulada")])
    decidido_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="decisiones_cotizacion_finalizadas")
    fecha_decision = models.DateTimeField(null=True, blank=True)
    anulada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="decisiones_cotizacion_anuladas")
    fecha_anulacion = models.DateTimeField(null=True, blank=True)
    motivo_anulacion = models.TextField(blank=True)

    class Meta:
        ordering = ["-pk"]
        constraints = [
            models.UniqueConstraint(fields=["cotizacion"], condition=models.Q(estado__in=["pendiente", "aprobada"]), name="cot_decision_activa_unica"),
            models.CheckConstraint(condition=models.Q(estado__in=["pendiente", "aprobada", "anulada"]), name="cot_decision_estado_valido"),
            models.CheckConstraint(condition=models.Q(modalidad__in=["completa", "lineas"]), name="cot_decision_modalidad_valida"),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            anterior = type(self).objects.get(pk=self.pk)
            mutables = {"estado", "decidido_por", "fecha_decision", "anulada_por", "fecha_anulacion", "motivo_anulacion"}
            for campo in self._meta.concrete_fields:
                if campo.name not in mutables and getattr(anterior, campo.attname) != getattr(self, campo.attname):
                    raise ValidationError("La propuesta y su comparativo se conservan. Anule y registre otra decisión.")
            if anterior.estado == "anulada" or (anterior.estado == "aprobada" and self.estado != "anulada"):
                raise ValidationError("La decisión histórica se conserva.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Las decisiones se conservan.")


class AdjudicacionCotizacion(models.Model):
    objects = OfertaProtegidaQuerySet.as_manager()
    decision = models.ForeignKey(DecisionCotizacion, on_delete=models.PROTECT, related_name="adjudicaciones")
    linea = models.ForeignKey(LineaCotizacion, on_delete=models.PROTECT)
    oferta = models.ForeignKey(Oferta, on_delete=models.PROTECT)
    oferta_linea = models.ForeignKey(OfertaLinea, on_delete=models.PROTECT)

    class Meta:
        ordering = ["linea__orden", "pk"]
        constraints = [models.UniqueConstraint(fields=["decision", "linea"], name="cot_adjudicacion_linea_unica")]

    def clean(self):
        if self.oferta.cotizacion_id != self.decision.cotizacion_id or self.linea.cotizacion_id != self.decision.cotizacion_id:
            raise ValidationError("Seleccione líneas y ofertas de la misma cotización.")
        if self.oferta_linea.oferta_id != self.oferta_id or self.oferta_linea.linea_id != self.linea_id:
            raise ValidationError("El precio seleccionado no pertenece a la línea y oferta.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Las adjudicaciones históricas se conservan.")
        self.clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Las adjudicaciones se conservan.")


class AprobacionCotizacion(models.Model):
    objects = OfertaProtegidaQuerySet.as_manager()
    decision = models.ForeignKey(DecisionCotizacion, on_delete=models.PROTECT, related_name="aprobaciones")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    fecha = models.DateTimeField(default=timezone.now)
    motivo = models.TextField()
    contrato_datos = models.JSONField(default=dict, blank=True, editable=False)

    class Meta:
        ordering = ["fecha", "pk"]
        constraints = [models.UniqueConstraint(fields=["decision", "actor"], name="cot_aprobador_distinto")]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Las aprobaciones se conservan.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Las aprobaciones se conservan.")
