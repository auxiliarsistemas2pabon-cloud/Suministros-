"""Plantilla y lectura acotada de Excel; nunca ejecuta fórmulas del archivo."""

from decimal import Decimal, InvalidOperation
from io import BytesIO
from pathlib import Path
import re
from zipfile import BadZipFile, ZipFile
from xml.etree.ElementTree import ParseError

from django.core.exceptions import ValidationError
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils.exceptions import InvalidFileException
from openpyxl.utils.cell import column_index_from_string
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.xml.functions import iterparse

from proyecciones.models import CAMPOS_CANTIDADES_MENSUALES, Linea, UnidadMedida

MAX_BYTES = 10 * 1024 * 1024
MAX_DESCOMPRIMIDO = 50 * 1024 * 1024
MAX_FILAS = 1000
CAMPOS = ("producto_servicio", "dependencia", "unidad_id", *CAMPOS_CANTIDADES_MENSUALES, "precio_estimado")
ENCABEZADOS = (
    "Producto o servicio", "Dependencia", "Unidad (abreviatura)",
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre", "Precio estimado",
)


def plantilla_excel():
    libro = Workbook()
    hoja = libro.active
    hoja.title = "Proyección"
    hoja.append(ENCABEZADOS)
    hoja.freeze_panes = "D2"
    hoja.auto_filter.ref = f"A1:P{MAX_FILAS + 1}"
    for celda in hoja[1]:
        celda.fill = PatternFill("solid", fgColor="172554")
        celda.font = Font(color="FFFFFF", bold=True)
        hoja.column_dimensions[celda.column_letter].width = 20
    instrucciones = libro.create_sheet("Instrucciones")
    for texto in (
        "Diligencie la hoja Proyección sin cambiar los encabezados.",
        "Producto y precio son obligatorios; dependencia es opcional.",
        "Seleccione una abreviatura de unidad activa del catálogo.",
        "Cantidades: enteros no negativos; una cantidad vacía equivale a cero.",
        "Precio: número no negativo, hasta dos decimales. No use fórmulas.",
        f"Máximo {MAX_FILAS} filas y 10 MB. No agregue columnas.",
        "La carga muestra una vista previa; solo se guarda al confirmar.",
        "Puede agregar o reemplazar; las filas con errores no se importan.",
    ):
        instrucciones.append([texto])
    instrucciones.column_dimensions["A"].width = 100
    unidades = libro.create_sheet("Unidades")
    for unidad in UnidadMedida.objects.filter(activa=True).order_by("nombre"):
        unidades.append([unidad.abreviatura, unidad.nombre])
        # Los catálogos son texto, incluso si comienzan por '='.
        for celda in unidades[unidades.max_row]:
            celda.data_type = "s"
    if unidades.max_row and unidades["A1"].value:
        validacion = DataValidation(type="list", formula1=f"'Unidades'!$A$1:$A${unidades.max_row}")
        validacion.errorTitle = "Unidad no válida"
        validacion.error = "Seleccione una unidad del catálogo."
        validacion.showErrorMessage = True
        hoja.add_data_validation(validacion)
        validacion.add(f"C2:C{MAX_FILAS + 1}")
    unidades.sheet_state = "hidden"
    salida = BytesIO()
    libro.save(salida)
    return salida.getvalue()


def _numero(valor, *, entero=False):
    if entero and valor in (None, ""):
        return 0
    if isinstance(valor, bool) or valor in (None, ""):
        raise ValidationError("Indique un número no negativo.")
    try:
        numero = Decimal(str(valor).strip())
    except (InvalidOperation, ValueError):
        raise ValidationError("Indique un número válido; use punto decimal.") from None
    if not numero.is_finite() or numero < 0:
        raise ValidationError("El número debe ser finito y no negativo.")
    if entero:
        if numero > 2147483647 or numero != numero.to_integral_value():
            raise ValidationError("Indique un entero entre 0 y 2147483647.")
        return int(numero)
    if numero > Decimal("999999999999.99") or numero != numero.quantize(Decimal("0.01")):
        raise ValidationError("El precio admite hasta 12 enteros y dos decimales.")
    return str(numero.quantize(Decimal("0.01")))


