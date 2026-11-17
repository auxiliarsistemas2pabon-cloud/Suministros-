"""Modelos de la proyección anual (FR-GDS-11) y sus catálogos."""

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import FieldDoesNotExist, ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models.functions import Lower

from config.utilidades import normalizar_espacios, validar_unico_sin_mayusculas


class UnidadMedida(models.Model):
    """Unidad de medida (caja, unidad, frasco...). Se desactiva; no se borra."""

    nombre = models.CharField("nombre", max_length=80)
    abreviatura = models.CharField("abreviatura", max_length=15)
    activa = models.BooleanField("activa", default=True)
    fecha_creacion = models.DateTimeField("fecha de creación", auto_now_add=True)

    class Meta:
        verbose_name = "unidad de medida"
        verbose_name_plural = "unidades de medida"
        ordering = ["nombre"]
        constraints = [
            models.UniqueConstraint(
                Lower("nombre"),
                name="unidad_nombre_unico_sin_mayusculas",
                violation_error_message="Ya existe una unidad de medida con este nombre.",
            ),
            models.UniqueConstraint(
                Lower("abreviatura"),
                name="unidad_abreviatura_unica_sin_mayusculas",
                violation_error_message="Ya existe una unidad de medida con esta abreviatura.",
            ),
        ]

    def __str__(self):
        return f"{self.nombre} ({self.abreviatura})"

    def _normalizar(self):
        self.nombre = normalizar_espacios(self.nombre)
        self.abreviatura = normalizar_espacios(self.abreviatura)

    def clean(self):
        super().clean()
        self._normalizar()
        errores = {}
        for campo, mensaje in (
            ("nombre", "Ya existe una unidad de medida con este nombre."),
            ("abreviatura", "Ya existe una unidad de medida con esta abreviatura."),
        ):
            try:
                validar_unico_sin_mayusculas(self, campo, mensaje)
            except ValidationError as error:
                errores.update(error.message_dict)
        if errores:
            raise ValidationError(errores)

    def save(self, *args, **kwargs):
        self._normalizar()
        super().save(*args, **kwargs)


class ProductoSugerido(models.Model):
    """Producto que se sugiere al registrar la proyección anual."""

    nombre = models.CharField("nombre", max_length=200)
    unidad_por_defecto = models.ForeignKey(
        UnidadMedida,
        verbose_name="unidad por defecto",
        on_delete=models.PROTECT,
        related_name="productos_sugeridos",
    )
    activo = models.BooleanField("activo", default=True)
    fecha_creacion = models.DateTimeField("fecha de creación", auto_now_add=True)

    class Meta:
        verbose_name = "producto sugerido"
        verbose_name_plural = "productos sugeridos"
        ordering = ["nombre"]
        constraints = [
            models.UniqueConstraint(
                Lower("nombre"),
                name="producto_nombre_unico_sin_mayusculas",
                violation_error_message="Ya existe un producto sugerido con este nombre.",
            ),
        ]

    def __str__(self):
        return self.nombre

    def clean(self):
        super().clean()
        self.nombre = normalizar_espacios(self.nombre)
        validar_unico_sin_mayusculas(self, "nombre", "Ya existe un producto sugerido con este nombre.")

    def save(self, *args, **kwargs):
        self.nombre = normalizar_espacios(self.nombre)
        super().save(*args, **kwargs)


class Periodo(models.Model):
    """Año en el que se diligencian las proyecciones de las áreas."""

    class Estado(models.TextChoices):
        ABIERTO = "abierto", "Abierto"
        CERRADO = "cerrado", "Cerrado"

    anio = models.PositiveSmallIntegerField(
        "año",
        unique=True,
        error_messages={"unique": "Ya existe un periodo con este año."},
    )
    fecha_apertura = models.DateField("fecha de apertura")
    fecha_limite_diligenciamiento = models.DateField("fecha límite de diligenciamiento")
    estado = models.CharField("estado", max_length=10, choices=Estado.choices, default=Estado.ABIERTO)
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="creado por",
        on_delete=models.PROTECT,
        related_name="periodos_creados",
    )
    fecha_creacion = models.DateTimeField("fecha de creación", auto_now_add=True)

    class Meta:
        verbose_name = "periodo"
        verbose_name_plural = "periodos"
        ordering = ["-anio"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(anio__gte=1),
                name="periodo_anio_positivo",
                violation_error_message="El año debe ser positivo.",
            ),
            models.CheckConstraint(
                condition=models.Q(estado__in=["abierto", "cerrado"]),
                name="periodo_estado_valido",
                violation_error_message="El estado del periodo no es válido.",
            ),
        ]

    def __str__(self):
        return str(self.anio)

    def clean(self):
        super().clean()
        if (
            self.fecha_apertura
            and self.fecha_limite_diligenciamiento
            and self.fecha_limite_diligenciamiento < self.fecha_apertura
        ):
            raise ValidationError(
                {
                    "fecha_limite_diligenciamiento": (
                        "La fecha límite debe ser igual o posterior a la fecha de apertura."
                    )
                }
            )


