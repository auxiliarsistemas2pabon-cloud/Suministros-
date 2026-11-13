"""Modelos del área: elegibles."""
from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone
from config.utilidades import normalizar_espacios
from compras.modelos.necesidades import Necesidad


class ListaElegibles(models.Model):
    necesidad = models.ForeignKey(Necesidad, on_delete=models.PROTECT, related_name="listas")
    fecha = models.DateField(default=timezone.localdate)
    estado = models.CharField(max_length=12, default="borrador", editable=False)
    creada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    version_criterios = models.ForeignKey("VersionCriterios", on_delete=models.PROTECT, null=True, blank=True)
    reglas_calculo = models.JSONField(default=dict, blank=True, editable=False)
    justificacion_documental = models.TextField(blank=True)
    documental_reglas = models.JSONField(default=dict, blank=True, editable=False)
    documental_referencia = models.DateField(null=True, blank=True, editable=False)
    documental_fecha = models.DateTimeField(null=True, blank=True, editable=False)
    documental_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="cierres_documentales_elegibles", editable=False)
    cerrada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="listas_elegibles_cerradas", editable=False)
    fecha_cierre = models.DateTimeField(null=True, blank=True, editable=False)
    reabierta_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="listas_elegibles_reabiertas", editable=False)
    fecha_reapertura = models.DateTimeField(null=True, blank=True, editable=False)
    anulada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="listas_elegibles_anuladas", editable=False)
    fecha_anulacion = models.DateTimeField(null=True, blank=True, editable=False)
    motivo_anulacion = models.TextField(blank=True, editable=False)
    resultado_cierre = models.JSONField(default=dict, blank=True, editable=False)

    class Meta:
        ordering = ["-fecha", "-pk"]
        constraints = [models.CheckConstraint(condition=models.Q(estado__in=["borrador", "cerrada", "anulada"]), name="lista_elegibles_estado_valido")]

    def __str__(self):
        return f"Lista {self.pk} · necesidad {self.necesidad_id}"

    @property
    def estado_flujo(self):
        from compras.cotizacion_origen import hay_cotizacion
        if self.estado != "anulada" and hay_cotizacion(self):
            return "Con cotización"
        return {"borrador": "Borrador", "cerrada": "Cerrada", "anulada": "Anulada"}[self.estado]


class ParticipanteElegible(models.Model):
    lista = models.ForeignKey(ListaElegibles, on_delete=models.PROTECT, related_name="participantes")
    proveedor = models.ForeignKey("proveedores.Proveedor", on_delete=models.PROTECT)
    nit = models.CharField(max_length=25, editable=False)
    razon_social = models.CharField(max_length=200, editable=False)
    activo = models.BooleanField(default=True)
    cantidad_autorizada = models.DecimalField(max_digits=14, decimal_places=3, default=0, validators=[MinValueValidator(0)])
    observacion = models.TextField("observación de decisión", blank=True)
    justificacion_eleccion = models.TextField("justificación de elección excepcional", blank=True)
    decision_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="decisiones_elegibles")
    decision_fecha = models.DateTimeField(null=True, blank=True)
    evaluacion_fr14 = models.ForeignKey("proveedores.EvaluacionProveedor", on_delete=models.PROTECT, null=True, blank=True, editable=False)
    estado_documental = models.JSONField(default=dict, blank=True, editable=False)

    class Meta:
        ordering = ["razon_social", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["lista", "proveedor"], name="lista_proveedor_unico"),
            models.UniqueConstraint(fields=["lista", "nit"], name="lista_nit_unico"),
            models.CheckConstraint(condition=models.Q(cantidad_autorizada__gte=0), name="ele_cantidad_autorizada_valida"),
        ]


class CatalogoCriteriosQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Use los servicios de criterios para conservar el historial.")

    def delete(self):
        raise ValidationError("Use los servicios de criterios para conservar el historial.")

    def bulk_create(self, *args, **kwargs):
        raise ValidationError("Guarde los criterios mediante sus servicios.")

    def bulk_update(self, *args, **kwargs):
        raise ValidationError("Guarde los criterios mediante sus servicios.")

    def _transicion(self, **kwargs):
        return super().update(**kwargs)

    def _reemplazar(self):
        return super().delete()


class VersionCriterios(models.Model):
    objects = CatalogoCriteriosQuerySet.as_manager()
    numero = models.PositiveIntegerField("número", unique=True, validators=[MinValueValidator(1)])
    estado = models.CharField(max_length=12, choices=[("borrador", "Borrador"), ("publicada", "Publicada"), ("retirada", "Retirada")], default="borrador")
    desde = models.DateField("vigente desde", null=True, blank=True)
    hasta = models.DateField("vigente hasta", null=True, blank=True)
    notas = models.TextField(blank=True)

    class Meta:
        ordering = ["-numero"]
        verbose_name = "versión de criterios de elegibles"
        verbose_name_plural = "versiones de criterios de elegibles"
        constraints = [
            models.CheckConstraint(condition=models.Q(numero__gte=1), name="ele_version_numero_positivo"),
            models.CheckConstraint(condition=models.Q(estado__in=["borrador", "publicada", "retirada"]), name="ele_version_estado_valido"),
            models.CheckConstraint(condition=models.Q(estado="borrador") | models.Q(desde__isnull=False), name="ele_version_publicada_con_fecha"),
            models.CheckConstraint(condition=models.Q(hasta__isnull=True) | models.Q(hasta__gte=models.F("desde")), name="ele_version_fechas_validas"),
        ]

    def __str__(self):
        return f"Versión {self.numero} · {self.get_estado_display()}"

    def save(self, *args, **kwargs):
        from django.db import transaction
        with transaction.atomic():
            if self.estado != "borrador":
                raise ValidationError("Publique los criterios mediante el servicio de publicación.")
            if self.pk:
                anterior = type(self).objects.select_for_update().get(pk=self.pk)
                if anterior.estado != "borrador":
                    raise ValidationError("Una versión publicada se conserva. Copie otra versión.")
            super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Las versiones de criterios se conservan.")


