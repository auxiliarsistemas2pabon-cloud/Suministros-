"""Fuentes reales conservadas y referencias históricas, separadas de autorizaciones nuevas."""
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class FormatoInstitucional(models.Model):
    codigo = models.CharField(max_length=12, db_index=True)
    titulo = models.CharField(max_length=180)
    nombre_original = models.CharField(max_length=255)
    sha256 = models.CharField(max_length=64, unique=True)
    archivo = models.FileField(upload_to="formatos_institucionales/", max_length=255)
    contenido = models.JSONField(default=list)
    cargado_el = models.DateTimeField(default=timezone.now, editable=False)
    resumen = models.JSONField(default=dict)

    class Meta:
        ordering = ["codigo", "-cargado_el"]

    def __str__(self):
        return f"{self.codigo} · {self.nombre_original}"


class CompraHistorica(models.Model):
    fuente = models.ForeignKey(FormatoInstitucional, on_delete=models.PROTECT)
    hoja = models.CharField(max_length=80)
    fila = models.PositiveIntegerField()
    orden_original = models.TextField()
    fecha_comite = models.CharField(max_length=250, blank=True)
    proveedor_original = models.TextField(blank=True)
    objeto = models.TextField(blank=True)
    valor_original = models.TextField(blank=True)
    seguimientos = models.JSONField(default=list)

    class Meta:
        ordering = ["fuente_id", "hoja", "fila"]
        constraints = [models.UniqueConstraint(fields=["fuente", "hoja", "fila"], name="fuente_compra_fila_unica")]


class ElegibleHistorico(models.Model):
    fuente = models.ForeignKey(FormatoInstitucional, on_delete=models.PROTECT)
    hoja = models.CharField(max_length=80)
    fila = models.PositiveIntegerField()
    proveedor = models.TextField()
    area_original = models.TextField(blank=True)
    objeto = models.TextField(blank=True)
    puntaje_original = models.CharField(max_length=200, blank=True)
    puesto_original = models.CharField(max_length=200, blank=True)
    observaciones = models.TextField(blank=True)

    class Meta:
        ordering = ["hoja", "fila"]
        constraints = [models.UniqueConstraint(fields=["fuente", "hoja", "fila"], name="fuente_elegible_fila_unica")]


class SerieArea(models.Model):
    area = models.OneToOneField("areas.Area", on_delete=models.PROTECT, related_name="serie_institucional")
    fuente = models.ForeignKey(FormatoInstitucional, on_delete=models.PROTECT)
    codigo = models.CharField(max_length=20, unique=True)
    sin_prefijo = models.BooleanField(default=False)
    ultimo_historico = models.PositiveBigIntegerField()
    longitud = models.PositiveSmallIntegerField(default=2, validators=[MinValueValidator(1), MaxValueValidator(20)])
    celda_origen = models.CharField(max_length=200)
    referencia_original = models.TextField()
    observaciones = models.TextField(blank=True)
    habilitada = models.BooleanField(default=True)

    class Meta:
        ordering = ["codigo"]

    @property
    def clave_contador(self):
        return f"area:{self.area_id}"

    def formatear(self, numero):
        return str(numero) if self.sin_prefijo else f"{self.codigo}-{str(numero).zfill(self.longitud)}"

    def save(self, *args, **kwargs):
        if self.pk:
            previo = type(self).objects.get(pk=self.pk)
            if self.ultimo_historico < previo.ultimo_historico:
                raise ValidationError("El corte histórico no puede retroceder.")
            if (self.codigo, self.area_id, self.sin_prefijo) != (previo.codigo, previo.area_id, previo.sin_prefijo):
                raise ValidationError("La identidad de una serie cargada se conserva.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Las series y sus referencias se conservan.")
