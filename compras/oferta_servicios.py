"""Una oferta vigente por proveedor; cada guardado conserva una revisión."""
from decimal import Decimal, localcontext

from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.utils import timezone

from bitacora.servicios import guardar_con_bitacora, instantanea, registrar
from compras.cotizacion_servicios import limites_actuales
from compras.importes import calcular_importes, decimal_valido
from compras.models import Cotizacion, InvitadoCotizacion, LineaCotizacion, Oferta, OfertaLinea, PdfOferta, RevisionOferta, TarifaImpuesto
from parametros.catalogo import DECIMALES_OFERTA, MAX_OFERENTES_COTIZACION, REDONDEO_OFERTA, validar_decimales_oferta, validar_redondeo_oferta
from parametros.models import Parametro
from parametros.servicios import obtener
from proveedores import archivos
from proveedores.models import Proveedor
from proveedores.servicios import _exigir_admin, _exigir_motivo

CAMPOS = ["cotizacion", "proveedor", "invitado", "nit", "razon_social", "contacto_nombre", "contacto_correo", "contacto_telefono",
          "fecha", "vigente_hasta", "observacion", "subtotal", "impuesto", "total", "reglas_calculo", "pdf", "revision", "registrada_por", "fecha_modificacion"]
CAMPOS_LINEA = ["oferta", "linea", "linea_datos", "cantidad", "precio_unitario", "tarifa", "tarifa_nombre", "porcentaje", "subtotal", "impuesto", "total"]


def reglas_actuales():
    return {"decimales": validar_decimales_oferta(obtener(DECIMALES_OFERTA)),
            "modo": validar_redondeo_oferta(obtener(REDONDEO_OFERTA)), "pendiente": True}


@transaction.atomic
def guardar_tarifa(tarifa, *, actor, motivo):
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    tarifa.porcentaje = decimal_valido(tarifa.porcentaje)
    tarifa.full_clean()
    guardar_con_bitacora(tarifa, ["nombre", "porcentaje", "activo"], accion_crear="oferta.tarifa_creada", accion_modificar="oferta.tarifa_modificada", actor=actor, motivo=motivo)
    return tarifa


@transaction.atomic
def invitar_proveedor(cotizacion, proveedor, *, actor, motivo):
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    cotizacion = Cotizacion.objects.select_for_update().get(pk=cotizacion.pk)
    if cotizacion.estado not in ("borrador", "en_comparacion"):
        raise ValidationError("La cotización ya no admite invitados ni ofertas.")
    proveedor = Proveedor.objects.select_for_update().get(pk=proveedor.pk)
    if not proveedor.activo:
        raise ValidationError("Seleccione un proveedor activo registrado.")
    if cotizacion.invitados.filter(proveedor=proveedor).exists():
        raise ValidationError("El proveedor ya está invitado.")
    foto = None
    if cotizacion.lista_elegibles_id:
        foto = next((f for f in cotizacion.lista_elegibles.resultado_cierre["filas"] if f["elegido"] and f["proveedor_id"] == proveedor.pk), None)
        if foto is None:
            raise ValidationError("Esta cotización conserva los proveedores elegidos de su lista cerrada.")
    list(Parametro.objects.select_for_update().filter(clave=MAX_OFERENTES_COTIZACION))
    limite = limites_actuales()["oferentes"]
    if limite and cotizacion.invitados.count() >= limite:
        raise ValidationError("Se alcanzó el límite D-10 actual de proveedores invitados.")
    invitado = InvitadoCotizacion(cotizacion=cotizacion, proveedor=proveedor, nit=foto["nit"] if foto else proveedor.nit,
        razon_social=foto["razon_social"] if foto else proveedor.razon_social,
        participante_origen_id=foto["participante_id"] if foto else None,
        cantidad_autorizada=Decimal(foto["cantidad_autorizada"]) if foto else None)
    invitado.full_clean()
    invitado.save()
    registrar("cotizacion.invitado_agregado", actor=actor, objeto=invitado,
        nuevo=instantanea(invitado, ["cotizacion", "proveedor", "nit", "razon_social", "participante_origen", "cantidad_autorizada"]), motivo=motivo)
    return invitado


def _contenido(oferta):
    return {"nit": oferta.nit, "razon_social": oferta.razon_social, "contacto_nombre": oferta.contacto_nombre,
        "contacto_correo": oferta.contacto_correo, "contacto_telefono": oferta.contacto_telefono,
        "fecha": oferta.fecha.isoformat(), "vigente_hasta": oferta.vigente_hasta.isoformat() if oferta.vigente_hasta else None,
        "observacion": oferta.observacion, "reglas": oferta.reglas_calculo,
        "subtotal": str(oferta.subtotal), "impuesto": str(oferta.impuesto), "total": str(oferta.total),
        "lineas": [{"linea_id": l.linea_id, "especificacion": l.linea_datos, "cantidad": str(l.cantidad),
                    "precio_unitario": str(l.precio_unitario), "tarifa": l.tarifa_nombre, "porcentaje": str(l.porcentaje),
                    "subtotal": str(l.subtotal), "impuesto": str(l.impuesto), "total": str(l.total)} for l in oferta.lineas.all()]}


