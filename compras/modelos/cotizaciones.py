"""Modelos del área: cotizaciones."""
from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone
from config.utilidades import normalizar_espacios
from compras.modelos.elegibles import CierreListaElegibles, ListaElegibles, ParticipanteElegible
from compras.modelos.necesidades import Necesidad, OrigenNecesidad


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
            from compras.modelos.decisiones import AprobacionCotizacion
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
