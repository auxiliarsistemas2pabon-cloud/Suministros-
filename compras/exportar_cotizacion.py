from decimal import Decimal
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import PatternFill

from compras.exportar_elegibles import _fila

MENOR = PatternFill("solid", fgColor="DBEAFE")


def exportar(datos, decision=None):
    libro = Workbook()
    hoja = libro.active
    hoja.title = "Comparativo"
    _fila(hoja, 1, [datos["consecutivo"], datos["objeto"]])
    _fila(hoja, 2, ["Menor costo = total con impuestos; empates resaltados en azul claro."])
    cabecera = ["Línea", "Descripción", "Cantidad", "Unidad"]
    for oferta in datos["ofertas"]:
        cabecera.extend([f"{oferta['razon_social']} · {oferta['nit']} · precio unitario", "Impuesto", "Total"])
    _fila(hoja, 3, cabecera, True)
    for n, fila in enumerate(datos["filas"], 4):
        valores = [fila["orden"], fila["descripcion"], Decimal(fila["cantidad"]), fila["unidad"]]
        for c in fila["celdas"]:
            valores.extend([Decimal(c[k]) if c[k] is not None else "Sin precio" for k in ("precio_unitario", "impuesto", "total")])
        _fila(hoja, n, valores)
        for i, c in enumerate(fila["celdas"]):
            if c["menor"]:
                for columna in range(5 + i * 3, 8 + i * 3):
                    hoja.cell(n, columna).fill = MENOR
    n = len(datos["filas"]) + 4
    valores = ["", "Totales por oferente", "", ""]
    for oferta in datos["ofertas"]:
        valores.extend(["", Decimal(oferta["impuesto"]), Decimal(oferta["total"])])
    _fila(hoja, n, valores)
    controles = libro.create_sheet("Verificaciones")
    _fila(controles, 1, ["NIT", "Proveedor", "Tipo", "Activa", "Obligatoria", "Estado confirmado", "Clasificación efectiva", "Reconfirmar", "Fecha", "Usuario", "Observación"], True)
    numero = 2
    for oferta in datos["ofertas"]:
        for c in oferta["verificaciones"]:
            _fila(controles, numero, [oferta["nit"], oferta["razon_social"], c["tipo"], c["activo"], c["obligatoria"], c["estado"], c["clasificacion"], c["desactualizada"], c["fecha"], c["usuario"], c["observacion"]])
            numero += 1
    elegibles = libro.create_sheet("Elegibles de origen")
    _fila(elegibles, 1, ["NIT", "Proveedor", "Puntaje", "Máximo", "Puesto", "Cierre de origen"], True)
    for numero, oferta in enumerate(datos["ofertas"], 2):
        origen = oferta["elegibles"] or {}
        _fila(elegibles, numero, [oferta["nit"], oferta["razon_social"], origen.get("total", "Sin lista de origen"), origen.get("maximo"), origen.get("puesto"), datos["cierre_origen_id"]])
    seleccion = libro.create_sheet("Decisión")
    if decision:
        _fila(seleccion, 1, ["Decisión", decision.pk, "Estado", decision.estado, "Modalidad", decision.modalidad])
        _fila(seleccion, 2, ["Recomendación", decision.recomendacion, "Justificación de elección", decision.motivo_eleccion])
        _fila(seleccion, 3, ["Justificación de verificaciones", decision.justificacion_verificaciones])
        _fila(seleccion, 4, ["Decidió", str(decision.decidido_por) if decision.decidido_por_id else "Pendiente", "Fecha", decision.fecha_decision.isoformat() if decision.fecha_decision else ""])
        _fila(seleccion, 5, ["Línea", "Oferta", "Total adjudicado", "Proveedor", "NIT"], True)
        for numero, s in enumerate(decision.contenido["seleccion"], 6):
            _fila(seleccion, numero, [s["descripcion"], s["oferta_id"], Decimal(s["total"]), s["razon_social"], s["nit"]])
        _fila(seleccion, len(decision.contenido["seleccion"]) + 6, ["Total adjudicado", Decimal(decision.contenido["total_adjudicado"])])
        firmas = libro.create_sheet("Aprobaciones")
        _fila(firmas, 1, ["Requeridas", decision.reglas["aprobaciones"], "Roles", ", ".join(decision.reglas["roles"])])
        _fila(firmas, 2, ["Usuario", "Fecha", "Motivo"], True)
        for numero, aprobacion in enumerate(decision.aprobaciones.select_related("actor"), 3):
            _fila(firmas, numero, [str(aprobacion.actor), aprobacion.fecha.isoformat(), aprobacion.motivo])
    else:
        _fila(seleccion, 1, ["Sin propuesta de decisión registrada"])
    for pestaña in libro:
        pestaña.freeze_panes = "E4" if pestaña == hoja else "A2"
        for columna in pestaña.columns:
            pestaña.column_dimensions[columna[0].column_letter].width = 24
    salida = BytesIO()
    libro.save(salida)
    return salida.getvalue()