def guardar_oferta(cotizacion, invitado, *, contacto_nombre, contacto_correo, contacto_telefono, fecha, vigente_hasta=None,
                   observacion="", precios, archivo=None, quitar_pdf=False, revision_esperada=None, actor, motivo):
    _exigir_admin(actor)
    _exigir_motivo(motivo)
    if archivo is not None:
        archivos.validar_pdf(archivo)
        if any(not getattr(b, "_from_testcase", False) for b in connection.atomic_blocks):
            raise ValidationError("Cargue el PDF fuera de una transacción externa.")
    if archivo is not None and quitar_pdf:
        raise ValidationError("Elija cargar un PDF o retirar el actual, no ambas acciones.")
    ruta = ""
    try:
        with transaction.atomic(durable=archivo is not None):
            cotizacion = Cotizacion.objects.select_for_update().get(pk=cotizacion.pk)
            if cotizacion.estado not in ("borrador", "en_comparacion"):
                raise ValidationError("La cotización ya no admite cambios de ofertas.")
            invitado = InvitadoCotizacion.objects.filter(pk=invitado.pk, cotizacion=cotizacion).first()
            if invitado is None:
                raise ValidationError("La invitación pertenece a otra cotización.")
            proveedor = Proveedor.objects.select_for_update().get(pk=invitado.proveedor_id)
            if not proveedor.activo:
                raise ValidationError("El proveedor está inactivo.")
            oferta = Oferta.objects.select_for_update().filter(cotizacion=cotizacion, proveedor=proveedor).first()
            if revision_esperada is not None and revision_esperada != (oferta.revision if oferta else 0):
                raise ValidationError("La oferta cambió desde que abrió el formulario. Recargue antes de guardar.")
            anterior = instantanea(oferta, CAMPOS) if oferta else None
            lineas = {l.pk: l for l in cotizacion.lineas.all()}
            ids = [d["linea"].pk if isinstance(d["linea"], LineaCotizacion) else d["linea"] for d in precios]
            if not lineas or len(ids) != len(set(ids)) or set(ids) != set(lineas):
                raise ValidationError("Registre cada línea de esta cotización exactamente una vez; no mezcle líneas de otra.")
            list(Parametro.objects.select_for_update().filter(clave__in=[DECIMALES_OFERTA, REDONDEO_OFERTA]).order_by("pk"))
            reglas = reglas_actuales()
            calculadas = []
            for dato, pk in zip(precios, ids):
                tarifa_id = dato["tarifa"].pk if isinstance(dato["tarifa"], TarifaImpuesto) else dato["tarifa"]
                tarifa = TarifaImpuesto.objects.select_for_update().filter(pk=tarifa_id, activo=True).first()
                if tarifa is None:
                    raise ValidationError("Seleccione una tarifa activa para cada línea.")
                precio = decimal_valido(dato["precio_unitario"])
                precio = OfertaLinea._meta.get_field("precio_unitario").clean(precio, None)
                calculadas.append({"linea": lineas[pk], "tarifa": tarifa, "precio": precio,
                    **calcular_importes(lineas[pk].cantidad, precio, tarifa.porcentaje, reglas)})
            oferta = oferta or Oferta(cotizacion=cotizacion, proveedor=proveedor, invitado=invitado,
                nit=invitado.nit, razon_social=invitado.razon_social)
            oferta.contacto_nombre = contacto_nombre.strip()
            oferta.contacto_correo = contacto_correo.strip().lower()
            oferta.contacto_telefono = contacto_telefono.strip()
            oferta.fecha, oferta.vigente_hasta, oferta.observacion = fecha, vigente_hasta, observacion.strip()
            oferta.reglas_calculo = reglas
            with localcontext() as contexto:
                contexto.prec = 50
                oferta.subtotal = sum((d["subtotal"] for d in calculadas), Decimal(0))
                oferta.impuesto = sum((d["impuesto"] for d in calculadas), Decimal(0))
                oferta.total = oferta.subtotal + oferta.impuesto
            oferta.revision += 1
            oferta.registrada_por, oferta.fecha_modificacion = actor, timezone.now()
            if quitar_pdf:
                oferta.pdf = None
            oferta.full_clean()
            oferta.save()
            for dato in calculadas:
                linea, tarifa = dato["linea"], dato["tarifa"]
                precio = OfertaLinea.objects.filter(oferta=oferta, linea=linea).first() or OfertaLinea(oferta=oferta, linea=linea)
                precio.cantidad, precio.precio_unitario = linea.cantidad, dato["precio"]
                precio.linea_datos = {"descripcion": linea.descripcion, "unidad": linea.unidad_texto, "especificacion": linea.especificacion}
                precio.tarifa, precio.tarifa_nombre, precio.porcentaje = tarifa, tarifa.nombre, tarifa.porcentaje
                precio.subtotal, precio.impuesto, precio.total = dato["subtotal"], dato["impuesto"], dato["total"]
                precio.full_clean()
                guardar_con_bitacora(precio, CAMPOS_LINEA, accion_crear="oferta.precio_creado", accion_modificar="oferta.precio_modificado", actor=actor, motivo=motivo)
            if archivo is not None:
                ruta = archivos.guardar_pdf(archivo, carpeta="ofertas")
                adjunto = PdfOferta(oferta=oferta, archivo=ruta, nombre_archivo=archivos.nombre_original(archivo), cargado_por=actor)
                adjunto.full_clean()
                adjunto.save()
                oferta.pdf = adjunto
                oferta.full_clean()
                oferta.save()
                registrar("oferta.pdf_cargado", actor=actor, objeto=adjunto,
                    nuevo=instantanea(adjunto, ["oferta", "nombre_archivo", "cargado_por", "fecha"]), motivo=motivo)
            revision = RevisionOferta(oferta=oferta, numero=oferta.revision, contenido=_contenido(oferta), pdf=oferta.pdf, actor=actor, motivo=motivo.strip())
            revision.full_clean()
            revision.save()
            registrar("oferta.creada" if anterior is None else "oferta.modificada", actor=actor, objeto=oferta,
                      anterior=anterior, nuevo=instantanea(oferta, CAMPOS), motivo=motivo)
    except BaseException:
        archivos.borrar_ahora(ruta)
        raise
    return oferta
