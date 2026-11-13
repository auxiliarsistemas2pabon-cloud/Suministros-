from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
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


class TipoCotizacion(models.Model):
    nombre = models.CharField(max_length=120)
    descripcion = models.TextField("descripción", blank=True)
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ["nombre"]
        verbose_name = "tipo de cotización"
        verbose_name_plural = "tipos de cotización"
        constraints = [models.UniqueConstraint(Lower("nombre"), name="cot_tipo_nombre_unico")]

    def __str__(self):
        return self.nombre

    def clean(self):
        self.nombre = normalizar_espacios(self.nombre)
        if not self.nombre:
            raise ValidationError({"nombre": "El nombre es obligatorio."})
        if any(n.casefold() == self.nombre.casefold() for n in type(self).objects.exclude(pk=self.pk).values_list("nombre", flat=True)):
            raise ValidationError({"nombre": "Ya existe un tipo de cotización con este nombre."})


class SecuenciaCotizacion(models.Model):
    ultimo = models.PositiveBigIntegerField(default=0)

    class Meta:
        verbose_name = "secuencia interna de cotizaciones"
        verbose_name_plural = "secuencia interna de cotizaciones"
        constraints = [models.CheckConstraint(condition=models.Q(pk=1), name="cot_secuencia_unica")]


class CotizacionQuerySet(models.QuerySet):
    CAMPOS_UNICO = {"proveedor_unico", "causal_proveedor_unico", "causal_proveedor_unico_id", "causal_unico_nombre",
        "justificacion_proveedor_unico", "pdf_proveedor_unico", "pdf_proveedor_unico_id", "revision_proveedor_unico",
        "reglas_proveedor_unico", "oferta_unica_datos", "requiere_contrato", "revision_requiere_contrato"}

    def update(self, **kwargs):
        if "estado" in kwargs or self.CAMPOS_UNICO.intersection(kwargs):
            raise ValidationError("Use los servicios de cotización para validar proveedor único y conservar su historial.")
        return super().update(**kwargs)

    def bulk_update(self, objs, fields, **kwargs):
        if "estado" in fields or self.CAMPOS_UNICO.intersection(fields):
            raise ValidationError("No modifique decisiones o proveedor único de forma masiva.")
        return super().bulk_update(objs, fields, **kwargs)

    def bulk_create(self, *args, **kwargs):
        raise ValidationError("Use el servicio de creación de cotizaciones.")


class Cotizacion(models.Model):
    objects = CotizacionQuerySet.as_manager()
    necesidad = models.ForeignKey(Necesidad, on_delete=models.PROTECT, related_name="cotizaciones")
    lista_elegibles = models.ForeignKey(ListaElegibles, on_delete=models.PROTECT, null=True, blank=True, related_name="cotizaciones")
    cierre_origen = models.ForeignKey(CierreListaElegibles, on_delete=models.PROTECT, null=True, blank=True)
    fecha = models.DateField(default=timezone.localdate)
    area = models.ForeignKey("areas.Area", on_delete=models.PROTECT)
    responsable = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    tipo = models.ForeignKey(TipoCotizacion, on_delete=models.PROTECT)
    objeto = models.TextField()
    estado = models.CharField(max_length=16, default="borrador", editable=False,
        choices=[("borrador", "Borrador"), ("en_comparacion", "En comparación"), ("decidida", "Decidida"), ("anulada", "Anulada")])
    numero = models.PositiveBigIntegerField(unique=True, editable=False)
    consecutivo = models.CharField(max_length=40, unique=True, editable=False)
    origen_datos = models.JSONField(default=dict, blank=True, editable=False)
    limites_aplicados = models.JSONField(default=dict, editable=False)
    fecha_creacion = models.DateTimeField(default=timezone.now, editable=False)
    proveedor_unico = models.BooleanField(default=False)
    causal_proveedor_unico = models.ForeignKey("CausalProveedorUnico", on_delete=models.PROTECT, null=True, blank=True)
    causal_unico_nombre = models.CharField(max_length=120, blank=True, editable=False)
    justificacion_proveedor_unico = models.TextField(blank=True)
    pdf_proveedor_unico = models.ForeignKey("PdfProveedorUnico", on_delete=models.PROTECT, null=True, blank=True, related_name="cotizaciones_actuales", editable=False)
    revision_proveedor_unico = models.PositiveIntegerField(default=0, editable=False)
    reglas_proveedor_unico = models.JSONField(default=dict, blank=True, editable=False)
    oferta_unica_datos = models.JSONField(default=dict, blank=True, editable=False)
    requiere_contrato = models.BooleanField(default=False)
    revision_requiere_contrato = models.PositiveIntegerField(default=0, editable=False)

    class Meta:
        ordering = ["-fecha", "-pk"]
        verbose_name = "cotización"
        verbose_name_plural = "cotizaciones"
        constraints = [
            models.CheckConstraint(condition=models.Q(estado__in=["borrador", "en_comparacion", "decidida", "anulada"]), name="cot_estado_valido"),
            models.CheckConstraint(condition=models.Q(numero__gte=1), name="cot_numero_positivo"),
        ]

    def __str__(self):
        return self.consecutivo

    def clean(self):
        self.objeto = self.objeto.strip()
        if not self.objeto:
            raise ValidationError({"objeto": "Describa el objeto de la cotización."})
        if self.necesidad_id and self.area_id != self.necesidad.area_id:
            raise ValidationError("La cotización debe pertenecer al área de su necesidad.")
        if self.lista_elegibles_id and (self.lista_elegibles.necesidad_id != self.necesidad_id or self.lista_elegibles.estado != "cerrada"):
            raise ValidationError("Seleccione una lista cerrada de la misma necesidad.")
        if self.cierre_origen_id and self.cierre_origen.lista_id != self.lista_elegibles_id:
            raise ValidationError("El cierre no pertenece a la lista de origen.")
        if self.pdf_proveedor_unico_id and self.pdf_proveedor_unico.cotizacion_id != self.pk:
            raise ValidationError("La evidencia de proveedor único pertenece a otra cotización.")

    def save(self, *args, **kwargs):
        from django.db import transaction
        if self.estado == "decidida":
            from compras.proveedor_unico_servicios import _validar_para_decidir
            with transaction.atomic():
                actual = type(self).objects.select_for_update().get(pk=self.pk) if self.pk else self
                campos = kwargs.get("update_fields")
                escribe_estado = campos is None or "estado" in campos
                if actual.estado != "decidida" and escribe_estado:
                    # Valide exactamente los valores que se persistirán, incluso al
                    # guardar solo estado desde una instancia cargada antes del caso.
                    datos = {f.attname: getattr(self if campos is None or f.name in campos or f.attname in campos else actual, f.attname)
                        for f in self._meta.concrete_fields}
                    _validar_para_decidir(type(self)(**datos))
                    if datos["requiere_contrato"] and not AprobacionCotizacion.objects.filter(decision__cotizacion_id=self.pk,
                            decision__estado="aprobada", contrato_datos__requiere_contrato=True).exists():
                        raise ValidationError("Complete la aprobación de la decisión con su contrato antes de pasar a Decidida.")
                return super().save(*args, **kwargs)
        return super().save(*args, **kwargs)


