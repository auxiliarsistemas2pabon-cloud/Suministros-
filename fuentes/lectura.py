"""Lectura acotada de los valores originales de XLSX, sin ejecutar sus fórmulas."""
from pathlib import PurePosixPath
from zipfile import ZipFile
import re
import xml.etree.ElementTree as ET

from django.core.exceptions import ValidationError

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


def leer_libro(path):
    with ZipFile(path) as archivo:
        if sum(i.file_size for i in archivo.infolist()) > 70_000_000 or len(archivo.infolist()) > 2500:
            raise ValidationError("El Excel supera el límite técnico de lectura.")
        cadenas = []
        if "xl/sharedStrings.xml" in archivo.namelist():
            cadenas = ["".join(si.itertext()) for si in ET.fromstring(archivo.read("xl/sharedStrings.xml")).findall("m:si", NS)]
        relaciones = {r.get("Id"): r.get("Target") for r in ET.fromstring(archivo.read("xl/_rels/workbook.xml.rels"))}
        resultado = []
        total = 0
        for hoja in ET.fromstring(archivo.read("xl/workbook.xml")).findall("m:sheets/m:sheet", NS):
            destino = relaciones[hoja.get(REL)]
            destino = destino.lstrip("/") if destino.startswith("/") else "xl/" + destino
            if ".." in PurePosixPath(destino).parts:
                raise ValidationError("Relación de hoja inválida.")
            celdas, formulas = {}, {}
            for celda in ET.fromstring(archivo.read(destino)).findall(".//m:sheetData/m:row/m:c", NS):
                valor = celda.find("m:v", NS)
                texto = valor.text if valor is not None else ""
                if celda.get("t") == "s" and texto:
                    texto = cadenas[int(texto)]
                elif celda.get("t") == "inlineStr":
                    texto = "".join(celda.find("m:is", NS).itertext())
                if texto:
                    celdas[celda.get("r")] = texto
                    total += 1
                    if total > 250_000:
                        raise ValidationError("El Excel supera el máximo de celdas con información.")
                formula = celda.find("m:f", NS)
                if formula is not None and formula.text:
                    formulas[celda.get("r")] = formula.text
            resultado.append({"nombre": hoja.get("name"), "celdas": celdas, "formulas": formulas})
        return resultado


def compras_historicas(libro):
    for hoja in libro:
        celdas = hoja["celdas"]
        encabezados = [a for a, v in celdas.items() if "ORDEN DE COMPRA (si aplica)" in v]
        if not encabezados:
            continue
        direccion = encabezados[0]
        columna = re.match(r"[A-Z]+", direccion)[0]
        inicio = int(re.search(r"\d+", direccion)[0])
        desplazamiento = 1 if columna == "D" else 0
        for direccion, numero in celdas.items():
            if not re.fullmatch(columna + r"\d+", direccion):
                continue
            fila = int(re.search(r"\d+", direccion)[0])
            if fila <= inicio or numero.strip().upper() in {"N/A", "NA", "NO APLICA", ""}:
                continue
            def dato(col):
                return celdas.get(f"{chr(ord(col) + desplazamiento)}{fila}", "")
            yield {"hoja": hoja["nombre"], "fila": fila, "orden_original": numero.strip(), "fecha_comite": dato("B"),
                   "proveedor_original": dato("F"), "objeto": dato("G"), "valor_original": dato("H"),
                   "seguimientos": [dato(c) for c in "LMNO"]}


def elegibles_historicos(libro):
    for hoja in libro:
        celdas = hoja["celdas"]
        for direccion, valor in celdas.items():
            if not re.fullmatch(r"E\d+", direccion) or valor.strip().upper() != "CRITERIOS ADM":
                continue
            fila = int(direccion[1:])
            proveedor = celdas.get(f"D{fila}", "").strip()
            if proveedor:
                yield {"hoja": hoja["nombre"], "fila": fila, "proveedor": proveedor,
                       "area_original": celdas.get(f"C{fila}", ""), "objeto": celdas.get(f"B{fila}", ""),
                       "puntaje_original": celdas.get(f"J{fila}", ""), "puesto_original": celdas.get(f"K{fila}", ""),
                       "observaciones": celdas.get(f"M{fila}", "")}
