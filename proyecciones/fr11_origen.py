"""Lectura del consolidado institucional FR-GDS-11 sin escrituras ni fórmulas ejecutadas.

La fuente contiene cantidades y un presupuesto anual, no unidades ni precios
unitarios. Las filas incompletas se conservan como pendientes para su revisión.
"""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
import hashlib
from io import BytesIO
import math
from pathlib import Path
import re
import unicodedata
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile, ZipFile

from django.core.exceptions import ValidationError
from openpyxl import load_workbook
from openpyxl.utils.cell import column_index_from_string
from openpyxl.utils.exceptions import InvalidFileException
from openpyxl.xml.functions import iterparse

MAX_BYTES = 20 * 1024 * 1024
MAX_DESCOMPRIMIDO = 512 * 1024 * 1024
MAX_FILAS = 5000
MAX_COLUMNAS = 128  # El original contiene columnas vacías con formato después de Q.
MAX_HOJAS = 32
MAX_CELDAS = 500_000
MAX_ENTRADAS = 2000
MESES = ("ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE")
ENCABEZADOS = ("EQUIPO/PRODUCTO/SERVICIO", "DEPENDENCIA", "SERIE", *MESES, "AUTORIZADO", "COSTO PROYECTADO")
CENTAVO = Decimal("0.01")


def _normalizar(valor):
    texto = unicodedata.normalize("NFKD", str(valor or ""))
    texto = "".join(letra for letra in texto if not unicodedata.combining(letra))
    return re.sub(r"\s*/\s*", "/", " ".join(texto.upper().split()))


def _original(valor):
    if valor is None or isinstance(valor, (str, bool, int)):
        return valor
    if isinstance(valor, float) and math.isfinite(valor):
        return valor
    return str(valor)


def _importe(valor):
    if valor is None or isinstance(valor, bool) or str(valor).strip() == "":
        raise ValueError("Falta el costo proyectado anual; no se reemplaza por cero.")
    texto = str(valor).strip()
    if isinstance(valor, str):
        if not re.fullmatch(r"(?:\$\s*)?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?", texto):
            raise ValueError("Use un importe no negativo con punto decimal y comas de miles, como $ 1,000.50.")
        texto = texto.removeprefix("$").strip().replace(",", "")
    try:
        numero = Decimal(texto)
        if not numero.is_finite() or numero < 0 or numero > Decimal("9999999999999999.99"):
            raise ValueError("El costo debe ser finito, no negativo y tener hasta 16 enteros.")
        if numero != numero.quantize(CENTAVO):
            raise ValueError("El costo proyectado admite como máximo dos decimales.")
    except InvalidOperation:
        raise ValueError("El costo proyectado no es un importe válido.") from None
    return numero


def _entero(valor):
    if valor is None or isinstance(valor, bool) or str(valor).strip() == "":
        raise ValueError("Cantidad pendiente; indique un entero, incluido cero cuando corresponda.")
    try:
        numero = Decimal(str(valor).strip())
        if not numero.is_finite() or numero < 0 or numero > 2147483647 or numero != numero.to_integral_value():
            raise ValueError("Indique un entero no negativo entre 0 y 2147483647.")
    except InvalidOperation:
        raise ValueError("La cantidad no es un entero válido.") from None
    return int(numero)


def _formula_meses(formula, fila):
    formula = re.sub(r"\s+", "", str(formula)).replace("$", "").upper()
    if formula in (f"=SUM(D{fila}:O{fila})", f"=SUMA(D{fila}:O{fila})"):
        return True
    terminos = formula.removeprefix("=").split("+")
    return formula.startswith("=") and len(terminos) == 12 and set(terminos) == {f"{col}{fila}" for col in "DEFGHIJKLMNO"}


