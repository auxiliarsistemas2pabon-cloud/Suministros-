"""Modelos del área: comunes."""
from django.core.exceptions import ValidationError
from django.db import models


class OfertaProtegidaQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Use el servicio de ofertas para conservar identidad, cálculos e historial.")

    def delete(self):
        raise ValidationError("Las ofertas y su historial se conservan.")

    def bulk_create(self, *args, **kwargs):
        raise ValidationError("Use el servicio de ofertas.")

    def bulk_update(self, *args, **kwargs):
        raise ValidationError("Use el servicio de ofertas.")
