"""Modelos del área: ofertas."""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone
from config.utilidades import normalizar_espacios
from compras.modelos.comunes import OfertaProtegidaQuerySet
from compras.modelos.cotizaciones import Cotizacion, InvitadoCotizacion, LineaCotizacion


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
