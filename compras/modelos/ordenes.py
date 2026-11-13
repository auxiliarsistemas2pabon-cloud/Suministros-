"""Modelos del área: ordenes."""
from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone
from compras.modelos.comunes import OfertaProtegidaQuerySet
from compras.modelos.cotizaciones import Cotizacion
from compras.modelos.decisiones import DecisionCotizacion
from compras.modelos.necesidades import OrigenNecesidad
from compras.modelos.ofertas import OfertaLinea


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