class CriterioElegible(models.Model):
    objects = CatalogoCriteriosQuerySet.as_manager()
    version = models.ForeignKey(VersionCriterios, on_delete=models.PROTECT, related_name="criterios")
    orden = models.PositiveSmallIntegerField(validators=[MinValueValidator(1)])
    nombre = models.CharField(max_length=120)
    peso = models.DecimalField("peso %", max_digits=5, decimal_places=2, validators=[MinValueValidator(Decimal("0.01")), MaxValueValidator(100)])

    class Meta:
        ordering = ["orden", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["version", "orden"], name="ele_criterio_orden_unico"),
            models.UniqueConstraint(Lower("nombre"), "version", name="ele_criterio_nombre_unico"),
            models.CheckConstraint(condition=models.Q(peso__gt=0, peso__lte=100), name="ele_criterio_peso_valido"),
        ]

    def __str__(self):
        return self.nombre

    def clean(self):
        self.nombre = normalizar_espacios(self.nombre)
        if not self.nombre:
            raise ValidationError({"nombre": "El nombre es obligatorio."})

    def save(self, *args, **kwargs):
        from django.db import transaction
        with transaction.atomic():
            version = VersionCriterios.objects.select_for_update().get(pk=self.version_id)
            if version.estado != "borrador":
                raise ValidationError("Los criterios publicados se conservan. Copie otra versión.")
            if self.pk and type(self).objects.exclude(version_id=self.version_id).filter(pk=self.pk).exists():
                raise ValidationError("No traslade un criterio a otra versión.")
            super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Edite el conjunto de criterios desde su versión en borrador.")


class CalificacionElegible(models.Model):
    objects = CatalogoCriteriosQuerySet.as_manager()
    participante = models.ForeignKey(ParticipanteElegible, on_delete=models.PROTECT, related_name="calificaciones")
    criterio = models.ForeignKey(CriterioElegible, on_delete=models.PROTECT)
    cumplimiento = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True)
    observacion = models.TextField("observación", blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["participante", "criterio"], name="ele_calificacion_unica"),
            models.CheckConstraint(condition=models.Q(cumplimiento__isnull=True) | models.Q(cumplimiento__gte=0, cumplimiento__lte=100), name="ele_cumplimiento_valido"),
        ]

    def clean(self):
        if self.participante_id and self.criterio_id:
            lista = self.participante.lista
            if lista.estado != "borrador" or not self.participante.activo:
                raise ValidationError("Solo se califican participantes activos de una lista en borrador.")
            if self.criterio.version_id != lista.version_criterios_id:
                raise ValidationError("El criterio no pertenece a la versión de la lista.")
            if self.cumplimiento is not None and str(self.cumplimiento.normalize()) not in {str(Decimal(v).normalize()) for v in lista.reglas_calculo.get("escala", [])}:
                raise ValidationError({"cumplimiento": "Seleccione un valor de la escala guardada en la lista."})

    def save(self, *args, **kwargs):
        from django.db import transaction
        with transaction.atomic():
            participante = ParticipanteElegible.objects.get(pk=self.participante_id)
            ListaElegibles.objects.select_for_update().get(pk=participante.lista_id)
            if self.pk:
                anterior = type(self).objects.get(pk=self.pk)
                if anterior.participante_id != self.participante_id or anterior.criterio_id != self.criterio_id:
                    raise ValidationError("No traslade una calificación a otro participante o criterio.")
            self.participante = ParticipanteElegible.objects.get(pk=self.participante_id)
            self.clean()
            super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Las calificaciones se conservan; deje el cumplimiento pendiente con motivo.")


class DesempateElegibles(models.Model):
    lista = models.ForeignKey(ListaElegibles, on_delete=models.PROTECT, related_name="desempates")
    total = models.DecimalField(max_digits=8, decimal_places=4)
    orden = models.JSONField(default=list)
    justificacion = models.TextField()
    registrado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    fecha = models.DateTimeField(default=timezone.now)
    activo = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["lista", "total"], name="ele_desempate_total_unico")]


class DecisionElegibles(models.Model):
    lista = models.OneToOneField(ListaElegibles, on_delete=models.PROTECT, related_name="decision")
    justificacion_unico = models.TextField(blank=True)
    justificacion_cantidad = models.TextField(blank=True)
    registrada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    fecha = models.DateTimeField(default=timezone.now)
    contexto = models.JSONField(default=dict)
    vigente = models.BooleanField(default=True)


class HistorialCierreQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Los cierres históricos se conservan.")

    def delete(self):
        raise ValidationError("Los cierres históricos se conservan.")

    def bulk_update(self, *args, **kwargs):
        raise ValidationError("Los cierres históricos se conservan.")

    def bulk_create(self, *args, **kwargs):
        raise ValidationError("Use el servicio de cierre de listas.")


class CierreListaElegibles(models.Model):
    objects = HistorialCierreQuerySet.as_manager()
    lista = models.ForeignKey(ListaElegibles, on_delete=models.PROTECT, related_name="cierres")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    fecha = models.DateTimeField(default=timezone.now)
    motivo = models.TextField()
    contenido = models.JSONField(default=dict)

    class Meta:
        ordering = ["-fecha", "-pk"]
        verbose_name = "cierre histórico de elegibles"
        verbose_name_plural = "cierres históricos de elegibles"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Los cierres históricos se conservan.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Los cierres históricos se conservan.")
