"""Lectura del CSV FR14 sin cambios en la base de datos."""

import csv
from io import StringIO

from django.core.exceptions import ValidationError

from config.utilidades import normalizar_espacios
from proveedores.models import Requisito

MAX_BYTES = 2 * 1024 * 1024
MAX_FILAS = 5000
COLUMNAS = ["grupo", "numero", "texto", "categoria", "peso"]


def leer_csv(archivo):
    contenido = archivo.read(MAX_BYTES + 1)
    if not isinstance(contenido, bytes):
        raise ValidationError("Abra el CSV como archivo binario UTF-8.")
    if len(contenido) > MAX_BYTES:
        raise ValidationError("El CSV supera los 2 MB.")
    try:
        texto = contenido.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValidationError("Guarde el CSV con codificación UTF-8.") from None
    if "\x00" in texto:
        raise ValidationError("El CSV contiene caracteres nulos no permitidos.")
    lector = csv.DictReader(StringIO(texto, newline=""), strict=True)
    filas, errores, pares, requisitos = [], [], set(), {}
    try:
        if lector.fieldnames != COLUMNAS:
            raise ValidationError("Encabezados esperados: grupo,numero,texto,categoria,peso (separados por coma).")
        for indice, fila in enumerate(lector, start=1):
            numero_fila = lector.line_num
            if indice > MAX_FILAS:
                raise ValidationError(f"El CSV supera las {MAX_FILAS} filas.")
            if None in fila or any(v is None for v in fila.values()):
                errores.append(f"Fila {numero_fila}: faltan o sobran columnas.")
                continue
            fila = {c: v.strip() for c, v in fila.items()}
            if not any(fila.values()):
                continue
            grupo, numero, texto, categoria, peso = (fila[c] for c in COLUMNAS)
            categoria = normalizar_espacios(categoria)
            if grupo not in Requisito.Grupo.values:
                errores.append(f"Fila {numero_fila}: grupo inválido (calidad, ambiental o sgsst).")
                continue
            if not numero.isascii() or not numero.isdecimal() or not 1 <= int(numero) <= 32767:
                errores.append(f"Fila {numero_fila}: número de requisito inválido (1 a 32767).")
                continue
            numero = int(numero)
            if not texto or len(texto) > 20000 or not categoria or len(categoria) > 120 or peso not in ("1", "2"):
                errores.append(f"Fila {numero_fila}: revise texto, categoría (máximo 120 caracteres) y peso (1 o 2).")
                continue
            par = (numero, categoria.casefold())
            if par in pares:
                errores.append(f"Fila {numero_fila}: requisito y categoría duplicados dentro del CSV.")
                continue
            if numero in requisitos and requisitos[numero] != (grupo, texto):
                errores.append(f"Fila {numero_fila}: grupo o texto inconsistente para el requisito {numero}.")
                continue
            pares.add(par)
            requisitos[numero] = (grupo, texto)
            filas.append({"grupo": grupo, "numero": numero, "texto": texto, "categoria": categoria, "valor": int(peso)})
    except csv.Error:
        raise ValidationError(f"CSV inválido cerca de la fila {lector.line_num}.") from None
    if errores:
        raise ValidationError(errores)
    if not filas:
        raise ValidationError("El CSV no contiene requisitos.")
    return filas