class ProyeccionArea(models.Model):
    """Proyección anual diligenciada por un área."""

    class Estado(models.TextChoices):
        BORRADOR = "borrador", "Borrador"
        ENVIADA = "enviada", "Enviada"
        APROBADA = "aprobada", "Aprobada"

    periodo = models.ForeignKey(
        Periodo,
        verbose_name="periodo",
        on_delete=models.PROTECT,
        related_name="proyecciones_area",
    )
    area = models.ForeignKey(
        "areas.Area",
        verbose_name="área",
        on_delete=models.PROTECT,
        related_name="proyecciones",
    )
    estado = models.CharField("estado", max_length=10, choices=Estado.choices, default=Estado.BORRADOR)
    fecha_envio = models.DateTimeField("fecha de envío", null=True, blank=True)
    enviado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="enviado por",
        on_delete=models.PROTECT,
        related_name="proyecciones_enviadas",
        null=True,
        blank=True,
    )
    fecha_aprobacion = models.DateTimeField("fecha de aprobación", null=True, blank=True)
    aprobado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="aprobado por",
        on_delete=models.PROTECT,
        related_name="proyecciones_aprobadas",
        null=True,
        blank=True,
    )
    fecha_creacion = models.DateTimeField("fecha de creación", auto_now_add=True)

    class Meta:
        verbose_name = "proyección por área"
        verbose_name_plural = "proyecciones por área"
        ordering = ["-periodo__anio", "area__nombre"]
        constraints = [
            models.UniqueConstraint(
                fields=["periodo", "area"],
                name="proyeccion_area_periodo_area_unicos",
                violation_error_message="Ya existe una proyección para esta área y este periodo.",
            ),
            models.CheckConstraint(
                condition=models.Q(estado__in=["borrador", "enviada", "aprobada"]),
                name="proyeccion_area_estado_valido",
                violation_error_message="El estado de la proyección no es válido.",
            ),
        ]

    def __str__(self):
        return f"{self.area} · {self.periodo}"

    def clean(self):
        super().clean()
        errores = {}
        tiene_envio = self.fecha_envio is not None or self.enviado_por_id is not None
        tiene_aprobacion = self.fecha_aprobacion is not None or self.aprobado_por_id is not None
        envio_completo = self.fecha_envio is not None and self.enviado_por_id is not None
        aprobacion_completa = self.fecha_aprobacion is not None and self.aprobado_por_id is not None

        if self.estado in (self.Estado.ENVIADA, self.Estado.APROBADA) and not envio_completo:
            errores["fecha_envio"] = "Una proyección enviada debe tener fecha y usuario de envío."
        if self.estado == self.Estado.APROBADA and not aprobacion_completa:
            errores["fecha_aprobacion"] = "Una proyección aprobada debe tener fecha y usuario de aprobación."
        if self.estado == self.Estado.BORRADOR and tiene_envio:
            errores["estado"] = "Una proyección en borrador no puede tener datos de envío."
        if self.estado != self.Estado.APROBADA and tiene_aprobacion:
            errores["estado"] = "Solo una proyección aprobada puede tener datos de aprobación."
        if self.estado == self.Estado.ENVIADA and tiene_aprobacion:
            errores["estado"] = "Una proyección enviada aún no puede tener datos de aprobación."
        if errores:
            raise ValidationError(errores)


CAMPOS_CANTIDADES_MENSUALES = (
    "cantidad_enero",
    "cantidad_febrero",
    "cantidad_marzo",
    "cantidad_abril",
    "cantidad_mayo",
    "cantidad_junio",
    "cantidad_julio",
    "cantidad_agosto",
    "cantidad_septiembre",
    "cantidad_octubre",
    "cantidad_noviembre",
    "cantidad_diciembre",
)


