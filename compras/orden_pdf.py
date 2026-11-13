"""FR-GDS-21 a partir del documento congelado, sin leer catálogos vivos.

Referencia: https://docs.reportlab.com/reportlab/userguide/ch5_platypus/
"""
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape
from decimal import Decimal

import reportlab
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle


def generar(documento, *, anulada=False, motivo_anulacion=""):
    if "SuministrosVera" not in pdfmetrics.getRegisteredFontNames():
        carpeta = Path(reportlab.__file__).parent / "fonts"
        pdfmetrics.registerFont(TTFont("SuministrosVera", str(carpeta / "Vera.ttf")))
        pdfmetrics.registerFont(TTFont("SuministrosVera-Bold", str(carpeta / "VeraBd.ttf")))
        pdfmetrics.registerFontFamily("SuministrosVera", normal="SuministrosVera", bold="SuministrosVera-Bold", italic="SuministrosVera", boldItalic="SuministrosVera-Bold")
    estilos = getSampleStyleSheet()
    for estilo in estilos.byName.values():
        estilo.fontName = "SuministrosVera"
    estilos["BodyText"].fontSize, estilos["BodyText"].leading = 8, 11
    estilos["Title"].fontSize = 16
    p = lambda texto, estilo="BodyText": Paragraph(escape(str(texto or "")).replace("\n", "<br/>"), estilos[estilo])
    dinero = lambda valor: f"{Decimal(str(valor)):,.2f}"
    foto, cliente = documento["orden"], documento["cliente"]
    salida = BytesIO()
    pdf = SimpleDocTemplate(salida, pagesize=landscape(A4), rightMargin=12*mm, leftMargin=12*mm,
        topMargin=12*mm, bottomMargin=14*mm, title=f'FR-GDS-21 {foto["consecutivo"]}', author=cliente["nombre"])
    bloques = [p(f'Orden de compra · {foto["consecutivo"]}', "Title"), p(f'FR-GDS-21 · {cliente["nombre"]} · NIT {cliente["nit"]}'),
        p(f'Proveedor: {foto["razon_social"]} · NIT {foto["nit"]}'),
        p(f'Cotización: {documento["cotizacion"]} · Área: {cliente["area"]}'),
        p(f'Elaboró: {cliente["elaborada_por"]} · Fecha: {foto["fecha_elaboracion"]} · Emisión: {foto["fecha_emision"]}'),
        p(f'{foto["etiqueta_vencimiento"]}: {foto["fecha_vencimiento"] or "No indicada"}'), p(f'Pago: {foto["condiciones_pago"] or "Sin condiciones registradas"}'), Spacer(1, 4*mm)]
    if anulada:
        bloques.append(p(f'ORDEN ANULADA · {motivo_anulacion}', "Heading2"))
    filas = [[p(t) for t in ("Referencia / descripción", "Cantidad / unidad", "Precio unitario", "Tarifa", "Bruto", "Descuento aplicado", "Base neta", "Impuesto", "Total")]]
    for l in foto["lineas"]:
        filas.append([p(f'{l["referencia"]} {l["descripcion"]}\n{l["especificacion"]}'), p(f'{l["cantidad"]} {l["unidad"]}'),
            p(l["precio_unitario"]), p(f'{l["tarifa_nombre"]} ({l["porcentaje"]} %)'),
            *[p(dinero(l[k])) for k in ("subtotal", "descuento_aplicado", "base", "impuesto", "total")]])
    tabla = Table(filas, colWidths=[68*mm, 28*mm, 27*mm, 30*mm, *([24*mm]*5)], repeatRows=1, splitByRow=1, splitInRow=1)
    tabla.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#edf2f7")), ("GRID", (0, 0), (-1, -1), .3, colors.grey), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    bloques += [tabla, Spacer(1, 3*mm)]
    for titulo, campo in (("Subtotal bruto", "subtotal"), ("Descuento", "descuento"), ("Base neta", "base"), ("Impuestos", "impuesto"), ("Antes de retenciones", "total_sin_retenciones"), ("Retenciones", "retencion"), ("Total a pagar", "total")):
        bloques.append(p(f'{titulo}: {dinero(foto[campo])}'))
    for r in foto["retenciones_aplicadas"]:
        bloques.append(p(f'{r["nombre"]}: {r["porcentaje"]} % sobre {r["base"]}; mínimo {r["base_minima"] or "sin mínimo"}; importe {r["importe"]}'))
    bloques.append(p("Aprobaciones", "Heading2"))
    for firma in documento["firmas"]:
        bloques.append(p(f'{firma["usuario"]} · {firma["fecha"]} · {firma["decision"]} · {firma["comentario"]}'))
    bloques.append(p(f'Reglas de importes: {documento["reglas_importes_texto"]}'))
    def pie(canvas, doc):
        canvas.saveState()
        canvas.setFont("SuministrosVera", 7)
        canvas.drawRightString(285*mm, 7*mm, f'{foto["consecutivo"]} · Página {doc.page}')
        canvas.restoreState()
    pdf.build(bloques, onFirstPage=pie, onLaterPages=pie)
    return salida.getvalue()
