"""Bitácora de auditoría: solo inserción.

Cada registro guarda quién hizo el cambio, cuándo, qué acción, sobre qué
objeto, los valores anterior y nuevo y el motivo. Los registros nunca se
modifican ni se borran: lo impide este modelo y, además, un disparador de
PostgreSQL (migración 0002).
"""

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models


class BitacoraInmutableError(Exception):
    """Se intentó modificar o borrar un registro de la bitácora."""


MENSAJE_INMUTABLE = "La bitácora es de solo inserción: sus registros no se modifican ni se borran."


class RegistroBitacoraQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise BitacoraInmutableError(MENSAJE_INMUTABLE)

    def delete(self):
        raise BitacoraInmutableError(MENSAJE_INMUTABLE)


class RegistroBitacora(models.Model):
    fecha = models.DateTimeField("fecha y hora", auto_now_add=True, db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="actor",
        on_delete=models.PROTECT,
        related_name="registros_bitacora",
        null=True,
        blank=True,
        help_text="Vacío si la acción la hizo el sistema.",
    )
    # Copia del correo del actor en el momento de la acción (por si cambia después).
    actor_texto = models.CharField("actor (texto)", max_length=254, blank=True)
    accion = models.CharField("acción", max_length=100, db_index=True)
    tipo_objeto = models.ForeignKey(
        ContentType,
        verbose_name="tipo de objeto",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    objeto_id = models.CharField("id del objeto", max_length=64, blank=True)
    objeto_texto = models.CharField("objeto", max_length=255, blank=True)
    valor_anterior = models.JSONField("valor anterior", null=True, blank=True, encoder=DjangoJSONEncoder)
    valor_nuevo = models.JSONField("valor nuevo", null=True, blank=True, encoder=DjangoJSONEncoder)
    motivo = models.TextField("motivo", blank=True)
    ip = models.GenericIPAddressField("dirección IP", null=True, blank=True)

    objects = RegistroBitacoraQuerySet.as_manager()

    class Meta:
        verbose_name = "registro de bitácora"
        verbose_name_plural = "bitácora"
        ordering = ["-fecha", "-id"]
        indexes = [models.Index(fields=["tipo_objeto", "objeto_id"], name="bitacora_objeto_idx")]

    def __str__(self):
        return f"{self.fecha:%Y-%m-%d %H:%M} · {self.actor_texto or 'sistema'} · {self.accion}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise BitacoraInmutableError(MENSAJE_INMUTABLE)
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise BitacoraInmutableError(MENSAJE_INMUTABLE)