class LineaCotizacion(models.Model):
    cotizacion = models.ForeignKey(Cotizacion, on_delete=models.PROTECT, related_name="lineas")
    orden = models.PositiveIntegerField()
    descripcion = models.CharField("descripción", max_length=255)
    unidad = models.ForeignKey("proyecciones.UnidadMedida", on_delete=models.PROTECT)
    unidad_texto = models.CharField(max_length=120, editable=False)
    cantidad = models.DecimalField(max_digits=14, decimal_places=3, validators=[MinValueValidator(Decimal("0.001"))])
    especificacion = models.TextField("especificación técnica", blank=True)
    origen = models.ForeignKey(OrigenNecesidad, on_delete=models.PROTECT, null=True, blank=True)
    origen_datos = models.JSONField(default=dict, blank=True, editable=False)

    class Meta:
        ordering = ["orden", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["cotizacion", "orden"], name="cot_linea_orden_unico"),
            models.CheckConstraint(condition=models.Q(cantidad__gt=0), name="cot_linea_cantidad_positiva"),
        ]

    def clean(self):
        self.descripcion = normalizar_espacios(self.descripcion)
        if not self.descripcion:
            raise ValidationError({"descripcion": "Describa el producto o servicio."})
        if self.origen_id and self.cotizacion_id and self.origen.necesidad_id != self.cotizacion.necesidad_id:
            raise ValidationError("La línea de origen no pertenece a la necesidad de la cotización.")


class InvitadoCotizacion(models.Model):
    cotizacion = models.ForeignKey(Cotizacion, on_delete=models.PROTECT, related_name="invitados")
    proveedor = models.ForeignKey("proveedores.Proveedor", on_delete=models.PROTECT)
    participante_origen = models.ForeignKey(ParticipanteElegible, on_delete=models.PROTECT, null=True, blank=True)
    nit = models.CharField(max_length=25, editable=False)
    razon_social = models.CharField(max_length=200, editable=False)
    cantidad_autorizada = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True, validators=[MinValueValidator(0)])

    class Meta:
        ordering = ["razon_social", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["cotizacion", "proveedor"], name="cot_invitado_proveedor_unico"),
            models.UniqueConstraint(fields=["cotizacion", "nit"], name="cot_invitado_nit_unico"),
            models.CheckConstraint(condition=models.Q(cantidad_autorizada__isnull=True) | models.Q(cantidad_autorizada__gte=0), name="cot_invitado_cantidad_valida"),
        ]

    def clean(self):
        if self.participante_origen_id and self.cotizacion_id:
            p = self.participante_origen
            if p.lista_id != self.cotizacion.lista_elegibles_id or p.proveedor_id != self.proveedor_id:
                raise ValidationError("El participante no pertenece a la lista o proveedor de esta cotización.")


class TarifaImpuesto(models.Model):
    nombre = models.CharField(max_length=120)
    porcentaje = models.DecimalField(max_digits=7, decimal_places=4, validators=[MinValueValidator(0), MaxValueValidator(100)])
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ["porcentaje", "nombre"]
        verbose_name = "tarifa de impuesto"
        verbose_name_plural = "tarifas de impuesto"
        constraints = [
            models.UniqueConstraint(Lower("nombre"), name="oferta_tarifa_nombre_unico"),
            models.CheckConstraint(condition=models.Q(porcentaje__gte=0, porcentaje__lte=100), name="oferta_tarifa_rango"),
        ]

    def __str__(self):
        return f"{self.nombre} · {self.porcentaje} %"

    def clean(self):
        self.nombre = normalizar_espacios(self.nombre)
        if not self.nombre:
            raise ValidationError({"nombre": "El nombre es obligatorio."})
        if any(n.casefold() == self.nombre.casefold() for n in type(self).objects.exclude(pk=self.pk).values_list("nombre", flat=True)):
            raise ValidationError({"nombre": "Ya existe una tarifa con este nombre."})


class TipoRetencion(models.Model):
    nombre = models.CharField(max_length=120)
    porcentaje = models.DecimalField(max_digits=7, decimal_places=4, validators=[MinValueValidator(0), MaxValueValidator(100)])
    base_minima = models.DecimalField(max_digits=32, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)])
    base_calculo = models.CharField(max_length=25, default="base_neta", choices=[("base_neta", "Base neta después del descuento"), ("subtotal", "Subtotal bruto"), ("total_con_impuestos", "Total con impuestos")])
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ["nombre", "pk"]
        constraints = [
            models.UniqueConstraint(Lower("nombre"), name="retencion_nombre_unico"),
            models.CheckConstraint(condition=models.Q(porcentaje__gte=0, porcentaje__lte=100), name="retencion_porcentaje_valido"),
            models.CheckConstraint(condition=models.Q(base_minima__isnull=True) | models.Q(base_minima__gte=0), name="retencion_base_valida"),
            models.CheckConstraint(condition=models.Q(base_calculo__in=["base_neta", "subtotal", "total_con_impuestos"]), name="retencion_tipo_base_valido"),
        ]

    def __str__(self):
        return f"{self.nombre} · {self.porcentaje} %"

    def clean(self):
        self.nombre = normalizar_espacios(self.nombre)
        if not self.nombre:
            raise ValidationError({"nombre": "El nombre es obligatorio."})
        if any(n.casefold() == self.nombre.casefold() for n in type(self).objects.exclude(pk=self.pk).values_list("nombre", flat=True)):
            raise ValidationError({"nombre": "Ya existe una retención con este nombre."})


class OfertaProtegidaQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Use el servicio de ofertas para conservar identidad, cálculos e historial.")

    def delete(self):
        raise ValidationError("Las ofertas y su historial se conservan.")

    def bulk_create(self, *args, **kwargs):
        raise ValidationError("Use el servicio de ofertas.")

    def bulk_update(self, *args, **kwargs):
        raise ValidationError("Use el servicio de ofertas.")


class Oferta(models.Model):
    objects = OfertaProtegidaQuerySet.as_manager()
    cotizacion = models.ForeignKey(Cotizacion, on_delete=models.PROTECT, related_name="ofertas")
    proveedor = models.ForeignKey("proveedores.Proveedor", on_delete=models.PROTECT)
    invitado = models.ForeignKey(InvitadoCotizacion, on_delete=models.PROTECT)
    nit = models.CharField(max_length=25, editable=False)
    razon_social = models.CharField(max_length=200, editable=False)
    contacto_nombre = models.CharField(max_length=120)
    contacto_correo = models.EmailField(max_length=254)
    contacto_telefono = models.CharField(max_length=50)
    fecha = models.DateField(default=timezone.localdate)
    vigente_hasta = models.DateField(null=True, blank=True)
    observacion = models.TextField(blank=True)
    subtotal = models.DecimalField(max_digits=32, decimal_places=2, default=0, editable=False)
    impuesto = models.DecimalField(max_digits=32, decimal_places=2, default=0, editable=False)
    total = models.DecimalField(max_digits=32, decimal_places=2, default=0, editable=False)
    reglas_calculo = models.JSONField(default=dict, editable=False)
    pdf = models.ForeignKey("PdfOferta", on_delete=models.PROTECT, null=True, blank=True, related_name="ofertas_actuales", editable=False)
    revision = models.PositiveIntegerField(default=0, editable=False)
    registrada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    fecha_modificacion = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["cotizacion", "proveedor"], name="oferta_cotizacion_proveedor_unico"),
            models.UniqueConstraint(fields=["cotizacion", "nit"], name="oferta_cotizacion_nit_unico"),
            models.CheckConstraint(condition=models.Q(vigente_hasta__isnull=True) | models.Q(vigente_hasta__gte=models.F("fecha")), name="oferta_fechas_validas"),
            models.CheckConstraint(condition=models.Q(subtotal__gte=0, impuesto__gte=0, total__gte=0), name="oferta_totales_positivos"),
        ]

    def __str__(self):
        return f"Oferta {self.pk} · {self.razon_social}"

    def clean(self):
        if self.invitado_id and (self.invitado.cotizacion_id != self.cotizacion_id or self.invitado.proveedor_id != self.proveedor_id):
            raise ValidationError("La invitación no pertenece a esta cotización y proveedor.")
        if self.pdf_id and self.pdf.oferta_id != self.pk:
            raise ValidationError("El PDF pertenece a otra oferta.")

    def save(self, *args, **kwargs):
        from django.db import transaction
        with transaction.atomic():
            if Cotizacion.objects.select_for_update().get(pk=self.cotizacion_id).estado not in ("borrador", "en_comparacion"):
                raise ValidationError("La cotización ya no admite cambios de ofertas.")
            if self.pk:
                original = type(self).objects.get(pk=self.pk)
                if (original.cotizacion_id, original.proveedor_id, original.invitado_id) != (self.cotizacion_id, self.proveedor_id, self.invitado_id):
                    raise ValidationError("La identidad de la oferta se conserva.")
            self.clean()
            super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Las ofertas se conservan.")


class OfertaLinea(models.Model):
    objects = OfertaProtegidaQuerySet.as_manager()
    oferta = models.ForeignKey(Oferta, on_delete=models.PROTECT, related_name="lineas")
    linea = models.ForeignKey(LineaCotizacion, on_delete=models.PROTECT)
    cantidad = models.DecimalField(max_digits=14, decimal_places=3, editable=False)
    linea_datos = models.JSONField(default=dict, editable=False)
    precio_unitario = models.DecimalField(max_digits=18, decimal_places=4, validators=[MinValueValidator(0)])
    tarifa = models.ForeignKey(TarifaImpuesto, on_delete=models.PROTECT)
    tarifa_nombre = models.CharField(max_length=120, editable=False)
    porcentaje = models.DecimalField(max_digits=7, decimal_places=4, editable=False)
    subtotal = models.DecimalField(max_digits=32, decimal_places=2, editable=False)
    impuesto = models.DecimalField(max_digits=32, decimal_places=2, editable=False)
    total = models.DecimalField(max_digits=32, decimal_places=2, editable=False)

    class Meta:
        ordering = ["linea__orden", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["oferta", "linea"], name="oferta_linea_unica"),
            models.CheckConstraint(condition=models.Q(precio_unitario__gte=0, cantidad__gt=0, porcentaje__gte=0, porcentaje__lte=100), name="oferta_linea_valores_validos"),
            models.CheckConstraint(condition=models.Q(subtotal__gte=0, impuesto__gte=0, total__gte=0), name="oferta_linea_importes_validos"),
        ]

    def clean(self):
        if self.oferta_id and self.linea_id and self.oferta.cotizacion_id != self.linea.cotizacion_id:
            raise ValidationError("La línea pertenece a otra cotización.")

    def save(self, *args, **kwargs):
        from django.db import transaction
        with transaction.atomic():
            oferta = Oferta.objects.get(pk=self.oferta_id)
            if Cotizacion.objects.select_for_update().get(pk=oferta.cotizacion_id).estado not in ("borrador", "en_comparacion"):
                raise ValidationError("La cotización ya no admite cambios de ofertas.")
            if self.pk:
                original = type(self).objects.get(pk=self.pk)
                if (original.oferta_id, original.linea_id) != (self.oferta_id, self.linea_id):
                    raise ValidationError("No traslade precios a otra oferta o línea.")
            self.clean()
            super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Los precios y sus revisiones se conservan.")