class Linea(models.Model):
    """Producto o servicio solicitado dentro de una proyección por área."""

    proyeccion = models.ForeignKey(
        ProyeccionArea,
        verbose_name="proyección",
        on_delete=models.PROTECT,
        related_name="lineas",
    )
    producto_servicio = models.CharField("producto o servicio", max_length=255)
    # El significado de dependencia queda pendiente de confirmación con la clínica.
    dependencia = models.CharField("dependencia", max_length=255, blank=True)
    unidad = models.ForeignKey(
        UnidadMedida,
        verbose_name="unidad de medida",
        on_delete=models.PROTECT,
        related_name="lineas_proyectadas",
    )
    cantidad_enero = models.PositiveIntegerField("cantidad de enero", default=0)
    cantidad_febrero = models.PositiveIntegerField("cantidad de febrero", default=0)
    cantidad_marzo = models.PositiveIntegerField("cantidad de marzo", default=0)
    cantidad_abril = models.PositiveIntegerField("cantidad de abril", default=0)
    cantidad_mayo = models.PositiveIntegerField("cantidad de mayo", default=0)
    cantidad_junio = models.PositiveIntegerField("cantidad de junio", default=0)
    cantidad_julio = models.PositiveIntegerField("cantidad de julio", default=0)
    cantidad_agosto = models.PositiveIntegerField("cantidad de agosto", default=0)
    cantidad_septiembre = models.PositiveIntegerField("cantidad de septiembre", default=0)
    cantidad_octubre = models.PositiveIntegerField("cantidad de octubre", default=0)
    cantidad_noviembre = models.PositiveIntegerField("cantidad de noviembre", default=0)
    cantidad_diciembre = models.PositiveIntegerField("cantidad de diciembre", default=0)
    precio_estimado = models.DecimalField(
        "precio estimado",
        max_digits=14,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
    )
    costo_proyectado_total = models.DecimalField(
        "costo proyectado total informado",
        max_digits=30,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0"))],
        help_text="Total anual informado. Si se indica, prevalece sobre cantidades por precio unitario; cero es un valor válido.",
    )
    cantidad_autorizada = models.PositiveIntegerField(
        "cantidad autorizada",
        null=True,
        blank=True,
    )
    fecha_creacion = models.DateTimeField("fecha de creación", auto_now_add=True)

    class Meta:
        verbose_name = "línea de proyección"
        verbose_name_plural = "líneas de proyección"
        ordering = ["producto_servicio", "id"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(cantidad_enero__gte=0)
                    & models.Q(cantidad_febrero__gte=0)
                    & models.Q(cantidad_marzo__gte=0)
                    & models.Q(cantidad_abril__gte=0)
                    & models.Q(cantidad_mayo__gte=0)
                    & models.Q(cantidad_junio__gte=0)
                    & models.Q(cantidad_julio__gte=0)
                    & models.Q(cantidad_agosto__gte=0)
                    & models.Q(cantidad_septiembre__gte=0)
                    & models.Q(cantidad_octubre__gte=0)
                    & models.Q(cantidad_noviembre__gte=0)
                    & models.Q(cantidad_diciembre__gte=0)
                ),
                name="linea_cantidades_no_negativas",
                violation_error_message="Las cantidades mensuales no pueden ser negativas.",
            ),
            models.CheckConstraint(
                condition=models.Q(precio_estimado__gte=0),
                name="linea_precio_no_negativo",
                violation_error_message="El precio estimado no puede ser negativo.",
            ),
            models.CheckConstraint(
                condition=models.Q(costo_proyectado_total__isnull=True) | models.Q(costo_proyectado_total__gte=0),
                name="linea_costo_total_no_negativo",
                violation_error_message="El costo proyectado total no puede ser negativo.",
            ),
            models.CheckConstraint(
                condition=models.Q(cantidad_autorizada__gte=0) | models.Q(cantidad_autorizada__isnull=True),
                name="linea_autorizada_no_negativa",
                violation_error_message="La cantidad autorizada no puede ser negativa.",
            ),
        ]

    def __str__(self):
        return f"{self.producto_servicio} · {self.proyeccion}"

    @property
    def total_anual(self):
        """Suma entera de las cantidades proyectadas de enero a diciembre."""
        return sum(getattr(self, campo) or 0 for campo in CAMPOS_CANTIDADES_MENSUALES)

    @property
    def costo_anual(self):
        """Total informado o cálculo por cantidades, conservando los montos Decimal."""
        if self.costo_proyectado_total is not None:
            return self.costo_proyectado_total
        if self.precio_estimado is None:
            return Decimal("0")
        return Decimal(self.total_anual) * self.precio_estimado

    def clean(self):
        super().clean()
        self.producto_servicio = normalizar_espacios(self.producto_servicio)
        self.dependencia = normalizar_espacios(self.dependencia)
        if not self.producto_servicio:
            raise ValidationError({"producto_servicio": "El producto o servicio es obligatorio."})

    def save(self, *args, **kwargs):
        self.producto_servicio = normalizar_espacios(self.producto_servicio)
        self.dependencia = normalizar_espacios(self.dependencia)
        super().save(*args, **kwargs)


CAMPOS_AJUSTABLES = ("cantidad_autorizada", "precio_estimado", "costo_proyectado_total", *CAMPOS_CANTIDADES_MENSUALES)

MENSAJE_SOLO_INSERCION = "Este registro es histórico: no se modifica ni se borra."


class RegistroHistoricoError(Exception):
    """Se intentó modificar o borrar una aprobación o un ajuste ya registrado."""


class SoloInsercionQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise RegistroHistoricoError(MENSAJE_SOLO_INSERCION)

    def delete(self):
        raise RegistroHistoricoError(MENSAJE_SOLO_INSERCION)


class SoloInsercion(models.Model):
    """Base de los registros históricos de la proyección: solo se insertan."""

    objects = SoloInsercionQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise RegistroHistoricoError(MENSAJE_SOLO_INSERCION)
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RegistroHistoricoError(MENSAJE_SOLO_INSERCION)


class AprobacionProyeccion(SoloInsercion):
    """Aprobación de un envío de la proyección por un administrador.

    El número de aprobaciones requeridas es la decisión D-01 (parámetro
    `proyeccion.aprobaciones_requeridas`, por defecto 1). Cada aprobación queda
    ligada a la fecha del envío que aprobó: si la proyección se devuelve y se
    vuelve a enviar, las aprobaciones anteriores dejan de contar, sin borrarse.
    """

    proyeccion = models.ForeignKey(
        ProyeccionArea,
        verbose_name="proyección",
        on_delete=models.PROTECT,
        related_name="aprobaciones",
    )
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="aprobada por",
        on_delete=models.PROTECT,
        related_name="aprobaciones_de_proyeccion",
    )
    fecha_envio_aprobada = models.DateTimeField("fecha del envío aprobado")
    motivo = models.TextField("motivo")
    fecha = models.DateTimeField("fecha y hora", auto_now_add=True)

    class Meta:
        verbose_name = "aprobación de proyección"
        verbose_name_plural = "aprobaciones de proyección"
        ordering = ["fecha", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["proyeccion", "usuario", "fecha_envio_aprobada"],
                name="aprobacion_unica_por_usuario_y_envio",
                violation_error_message="Este usuario ya aprobó este envío de la proyección.",
            ),
        ]

    def __str__(self):
        return f"{self.proyeccion} · {self.usuario}"

    def clean(self):
        super().clean()
        self.motivo = (self.motivo or "").strip()
        if not self.motivo:
            raise ValidationError({"motivo": "El motivo es obligatorio."})


class Ajuste(SoloInsercion):
    """Cambio justificado de una línea después de la aprobación.

    La línea conserva los valores aprobados; el valor vigente de un campo es el
    `valor_nuevo` de su último ajuste (o el aprobado si no tiene ajustes).
    """

    linea = models.ForeignKey(
        Linea,
        verbose_name="línea",
        on_delete=models.PROTECT,
        related_name="ajustes",
    )
    campo = models.CharField("campo", max_length=100)
    valor_aprobado = models.JSONField(
        "valor aprobado",
        null=True,
        blank=True,
        encoder=DjangoJSONEncoder,
    )
    valor_anterior = models.JSONField(
        "valor vigente antes del ajuste",
        null=True,
        blank=True,
        encoder=DjangoJSONEncoder,
    )
    valor_nuevo = models.JSONField(
        "valor nuevo",
        null=True,
        blank=True,
        encoder=DjangoJSONEncoder,
    )
    justificacion = models.TextField("justificación")
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="usuario",
        on_delete=models.PROTECT,
        related_name="ajustes_de_proyeccion",
    )
    fecha = models.DateTimeField("fecha y hora", auto_now_add=True)

    class Meta:
        verbose_name = "ajuste de proyección"
        verbose_name_plural = "ajustes de proyección"
        ordering = ["-fecha", "-id"]
        indexes = [models.Index(fields=["linea", "campo", "-fecha", "-id"], name="ajuste_linea_campo_fecha_idx")]

    def __str__(self):
        return f"{self.linea} · {self.campo}"

    @property
    def etiqueta_campo(self):
        try:
            etiqueta = str(Linea._meta.get_field(self.campo).verbose_name)
        except FieldDoesNotExist:  # campo desconocido: se muestra tal cual
            return self.campo
        return etiqueta[:1].upper() + etiqueta[1:]

    def clean(self):
        super().clean()
        self.campo = normalizar_espacios(self.campo)
        self.justificacion = (self.justificacion or "").strip()
        errores = {}
        if not self.campo:
            errores["campo"] = "El campo es obligatorio."
        elif self.campo not in CAMPOS_AJUSTABLES:
            errores["campo"] = "Ese campo no se puede ajustar."
        if not self.justificacion:
            errores["justificacion"] = "La justificación es obligatoria."
        if self.linea_id:
            try:
                linea = self.linea
            except Linea.DoesNotExist:
                linea = None
            if linea is not None and linea.proyeccion.estado != ProyeccionArea.Estado.APROBADA:
                errores["linea"] = "Solo se pueden ajustar líneas de una proyección aprobada."
        if errores:
            raise ValidationError(errores)

    def save(self, *args, **kwargs):
        self.campo = normalizar_espacios(self.campo)
        self.justificacion = (self.justificacion or "").strip()
        super().save(*args, **kwargs)
