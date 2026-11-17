"""Exportación del consolidado de proyecciones a Excel con openpyxl (GDS-PRY-06).

Libro: una hoja «Resumen» (una fila por año y área, más los totales) y una hoja por cada
proyección del filtro con sus líneas y totales. Encabezados en azul #172554 con texto blanco;
los montos con formato de moneda. Los totales se escriben como valores (calculados en la base
de datos), no como fórmulas, para que coincidan exactamente con la pantalla.
"""

import re
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from proyecciones import consolidado
from proyecciones.models import CAMPOS_CANTIDADES_MENSUALES

AZUL = "172554"
AZUL_CLARO = "DBEAFE"
FORMATO_MONEDA = '"$" #,##0.00'
FORMATO_ENTERO = "#,##0"
MESES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]

ENCABEZADO_FONDO = PatternFill("solid", start_color=AZUL, end_color=AZUL)
ENCABEZADO_FUENTE = Font(bold=True, color="FFFFFF")
TOTAL_FONDO = PatternFill("solid", start_color=AZUL_CLARO, end_color=AZUL_CLARO)
TOTAL_FUENTE = Font(bold=True, color=AZUL)

COLUMNAS_RESUMEN = [
    "Año",
    "Área",
    "Código",
    "Estado",
    "Líneas",
    *MESES,
    "Total anual",
    "Costo",
    "Cantidad autorizada",
    "Cantidad ajustada",
    "Total anual ajustado",
    "Costo ajustado",
]
COLUMNAS_AREA = [
    "Producto o servicio",
    "Dependencia",
    "Unidad",
    *MESES,
    "Total anual",
    "Precio estimado",
    "Costo",
    "Cantidad autorizada",
    "Cantidad ajustada",
    "Total anual ajustado",
    "Precio vigente",
    "Costo ajustado",
]
MONEDA_RESUMEN = {"Costo", "Costo ajustado"}
MONEDA_AREA = {"Precio estimado", "Costo", "Precio vigente", "Costo ajustado"}

CARACTERES_PROHIBIDOS = re.compile(r"[\\/*?:\[\]]")


def nombre_hoja(texto, usados):
    """Nombre válido y único para una hoja: sin \\ / * ? : [ ], máximo 31 caracteres."""
    base = CARACTERES_PROHIBIDOS.sub("-", texto).strip().strip("'") or "Hoja"
    base = base[:31]
    nombre, numero = base, 2
    while nombre.lower() in usados:
        sufijo = f" ({numero})"
        nombre = base[: 31 - len(sufijo)] + sufijo
        numero += 1
    usados.add(nombre.lower())
    return nombre


def _encabezado(hoja, fila, columnas):
    for indice, titulo in enumerate(columnas, start=1):
        celda = hoja.cell(row=fila, column=indice, value=titulo)
        celda.fill = ENCABEZADO_FONDO
        celda.font = ENCABEZADO_FUENTE
        celda.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    hoja.freeze_panes = hoja.cell(row=fila + 1, column=1)


def _fila(hoja, fila, valores, columnas, moneda, es_total=False):
    for indice, (titulo, valor) in enumerate(zip(columnas, valores), start=1):
        celda = hoja.cell(row=fila, column=indice, value=valor)
        if isinstance(valor, str):
            celda.data_type = "s"
        if titulo in moneda:
            celda.number_format = FORMATO_MONEDA
        elif isinstance(valor, int):
            celda.number_format = FORMATO_ENTERO
        if es_total:
            celda.fill = TOTAL_FONDO
            celda.font = TOTAL_FUENTE


def _anchos(hoja, columnas):
    for indice, titulo in enumerate(columnas, start=1):
        ancho = 34 if titulo in ("Área", "Producto o servicio") else max(10, min(len(titulo) + 4, 22))
        hoja.column_dimensions[get_column_letter(indice)].width = ancho


def _titulo(hoja, texto, subtitulo):
    hoja["A1"] = texto
    hoja["A1"].font = Font(bold=True, size=14, color=AZUL)
    hoja["A2"] = subtitulo


def _valores_resumen(fila):
    return [
        fila["numero_lineas"],
        *fila["meses"],
        fila["total_anual"],
        fila["costo"],
        fila["cantidad_autorizada"],
        fila["cantidad_ajustada"],
        fila["total_ajustado"],
        fila["costo_ajustado"],
    ]


def libro_consolidado(consulta, descripcion_filtro=""):
    """Construye el libro del consolidado para las proyecciones de `consulta`."""
    libro = Workbook()
    resumen = libro.active
    resumen.title = "Resumen"
    usados = {"resumen"}
    _titulo(resumen, "Consolidado de proyecciones", descripcion_filtro)
    _encabezado(resumen, 4, COLUMNAS_RESUMEN)

    filas = consolidado.filas_por_area(consulta)
    numero = 5
    for fila in filas:
        valores = [fila["anio"], fila["area"], fila["codigo_area"], fila["estado"], *_valores_resumen(fila)]
        _fila(resumen, numero, valores, COLUMNAS_RESUMEN, MONEDA_RESUMEN)
        numero += 1
    total = consolidado.totales(consulta)
    _fila(resumen, numero, ["Total", "", "", "", *_valores_resumen(total)], COLUMNAS_RESUMEN, MONEDA_RESUMEN, True)
    _anchos(resumen, COLUMNAS_RESUMEN)

    for fila in filas:
        proyeccion = fila["proyeccion"]
        hoja = libro.create_sheet(nombre_hoja(f"{fila['codigo_area']} {fila['anio']}", usados))
        _titulo(hoja, f"{fila['area']} · periodo {fila['anio']}", f"Estado: {fila['estado']}")
        _encabezado(hoja, 4, COLUMNAS_AREA)
        numero = 5
        for linea in consolidado.lineas_de(proyeccion):
            valores = [
                linea.producto_servicio,
                linea.dependencia,
                str(linea.unidad),
                *[getattr(linea, campo) for campo in CAMPOS_CANTIDADES_MENSUALES],
                linea.total,
                "No informado" if linea.costo_proyectado_total is not None and linea.precio_estimado == 0 else linea.precio_estimado,
                linea.costo,
                linea.cantidad_autorizada,
                linea.v_cantidad_autorizada,
                linea.v_total,
                "No informado" if linea.v_costo_proyectado_total is not None and linea.v_precio_estimado == 0 else linea.v_precio_estimado,
                linea.v_costo,
            ]
            _fila(hoja, numero, valores, COLUMNAS_AREA, MONEDA_AREA)
            numero += 1
        valores_total = [
            "Total",
            "",
            "",
            *fila["meses"],
            fila["total_anual"],
            None,
            fila["costo"],
            fila["cantidad_autorizada"],
            fila["cantidad_ajustada"],
            fila["total_ajustado"],
            None,
            fila["costo_ajustado"],
        ]
        _fila(hoja, numero, valores_total, COLUMNAS_AREA, MONEDA_AREA, True)
        _anchos(hoja, COLUMNAS_AREA)
    return libro


def exportar_consolidado(consulta, descripcion_filtro=""):
    """Bytes del archivo .xlsx del consolidado."""
    salida = BytesIO()
    libro_consolidado(consulta, descripcion_filtro).save(salida)
    return salida.getvalue()
