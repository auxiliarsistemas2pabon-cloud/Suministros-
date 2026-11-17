"""El FR11 se analiza sin escrituras ni datos inventados para completar omisiones."""

import hashlib
from io import BytesIO
import json
from unittest.mock import patch
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase
from openpyxl import Workbook
from openpyxl.styles import PatternFill

from proyecciones.fr11_origen import ENCABEZADOS, leer_consolidado

NAMESPACE = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def archivo(libro, caches=None, cambiar_xml=None):
    salida = BytesIO()
    libro.save(salida)
    contenido = salida.getvalue()
    if caches or cambiar_xml:
        reemplazo = BytesIO()
        with ZipFile(BytesIO(contenido)) as original, ZipFile(reemplazo, "w") as destino:
            for entrada in original.infolist():
                valor = original.read(entrada.filename)
                if entrada.filename.startswith("xl/worksheets/sheet") and entrada.filename.endswith(".xml"):
                    raiz = ET.fromstring(valor)
                    for celda in raiz.findall(f".//{{{NAMESPACE}}}c"):
                        clave = (entrada.filename, celda.attrib["r"])
                        if clave in (caches or {}):
                            cache = celda.find(f"{{{NAMESPACE}}}v")
                            if cache is None:
                                cache = ET.SubElement(celda, f"{{{NAMESPACE}}}v")
                            cache.text = str(caches[clave])
                    if cambiar_xml:
                        cambiar_xml(raiz, entrada.filename)
                    valor = ET.tostring(raiz, encoding="utf-8")
                destino.writestr(entrada, valor)
        contenido = reemplazo.getvalue()
    fuente = BytesIO(contenido)
    fuente.name = "consolidado_ficticio.xlsx"
    return fuente


def libro_area(nombre="Área ficticia", *, meses=None, costo="12.00", formula=None, autorizada=None):
    libro = Workbook()
    hoja = libro.active
    hoja.title = nombre
    hoja["A5"] = "AÑO 2026"
    for columna, encabezado in enumerate(ENCABEZADOS, 1):
        hoja.cell(6, columna, encabezado)
    hoja.append(["Producto ficticio", nombre, "N/A", *(meses if meses is not None else [1] * 12), formula or (autorizada if autorizada is not None else 12), costo])
    return libro, hoja


