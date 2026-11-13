from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower, Upper

from config.utilidades import normalizar_espacios, validar_unico_sin_mayusculas


class Area(models.Model):
    """Área o servicio de la clínica. Se desactiva; no se borra."""

    nombre = models.CharField("nombre", max_length=150)
    codigo_area = models.CharField(
        "código del área",
        max_length=20,
        unique=True,
        error_messages={"unique": "Ya existe un área con este código."},
    )
    activa = models.BooleanField("activa", default=True)
    fecha_creacion = models.DateTimeField("fecha de creación", auto_now_add=True)

    class Meta:
        verbose_name = "área"
        verbose_name_plural = "áreas"
        ordering = ["nombre"]
        constraints = [
            models.UniqueConstraint(
                Lower("nombre"),
                name="area_nombre_unico_sin_mayusculas",
                violation_error_message="Ya existe un área con este nombre.",
            ),
            # Con el código siempre en mayúsculas, unique=True ya impide
            # duplicados sin distinguir mayúsculas.
            models.CheckConstraint(
                condition=Q(codigo_area=Upper("codigo_area")),
                name="area_codigo_en_mayusculas",
                violation_error_message="El código del área debe ir en mayúsculas.",
            ),
        ]

    def __str__(self):
        return f"{self.nombre} ({self.codigo_area})"

    def _normalizar(self):
        self.nombre = normalizar_espacios(self.nombre)
        self.codigo_area = normalizar_espacios(self.codigo_area).upper()

    def clean(self):
        super().clean()
        self._normalizar()
        validar_unico_sin_mayusculas(self, "nombre", "Ya existe un área con este nombre.")

    def save(self, *args, **kwargs):
        self._normalizar()
        super().save(*args, **kwargs)