class PdfOferta(models.Model):
    objects = OfertaProtegidaQuerySet.as_manager()
    oferta = models.ForeignKey(Oferta, on_delete=models.PROTECT, related_name="adjuntos")
    archivo = models.FileField(max_length=255)
    nombre_archivo = models.CharField(max_length=255)
    cargado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    fecha = models.DateTimeField(default=timezone.now)

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Los PDF anteriores se conservan. Cargue otro archivo.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Los PDF de ofertas se conservan.")


class RevisionOferta(models.Model):
    objects = OfertaProtegidaQuerySet.as_manager()
    oferta = models.ForeignKey(Oferta, on_delete=models.PROTECT, related_name="revisiones")
    numero = models.PositiveIntegerField()
    contenido = models.JSONField()
    pdf = models.ForeignKey(PdfOferta, on_delete=models.PROTECT, null=True, blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    motivo = models.TextField()
    fecha = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-numero"]
        constraints = [models.UniqueConstraint(fields=["oferta", "numero"], name="oferta_revision_unica")]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Las revisiones de ofertas se conservan.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Las revisiones de ofertas se conservan.")


class TipoVerificacion(models.Model):
    nombre = models.CharField(max_length=120)
    orden = models.PositiveSmallIntegerField(default=1)
    obligatoria = models.BooleanField(default=False)
    origen = models.CharField(max_length=12, choices=[("manual", "Revisión manual"), ("documental", "Propuesta de vigencia documental")], default="manual")
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ["orden", "nombre", "pk"]
        verbose_name = "tipo de verificación"
        verbose_name_plural = "tipos de verificación"
        constraints = [
            models.UniqueConstraint(Lower("nombre"), name="verificacion_tipo_nombre_unico"),
            models.CheckConstraint(condition=models.Q(origen__in=["manual", "documental"]), name="verificacion_origen_valido"),
        ]

    def __str__(self):
        return self.nombre

    def clean(self):
        self.nombre = normalizar_espacios(self.nombre)
        if not self.nombre:
            raise ValidationError({"nombre": "El nombre es obligatorio."})
        if any(n.casefold() == self.nombre.casefold() for n in type(self).objects.exclude(pk=self.pk).values_list("nombre", flat=True)):
            raise ValidationError({"nombre": "Ya existe un tipo con este nombre."})


class EstadoVerificacion(models.Model):
    CLASES = [("si", "Sí / cumple"), ("no", "No / no cumple"), ("pendiente", "Pendiente de verificar"), ("na", "No aplica")]
    nombre = models.CharField(max_length=80)
    clasificacion = models.CharField(max_length=12, choices=CLASES)
    orden = models.PositiveSmallIntegerField(default=1)
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ["orden", "nombre", "pk"]
        verbose_name = "estado de verificación"
        verbose_name_plural = "estados de verificación"
        constraints = [
            models.UniqueConstraint(Lower("nombre"), name="verificacion_estado_nombre_unico"),
            models.CheckConstraint(condition=models.Q(clasificacion__in=["si", "no", "pendiente", "na"]), name="verificacion_estado_clase_valida"),
        ]

    def __str__(self):
        return self.nombre

    def clean(self):
        self.nombre = normalizar_espacios(self.nombre)
        if not self.nombre:
            raise ValidationError({"nombre": "El nombre es obligatorio."})
        if any(n.casefold() == self.nombre.casefold() for n in type(self).objects.exclude(pk=self.pk).values_list("nombre", flat=True)):
            raise ValidationError({"nombre": "Ya existe un estado con este nombre."})


class VerificacionOferta(models.Model):
    objects = OfertaProtegidaQuerySet.as_manager()
    oferta = models.ForeignKey(Oferta, on_delete=models.PROTECT, related_name="verificaciones")
    tipo = models.ForeignKey(TipoVerificacion, on_delete=models.PROTECT, related_name="registros")
    estado = models.ForeignKey(EstadoVerificacion, on_delete=models.PROTECT)
    fecha = models.DateField(default=timezone.localdate)
    verificado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    observacion = models.TextField(blank=True)
    tipo_nombre = models.CharField(max_length=120, editable=False)
    tipo_obligatoria = models.BooleanField(default=False, editable=False)
    tipo_origen = models.CharField(max_length=12, editable=False)
    estado_nombre = models.CharField(max_length=80, editable=False)
    estado_clasificacion = models.CharField(max_length=12, editable=False)
    oferta_revision = models.PositiveIntegerField(editable=False)
    revision = models.PositiveIntegerField(default=0, editable=False)
    propuesta = models.JSONField(default=dict, blank=True, editable=False)
    pdf = models.ForeignKey("PdfVerificacionOferta", on_delete=models.PROTECT, null=True, blank=True, related_name="verificaciones_actuales", editable=False)
    fecha_registro = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["oferta", "tipo"], name="verificacion_oferta_tipo_unico"),
            models.CheckConstraint(condition=models.Q(estado_clasificacion__in=["si", "no", "pendiente", "na"]), name="verificacion_foto_clase_valida"),
        ]

    def clean(self):
        if self.pdf_id and self.pdf.verificacion_id != self.pk:
            raise ValidationError("La evidencia pertenece a otra verificación.")

    def save(self, *args, **kwargs):
        from django.db import transaction
        with transaction.atomic():
            oferta = Oferta.objects.get(pk=self.oferta_id)
            if Cotizacion.objects.select_for_update().get(pk=oferta.cotizacion_id).estado not in ("borrador", "en_comparacion"):
                raise ValidationError("La cotización ya no admite cambios de verificaciones.")
            if self.pk:
                original = type(self).objects.get(pk=self.pk)
                if (original.oferta_id, original.tipo_id) != (self.oferta_id, self.tipo_id):
                    raise ValidationError("No traslade una verificación a otro oferente o tipo.")
            self.clean()
            super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Las verificaciones y sus evidencias se conservan.")