class ConsolidadoOrigenTests(SimpleTestCase):
    def test_areas_total_exacto_y_salida_serializable_sin_cambiar_el_archivo(self):
        libro, hoja = libro_area(costo="$ 8,000,000.00")
        dos = libro.copy_worksheet(hoja)
        dos.title = "Otra área ficticia"
        dos["Q7"] = 471200756.25
        control = libro.create_sheet("control")
        control["A1"] = "Texto de control que no se ejecuta ni se importa."
        fuente = archivo(libro)
        contenido = fuente.getvalue()
        datos = leer_consolidado(fuente)
        self.assertEqual(datos["anio"], 2026)
        self.assertEqual(len(datos["areas"]), 2)
        self.assertEqual(datos["costo_proyectado_total"], "479200756.25")
        self.assertEqual(datos["lineas_importables"], 2)
        self.assertIn("control", datos["observaciones"][0])
        self.assertEqual(datos["archivo_sha256"], hashlib.sha256(contenido).hexdigest())
        self.assertEqual(fuente.getvalue(), contenido)
        json.dumps(datos, allow_nan=False)

    def test_x_requiere_confirmacion_y_conserva_celda_y_suma_original(self):
        meses = [1] + [0] * 9 + ["x", 0]
        libro, _ = libro_area(meses=meses, costo=6, formula="=SUM(D7:O7)")
        caches = {("xl/worksheets/sheet1.xml", "P7"): 1}
        sin_confirmar = leer_consolidado(archivo(libro, caches))["areas"][0]["lineas"][0]
        self.assertFalse(sin_confirmar["importable"])
        self.assertIsNone(sin_confirmar["cantidad_total"])
        self.assertEqual(sin_confirmar["errores"][0]["celda"], "N7")
        self.assertEqual(sin_confirmar["errores"][0]["valor_original"], "x")
        confirmada = leer_consolidado(archivo(libro, caches), equis_como_unidad=True)["areas"][0]["lineas"][0]
        self.assertTrue(confirmada["importable"])
        self.assertEqual(confirmada["cantidad_total"], 2)
        self.assertEqual(confirmada["cantidad_hoja"], 1)
        self.assertEqual(confirmada["precio_estimado_referencial"], "3.00")
        self.assertIn("N7", " ".join(confirmada["observaciones"]))
        self.assertIn("original 'x'", " ".join(confirmada["observaciones"]))
        self.assertIn("no incluía la X", " ".join(confirmada["observaciones"]))
        self.assertNotIn("cantidad_autorizada", confirmada)

    def test_meses_pendientes_se_conservan_sin_omitir_la_fila_ni_su_presupuesto(self):
        meses = [1] * 12
        meses[5] = meses[8] = None
        libro, hoja = libro_area(meses=meses, costo="25.75", autorizada=10)
        hoja.append(["Otro producto ficticio", hoja.title, "N/A", *([1] * 12), 12, "12.00"])
        datos = leer_consolidado(archivo(libro))
        fila = datos["areas"][0]["lineas"][0]
        self.assertEqual(len(fila["meses"]), 12)
        self.assertIsNone(fila["meses"][5])
        self.assertIsNone(fila["meses"][8])
        self.assertIsNone(fila["cantidad_total"])
        self.assertIsNone(fila["precio_estimado_referencial"])
        self.assertEqual({error["celda"] for error in fila["errores"]}, {"I7", "L7"})
        self.assertEqual(datos["costo_proyectado_total"], "37.75")
        self.assertEqual(datos["costo_lineas_pendientes"], "25.75")
        self.assertEqual(datos["lineas_importables"], 1)
        self.assertEqual(datos["lineas_pendientes"], 1)

    def test_division_referencial_redondea_y_conserva_costo_total_de_origen(self):
        libro, _ = libro_area(meses=[3] + [0] * 11, costo="10.00", autorizada=3)
        fila = leer_consolidado(archivo(libro))["areas"][0]["lineas"][0]
        self.assertTrue(fila["importable"])
        self.assertEqual(fila["precio_estimado_referencial"], "3.33")
        self.assertEqual(fila["costo_proyectado_total"], "10.00")
        self.assertEqual(fila["costo_original"], "10.00")
        self.assertIn("-0.01", " ".join(fila["observaciones"]))

    def test_suma_literal_de_meses_y_formula_sum_solo_se_reconocen_no_se_ejecutan(self):
        for formula in ("=SUM(D7:O7)", "=SUMA($D$7:$O$7)", "=" + "+".join(f"{c}7" for c in "DEFGHIJKLMNO")):
            with self.subTest(formula=formula):
                libro, _ = libro_area(formula=formula)
                fila = leer_consolidado(archivo(libro))["areas"][0]["lineas"][0]
                self.assertTrue(fila["importable"])
                self.assertIsNone(fila["cantidad_hoja"])
                self.assertEqual(fila["cantidad_total"], 12)
                self.assertIn("sin ejecutar", " ".join(fila["observaciones"]))

    def test_formula_ajena_o_costo_formula_son_pendientes_no_datos_cero(self):
        libro, hoja = libro_area(formula="=SUM(D8:O8)", costo="=1+1")
        hoja.append(["Fila válida ficticia", hoja.title, "N/A", *([1] * 12), 12, 2])
        datos = leer_consolidado(archivo(libro))
        fila = datos["areas"][0]["lineas"][0]
        self.assertFalse(fila["importable"])
        self.assertEqual({error["celda"] for error in fila["errores"]}, {"P7", "Q7"})
        self.assertIsNone(fila["costo_proyectado_total"])
        self.assertEqual(fila["costo_original"], "=1+1")
        self.assertIsNone(datos["costo_proyectado_total"])
        self.assertEqual(datos["costo_conocido_total"], "2.00")
        self.assertEqual(datos["lineas_importables"], 1)

    def test_no_admite_cantidades_negativas_booleanas_fraccionarias_o_formulas(self):
        for valor in (-1, True, "1.5", "=1+1", "desconocido"):
            with self.subTest(valor=valor):
                libro, _ = libro_area(meses=[valor] + [0] * 11)
                fila = leer_consolidado(archivo(libro))["areas"][0]["lineas"][0]
                self.assertFalse(fila["importable"])
                self.assertIsNone(fila["meses"][0])
                self.assertEqual(fila["errores"][0]["celda"], "D7")

    def test_importes_invalidos_no_se_confunden_con_ceros(self):
        for valor in (None, "", "sin dato", "$ -1.00", "1.000,50", "1.234", True):
            with self.subTest(valor=valor):
                libro, _ = libro_area(costo=valor)
                datos = leer_consolidado(archivo(libro))
                fila = datos["areas"][0]["lineas"][0]
                self.assertFalse(fila["importable"])
                self.assertIsNone(fila["costo_proyectado_total"])
                self.assertIsNone(datos["costo_proyectado_total"])
                self.assertEqual(fila["errores"][0]["celda"], "Q7")

    def test_costo_cero_explicito_es_valido_y_no_es_un_costo_omitido(self):
        libro, _ = libro_area(costo=0)
        datos = leer_consolidado(archivo(libro))
        self.assertTrue(datos["areas"][0]["lineas"][0]["importable"])
        self.assertEqual(datos["costo_proyectado_total"], "0.00")

    def test_fila_sin_cantidad_positiva_no_inventa_precio_unitario(self):
        libro, _ = libro_area(meses=[0] * 12, costo=3, autorizada=0)
        fila = leer_consolidado(archivo(libro))["areas"][0]["lineas"][0]
        self.assertTrue(fila["importable"])
        self.assertIsNone(fila["precio_estimado_referencial"])
        self.assertEqual(fila["costo_proyectado_total"], "3.00")
        self.assertEqual(fila["cantidad_total"], 0)
        self.assertIn("precio unitario no informado", " ".join(fila["observaciones"]))

    def test_total_de_hoja_se_reconoce_sin_crear_un_producto(self):
        libro, hoja = libro_area(costo=12)
        hoja["Q8"] = "=SUM(Q7:Q7)"
        datos = leer_consolidado(archivo(libro))
        area = datos["areas"][0]
        self.assertEqual(len(area["lineas"]), 1)
        self.assertEqual(area["costo_proyectado_total"], "12.00")
        self.assertIn("sin ejecutar fórmulas", " ".join(area["observaciones"]))
        self.assertEqual(area["errores"], [])

    def test_total_de_hoja_no_reconocido_o_diferente_queda_señalado(self):
        libro, hoja = libro_area(costo=12)
        hoja["Q8"] = "=SUM(Q7:Q7)"
        cache = {("xl/worksheets/sheet1.xml", "Q8"): 100}
        area = leer_consolidado(archivo(libro, cache))["areas"][0]
        self.assertIn("100.00", " ".join(area["observaciones"]))
        self.assertEqual(area["costo_proyectado_total"], "12.00")
        hoja["Q8"] = "=SUM(Q7:Q50)"
        area = leer_consolidado(archivo(libro))["areas"][0]
        self.assertEqual(area["errores"][0]["celda"], "Q8")

    def test_no_omite_hojas_mezcladas_con_encabezados_o_anios_distintos(self):
        libro, hoja = libro_area()
        otra = libro.copy_worksheet(hoja)
        otra.title = "Otra área"
        otra["A5"] = "AÑO 2027"
        with self.assertRaises(ValidationError):
            leer_consolidado(archivo(libro))
        otra["A5"] = "AÑO 2026"
        otra["B6"] = "Otro encabezado"
        with self.assertRaises(ValidationError):
            leer_consolidado(archivo(libro))

    def test_solo_control_y_hojas_vacias_no_se_presentan_como_consolidado(self):
        libro = Workbook()
        libro.active.title = "control"
        with self.assertRaises(ValidationError):
            leer_consolidado(archivo(libro))
        libro.create_sheet("Sin datos")
        with self.assertRaises(ValidationError):
            leer_consolidado(archivo(libro))

    def test_formato_vacio_hasta_aa_se_tolerea_pero_datos_fuera_de_q_no(self):
        libro, hoja = libro_area()
        hoja["AA20"].fill = PatternFill("solid", fgColor="172554")
        self.assertEqual(leer_consolidado(archivo(libro))["lineas_importables"], 1)
        hoja["R7"] = "Dato fuera del esquema"
        with self.assertRaises(ValidationError):
            leer_consolidado(archivo(libro))

    def test_dimension_falsa_no_oculta_productos(self):
        libro, _ = libro_area()

        def ocultar(raiz, nombre):
            raiz.find(f"{{{NAMESPACE}}}dimension").set("ref", "A1")

        self.assertEqual(leer_consolidado(archivo(libro, cambiar_xml=ocultar))["lineas_importables"], 1)

    def test_limites_reales_y_celdas_fuera_de_rango_se_rechazan(self):
        libro, hoja = libro_area()
        hoja["A5001"] = "Fuera del límite"
        with self.assertRaises(ValidationError):
            leer_consolidado(archivo(libro))
        libro, hoja = libro_area()
        hoja["EA1"] = "Fuera de columnas permitidas"
        with self.assertRaises(ValidationError):
            leer_consolidado(archivo(libro))

    def test_archivo_dañado_extension_macros_y_limite_zip(self):
        libro, _ = libro_area()
        fuente = archivo(libro)
        fuente.name = "consolidado.xls"
        with self.assertRaises(ValidationError):
            leer_consolidado(fuente)
        fuente = BytesIO("archivo ficticio dañado".encode("utf-8"))
        fuente.name = "consolidado.xlsx"
        with self.assertRaises(ValidationError):
            leer_consolidado(fuente)
        fuente = archivo(libro)
        contenido = BytesIO(fuente.getvalue())
        with ZipFile(contenido, "a") as comprimido:
            comprimido.writestr("xl/vbaProject.bin", b"macro ficticia")
        contenido.name = "macro.xlsx"
        contenido.seek(0)
        with self.assertRaises(ValidationError):
            leer_consolidado(contenido)
        with patch("proyecciones.fr11_origen.MAX_DESCOMPRIMIDO", 1):
            with self.assertRaises(ValidationError):
                leer_consolidado(archivo(libro))

    def test_confirmacion_de_x_no_admite_texto_verdadero_por_accidente(self):
        libro, _ = libro_area()
        with self.assertRaises(ValidationError):
            leer_consolidado(archivo(libro), equis_como_unidad="false")