def _validar_dimensiones_reales(hoja):
    """No confiar en <dimension>: algunos archivos declaran A1 y ocultan filas o columnas.

    Se usa la fuente de ReadOnlyWorksheet de la versión fijada de openpyxl, antes de
    iterar celdas; así un índice desmesurado no obliga a crear millones de casillas.
    """
    anterior, columnas = 0, 0
    with hoja._get_source() as fuente:
        for evento, elemento in iterparse(fuente, events=("start", "end")):
            etiqueta = elemento.tag.rsplit("}", 1)[-1]
            if evento == "start":
                if etiqueta == "row":
                    actual = int(elemento.attrib.get("r", anterior + 1))
                    if actual <= anterior or actual > MAX_FILAS + 1:
                        raise ValidationError(f"Use hasta {MAX_FILAS} filas, ordenadas y sin filas duplicadas.")
                    anterior, columnas = actual, 0
                elif etiqueta == "c":
                    columnas += 1
                    referencia = elemento.attrib.get("r")
                    if referencia:
                        coincidencia = re.fullmatch(r"([A-Z]{1,3})([1-9][0-9]{0,6})", referencia)
                        if not coincidencia or column_index_from_string(coincidencia[1]) > len(CAMPOS) or int(coincidencia[2]) > MAX_FILAS + 1:
                            raise ValidationError("El Excel contiene celdas fuera de las 16 columnas o del límite de filas.")
                    if columnas > len(CAMPOS):
                        raise ValidationError("Use solo las 16 columnas de la plantilla.")
            else:
                elemento.clear()


def leer_excel(archivo, proyeccion):
    if Path(archivo.name).suffix.lower() != ".xlsx":
        raise ValidationError("Seleccione un archivo .xlsx.")
    contenido = archivo.read(MAX_BYTES + 1)
    if len(contenido) > MAX_BYTES:
        raise ValidationError("El archivo supera el máximo de 10 MB.")
    libro = None
    try:
        with ZipFile(BytesIO(contenido)) as comprimido:
            entradas = comprimido.infolist()
            if len(entradas) > 1000 or sum(e.file_size for e in entradas) > MAX_DESCOMPRIMIDO:
                raise ValidationError("El contenido descomprimido del Excel es demasiado grande.")
            if "xl/vbaProject.bin" in comprimido.namelist():
                raise ValidationError("No se admiten archivos con macros.")
        libro = load_workbook(BytesIO(contenido), read_only=True, data_only=False, keep_links=False)
        if "Proyección" not in libro.sheetnames:
            raise ValidationError("Falta la hoja Proyección. Descargue la plantilla.")
        hoja = libro["Proyección"]
        if (hoja.max_row or 0) > MAX_FILAS + 1 or (hoja.max_column or 0) > len(CAMPOS):
            raise ValidationError(f"Use hasta {MAX_FILAS} filas y las 16 columnas de la plantilla.")
        _validar_dimensiones_reales(hoja)
        hoja.reset_dimensions()
        filas = hoja.iter_rows(max_col=len(CAMPOS))
        encabezado = next(filas, ())
        if tuple(c.value for c in encabezado) != ENCABEZADOS:
            raise ValidationError("Los encabezados no coinciden con la plantilla.")
        unidades = {u.abreviatura.casefold(): u.pk for u in UnidadMedida.objects.filter(activa=True)}
        validas, errores = [], []
        for numero, celdas in enumerate(filas, start=2):
            if numero > MAX_FILAS + 1:
                raise ValidationError(f"Se permiten hasta {MAX_FILAS} filas.")
            if all(c.value in (None, "") for c in celdas):
                continue
            try:
                datos = {}
                for campo, etiqueta, celda in zip(CAMPOS, ENCABEZADOS, celdas):
                    if celda.data_type in ("f", "e"):
                        raise ValidationError(f"{etiqueta}: no se admiten fórmulas ni errores de Excel.")
                    valor = celda.value
                    if campo in CAMPOS_CANTIDADES_MENSUALES or campo == "precio_estimado":
                        try:
                            datos[campo] = _numero(valor, entero=campo != "precio_estimado")
                        except ValidationError as error:
                            raise ValidationError(f"{etiqueta}: {' '.join(error.messages)}") from None
                    elif campo == "unidad_id":
                        datos[campo] = unidades.get(str(valor or "").strip().casefold())
                        if datos[campo] is None:
                            raise ValidationError("Seleccione una abreviatura de unidad activa.")
                    else:
                        datos[campo] = str(valor or "").strip()
                linea = Linea(proyeccion=proyeccion, **datos)
                linea.full_clean()
                datos["producto_servicio"] = linea.producto_servicio
                datos["dependencia"] = linea.dependencia
                validas.append({"fila": numero, "datos": datos})
            except ValidationError as error:
                errores.append({"fila": numero, "error": " ".join(error.messages)})
        if not validas and not errores:
            raise ValidationError("El archivo no contiene líneas para importar.")
        return validas, errores
    except ValidationError:
        raise
    except (BadZipFile, InvalidFileException, ParseError, KeyError, ValueError, TypeError, OSError, EOFError, RuntimeError):
        raise ValidationError("El archivo no es un Excel .xlsx válido o está dañado.") from None
    finally:
        if libro is not None:
            libro.close()