class PdfVerificacionOferta(models.Model):
    objects = OfertaProtegidaQuerySet.as_manager()
    verificacion = models.ForeignKey(VerificacionOferta, on_delete=models.PROTECT, related_name="adjuntos")
    archivo = models.FileField(max_length=255)
    nombre_archivo = models.CharField(max_length=255)
    cargado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    fecha = models.DateTimeField(default=timezone.now)

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("La evidencia se conserva. Cargue otro PDF.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Las evidencias de verificaciones se conservan.")


class RevisionVerificacionOferta(models.Model):
    objects = OfertaProtegidaQuerySet.as_manager()
    verificacion = models.ForeignKey(VerificacionOferta, on_delete=models.PROTECT, related_name="revisiones")
    numero = models.PositiveIntegerField()
    contenido = models.JSONField()
    pdf = models.ForeignKey(PdfVerificacionOferta, on_delete=models.PROTECT, null=True, blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    fecha = models.DateTimeField(default=timezone.now)
    motivo = models.TextField()

    class Meta:
        ordering = ["-numero"]
        constraints = [models.UniqueConstraint(fields=["verificacion", "numero"], name="verificacion_revision_unica")]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("El historial de verificaciones se conserva.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("El historial de verificaciones se conserva.")


class CausalProveedorUnico(models.Model):
    nombre = models.CharField(max_length=120)
    descripcion = models.TextField("descripción", blank=True)
    orden = models.PositiveSmallIntegerField(default=1)
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ["orden", "nombre", "pk"]
        verbose_name = "causal de proveedor único"
        verbose_name_plural = "causales de proveedor único"
        constraints = [models.UniqueConstraint(Lower("nombre"), name="unico_causal_nombre_unico")]

    def __str__(self):
        return self.nombre

    def clean(self):
        self.nombre = normalizar_espacios(self.nombre)
        if not self.nombre:
            raise ValidationError({"nombre": "El nombre es obligatorio."})
        if any(n.casefold() == self.nombre.casefold() for n in type(self).objects.exclude(pk=self.pk).values_list("nombre", flat=True)):
            raise ValidationError({"nombre": "Ya existe una causal con este nombre."})


class PdfProveedorUnico(models.Model):
    objects = OfertaProtegidaQuerySet.as_manager()
    cotizacion = models.ForeignKey(Cotizacion, on_delete=models.PROTECT, related_name="evidencias_proveedor_unico")
    archivo = models.FileField(max_length=255)
    nombre_archivo = models.CharField(max_length=255)
    cargado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    fecha = models.DateTimeField(default=timezone.now)

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("La evidencia se conserva. Cargue otro PDF.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Las evidencias de proveedor único se conservan.")


class RevisionProveedorUnico(models.Model):
    objects = OfertaProtegidaQuerySet.as_manager()
    cotizacion = models.ForeignKey(Cotizacion, on_delete=models.PROTECT, related_name="revisiones_proveedor_unico")
    numero = models.PositiveIntegerField()
    contenido = models.JSONField()
    pdf = models.ForeignKey(PdfProveedorUnico, on_delete=models.PROTECT, null=True, blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    motivo = models.TextField()
    fecha = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-numero"]
        constraints = [models.UniqueConstraint(fields=["cotizacion", "numero"], name="unico_revision_unica")]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("El historial de proveedor único se conserva.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("El historial de proveedor único se conserva.")


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


def _contrato_editable(decision_id):
    """El llamador mantiene una transacción; se comparte el bloqueo de decisión B13."""
    cotizacion_id = DecisionCotizacion.objects.values_list("cotizacion_id", flat=True).get(pk=decision_id)
    cotizacion = Cotizacion.objects.select_for_update().get(pk=cotizacion_id)
    decision = DecisionCotizacion.objects.get(pk=decision_id)
    if decision.estado != "pendiente" or cotizacion.estado != "en_comparacion" or decision.aprobaciones.exists():
        raise ValidationError("El contrato y sus pólizas solo se modifican antes de la primera aprobación. Anule la decisión para registrar cambios.")
    if not decision.contenido["comparativo"].get("requiere_contrato", False):
        raise ValidationError("La propuesta no requiere contrato.")
    return decision


class TipoPoliza(models.Model):
    nombre = models.CharField(max_length=120)
    orden = models.PositiveSmallIntegerField(default=1)
    activo = models.BooleanField(default=True)
    dias_alerta = models.PositiveSmallIntegerField("días de alerta particulares", null=True, blank=True)

    class Meta:
        ordering = ["orden", "nombre", "pk"]
        constraints = [models.UniqueConstraint(Lower("nombre"), name="poliza_tipo_nombre_unico")]

    def __str__(self):
        return self.nombre

    @property
    def usar_alerta_general(self):
        return self.dias_alerta is None

    def clean(self):
        self.nombre = normalizar_espacios(self.nombre)
        if not self.nombre:
            raise ValidationError({"nombre": "El nombre es obligatorio."})
        if any(n.casefold() == self.nombre.casefold() for n in type(self).objects.exclude(pk=self.pk).values_list("nombre", flat=True)):
            raise ValidationError({"nombre": "Ya existe un tipo con este nombre."})


class Contrato(models.Model):
    objects = OfertaProtegidaQuerySet.as_manager()
    decision = models.OneToOneField(DecisionCotizacion, on_delete=models.PROTECT, related_name="contrato")
    numero = models.CharField("número", max_length=120, blank=True)
    supervisor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True)
    supervisor_texto = models.CharField("supervisor por texto", max_length=255, blank=True)
    supervisor_nombre = models.CharField(max_length=450, blank=True, editable=False)
    cargo = models.CharField(max_length=150, blank=True)
    fecha_inicio = models.DateField(null=True, blank=True)
    fecha_fin = models.DateField(null=True, blank=True)
    forma_pago = models.TextField("forma de pago", blank=True)
    valor = models.DecimalField(max_digits=32, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)])
    pdf = models.ForeignKey("PdfContractual", on_delete=models.PROTECT, null=True, blank=True, related_name="contratos_actuales", editable=False)
    revision = models.PositiveIntegerField(default=0, editable=False)

    def clean(self):
        if self.supervisor_id and self.supervisor_texto.strip():
            raise ValidationError("Indique supervisor por usuario o por texto, sin mezclar ambas opciones.")
        if self.fecha_inicio and self.fecha_fin and self.fecha_fin < self.fecha_inicio:
            raise ValidationError({"fecha_fin": "El fin no puede ser anterior al inicio."})
        if self.pdf_id and (self.pdf.contrato_id != self.pk or self.pdf.poliza_id is not None):
            raise ValidationError("La evidencia no pertenece al contrato.")

    def save(self, *args, **kwargs):
        from django.db import transaction
        with transaction.atomic():
            _contrato_editable(self.decision_id)
            if self.pk and type(self).objects.get(pk=self.pk).decision_id != self.decision_id:
                raise ValidationError("No traslade contratos entre decisiones.")
            self.clean()
            super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Los contratos y sus evidencias se conservan.")


class Poliza(models.Model):
    objects = OfertaProtegidaQuerySet.as_manager()
    contrato = models.ForeignKey(Contrato, on_delete=models.PROTECT, related_name="polizas")
    tipo = models.ForeignKey(TipoPoliza, on_delete=models.PROTECT, null=True, blank=True)
    tipo_nombre = models.CharField(max_length=120, blank=True, editable=False)
    aseguradora = models.CharField(max_length=200, blank=True)
    numero = models.CharField("número", max_length=120, blank=True)
    valor_asegurado = models.DecimalField(max_digits=32, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)])
    vigencia_desde = models.DateField(null=True, blank=True)
    vigencia_hasta = models.DateField(null=True, blank=True)
    pdf = models.ForeignKey("PdfContractual", on_delete=models.PROTECT, null=True, blank=True, related_name="polizas_actuales", editable=False)
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ["pk"]

    def clean(self):
        if self.vigencia_desde and self.vigencia_hasta and self.vigencia_hasta < self.vigencia_desde:
            raise ValidationError({"vigencia_hasta": "El vencimiento no puede ser anterior al inicio."})
        if self.pdf_id and (self.pdf.poliza_id != self.pk or self.pdf.contrato_id != self.contrato_id):
            raise ValidationError("La evidencia no pertenece a esta póliza y contrato.")

    def save(self, *args, **kwargs):
        from django.db import transaction
        with transaction.atomic():
            _contrato_editable(self.contrato.decision_id)
            if self.pk and type(self).objects.get(pk=self.pk).contrato_id != self.contrato_id:
                raise ValidationError("No traslade pólizas entre contratos.")
            self.clean()
            super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Desactive la póliza con motivo; su historial se conserva.")


