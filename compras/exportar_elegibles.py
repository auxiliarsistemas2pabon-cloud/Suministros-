"""Exportación FR-GDS-20 con valores del servidor y texto sin fórmulas."""
from io import BytesIO

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter

from proyecciones.exportar import AZUL, ENCABEZADO_FONDO, ENCABEZADO_FUENTE


def _fila(hoja, numero, valores, cabecera=False):
    for indice, valor in enumerate(valores, 1):
        if isinstance(valor, str):
            valor = ILLEGAL_CHARACTERS_RE.sub("", valor)[:32767]
        celda = hoja.cell(numero, indice, valor)
        if isinstance(valor, str):
            celda.data_type = "s"
        celda.alignment = Alignment(vertical="top", wrap_text=True)
        if cabecera:
            celda.fill, celda.font = ENCABEZADO_FONDO, ENCABEZADO_FUENTE


def exportar_lista(lista, resultado, decision, documental=None):
    libro = Workbook()
    hoja = libro.active
    hoja.title = "Elegibles"
    hoja["A1"] = "Lista de elegibles FR-GDS-20"
    hoja["A1"].font = Font(bold=True, size=14, color=AZUL)
    origen = lista.resultado_cierre.get("necesidad", {}) if resultado.get("historico") else {}
    _fila(hoja, 2, ["Objeto", origen.get("objeto", lista.necesidad.objeto)])
    _fila(hoja, 3, ["Área", origen.get("area", str(lista.necesidad.area)), "Fecha", lista.fecha.isoformat(), "Estado", lista.estado])
    numero_version = lista.resultado_cierre.get("numero_version") if resultado.get("historico") else None
    _fila(hoja, 4, ["Versión", numero_version or (lista.version_criterios.numero if lista.version_criterios_id else "Sin asignar"), "Método", resultado["reglas"].get("metodo", "Sin asignar")])
    _fila(hoja, 5, ["Cantidad base", resultado["base"]["cantidad"], "Unidad", resultado["base"]["unidad"]])
    _fila(hoja, 6, ["Decisión", "Registrada y vigente" if decision["vigente"] else "Pendiente de registrar o revisar", "D-08", "Reglas provisionales pendientes de aprobación"])
    _fila(hoja, 8, ["NIT", "Razón social", "Puntaje", "Máximo", "Puesto calculado", "Puesto con desempate", "Empate por puntaje", "Cantidad autorizada", "Unidad", "Observación", "Justificación de elección", "Registró", "Fecha de decisión"], True)
    detalle = libro.create_sheet("Calificaciones")
    _fila(detalle, 1, ["NIT", "Razón social", "Criterio", "Peso %", "Cumplimiento", "Subtotal", "Observación"], True)
    n = 2
    for fila, datos in enumerate(resultado["filas"], 9):
        p = datos["participante"]
        _fila(hoja, fila, [p.nit, p.razon_social, datos["total"], datos["maximo"], datos["puesto_calculado"], datos["puesto"],
            "Sí" if datos["empate"] else "No", p.cantidad_autorizada, resultado["base"]["unidad"], p.observacion,
            p.justificacion_eleccion, str(p.decision_por) if p.decision_por_id else "", p.decision_fecha.isoformat() if p.decision_fecha else ""])
        hoja.cell(fila, 3).number_format = "0.0000"
        hoja.cell(fila, 8).number_format = "0.000"
        for celda in datos["celdas"]:
            _fila(detalle, n, [p.nit, p.razon_social, celda["nombre"], celda["peso"], celda["cumplimiento"], celda["subtotal"], celda["observacion"]])
            detalle.cell(n, 6).number_format = "0.0000"
            n += 1
    reglas = libro.create_sheet("Decisión y reglas")
    _fila(reglas, 1, ["Dato", "Valor"], True)
    registro = decision["registro"]
    valores = [
        ("Lista", lista.pk), ("D-07 pendiente", "Sí" if resultado["reglas"].get("pendiente", True) else "No"),
        ("Escala", " / ".join(resultado["reglas"].get("escala", []))),
        ("Fórmula", {"directo": "Cumplimiento × peso % / 100", "escalado": "Cumplimiento / máximo de escala × peso %"}.get(resultado["reglas"].get("metodo"), "Sin asignar")),
        ("Redondeo", "Subtotal a cuatro decimales ROUND_HALF_UP; total = suma de subtotales"),
        ("Cantidad total autorizada", decision["total_autorizado"]), ("Origen de cantidad base", resultado["base"]["origen"]),
        ("Justificación proveedor único", registro.justificacion_unico if registro else ""),
        ("Justificación exceso de cantidad", registro.justificacion_cantidad if registro else ""),
        ("Decisión registrada por", str(registro.registrada_por) if registro else ""),
        ("Fecha", registro.fecha.isoformat() if registro else ""),
    ]
    for numero, valores_fila in enumerate(valores, 2):
        _fila(reglas, numero, valores_fila)
    fila = len(valores) + 4
    _fila(reglas, fila, ["Puntaje empatado", "Orden de participantes", "Justificación", "Registró", "Fecha"], True)
    for grupo in resultado["empates"]:
        desempate = grupo["desempate"]
        if desempate:
            fila += 1
            _fila(reglas, fila, [grupo["total"], ", ".join(str(pk) for pk in desempate.orden), desempate.justificacion,
                                str(desempate.registrado_por), desempate.fecha.isoformat()])
    for hoja_actual, fila_encabezado in ((hoja, 8), (detalle, 1), (reglas, 1)):
        hoja_actual.freeze_panes = f"A{fila_encabezado + 1}"
        if hoja_actual != reglas:
            hoja_actual.auto_filter.ref = f"A{fila_encabezado}:{get_column_letter(hoja_actual.max_column)}{hoja_actual.max_row}"
        for columna in range(1, hoja_actual.max_column + 1):
            hoja_actual.column_dimensions[get_column_letter(columna)].width = 30 if columna in (2, 7, 10, 11) else 22
    if documental is not None:
        estado = libro.create_sheet("Estado documental")
        _fila(estado, 1, ["Control documental FR-GDS-14", "Histórico conservado" if documental["historico"] else "Consulta actual"])
        _fila(estado, 2, ["Referencia", documental["referencia"].isoformat() if documental["referencia"] else "Sin foto histórica",
                         "Modo", documental["reglas"].get("modo", "Sin foto"), "Meses", documental["reglas"].get("meses")])
        _fila(estado, 3, ["Justificación documental", documental["justificacion"]])
        _fila(estado, 5, ["NIT", "Razón social", "Elegido", "Evaluación FR14", "Fecha FR14", "Calificación", "Advertencias", "Informativas", "Tipo de documento", "Obligatorio", "Estado", "Expedición", "Vencimiento", "Documento"], True)
        numero = 6
        for fila in documental["filas"]:
            p, foto = fila["participante"], fila["foto"]
            ev = foto.get("evaluacion") or {}
            prefijo = [p.nit, p.razon_social, "Sí" if fila["elegido"] else "No", ev.get("id"), ev.get("fecha"), ev.get("calificacion"),
                       " | ".join(foto.get("advertencias", [])) if foto else "Sin foto histórica", " | ".join(foto.get("informativas", []))]
            documentos = foto.get("documentos", [])
            if not documentos:
                _fila(estado, numero, prefijo + ["Sin exigencias en la foto" if foto else "Sin foto histórica"])
                numero += 1
            for documento in documentos:
                _fila(estado, numero, prefijo + [documento["tipo"], "Sí" if documento["obligatorio"] else "No", documento["etiqueta"],
                     documento["expedicion"], documento["vencimiento"], documento["documento_id"]])
                numero += 1
        estado.freeze_panes = "A6"
        estado.auto_filter.ref = f"A5:N{max(numero - 1, 5)}"
        for columna in range(1, 15):
            estado.column_dimensions[get_column_letter(columna)].width = 38 if columna in (2, 7, 8, 9) else 22
    salida = BytesIO()
    libro.save(salida)
    return salida.getvalue()