def _validar_fuente(hoja, presupuesto):
    """Acota índices reales aun cuando la dimensión declarada en XML sea falsa."""
    if (hoja.max_row or 0) > MAX_FILAS or (hoja.max_column or 0) > MAX_COLUMNAS:
        raise ValidationError(f"{hoja.title}: máximo {MAX_FILAS} filas y {MAX_COLUMNAS} columnas, contando formato vacío.")
    ultima_fila = 0
    fila_actual = 0
    columna_actual = 0
    with hoja._get_source() as fuente:
        for evento, elemento in iterparse(fuente, events=("start", "end")):
            etiqueta = elemento.tag.rsplit("}", 1)[-1]
            if evento == "start" and etiqueta == "row":
                fila_actual = int(elemento.attrib.get("r", ultima_fila + 1))
                if fila_actual <= ultima_fila or fila_actual > MAX_FILAS:
                    raise ValidationError(f"{hoja.title}: filas fuera del límite, repetidas o desordenadas.")
                ultima_fila, columna_actual = fila_actual, 0
            elif evento == "start" and etiqueta == "c":
                presupuesto[0] += 1
                if presupuesto[0] > MAX_CELDAS:
                    raise ValidationError("El consolidado supera el límite de celdas para su lectura.")
                referencia = elemento.attrib.get("r")
                coincidencia = re.fullmatch(r"([A-Z]{1,3})([1-9][0-9]{0,6})", referencia or "")
                columna = column_index_from_string(coincidencia[1]) if coincidencia else columna_actual + 1
                if referencia and (not coincidencia or int(coincidencia[2]) != fila_actual):
                    raise ValidationError(f"{hoja.title}: referencia de celda no válida.")
                if columna <= columna_actual or columna > MAX_COLUMNAS:
                    raise ValidationError(f"{hoja.title}: columnas fuera del límite, repetidas o desordenadas.")
                columna_actual = columna
            elif evento == "end" and etiqueta == "c":
                tiene_contenido = any(
                    hijo.tag.rsplit("}", 1)[-1] == "f" or (hijo.text is not None and hijo.text != "")
                    for hijo in elemento.iter() if hijo is not elemento
                )
                if columna_actual > 17 and tiene_contenido:
                    raise ValidationError(f"{hoja.title}: hay datos fuera de las 17 columnas del FR-GDS-11.")
                elemento.clear()
            elif evento == "end" and etiqueta == "row":
                elemento.clear()
    return ultima_fila