class PdfContractual(models.Model):
    objects = OfertaProtegidaQuerySet.as_manager()
    contrato = models.ForeignKey(Contrato, on_delete=models.PROTECT, related_name="adjuntos")
    poliza = models.ForeignKey(Poliza, on_delete=models.PROTECT, null=True, blank=True, related_name="adjuntos")
    archivo = models.FileField(max_length=255)
    nombre_archivo = models.CharField(max_length=255)
    cargado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    fecha = models.DateTimeField(default=timezone.now)

    def clean(self):
        if self.poliza_id and self.poliza.contrato_id != self.contrato_id:
            raise ValidationError("La póliza no pertenece al contrato indicado.")

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Las evidencias contractuales se conservan.")
        self.clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Las evidencias contractuales se conservan.")


class RevisionContrato(models.Model):
    objects = OfertaProtegidaQuerySet.as_manager()
    contrato = models.ForeignKey(Contrato, on_delete=models.PROTECT, related_name="revisiones")
    numero = models.PositiveIntegerField()
    contenido = models.JSONField()
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    motivo = models.TextField()
    fecha = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-numero"]
        constraints = [models.UniqueConstraint(fields=["contrato", "numero"], name="contrato_revision_unica")]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Las revisiones del contrato se conservan.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Las revisiones del contrato se conservan.")


