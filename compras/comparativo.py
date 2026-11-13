"""Comparación homogénea con importes guardados, sin recalcular tarifas actuales."""
from copy import deepcopy
from decimal import Decimal
import hashlib
import json

from django.core.serializers.json import DjangoJSONEncoder

from compras.verificacion_servicios import matriz_verificaciones
from proveedores.servicios import _exigir_admin


def huella(datos):
    return hashlib.sha256(json.dumps(datos, sort_keys=True, cls=DjangoJSONEncoder, separators=(",", ":")).encode()).hexdigest()


def construir(cotizacion, *, actor):
    _exigir_admin(actor)
    matriz = matriz_verificaciones(cotizacion)
    verificacion = {f["oferta"].pk: f for f in matriz["filas"]}
    elegibles = {f["proveedor_id"]: f for f in cotizacion.cierre_origen.contenido.get("resultado", {}).get("filas", [])} if cotizacion.cierre_origen_id else {}
    ofertas = list(cotizacion.ofertas.prefetch_related("lineas").order_by("nit", "pk"))
    precios = {(o.pk, p.linea_id): p for o in ofertas for p in o.lineas.all()}
    columnas = []
    for o in ofertas:
        controles = []
        for celda in verificacion[o.pk]["celdas"]:
            tipo, registro = celda["tipo"], celda["registro"]
            controles.append({"tipo_id": tipo.pk, "tipo": tipo.nombre, "activo": tipo.activo, "obligatoria": tipo.obligatoria,
                "clasificacion": celda["clasificacion"], "alerta": celda["alerta"], "desactualizada": celda["desactualizada"],
                "registro_id": registro.pk if registro else None, "revision": registro.revision if registro else 0,
                "estado": registro.estado_nombre if registro else "Pendiente", "fecha": registro.fecha if registro else None,
                "usuario": str(registro.verificado_por) if registro else "", "pdf_id": registro.pdf_id if registro else None,
                "observacion": registro.observacion if registro else "", "propuesta_confirmada": deepcopy(registro.propuesta) if registro else {}})
        origen = elegibles.get(o.proveedor_id)
        columnas.append({"id": o.pk, "proveedor_id": o.proveedor_id, "nit": o.nit, "razon_social": o.razon_social,
            "revision": o.revision, "fecha": o.fecha, "vigente_hasta": o.vigente_hasta, "subtotal": o.subtotal,
            "impuesto": o.impuesto, "total": o.total, "pdf_id": o.pdf_id, "reglas_calculo": deepcopy(o.reglas_calculo),
            "verificaciones": controles, "alertas": sum(c["alerta"] for c in controles),
            "elegibles": {k: origen.get(k) for k in ("total", "maximo", "puesto", "completo", "cantidad_autorizada")} if origen else None})
    filas = []
    for linea in cotizacion.lineas.order_by("orden", "pk"):
        disponibles = [precios[(o.pk, linea.pk)].total for o in ofertas if (o.pk, linea.pk) in precios]
        minimo = min(disponibles) if disponibles else None
        celdas = []
        for o in ofertas:
            precio = precios.get((o.pk, linea.pk))
            celdas.append({"oferta_id": o.pk, "oferta_linea_id": precio.pk if precio else None,
                "precio_unitario": precio.precio_unitario if precio else None,
                "subtotal": precio.subtotal if precio else None, "impuesto": precio.impuesto if precio else None,
                "total": precio.total if precio else None, "porcentaje": precio.porcentaje if precio else None,
                "tarifa": precio.tarifa_nombre if precio else "", "menor": bool(precio and precio.total == minimo)})
        filas.append({"id": linea.pk, "orden": linea.orden, "descripcion": linea.descripcion, "cantidad": linea.cantidad,
            "unidad": linea.unidad_texto, "especificacion": linea.especificacion, "minimo": minimo, "celdas": celdas})
    minimo_total = min((o.total for o in ofertas), default=None)
    for o in columnas:
        o["menor_total"] = Decimal(o["total"]) == minimo_total
    datos = {"cotizacion_id": cotizacion.pk, "consecutivo": cotizacion.consecutivo, "objeto": cotizacion.objeto,
        "fecha": cotizacion.fecha, "area": str(cotizacion.area),
        "cierre_origen_id": cotizacion.cierre_origen_id, "ofertas": columnas, "filas": filas,
        "minimo_total": minimo_total, "revision_unico": cotizacion.revision_proveedor_unico}
    # Omisión en No conserva la firma de propuestas previas a B14.
    if cotizacion.requiere_contrato:
        datos["requiere_contrato"] = True
    return json.loads(json.dumps(datos, cls=DjangoJSONEncoder))