def _leer_area(hoja, cache, ultima_fila, equis_como_unidad):
    hoja.reset_dimensions()
    cache.reset_dimensions()
    lineas, observaciones, totales, errores_area = [], [], [], []
    anio = None
    for numero, (celdas, guardadas) in enumerate(zip(
        hoja.iter_rows(max_row=ultima_fila, max_col=17),
        cache.iter_rows(max_row=ultima_fila, max_col=17),
    ), 1):
        if numero == 5:
            coincidencia = re.fullmatch(r"(?:ANO\s*:?\s*)?([0-9]{4})", _normalizar(celdas[0].value))
            if not coincidencia or int(coincidencia[1]) == 0 or celdas[0].data_type in ("f", "e"):
                raise ValidationError(f"{hoja.title}!A5: indique el año literal de la proyección.")
            anio = int(coincidencia[1])
        if numero == 6:
            if tuple(_normalizar(c.value) for c in celdas) != ENCABEZADOS:
                raise ValidationError(f"{hoja.title}: los encabezados de la fila 6 no corresponden al FR-GDS-11.")
        if numero <= 6 or all(c.value in (None, "") for c in celdas):
            continue
        if all(c.value in (None, "") for c in celdas[:16]) and celdas[16].data_type == "f":
            totales.append((numero, celdas[16].value, guardadas[16].value))
            continue
        errores, notas = [], []

        def error(columna, mensaje):
            errores.append({"celda": f"{columna}{numero}", "valor_original": _original(celdas[column_index_from_string(columna) - 1].value), "error": mensaje})

        textos = []
        for indice, columna in enumerate("ABC"):
            valor = celdas[indice].value
            texto = str(valor or "").strip()
            if celdas[indice].data_type in ("f", "e") or isinstance(valor, bool) or len(texto) > 255:
                error(columna, "Use texto literal de hasta 255 caracteres; no se admiten fórmulas ni errores.")
            if indice == 0 and not texto:
                error(columna, "Falta el producto o servicio.")
            textos.append(texto)
        meses = []
        tiene_equis = False
        for indice, columna in enumerate("DEFGHIJKLMNO", 3):
            celda = celdas[indice]
            if isinstance(celda.value, str) and celda.value.strip().casefold() == "x" and equis_como_unidad:
                meses.append(1)
                tiene_equis = True
                notas.append(f"{hoja.title}!{columna}{numero}: valor original {celda.value!r} interpretado como 1 por confirmación explícita.")
                continue
            try:
                if isinstance(celda.value, str) and celda.value.strip().casefold() == "x":
                    raise ValueError("La marca X requiere confirmación explícita para interpretarla como una unidad.")
                if celda.data_type in ("f", "e"):
                    raise ValueError("No se admiten fórmulas ni errores en cantidades mensuales.")
                meses.append(_entero(celda.value))
            except ValueError as fallo:
                meses.append(None)
                error(columna, str(fallo))
        cantidad = sum(meses) if all(valor is not None for valor in meses) else None
        cantidad_hoja = None
        try:
            if celdas[15].data_type == "f" and not _formula_meses(celdas[15].value, numero):
                raise ValueError("Fórmula de AUTORIZADO no reconocida; solo se admite la suma de los doce meses de esta fila.")
            if celdas[15].data_type == "e":
                raise ValueError("La celda AUTORIZADO contiene un error de Excel.")
            if guardadas[15].value is None and celdas[15].data_type == "f":
                notas.append(f"{hoja.title}!P{numero}: no hay resultado almacenado; la cantidad se obtiene de los meses, sin ejecutar la fórmula.")
            else:
                cantidad_hoja = _entero(guardadas[15].value)
        except ValueError as fallo:
            error("P", str(fallo))
        if cantidad is not None and cantidad_hoja is not None and cantidad != cantidad_hoja:
            detalle = " La suma almacenada no incluía la X como una unidad." if tiene_equis else ""
            notas.append(f"{hoja.title}!P{numero}: cantidad original almacenada {cantidad_hoja}; suma mensual revisada {cantidad}.{detalle} AUTORIZADO no constituye una aprobación en la aplicación.")
        costo = None
        try:
            if celdas[16].data_type in ("f", "e"):
                raise ValueError("El costo de cada producto debe ser un importe literal; no se ejecutan fórmulas ni se acepta un costo desconocido por falta de caché.")
            costo = _importe(celdas[16].value)
        except ValueError as fallo:
            error("Q", str(fallo))
        referencial = None
        if cantidad is not None and costo is not None:
            if cantidad <= 0:
                notas.append("Presupuesto anual sin cantidad programada; precio unitario no informado.")
            else:
                with localcontext() as contexto:
                    contexto.prec = 40
                    precio = (costo / Decimal(cantidad)).quantize(CENTAVO, rounding=ROUND_HALF_UP)
                    if precio > Decimal("999999999999.99"):
                        error("Q", "El precio unitario referencial supera el límite de la aplicación.")
                    else:
                        referencial = format(precio, ".2f")
                        diferencia = Decimal(cantidad) * precio - costo
                        if diferencia:
                            notas.append(f"Precio unitario referencial redondeado a dos decimales; cantidad por precio difiere del presupuesto original en {diferencia:.2f}. El costo anual de origen se conserva sin cambios.")
        lineas.append({
            "fila": numero, "producto_servicio": textos[0], "dependencia": textos[1], "serie": textos[2],
            "meses": meses, "cantidad_total": cantidad, "cantidad_hoja": cantidad_hoja,
            "costo_proyectado_total": format(costo, ".2f") if costo is not None else None,
            "costo_original": str(celdas[16].value) if celdas[16].value is not None else "",
            "precio_estimado_referencial": referencial, "observaciones": notas,
            "importable": not errores, "errores": errores,
        })
    if anio is None or not lineas:
        raise ValidationError(f"{hoja.title}: falta el año o no hay productos para revisar.")
    conocido = sum((Decimal(linea["costo_proyectado_total"]) for linea in lineas if linea["costo_proyectado_total"] is not None), Decimal(0))
    completo = all(linea["costo_proyectado_total"] is not None for linea in lineas)
    ultima_linea = max(linea["fila"] for linea in lineas)
    for fila, formula, valor in totales:
        normalizada = re.sub(r"\s+", "", str(formula)).replace("$", "").upper()
        if normalizada not in (f"=SUM(Q7:Q{ultima_linea})", f"=SUMA(Q7:Q{ultima_linea})") or fila <= ultima_linea:
            errores_area.append({"celda": f"Q{fila}", "valor_original": str(formula), "error": "Fórmula de total de hoja no reconocida."})
            continue
        if valor is None:
            observaciones.append(f"Q{fila}: el total de hoja no tiene caché; se conserva la suma de los importes literales, sin ejecutar fórmulas.")
        else:
            try:
                total_guardado = _importe(valor)
                if completo and total_guardado != conocido:
                    observaciones.append(f"Q{fila}: total almacenado {total_guardado:.2f}; suma de costos de origen {conocido:.2f}.")
            except ValueError as fallo:
                errores_area.append({"celda": f"Q{fila}", "valor_original": _original(valor), "error": str(fallo)})
    pendientes = [linea for linea in lineas if not linea["importable"]]
    return {"anio": anio, "nombre": hoja.title.strip(), "hoja": hoja.title, "lineas": lineas,
            "costo_proyectado_total": format(conocido, ".2f") if completo else None,
            "costo_conocido_total": format(conocido, ".2f"),
            "costo_lineas_pendientes": format(sum((Decimal(linea["costo_proyectado_total"]) for linea in pendientes if linea["costo_proyectado_total"] is not None), Decimal(0)), ".2f"),
            "lineas_importables": len(lineas) - len(pendientes), "lineas_pendientes": len(pendientes),
            "observaciones": observaciones, "errores": errores_area}