class OrdenCompra(models.Model):
    objects = OfertaProtegidaQuerySet.as_manager()
    decision = models.ForeignKey(DecisionCotizacion, on_delete=models.PROTECT, related_name="ordenes")
    cotizacion = models.ForeignKey(Cotizacion, on_delete=models.PROTECT, related_name="ordenes")
    proveedor = models.ForeignKey("proveedores.Proveedor", on_delete=models.PROTECT, related_name="ordenes")
    evaluacion_origen = models.ForeignKey("proveedores.EvaluacionProveedor", on_delete=models.PROTECT, null=True, blank=True)
    nit = models.CharField(max_length=25, editable=False)
    razon_social = models.CharField(max_length=200, editable=False)
    condiciones_pago = models.TextField(blank=True)
    fecha_elaboracion = models.DateField(default=timezone.localdate)
    elaborada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    fecha_creacion = models.DateTimeField(default=timezone.now, editable=False)
    numero = models.PositiveBigIntegerField(null=True, blank=True, editable=False)
    consecutivo = models.CharField(max_length=100, unique=True, null=True, blank=True, editable=False)
    anio_consecutivo = models.PositiveSmallIntegerField(null=True, blank=True, editable=False)
    serie_consecutivo = models.CharField(max_length=16, blank=True, editable=False)
    reglas_consecutivo = models.JSONField(default=dict, blank=True, editable=False)
    fecha_emision = models.DateTimeField(null=True, blank=True, editable=False)
    emitida_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="ordenes_emitidas")
    fecha_vencimiento = models.DateField(null=True, blank=True)
    fecha_esperada_entrega = models.DateField(null=True, blank=True)
    etiqueta_vencimiento = models.CharField(max_length=80, blank=True, editable=False)
    anulada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="ordenes_anuladas")
    fecha_anulacion = models.DateTimeField(null=True, blank=True, editable=False)
    motivo_anulacion = models.TextField(blank=True, editable=False)
    estado = models.CharField(max_length=20, default="borrador", editable=False, choices=[
        ("borrador", "Borrador"), ("en_aprobacion", "En aprobación"), ("emitida", "Emitida"), ("anulada", "Anulada"),
        ("recibida_parcial", "Recibida parcial"), ("recibida_total", "Recibida total"), ("cerrada", "Cerrada")])
    subtotal = models.DecimalField(max_digits=32, decimal_places=2, default=0, editable=False)
    descuento = models.DecimalField(max_digits=32, decimal_places=2, default=0, editable=False)
    impuesto = models.DecimalField(max_digits=32, decimal_places=2, default=0, editable=False)
    total = models.DecimalField(max_digits=32, decimal_places=2, default=0, editable=False)
    origen_datos = models.JSONField(editable=False)
    base = models.DecimalField(max_digits=32, decimal_places=2, default=0, editable=False)
    total_sin_retenciones = models.DecimalField(max_digits=32, decimal_places=2, default=0, editable=False)
    retencion = models.DecimalField(max_digits=32, decimal_places=2, default=0, editable=False)
    retenciones_aplicadas = models.JSONField(default=list, blank=True, editable=False)
    reglas_importes = models.JSONField(default=dict, blank=True, editable=False)
    calculo_emision = models.JSONField(default=dict, blank=True, editable=False)
    documento_emision = models.JSONField(default=dict, blank=True, editable=False)
    ciclo_aprobacion = models.PositiveIntegerField(default=0, editable=False)
    revision = models.PositiveIntegerField(default=0, editable=False)

    class Meta:
        ordering = ["-fecha_elaboracion", "-pk"]
        constraints = [
            models.UniqueConstraint(fields=["decision", "proveedor"], name="orden_decision_proveedor_unica"),
            models.UniqueConstraint(fields=["serie_consecutivo", "numero"], condition=models.Q(numero__isnull=False), name="orden_numero_serie_unico"),
            models.CheckConstraint(condition=(
                models.Q(numero__isnull=True, consecutivo__isnull=True, anio_consecutivo__isnull=True, fecha_emision__isnull=True, emitida_por__isnull=True, serie_consecutivo="")
                | (models.Q(numero__isnull=False, numero__gte=1, consecutivo__isnull=False, anio_consecutivo__isnull=False, anio_consecutivo__gte=1, fecha_emision__isnull=False, emitida_por__isnull=False)
                   & ~models.Q(serie_consecutivo="") & ~models.Q(consecutivo=""))
            ), name="orden_numeracion_completa"),
            models.CheckConstraint(condition=models.Q(estado__in=["borrador", "en_aprobacion", "emitida", "anulada", "recibida_parcial", "recibida_total", "cerrada"]), name="orden_estado_valido"),
            models.CheckConstraint(condition=models.Q(subtotal__gte=0, descuento__gte=0, impuesto__gte=0, total__gte=0), name="orden_importes_no_negativos"),
            models.CheckConstraint(condition=models.Q(base__gte=0, retencion__gte=0, total_sin_retenciones__gte=0, retencion__lte=models.F("total_sin_retenciones")), name="orden_retencion_valida"),
        ]

    def __str__(self):
        return f"{self.consecutivo or ('Orden ' + str(self.pk or 'nueva'))} · {self.razon_social}"

    def clean(self):
        if self.fecha_vencimiento and self.fecha_elaboracion and self.fecha_vencimiento < self.fecha_elaboracion:
            raise ValidationError({"fecha_vencimiento": "La fecha no puede ser anterior a la elaboración."})
        if self.fecha_esperada_entrega and self.fecha_esperada_entrega < self.fecha_elaboracion:
            raise ValidationError({"fecha_esperada_entrega": "La entrega esperada no puede preceder a la elaboración."})
        if self.decision.cotizacion_id != self.cotizacion_id:
            raise ValidationError("La decisión no corresponde a la cotización indicada.")
        if not self.decision.adjudicaciones.filter(oferta__proveedor_id=self.proveedor_id).exists():
            raise ValidationError("El proveedor no tiene adjudicaciones en esta decisión.")
        if self.evaluacion_origen_id and self.evaluacion_origen.proveedor_id != self.proveedor_id:
            raise ValidationError("La evaluación de origen pertenece a otro proveedor.")

    def save(self, *args, **kwargs):
        from django.db import transaction
        with transaction.atomic():
            cotizacion = Cotizacion.objects.select_for_update().get(pk=self.cotizacion_id)
            decision = DecisionCotizacion.objects.get(pk=self.decision_id)
            if decision.estado != "aprobada" or cotizacion.estado != "decidida":
                raise ValidationError("La orden requiere una decisión aprobada y cotización decidida.")
            if not self._state.adding:
                anterior = type(self).objects.get(pk=self.pk)
                emision = anterior.estado == "en_aprobacion" and self.estado == "emitida" and anterior.numero is None and self.numero is not None
                anulacion = anterior.estado in ("borrador", "en_aprobacion", "emitida") and self.estado == "anulada" and self.anulada_por_id and self.fecha_anulacion and self.motivo_anulacion.strip()
                operacion = getattr(self, "_operacion_flujo", False)
                if emision and not getattr(self, "_numeracion_autorizada", False):
                    raise ValidationError("Use el servicio de emisión con sus aprobaciones completas.")
                if anterior.estado != "borrador" and not (emision or anulacion or operacion):
                    raise ValidationError("Solo puede editar un borrador o registrar una transición de emisión/anulación.")
                numeracion = ("numero", "consecutivo", "anio_consecutivo", "serie_consecutivo", "reglas_consecutivo", "fecha_emision", "emitida_por_id", "etiqueta_vencimiento", "calculo_emision", "documento_emision")
                if not emision and any(getattr(anterior, c) != getattr(self, c) for c in numeracion):
                    raise ValidationError("El número se asigna al emitir y sus datos nunca se reescriben.")
                retorno_emitida = operacion and anterior.estado in ("recibida_parcial", "recibida_total", "cerrada") and self.numero is not None
                if self.estado == "emitida" and anterior.estado != "emitida" and not (emision or retorno_emitida):
                    raise ValidationError("Use el servicio de numeración desde una orden En aprobación.")
                if anterior.estado != "borrador":
                    for campo in ("condiciones_pago", "fecha_elaboracion", "fecha_vencimiento", "fecha_esperada_entrega", "subtotal", "descuento", "impuesto", "total", "base", "total_sin_retenciones", "retencion", "retenciones_aplicadas", "reglas_importes"):
                        if getattr(anterior, campo) != getattr(self, campo):
                            raise ValidationError("Los datos comerciales se conservan al emitir o anular.")
                for campo in ("decision_id", "cotizacion_id", "proveedor_id", "evaluacion_origen_id", "nit", "razon_social", "elaborada_por_id", "fecha_creacion", "origen_datos"):
                    if getattr(anterior, campo) != getattr(self, campo):
                        raise ValidationError("La identidad y foto de origen de la orden se conservan.")
            elif self.estado != "borrador" or self.numero is not None or self.consecutivo is not None:
                raise ValidationError("Las órdenes se crean en borrador.")
            self.clean()
            super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Las órdenes y su historial se conservan.")


