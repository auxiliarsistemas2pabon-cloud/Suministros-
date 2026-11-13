"""Parámetros editables por administración para las reglas de negocio pendientes de decisión.

Cada regla marcada como "pendiente" (por ejemplo D-01) no se fija en el código: se lee de
aquí, con un valor por defecto documentado en parametros/catalogo.py. Los parámetros no se
borran; solo se cambia su valor, con motivo y bitácora.
"""

from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models

VALORES_VERDADEROS = {"true", "1", "si", "sí"}
VALORES_FALSOS = {"false", "0", "no"}


class Parametro(models.Model):
    class Tipo(models.TextChoices):
        BOOLEANO = "booleano", "Sí / No"
        ENTERO = "entero", "Número entero"
        DECIMAL = "decimal", "Número decimal"
        TEXTO = "texto", "Texto"

    clave = models.CharField(
        "clave",
        max_length=100,
        unique=True,
        validators=[RegexValidator(r"^[a-z0-9_.]+$", "Use solo minúsculas, números, punto y guion bajo.")],
    )
    nombre = models.CharField("nombre", max_length=200)
    descripcion = models.TextField("descripción", blank=True)
    decision = models.CharField(
        "decisión pendiente",
        max_length=20,
        blank=True,
        help_text="Código de la decisión de negocio que este parámetro deja abierta, p. ej. D-01.",
    )
    tipo = models.CharField("tipo", max_length=10, choices=Tipo.choices)
    valor = models.CharField("valor", max_length=255)
    valor_por_defecto = models.CharField("valor por defecto", max_length=255)
    fecha_modificacion = models.DateTimeField("última modificación", auto_now=True)

    class Meta:
        verbose_name = "parámetro"
        verbose_name_plural = "parámetros"
        ordering = ["clave"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(tipo__in=["booleano", "entero", "decimal", "texto"]),
                name="parametro_tipo_valido",
                violation_error_message="El tipo del parámetro no es válido.",
            ),
        ]

    def __str__(self):
        return self.nombre

    @staticmethod
    def convertir(tipo, texto):
        """Convierte el texto guardado al tipo del parámetro; ValidationError si no es válido."""
        texto = (texto or "").strip()
        if tipo == Parametro.Tipo.BOOLEANO:
            if texto.lower() in VALORES_VERDADEROS:
                return True
            if texto.lower() in VALORES_FALSOS:
                return False
            raise ValidationError({"valor": "El valor debe ser Sí o No."})
        if tipo == Parametro.Tipo.ENTERO:
            try:
                return int(texto)
            except ValueError:
                raise ValidationError({"valor": "El valor debe ser un número entero."}) from None
        if tipo == Parametro.Tipo.DECIMAL:
            try:
                valor = Decimal(texto)
            except InvalidOperation:
                raise ValidationError({"valor": "El valor debe ser un número decimal."}) from None
            if not valor.is_finite():
                raise ValidationError({"valor": "El valor debe ser un número decimal."})
            return valor
        if not texto:
            raise ValidationError({"valor": "El valor no puede quedar vacío."})
        return texto

    @staticmethod
    def a_texto(tipo, valor):
        """Representación de un valor ya convertido, tal como se guarda en la base."""
        if tipo == Parametro.Tipo.BOOLEANO:
            return "true" if valor else "false"
        return str(valor)

    @property
    def valor_tipado(self):
        return self.convertir(self.tipo, self.valor)

    @property
    def valor_por_defecto_tipado(self):
        return self.convertir(self.tipo, self.valor_por_defecto)

    def clean(self):
        super().clean()
        self.valor = self.a_texto(self.tipo, self.convertir(self.tipo, self.valor))
        try:
            self.convertir(self.tipo, self.valor_por_defecto)
        except ValidationError:
            raise ValidationError({"valor_por_defecto": "El valor por defecto no corresponde al tipo."}) from None