def leer_consolidado(archivo, *, equis_como_unidad=False):
    """Devuelve datos y pendientes serializables; nunca modifica el archivo ni la base."""
    if type(equis_como_unidad) is not bool:
        raise ValidationError("La interpretación de X debe confirmarse mediante un booleano explícito.")
    if Path(getattr(archivo, "name", "")).suffix.casefold() != ".xlsx":
        raise ValidationError("Seleccione un archivo .xlsx del consolidado FR-GDS-11.")
    contenido = archivo.read(MAX_BYTES + 1)
    if not isinstance(contenido, bytes) or len(contenido) > MAX_BYTES:
        raise ValidationError("El consolidado supera el máximo de 20 MB o no es un archivo binario válido.")
    libro = cache = None
    try:
        with ZipFile(BytesIO(contenido)) as comprimido:
            entradas = comprimido.infolist()
            nombres = [entrada.filename for entrada in entradas]
            if len(entradas) > MAX_ENTRADAS or len(nombres) != len(set(nombres)) or sum(entrada.file_size for entrada in entradas) > MAX_DESCOMPRIMIDO:
                raise ValidationError("El consolidado supera los límites de contenido descomprimido o contiene entradas duplicadas.")
            if any("vbaproject" in nombre.casefold() for nombre in nombres):
                raise ValidationError("No se admiten archivos con macros.")
        libro = load_workbook(BytesIO(contenido), read_only=True, data_only=False, keep_links=False)
        cache = load_workbook(BytesIO(contenido), read_only=True, data_only=True, keep_links=False)
        if len(libro.worksheets) > MAX_HOJAS:
            raise ValidationError(f"El consolidado admite hasta {MAX_HOJAS} hojas.")
        areas, observaciones, presupuesto = [], [], [0]
        for hoja in libro.worksheets:
            ultima_fila = _validar_fuente(hoja, presupuesto)
            if _normalizar(hoja.title) == "CONTROL":
                observaciones.append(f"Hoja {hoja.title!r} omitida expresamente por ser de control.")
                continue
            areas.append(_leer_area(hoja, cache[hoja.title], ultima_fila, equis_como_unidad))
        if not areas or len({area["anio"] for area in areas}) != 1:
            raise ValidationError("El consolidado debe incluir áreas del mismo año.")
        conocido = sum((Decimal(area["costo_conocido_total"]) for area in areas), Decimal(0))
        return {"anio": areas[0]["anio"], "areas": areas,
                "costo_proyectado_total": format(conocido, ".2f") if all(area["costo_proyectado_total"] is not None for area in areas) else None,
                "costo_conocido_total": format(conocido, ".2f"),
                "costo_lineas_pendientes": format(sum((Decimal(area["costo_lineas_pendientes"]) for area in areas), Decimal(0)), ".2f"),
                "lineas_importables": sum(area["lineas_importables"] for area in areas),
                "lineas_pendientes": sum(area["lineas_pendientes"] for area in areas),
                "observaciones": observaciones, "archivo_sha256": hashlib.sha256(contenido).hexdigest()}
    except ValidationError:
        raise
    except (BadZipFile, InvalidFileException, ParseError, KeyError, ValueError, TypeError, OSError, EOFError, RuntimeError, OverflowError):
        raise ValidationError("El archivo no es un consolidado .xlsx válido o está dañado.") from None
    finally:
        if libro is not None:
            libro.close()
        if cache is not None:
            cache.close()