class OrdenLinea(models.Model):
    objects = OfertaProtegidaQuerySet.as_manager()
    orden = models.ForeignKey(OrdenCompra, on_delete=models.PROTECT, related_name="lineas")
    oferta_linea = models.ForeignKey(OfertaLinea, on_delete=models.PROTECT)
    proyeccion_origen = models.ForeignKey("proyecciones.Linea", on_delete=models.PROTECT, null=True, blank=True)
    posicion = models.PositiveIntegerField()
    referencia = models.CharField(max_length=120, blank=True)
    descripcion = models.CharField("descripción", max_length=255)
    especificacion = models.TextField("especificación", blank=True)
    unidad = models.CharField(max_length=120)
    cantidad = models.DecimalField(max_digits=14, decimal_places=3, validators=[MinValueValidator(Decimal("0.001"))])
    precio_unitario = models.DecimalField(max_digits=18, decimal_places=4, validators=[MinValueValidator(0)])
    tarifa_nombre = models.CharField(max_length=120, editable=False)
    porcentaje = models.DecimalField(max_digits=7, decimal_places=4, editable=False)
    descuento = models.DecimalField(max_digits=32, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    descuento_aplicado = models.DecimalField(max_digits=32, decimal_places=2, default=0, editable=False)
    base = models.DecimalField(max_digits=32, decimal_places=2, default=0, editable=False)
    base_impuesto = models.DecimalField(max_digits=32, decimal_places=2, default=0, editable=False)
    desglose_calculo = models.JSONField(default=dict, blank=True, editable=False)
    subtotal = models.DecimalField(max_digits=32, decimal_places=2, editable=False)
    impuesto = models.DecimalField(max_digits=32, decimal_places=2, editable=False)
    total = models.DecimalField(max_digits=32, decimal_places=2, editable=False)
    reglas_calculo = models.JSONField(editable=False)
    original = models.JSONField(editable=False)
    modificada = models.BooleanField(default=False, editable=False)
    cambios = models.JSONField(default=dict, blank=True, editable=False)

    class Meta:
        ordering = ["posicion", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["orden", "posicion"], name="orden_linea_posicion_unica"),
            models.UniqueConstraint(fields=["orden", "oferta_linea"], name="orden_precio_origen_unico"),
            models.CheckConstraint(condition=models.Q(cantidad__gt=0, precio_unitario__gte=0, porcentaje__gte=0, porcentaje__lte=100), name="orden_linea_valores_validos"),
            models.CheckConstraint(condition=models.Q(subtotal__gte=0, descuento__gte=0, impuesto__gte=0, total__gte=0), name="orden_linea_importes_validos"),
            models.CheckConstraint(condition=models.Q(base__gte=0, base_impuesto__gte=0, descuento_aplicado__gte=0, descuento_aplicado__lte=models.F("subtotal")), name="orden_linea_base_valida"),
        ]

    def clean(self):
        origen = self.oferta_linea
        if origen.oferta.cotizacion_id != self.orden.cotizacion_id or origen.oferta.proveedor_id != self.orden.proveedor_id or not self.orden.decision.adjudicaciones.filter(oferta_linea=origen).exists():
            raise ValidationError("La línea de oferta no fue adjudicada al proveedor de esta orden.")
        if self.proyeccion_origen_id and not OrigenNecesidad.objects.filter(necesidad_id=self.orden.cotizacion.necesidad_id, linea_id=self.proyeccion_origen_id).exists():
            raise ValidationError("La proyección no corresponde a la necesidad de origen.")

    def save(self, *args, **kwargs):
        from django.db import transaction
        with transaction.atomic():
            Cotizacion.objects.select_for_update().get(pk=self.orden.cotizacion_id)
            actual = OrdenCompra.objects.select_related("decision", "cotizacion").get(pk=self.orden_id)
            if actual.estado != "borrador" or actual.decision.estado != "aprobada" or actual.cotizacion.estado != "decidida":
                raise ValidationError("Solo se modifican líneas de una orden en borrador con decisión vigente.")
            if self.pk:
                anterior = type(self).objects.get(pk=self.pk)
                for campo in ("orden_id", "oferta_linea_id", "proyeccion_origen_id", "posicion", "original"):
                    if getattr(anterior, campo) != getattr(self, campo):
                        raise ValidationError("El origen, tarifa y reglas copiadas de la línea se conservan.")
            self.clean()
            super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Las líneas adjudicadas y sus cambios se conservan.")


class RevisionOrdenCompra(models.Model):
    objects = OfertaProtegidaQuerySet.as_manager()
    orden = models.ForeignKey(OrdenCompra, on_delete=models.PROTECT, related_name="revisiones")
    numero = models.PositiveIntegerField()
    contenido = models.JSONField()
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    motivo = models.TextField()
    fecha = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-numero"]
        constraints = [models.UniqueConstraint(fields=["orden", "numero"], name="orden_revision_unica")]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Las revisiones de órdenes se conservan.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Las revisiones de órdenes se conservan.")


class ContadorOrdenCompra(models.Model):
    objects = OfertaProtegidaQuerySet.as_manager()
    clave = models.CharField(max_length=16, primary_key=True)
    ultimo = models.PositiveBigIntegerField(default=0)

    def save(self, *args, **kwargs):
        from django.db import transaction
        with transaction.atomic():
            anterior = type(self).objects.select_for_update().filter(pk=self.pk).first()
            if anterior and self.ultimo < anterior.ultimo:
                raise ValidationError("El contador nunca puede retroceder ni reutilizar números.")
            super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Los contadores de órdenes se conservan.")


from compras.operacion_models import AprobacionOrden, EvidenciaEnvioOrden, ReglaAprobacionOrden, SolicitudAprobacionOrden
from compras.operacion_models import Recepcion, RecepcionLinea
