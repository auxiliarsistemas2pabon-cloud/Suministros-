"""Ficha de proveedor y documentos con vencimiento.

Los proveedores y los catálogos no se borran: se pasan a estado inactivo o se desactivan.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, RegexValidator, URLValidator
from django.db import models, transaction
from django.db.models import Q
from django.db.models.functions import Lower
from django.core.serializers.json import DjangoJSONEncoder
from django.utils import timezone

from config.utilidades import normalizar_espacios, validar_unico_sin_mayusculas
from proveedores import nit as utilidades_nit


class Catalogo(models.Model):
    """Catálogo simple con nombre único (sin distinguir mayúsculas) que se desactiva."""

    nombre = models.CharField("nombre", max_length=120)
    activo = models.BooleanField("activo", default=True)
    fecha_creacion = models.DateTimeField("fecha de creación", auto_now_add=True)

    MENSAJE_DUPLICADO = "Ya existe un registro con este nombre."

    class Meta:
        abstract = True
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre

    def clean(self):
        super().clean()
        self.nombre = normalizar_espacios(self.nombre)
        validar_unico_sin_mayusculas(self, "nombre", self.MENSAJE_DUPLICADO)

    def save(self, *args, **kwargs):
        self.nombre = normalizar_espacios(self.nombre)
        super().save(*args, **kwargs)


class CategoriaProveedor(Catalogo):
    descripcion = models.TextField("descripción", blank=True)
    MENSAJE_DUPLICADO = "Ya existe una categoría con este nombre."

    class Meta(Catalogo.Meta):
        verbose_name = "categoría de proveedor"
        verbose_name_plural = "categorías de proveedor"
        constraints = [
            models.UniqueConstraint(
                Lower("nombre"),
                name="categoria_proveedor_nombre_unico",
                violation_error_message="Ya existe una categoría con este nombre.",
            ),
        ]


class TipoDocumento(Catalogo):
    dias_alerta = models.PositiveSmallIntegerField("días de alerta", default=30, validators=[MinValueValidator(1)])
    usar_alerta_general = models.BooleanField(
        "usar los días de alerta generales", default=True,
        help_text="Si lo desmarca, se usarán los días de alerta indicados para este tipo de documento.",
    )
    requiere_vencimiento = models.BooleanField(
        "requiere fecha de vencimiento",
        default=True,
        help_text="Si está marcado, los documentos de este tipo deben indicar su fecha de vencimiento.",
    )

    MENSAJE_DUPLICADO = "Ya existe un tipo de documento con este nombre."

    class Meta(Catalogo.Meta):
        verbose_name = "tipo de documento"
        verbose_name_plural = "tipos de documento"
        constraints = [
            models.CheckConstraint(condition=Q(dias_alerta__gte=1), name="tipo_documento_alerta_positiva"),
            models.UniqueConstraint(
                Lower("nombre"),
                name="tipo_documento_nombre_unico",
                violation_error_message="Ya existe un tipo de documento con este nombre.",
            ),
        ]


class VersionQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Use el servicio de publicación para cambiar una matriz.")

    def _transicion(self, **kwargs):
        return super().update(**kwargs)

    def delete(self):
        raise ValidationError("Las versiones de matriz se conservan.")


class VersionMatriz(models.Model):
    objects = VersionQuerySet.as_manager()
    class Estado(models.TextChoices):
        BORRADOR = "borrador", "Borrador"
        VIGENTE = "vigente", "Publicada"
        RETIRADA = "retirada", "Retirada"

    numero = models.PositiveIntegerField("número", unique=True, validators=[MinValueValidator(1)])
    desde = models.DateField("vigente desde", null=True, blank=True)
    hasta = models.DateField("vigente hasta", null=True, blank=True)
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.BORRADOR)
    notas = models.TextField(blank=True)

    class Meta:
        ordering = ["-numero"]
        constraints = [
            models.CheckConstraint(condition=Q(numero__gte=1), name="matriz_numero_positivo"),
            models.CheckConstraint(condition=Q(estado__in=["borrador", "vigente", "retirada"]), name="matriz_estado_valido"),
            models.CheckConstraint(condition=Q(estado="borrador") | Q(desde__isnull=False), name="matriz_publicada_con_fecha"),
            models.CheckConstraint(condition=Q(hasta__isnull=True) | Q(hasta__gte=models.F("desde")), name="matriz_fechas_coherentes"),
        ]

    def __str__(self):
        return f"Versión {self.numero} ({self.get_estado_display()})"

    def save(self, *args, **kwargs):
        if self.estado != "borrador":
            raise ValidationError("Use el servicio de publicación para cambiar una matriz.")
        if self.pk and type(self).objects.exclude(estado="borrador").filter(pk=self.pk).exists():
            raise ValidationError("Una matriz publicada no se edita. Copie una versión nueva.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Las versiones de matriz se conservan.")


def version_inicial():
    return VersionMatriz.objects.get_or_create(numero=1)[0].pk


def exigir_matriz_borrador(version_id):
    version = VersionMatriz.objects.select_for_update().get(pk=version_id)
    if version.estado != VersionMatriz.Estado.BORRADOR:
        raise ValidationError("La matriz está publicada o retirada. Copie una versión nueva para modificarla.")


class MatrizQuerySet(models.QuerySet):
    def _validar(self):
        campo = "version_id" if self.model.__name__ == "Requisito" else "requisito__version_id"
        for pk in self.values_list(campo, flat=True).distinct():
            exigir_matriz_borrador(pk)

    @transaction.atomic
    def update(self, **kwargs):
        self._validar()
        if set(kwargs) & {"version", "version_id", "requisito", "requisito_id"}:
            raise ValidationError("No cambie la identidad de los registros de una matriz.")
        return super().update(**kwargs)

    @transaction.atomic
    def delete(self):
        self._validar()
        return super().delete()

    def bulk_create(self, *args, **kwargs):
        raise ValidationError("Use los servicios de matriz para crear registros.")


class ContenidoMatriz(models.Model):
    objects = MatrizQuerySet.as_manager()

    class Meta:
        abstract = True

    @transaction.atomic
    def save(self, *args, **kwargs):
        version_id = self.version_id if isinstance(self, Requisito) else self.requisito.version_id
        exigir_matriz_borrador(version_id)
        if self.pk:
            previo = type(self).objects.get(pk=self.pk)
            anterior = previo.version_id if isinstance(self, Requisito) else previo.requisito.version_id
            exigir_matriz_borrador(anterior)
        super().save(*args, **kwargs)

    @transaction.atomic
    def delete(self, *args, **kwargs):
        exigir_matriz_borrador(self.version_id if isinstance(self, Requisito) else self.requisito.version_id)
        return super().delete(*args, **kwargs)


class Requisito(ContenidoMatriz):
    class Grupo(models.TextChoices):
        CALIDAD = "calidad", "Calidad"
        AMBIENTAL = "ambiental", "Ambiental"
        SGSST = "sgsst", "SG-SST"

    version = models.ForeignKey(VersionMatriz, on_delete=models.PROTECT, related_name="requisitos", default=version_inicial)
    numero = models.PositiveSmallIntegerField("número", validators=[MinValueValidator(1)])
    grupo = models.CharField("grupo", max_length=10, choices=Grupo.choices)
    texto = models.TextField("texto")
    activo = models.BooleanField("activo", default=True)

    class Meta:
        ordering = ["numero"]
        verbose_name = "requisito FR-GDS-14"
        verbose_name_plural = "requisitos FR-GDS-14"
        constraints = [
            models.UniqueConstraint(fields=["version", "numero"], name="requisito_version_numero_unicos"),
            models.CheckConstraint(condition=Q(numero__gte=1), name="requisito_numero_positivo"),
            models.CheckConstraint(condition=Q(grupo__in=["calidad", "ambiental", "sgsst"]), name="requisito_grupo_valido"),
        ]

    def __str__(self):
        return f"{self.numero}. {self.texto[:100]}"

    def clean(self):
        super().clean()
        self.texto = (self.texto or "").strip()
        if not self.texto:
            raise ValidationError({"texto": "El texto del requisito es obligatorio."})


class Peso(ContenidoMatriz):
    requisito = models.ForeignKey(Requisito, on_delete=models.PROTECT, related_name="pesos", verbose_name="requisito")
    categoria = models.ForeignKey(CategoriaProveedor, on_delete=models.PROTECT, related_name="pesos", verbose_name="categoría")
    valor = models.PositiveSmallIntegerField("peso", choices=[(1, "1"), (2, "2")])

    class Meta:
        ordering = ["requisito__numero", "categoria__nombre"]
        verbose_name = "peso FR-GDS-14"
        verbose_name_plural = "pesos FR-GDS-14"
        constraints = [
            models.UniqueConstraint(fields=["requisito", "categoria"], name="peso_requisito_categoria_unicos"),
            models.CheckConstraint(condition=Q(valor__in=[1, 2]), name="peso_valor_uno_o_dos"),
        ]

    def __str__(self):
        return f"Requisito {self.requisito.numero} · {self.categoria}: {self.valor}"


def _validar_catalogo_activo(objeto, campo, modelo, mensaje):
    """Solo se puede elegir un registro activo; se conserva el que ya estaba guardado
    aunque después se haya desactivado (misma regla que áreas y unidades)."""
    valor_id = getattr(objeto, f"{campo}_id")
    if valor_id is None or modelo.objects.filter(pk=valor_id, activo=True).exists():
        return None
    anterior = None
    if objeto.pk:
        anterior = type(objeto).objects.filter(pk=objeto.pk).values_list(f"{campo}_id", flat=True).first()
    return None if anterior == valor_id else mensaje


validar_telefono = RegexValidator(
    r"^[0-9+()\s-]{7,30}$",
    "Escriba un teléfono válido: solo números, espacios, +, guiones y paréntesis (mínimo 7 caracteres).",
)


class DocumentoExigido(models.Model):
    categoria = models.ForeignKey(CategoriaProveedor, on_delete=models.PROTECT, verbose_name="categoría")
    tipo = models.ForeignKey(TipoDocumento, on_delete=models.PROTECT, verbose_name="tipo de documento")
    requisito = models.ForeignKey(Requisito, on_delete=models.PROTECT, null=True, blank=True, verbose_name="requisito respaldado")
    obligatorio = models.BooleanField("obligatorio", default=True)
    activo = models.BooleanField("activo", default=True)

    class Meta:
        ordering = ["categoria__nombre", "tipo__nombre", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["categoria", "tipo", "requisito"], name="doc_exigido_requisito_unico"),
            models.UniqueConstraint(fields=["categoria", "tipo"], condition=Q(requisito__isnull=True), name="doc_exigido_general_unico"),
        ]

    def __str__(self):
        return f"{self.categoria} · {self.tipo}"

    def clean(self):
        super().clean()
        if self.requisito_id and self.categoria_id and not Peso.objects.filter(requisito=self.requisito, categoria=self.categoria).exists():
            raise ValidationError({"requisito": "El requisito no tiene peso para esta categoría."})
        for campo, modelo in (("categoria", CategoriaProveedor), ("tipo", TipoDocumento)):
            mensaje = _validar_catalogo_activo(self, campo, modelo, "Seleccione un registro activo.")
            if mensaje:
                raise ValidationError({campo: mensaje})


class Proveedor(models.Model):
    @property
    def evaluacion_vigente(self):
        return self.evaluaciones.filter(estado="finalizada").order_by("-fecha_finalizacion", "-pk").first()

    class TipoPersona(models.TextChoices):
        NATURAL = "natural", "Persona natural"
        JURIDICA = "juridica", "Persona jurídica"

    class Estado(models.TextChoices):
        REGISTRADO = "registrado", "Registrado"
        EN_REVISION = "en_revision", "En revisión"
        APROBADO = "aprobado", "Aprobado"
        INACTIVO = "inactivo", "Inactivo"

    nit = models.CharField(
        "NIT",
        max_length=25,
        unique=True,
        error_messages={"unique": "Ya existe un proveedor con este NIT."},
        help_text=(
            "Puede escribirlo con puntos, espacios o guiones (por ejemplo 900.123.456-8). Se guarda solo "
            "con números; el dígito de verificación (el número después del último guion) se valida y se "
            "guarda aparte."
        ),
    )
    digito_verificacion = models.PositiveSmallIntegerField("dígito de verificación", editable=False)
    razon_social = models.CharField("razón social o nombre", max_length=200)
    tipo_persona = models.CharField("tipo de persona", max_length=10, choices=TipoPersona.choices)
    contacto_nombre = models.CharField("nombre del contacto", max_length=150)
    contacto_correo = models.EmailField("correo del contacto", max_length=254)
    contacto_telefono = models.CharField("teléfono del contacto", max_length=30, validators=[validar_telefono])
    direccion = models.CharField("dirección", max_length=250)
    categoria = models.ForeignKey(
        CategoriaProveedor,
        verbose_name="categoría",
        on_delete=models.PROTECT,
        related_name="proveedores",
        null=True,
        blank=True,
    )
    estado = models.CharField("estado", max_length=15, choices=Estado.choices, default=Estado.REGISTRADO)
    fecha_registro = models.DateTimeField("fecha de registro", auto_now_add=True)

    class Meta:
        verbose_name = "proveedor"
        verbose_name_plural = "proveedores"
        ordering = ["razon_social", "nit"]
        constraints = [
            # Respaldo en la base de la forma canónica (solo dígitos, sin ceros a la izquierda).
            models.CheckConstraint(
                condition=Q(nit__regex=r"^[1-9][0-9]{4,14}$"),
                name="proveedor_nit_canonico",
                violation_error_message="El NIT debe guardarse solo con números.",
            ),
            models.CheckConstraint(
                condition=Q(digito_verificacion__lte=9),
                name="proveedor_dv_un_digito",
                violation_error_message="El dígito de verificación debe estar entre 0 y 9.",
            ),
            models.CheckConstraint(
                condition=Q(estado__in=["registrado", "en_revision", "aprobado", "inactivo"]),
                name="proveedor_estado_valido",
                violation_error_message="El estado del proveedor no es válido.",
            ),
            models.CheckConstraint(
                condition=Q(tipo_persona__in=["natural", "juridica"]),
                name="proveedor_tipo_persona_valido",
                violation_error_message="El tipo de persona no es válido.",
            ),
        ]

    def __str__(self):
        return f"{self.razon_social} (NIT {self.nit_formateado})"

    @property
    def nit_formateado(self):
        return utilidades_nit.formatear(self.nit, self.digito_verificacion)

    @property
    def activo(self):
        return self.estado != self.Estado.INACTIVO

    def _normalizar(self):
        """Deja el NIT en su forma canónica y calcula el dígito de verificación.
        Devuelve los mensajes de error del NIT (lista vacía si es válido)."""
        self.razon_social = normalizar_espacios(self.razon_social)
        self.contacto_nombre = normalizar_espacios(self.contacto_nombre)
        self.contacto_correo = (self.contacto_correo or "").strip().lower()
        self.contacto_telefono = normalizar_espacios(self.contacto_telefono)
        self.direccion = normalizar_espacios(self.direccion)
        try:
            self.nit, self.digito_verificacion = utilidades_nit.normalizar(self.nit)
        except ValidationError as error:
            return error.messages
        return []

    def clean_fields(self, exclude=None):
        # La normalización va antes de validar los campos: así la unicidad y la longitud
        # se comprueban sobre el NIT canónico.
        errores_nit = self._normalizar()
        exclude = set(exclude or ())
        if errores_nit:
            exclude.add("digito_verificacion")
        errores = {}
        try:
            super().clean_fields(exclude=exclude)
        except ValidationError as error:
            errores = error.update_error_dict(errores)
        if errores_nit and "nit" not in exclude:
            errores["nit"] = errores_nit
        if errores:
            raise ValidationError(errores)

    def clean(self):
        super().clean()
        mensaje = _validar_catalogo_activo(
            self, "categoria", CategoriaProveedor, "La categoría seleccionada está inactiva. Elija una categoría activa."
        )
        if mensaje:
            raise ValidationError({"categoria": mensaje})

    def save(self, *args, **kwargs):
        self._normalizar()
        super().save(*args, **kwargs)


validar_enlace = URLValidator(schemes=["http", "https"], message="Escriba un enlace válido que empiece por https://.")


def errores_fechas_documento(tipo, expedicion, vencimiento):
    errores = {}
    if expedicion and expedicion > timezone.localdate():
        errores["fecha_expedicion"] = "La fecha de expedición no puede ser posterior a hoy."
    if tipo and tipo.requiere_vencimiento and not vencimiento:
        errores["fecha_vencimiento"] = f"Los documentos de tipo «{tipo}» deben indicar la fecha de vencimiento."
    if expedicion and vencimiento and vencimiento < expedicion:
        errores["fecha_vencimiento"] = "La fecha de vencimiento no puede ser anterior a la de expedición."
    return errores


class DocumentoProveedor(models.Model):
    """Documento de un proveedor: un PDF privado **o** un enlace, nunca ambos.

    El PDF se guarda con nombre uuid en archivos_privados/documentos/AAAA/MM/ y solo se
    descarga mediante la vista protegida. Al borrar o reemplazar el documento, el archivo
    anterior se borra cuando la transacción se confirma (proveedores/signals.py).
    """

    proveedor = models.ForeignKey(
        Proveedor, verbose_name="proveedor", on_delete=models.PROTECT, related_name="documentos"
    )
    tipo = models.ForeignKey(
        TipoDocumento, verbose_name="tipo de documento", on_delete=models.PROTECT, related_name="documentos"
    )
    fecha_expedicion = models.DateField("fecha de expedición")
    fecha_vencimiento = models.DateField("fecha de vencimiento", null=True, blank=True)
    archivo = models.FileField("archivo PDF", max_length=255, blank=True)
    nombre_archivo = models.CharField("nombre original del archivo", max_length=255, blank=True)
    enlace = models.URLField("enlace", max_length=500, blank=True, validators=[validar_enlace])
    cargado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="cargado por",
        on_delete=models.PROTECT,
        related_name="documentos_proveedor_cargados",
    )
    fecha_carga = models.DateTimeField("fecha de carga", default=timezone.now)

    class Meta:
        verbose_name = "documento de proveedor"
        verbose_name_plural = "documentos de proveedor"
        ordering = ["proveedor", "tipo__nombre", "-fecha_expedicion", "-pk"]
        constraints = [
            models.CheckConstraint(
                condition=(Q(archivo="") & ~Q(enlace="")) | (~Q(archivo="") & Q(enlace="")),
                name="documento_pdf_o_enlace",
                violation_error_message="El documento debe tener un PDF o un enlace, no ambos.",
            ),
            models.CheckConstraint(
                condition=Q(fecha_vencimiento__isnull=True) | Q(fecha_vencimiento__gte=models.F("fecha_expedicion")),
                name="documento_vence_despues_de_expedir",
                violation_error_message="La fecha de vencimiento no puede ser anterior a la de expedición.",
            ),
        ]
        indexes = [models.Index(fields=["fecha_vencimiento"], name="documento_vencimiento_idx")]

    def __str__(self):
        return f"{self.tipo} · {self.proveedor.razon_social}" if self.tipo_id and self.proveedor_id else "Documento"

    @property
    def tiene_pdf(self):
        return bool(self.archivo and self.archivo.name)

    def clean(self):
        super().clean()
        errores = errores_fechas_documento(self.tipo if self.tipo_id else None, self.fecha_expedicion, self.fecha_vencimiento)
        mensaje = _validar_catalogo_activo(
            self, "tipo", TipoDocumento, "El tipo de documento seleccionado está inactivo. Elija uno activo."
        )
        if mensaje:
            errores["tipo"] = mensaje
        if errores:
            raise ValidationError(errores)


class EvaluacionQuerySet(models.QuerySet):
    def _finalizar(self, **valores):
        return super().update(**valores)

    def update(self, **kwargs):
        raise ValidationError("La identidad de una evaluación se conserva.")

    def delete(self):
        raise ValidationError("Las evaluaciones se conservan.")


class EvaluacionProveedor(models.Model):
    objects = EvaluacionQuerySet.as_manager()
    proveedor = models.ForeignKey(Proveedor, on_delete=models.PROTECT, related_name="evaluaciones")
    categoria = models.ForeignKey(CategoriaProveedor, on_delete=models.PROTECT)
    version = models.ForeignKey(VersionMatriz, on_delete=models.PROTECT, related_name="evaluaciones")
    fecha = models.DateField(default=timezone.localdate)
    evaluador = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    estado = models.CharField(max_length=12, default="borrador", editable=False)
    resultado = models.JSONField(default=dict, blank=True, editable=False, encoder=DjangoJSONEncoder)
    finalizada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="evaluaciones_finalizadas")
    fecha_finalizacion = models.DateTimeField(null=True, blank=True)
    origen = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True, related_name="copias")
    anulada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="evaluaciones_anuladas")
    fecha_anulacion = models.DateTimeField(null=True, blank=True)
    motivo_anulacion = models.TextField(blank=True)
    categoria_nombre = models.CharField(max_length=120, editable=False)

    class Meta:
        ordering = ["-fecha", "-pk"]
        constraints = [
            models.CheckConstraint(condition=Q(estado__in=["borrador", "finalizada", "anulada"]), name="evaluacion_estado_inicial"),
            models.CheckConstraint(condition=Q(estado="borrador", finalizada_por__isnull=True, fecha_finalizacion__isnull=True) | Q(estado="finalizada", finalizada_por__isnull=False, fecha_finalizacion__isnull=False) | Q(estado="anulada", finalizada_por__isnull=True, fecha_finalizacion__isnull=True) | Q(estado="anulada", finalizada_por__isnull=False, fecha_finalizacion__isnull=False), name="evaluacion_finalizacion_coherente"),
            models.CheckConstraint(condition=(Q(estado="anulada", anulada_por__isnull=False, fecha_anulacion__isnull=False) & ~Q(motivo_anulacion="")) | (~Q(estado="anulada") & Q(anulada_por__isnull=True, fecha_anulacion__isnull=True, motivo_anulacion="")), name="evaluacion_anulacion_coherente"),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("La categoría y versión de una evaluación se conservan; cree otra evaluación.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Las evaluaciones se conservan.")


class EvidenciaEvaluacion(models.Model):
    objects = EvaluacionQuerySet.as_manager()
    evaluacion = models.ForeignKey(EvaluacionProveedor, on_delete=models.PROTECT, related_name="adjuntos")
    archivo = models.FileField(max_length=255)
    nombre_archivo = models.CharField(max_length=255)
    cargado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    fecha = models.DateTimeField(default=timezone.now)

    @transaction.atomic
    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Los adjuntos de evidencia se conservan; cargue otro PDF.")
        if EvaluacionProveedor.objects.select_for_update().get(pk=self.evaluacion_id).estado != "borrador":
            raise ValidationError("La evaluación está finalizada.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Los PDF de evidencia se conservan.")


class RespuestaQuerySet(models.QuerySet):
    @transaction.atomic
    def update(self, **kwargs):
        if set(kwargs) & {"evaluacion", "evaluacion_id", "requisito", "requisito_id"}:
            raise ValidationError("La identidad de una respuesta se conserva.")
        ids = self.values_list("evaluacion_id", flat=True)
        evaluaciones = list(EvaluacionProveedor.objects.select_for_update().filter(pk__in=ids))
        if any(e.estado != "borrador" for e in evaluaciones):
            raise ValidationError("Las respuestas finalizadas no se modifican.")
        return super().update(**kwargs)

    def delete(self):
        raise ValidationError("Las respuestas se conservan en el historial.")

    def bulk_create(self, *args, **kwargs):
        raise ValidationError("Use el servicio de respuestas.")


class RespuestaEvaluacion(models.Model):
    objects = RespuestaQuerySet.as_manager()
    class Valor(models.TextChoices):
        SI = "si", "Sí"
        NO = "no", "No"
        NA = "na", "No aplica"

    evaluacion = models.ForeignKey(EvaluacionProveedor, on_delete=models.PROTECT, related_name="respuestas")
    requisito = models.ForeignKey(Requisito, on_delete=models.PROTECT)
    respuesta = models.CharField(max_length=2, choices=Valor.choices)
    observacion = models.TextField(blank=True)
    confirma_na = models.BooleanField(default=False)
    documento = models.ForeignKey(DocumentoProveedor, on_delete=models.PROTECT, null=True, blank=True)
    evidencia_pdf = models.ForeignKey(EvidenciaEvaluacion, on_delete=models.PROTECT, null=True, blank=True)
    documento_datos = models.JSONField(default=dict, blank=True)
    control_documental = models.JSONField(default=dict, blank=True)
    respondido_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    fecha = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["requisito__numero"]
        constraints = [
            models.UniqueConstraint(fields=["evaluacion", "requisito"], name="respuesta_evaluacion_requisito_unicos"),
            models.CheckConstraint(condition=Q(respuesta__in=["si", "no", "na"]), name="respuesta_valor_valido"),
            models.CheckConstraint(condition=~Q(respuesta="na") | (Q(confirma_na=True) & ~Q(observacion="")), name="respuesta_na_confirmada"),
        ]

    def clean(self):
        super().clean()
        errores = {}
        if self.evaluacion_id and self.requisito_id:
            if self.requisito.version_id != self.evaluacion.version_id or not self.requisito.activo:
                errores["requisito"] = "El requisito no corresponde a la matriz activa de esta evaluación."
        if self.respuesta == "na" and (not self.confirma_na or not self.observacion.strip()):
            errores["observacion"] = "No aplica exige confirmación y observación."
        if self.documento_id and self.evaluacion_id and self.documento.proveedor_id != self.evaluacion.proveedor_id:
            errores["documento"] = "Seleccione un documento del proveedor evaluado."
        if self.evidencia_pdf_id and self.evaluacion_id and self.evidencia_pdf.evaluacion_id != self.evaluacion_id:
            errores["evidencia_pdf"] = "La evidencia pertenece a otra evaluación."
        if errores:
            raise ValidationError(errores)

    @transaction.atomic
    def save(self, *args, **kwargs):
        evaluacion = EvaluacionProveedor.objects.select_for_update().get(pk=self.evaluacion_id)
        if evaluacion.estado != "borrador":
            raise ValidationError("Las respuestas finalizadas no se modifican.")
        if self.pk:
            previo = type(self).objects.get(pk=self.pk)
            if (previo.evaluacion_id, previo.requisito_id) != (self.evaluacion_id, self.requisito_id):
                raise ValidationError("No se reasigna la identidad de una respuesta.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Las respuestas se conservan en el historial.")


class EnvioProveedor(models.Model):
    class Estado(models.TextChoices):
        PENDIENTE = "pendiente", "Pendiente de revisión"
        ACEPTADO = "aceptado", "Aceptado"
        DESCARTADO = "descartado", "Descartado"

    proveedor = models.ForeignKey(Proveedor, on_delete=models.PROTECT, related_name="envios", verbose_name="proveedor")
    tipo = models.ForeignKey(TipoDocumento, on_delete=models.PROTECT, related_name="envios", verbose_name="tipo de documento")
    fecha_expedicion = models.DateField("fecha de expedición")
    fecha_vencimiento = models.DateField("fecha de vencimiento", null=True, blank=True)
    archivo = models.FileField("archivo PDF", max_length=255, blank=True)
    documento = models.OneToOneField(DocumentoProveedor, on_delete=models.PROTECT, related_name="envio_origen", null=True, blank=True, verbose_name="documento aceptado")
    nombre_archivo = models.CharField("nombre original", max_length=255)
    enviado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="envios_proveedor", verbose_name="enviado por")
    fecha_envio = models.DateTimeField("fecha de envío", default=timezone.now)
    estado = models.CharField("estado", max_length=12, choices=Estado.choices, default=Estado.PENDIENTE)
    motivo = models.TextField("motivo de revisión", blank=True)
    revisado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="envios_revisados", null=True, blank=True)
    fecha_revision = models.DateTimeField("fecha de revisión", null=True, blank=True)

    class Meta:
        ordering = ["-fecha_envio", "-pk"]
        verbose_name = "envío de proveedor"
        verbose_name_plural = "envíos de proveedores"
        constraints = [
            models.CheckConstraint(condition=Q(estado__in=["pendiente", "aceptado", "descartado"]), name="envio_estado_valido"),
            models.CheckConstraint(condition=Q(fecha_vencimiento__isnull=True) | Q(fecha_vencimiento__gte=models.F("fecha_expedicion")), name="envio_fechas_coherentes"),
            models.CheckConstraint(condition=(Q(estado="pendiente", revisado_por__isnull=True, fecha_revision__isnull=True) | Q(estado__in=["aceptado", "descartado"], revisado_por__isnull=False, fecha_revision__isnull=False)), name="envio_revision_coherente"),
            models.CheckConstraint(condition=~Q(estado="descartado") | ~Q(motivo=""), name="envio_descarte_con_motivo"),
            models.CheckConstraint(condition=Q(estado="descartado") | ~Q(archivo=""), name="envio_pendiente_aceptado_con_pdf"),
            models.CheckConstraint(condition=Q(estado="aceptado", documento__isnull=False) | (~Q(estado="aceptado") & Q(documento__isnull=True)), name="envio_documento_segun_estado"),
        ]

    def __str__(self):
        return f"Envío {self.pk or 'nuevo'} · {self.proveedor.razon_social}" if self.proveedor_id else "Envío"

    def clean(self):
        super().clean()
        errores = errores_fechas_documento(self.tipo if self.tipo_id else None, self.fecha_expedicion, self.fecha_vencimiento)
        mensaje = _validar_catalogo_activo(self, "tipo", TipoDocumento, "El tipo de documento está inactivo.")
        if mensaje:
            errores["tipo"] = mensaje
        if self.estado == self.Estado.DESCARTADO and not self.motivo.strip():
            errores["motivo"] = "El motivo del descarte es obligatorio."
        if errores:
            raise ValidationError(errores)
