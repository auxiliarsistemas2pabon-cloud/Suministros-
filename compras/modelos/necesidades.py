"""Modelos del área: necesidades."""
from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone
from config.utilidades import normalizar_espacios


class TipoOrigen(models.Model):
    nombre = models.CharField(max_length=120)
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ["nombre"]
        constraints = [models.UniqueConstraint(Lower("nombre"), name="origen_necesidad_nombre_unico")]

    def __str__(self):
        return self.nombre

    def clean(self):
        self.nombre = normalizar_espacios(self.nombre)
        if not self.nombre:
            raise ValidationError({"nombre": "El nombre es obligatorio."})
        # SQLite no transforma todas las letras acentuadas con LOWER().
        otros = type(self).objects.exclude(pk=self.pk).values_list("nombre", flat=True)
        if any(nombre.casefold() == self.nombre.casefold() for nombre in otros):
            raise ValidationError({"nombre": "Ya existe un tipo de origen con este nombre."})


class Necesidad(models.Model):
    objeto = models.TextField("objeto o descripción")
    area = models.ForeignKey("areas.Area", on_delete=models.PROTECT, verbose_name="área")
    fecha = models.DateField(default=timezone.localdate)
    responsable = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    tipo_origen = models.ForeignKey(TipoOrigen, on_delete=models.PROTECT, null=True, blank=True)
    origen_texto = models.TextField("detalle del origen", blank=True)
    cantidad_base = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True, validators=[MinValueValidator(Decimal("0.001"))])
    unidad_base = models.CharField(max_length=120, blank=True)
    estado = models.CharField(max_length=12, default="abierta", editable=False)
    lineas = models.ManyToManyField("proyecciones.Linea", through="OrigenNecesidad", related_name="necesidades")

    class Meta:
        ordering = ["-fecha", "-pk"]
        constraints = [
            models.CheckConstraint(condition=models.Q(estado__in=["abierta", "cerrada", "anulada"]), name="necesidad_estado_valido"),
            models.CheckConstraint(condition=(models.Q(cantidad_base__isnull=True, unidad_base="") | (models.Q(cantidad_base__isnull=False, cantidad_base__gt=0) & ~models.Q(unidad_base=""))), name="necesidad_base_coherente"),
        ]

    def __str__(self):
        return f"Necesidad {self.pk or 'nueva'} · {self.objeto[:80]}"

    def clean(self):
        self.objeto = self.objeto.strip()
        self.unidad_base = normalizar_espacios(self.unidad_base)
        if not self.objeto:
            raise ValidationError({"objeto": "Describa el objeto de la necesidad."})
        if (self.cantidad_base is None) != (not self.unidad_base):
            raise ValidationError("Indique conjuntamente la cantidad base y su unidad.")


class OrigenNecesidad(models.Model):
    necesidad = models.ForeignKey(Necesidad, on_delete=models.PROTECT, related_name="origenes")
    linea = models.ForeignKey("proyecciones.Linea", on_delete=models.PROTECT, verbose_name="línea aprobada")
    cantidad = models.DecimalField(max_digits=14, decimal_places=3, validators=[MinValueValidator(Decimal("0.001"))])
    datos_origen = models.JSONField(default=dict)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["necesidad", "linea"], name="necesidad_linea_unica"),
            models.CheckConstraint(condition=models.Q(cantidad__gt=0), name="necesidad_cantidad_positiva"),
        ]

    def clean(self):
        if self.linea_id and self.necesidad_id:
            if self.linea.proyeccion.estado != "aprobada" or self.linea.proyeccion.area_id != self.necesidad.area_id:
                raise ValidationError("El origen debe ser una línea aprobada del área de la necesidad.")
