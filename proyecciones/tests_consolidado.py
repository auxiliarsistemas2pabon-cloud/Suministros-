"""GDS-PRY-06: consolidado por año y área y exportación a Excel."""

from datetime import date
from decimal import Decimal
from io import BytesIO

from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from proyecciones import consolidado, servicios
from proyecciones.exportar import FORMATO_MONEDA, nombre_hoja
from proyecciones.models import CAMPOS_CANTIDADES_MENSUALES, Linea, Periodo, ProyeccionArea
from proyecciones.tests_revision import MOTIVO, BaseRevision

CENTAVO = Decimal("0.01")


def esperado(proyecciones):
    """Totales calculados en Python, línea por línea, para comparar con la base de datos."""
    lineas = servicios.anotar_vigentes(
        Linea.objects.filter(proyeccion__in=proyecciones).prefetch_related("ajustes")
    )
    autorizadas = [linea.cantidad_autorizada for linea in lineas if linea.cantidad_autorizada is not None]
    ajustadas = [linea.vigente["cantidad_autorizada"] for linea in lineas if linea.vigente["cantidad_autorizada"] is not None]
    return {
        "numero_lineas": len(lineas),
        "meses": [sum(getattr(linea, campo) for linea in lineas) for campo in CAMPOS_CANTIDADES_MENSUALES],
        "total_anual": sum(linea.total_anual for linea in lineas),
        "costo": sum((linea.costo_anual for linea in lineas), Decimal("0")).quantize(CENTAVO),
        "cantidad_autorizada": sum(autorizadas) if autorizadas else None,
        "cantidad_ajustada": sum(ajustadas) if ajustadas else None,
        "total_ajustado": sum(linea.total_vigente for linea in lineas),
        "costo_ajustado": sum((linea.costo_vigente for linea in lineas), Decimal("0")).quantize(CENTAVO),
    }


def comparable(fila):
    return {clave: fila[clave] for clave in esperado(ProyeccionArea.objects.none())}


class BaseConsolidado(BaseRevision):
    def setUp(self):
        super().setUp()
        self.periodo_anterior = Periodo.objects.create(
            anio=2030,
            fecha_apertura=date(2030, 1, 1),
            fecha_limite_diligenciamiento=date(2030, 12, 15),
            creado_por=self.administrador,
            estado=Periodo.Estado.CERRADO,
        )
        self.proyeccion_anterior = ProyeccionArea.objects.create(
            periodo=self.periodo_anterior,
            area=self.area,
            estado=ProyeccionArea.Estado.ENVIADA,
            fecha_envio=timezone.now(),
            enviado_por=self.coordinador,
        )
        Linea.objects.create(
            proyeccion=self.proyeccion_anterior,
            producto_servicio="Gasas ficticias",
            unidad=self.unidad,
            cantidad_junio=40,
            precio_estimado=Decimal("0.75"),
        )
        # Proyección aprobada con ajustes: cantidad autorizada 5 → 3, precio 12,50 → 13,00 y enero 2 → 4.
        servicios.aprobar_proyeccion(self.proyeccion, actor=self.administrador, motivo=MOTIVO)
        for campo, valor in (("cantidad_autorizada", "3"), ("precio_estimado", "13.00"), ("cantidad_enero", "4")):
            servicios.registrar_ajuste(
                self.linea, campo, valor, actor=self.administrador, justificacion="Ajuste ficticio"
            )
        self.url = reverse("proyecciones:consolidado")
        self.url_exportar = reverse("proyecciones:consolidado_exportar")


class ConsolidadoTests(BaseConsolidado):
    def test_revision_muestra_costos_original_y_vigente_del_mismo_filtro(self):
        self.client.force_login(self.administrador)
        respuesta = self.client.get(reverse("proyecciones:revision"), {"periodo": self.periodo.pk, "area": self.area.pk})
        esperado_total = consolidado.totales(servicios.filtrar_proyecciones(periodo=self.periodo, area=self.area))
        self.assertEqual(respuesta.context["costo_total"], esperado_total["costo"])
        self.assertEqual(respuesta.context["costo_vigente"], esperado_total["costo_ajustado"])
        self.assertEqual(respuesta.context["pagina"][0].costo_vigente, esperado_total["costo_ajustado"])
        self.assertContains(respuesta, "Costo vigente")

    def test_exportacion_conserva_textos_que_parecen_formulas(self):
        from proyecciones.exportar import exportar_consolidado

        self.linea.producto_servicio = "=1+1"
        self.linea.dependencia = "=HYPERLINK(\"https://ejemplo.test\")"
        self.linea.save()
        datos = exportar_consolidado(servicios.filtrar_proyecciones(periodo=self.periodo, area=self.area))
        libro = load_workbook(BytesIO(datos), data_only=False)
        celda = libro["FAR 2031"]["A5"]
        self.assertEqual(celda.value, "=1+1")
        self.assertEqual(celda.data_type, "s")
        self.assertEqual(libro["FAR 2031"]["B5"].data_type, "s")

    def test_totales_coinciden_con_las_lineas_de_cada_filtro(self):
        casos = {
            "periodo 2031": servicios.filtrar_proyecciones(periodo=self.periodo),
            "periodo 2030": servicios.filtrar_proyecciones(periodo=self.periodo_anterior),
            "área FAR, todos los periodos": servicios.filtrar_proyecciones(area=self.area),
            "aprobadas": servicios.filtrar_proyecciones(estado=ProyeccionArea.Estado.APROBADA),
            "borradores": servicios.filtrar_proyecciones(estado=ProyeccionArea.Estado.BORRADOR),
            "todo": servicios.filtrar_proyecciones(),
        }
        for nombre, consulta in casos.items():
            with self.subTest(filtro=nombre):
                self.assertEqual(comparable(consolidado.totales(consulta)), esperado(consulta))
                for fila in consolidado.filas_por_area(consulta):
                    self.assertEqual(
                        comparable(fila), esperado(ProyeccionArea.objects.filter(pk=fila["proyeccion"].pk))
                    )

    def test_valores_conocidos_con_ajustes(self):
        fila = next(
            f for f in consolidado.filas_por_area(servicios.filtrar_proyecciones(periodo=self.periodo))
            if f["codigo_area"] == "FAR"
        )
        self.assertEqual(fila["numero_lineas"], 2)
        self.assertEqual(fila["meses"][0], 12)  # 2 + 10 (valores aprobados)
        self.assertEqual(fila["total_anual"], 15)
        self.assertEqual(fila["costo"], Decimal("73.50"))  # 5 × 12,50 + 10 × 1,10
        self.assertEqual(fila["cantidad_autorizada"], 15)  # 5 + 10 al aprobar
        self.assertEqual(fila["cantidad_ajustada"], 13)  # 3 + 10
        self.assertEqual(fila["total_ajustado"], 17)  # (4 + 3) + 10
        self.assertEqual(fila["costo_ajustado"], Decimal("102.00"))  # 7 × 13,00 + 10 × 1,10
        self.assertIsInstance(fila["costo_ajustado"], Decimal)

    def test_proyeccion_sin_lineas_aparece_en_cero(self):
        Linea.objects.filter(proyeccion=self.otra_proyeccion).delete()
        fila = consolidado.filas_por_area(servicios.filtrar_proyecciones(area=self.otra_area))[0]
        self.assertEqual(fila["numero_lineas"], 0)
        self.assertEqual(fila["meses"], [0] * 12)
        self.assertEqual(fila["costo"], Decimal("0.00"))
        self.assertIsNone(fila["cantidad_autorizada"])
        self.assertIsNone(fila["cantidad_ajustada"])

    def test_vista_usa_el_filtro_y_el_periodo_por_defecto(self):
        self.client.force_login(self.administrador)
        respuesta = self.client.get(self.url)
        self.assertEqual({fila["anio"] for fila in respuesta.context["filas"]}, {2031})
        consulta = servicios.filtrar_proyecciones(periodo=self.periodo)
        self.assertEqual(comparable(respuesta.context["total"]), esperado(consulta))
        self.assertContains(respuesta, "102,00")

        respuesta = self.client.get(self.url, {"periodo": "", "area": self.area.pk})
        self.assertEqual({(f["anio"], f["codigo_area"]) for f in respuesta.context["filas"]}, {(2031, "FAR"), (2030, "FAR")})
        self.assertContains(respuesta, f"{reverse('proyecciones:consolidado_exportar')}?periodo=&amp;area={self.area.pk}")


class ExportarTests(BaseConsolidado):
    def libro(self, **filtros):
        self.client.force_login(self.administrador)
        respuesta = self.client.get(self.url_exportar, filtros)
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(
            respuesta["Content-Type"], "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        self.assertIn("attachment;", respuesta["Content-Disposition"])
        self.assertEqual(respuesta["X-Content-Type-Options"], "nosniff")
        return respuesta, load_workbook(BytesIO(respuesta.content))

    @staticmethod
    def decimal(valor):
        return None if valor is None else Decimal(str(valor)).quantize(CENTAVO)

    def fila_resumen(self, hoja, numero):
        valores = [celda.value for celda in hoja[numero]]
        return {
            "numero_lineas": valores[4],
            "meses": valores[5:17],
            "total_anual": valores[17],
            "costo": self.decimal(valores[18]),
            "cantidad_autorizada": valores[19],
            "cantidad_ajustada": valores[20],
            "total_ajustado": valores[21],
            "costo_ajustado": self.decimal(valores[22]),
        }

    def test_excel_tiene_los_mismos_valores_que_el_consolidado(self):
        respuesta, libro = self.libro(periodo=self.periodo.pk)
        self.assertIn('filename="consolidado-proyecciones-2031.xlsx"', respuesta["Content-Disposition"])
        self.assertEqual(libro.sheetnames, ["Resumen", "FAR 2031", "LAB 2031"])
        resumen = libro["Resumen"]
        consulta = servicios.filtrar_proyecciones(periodo=self.periodo)
        filas = consolidado.filas_por_area(consulta)
        for numero, fila in enumerate(filas, start=5):
            with self.subTest(area=fila["codigo_area"]):
                self.assertEqual(resumen.cell(row=numero, column=2).value, fila["area"])
                self.assertEqual(self.fila_resumen(resumen, numero), comparable(fila))
        fila_total = 5 + len(filas)
        self.assertEqual(resumen.cell(row=fila_total, column=1).value, "Total")
        self.assertEqual(self.fila_resumen(resumen, fila_total), esperado(consulta))

    def test_hoja_por_area_con_lineas_y_totales(self):
        _, libro = self.libro(periodo=self.periodo.pk)
        hoja = libro["FAR 2031"]
        filas = list(hoja.iter_rows(min_row=5, values_only=True))
        lineas, total = filas[:-1], filas[-1]
        self.assertEqual([fila[0] for fila in lineas], ["Guantes de examen", "Jeringas de 5 ml"])
        guantes = lineas[0]
        self.assertEqual(guantes[3], 2)  # enero aprobado
        self.assertEqual(guantes[15], 5)  # total anual aprobado
        self.assertEqual(self.decimal(guantes[16]), Decimal("12.50"))
        self.assertEqual(self.decimal(guantes[17]), Decimal("62.50"))
        self.assertEqual(guantes[18], 5)  # autorizada
        self.assertEqual(guantes[19], 3)  # ajustada
        self.assertEqual(guantes[20], 7)  # total ajustado
        self.assertEqual(self.decimal(guantes[21]), Decimal("13.00"))
        self.assertEqual(self.decimal(guantes[22]), Decimal("91.00"))
        self.assertEqual(total[0], "Total")
        self.assertEqual(total[15], 15)
        self.assertEqual(self.decimal(total[17]), Decimal("73.50"))
        self.assertEqual(self.decimal(total[22]), Decimal("102.00"))

    def test_formato_de_encabezados_y_moneda(self):
        _, libro = self.libro(periodo=self.periodo.pk)
        for nombre in libro.sheetnames:
            hoja = libro[nombre]
            with self.subTest(hoja=nombre):
                encabezado = hoja["A4"]
                self.assertTrue(encabezado.fill.start_color.rgb.endswith("172554"))
                self.assertTrue(encabezado.font.color.rgb.endswith("FFFFFF"))
                self.assertTrue(encabezado.font.bold)
                self.assertEqual(hoja.freeze_panes, "A5")
        resumen = libro["Resumen"]
        self.assertEqual(resumen.cell(row=4, column=19).value, "Costo")
        self.assertEqual(resumen.cell(row=5, column=19).number_format, FORMATO_MONEDA)
        self.assertEqual(resumen.cell(row=5, column=23).number_format, FORMATO_MONEDA)

    def test_filtro_por_periodo_y_area_en_el_excel(self):
        respuesta, libro = self.libro(periodo=self.periodo_anterior.pk)
        self.assertEqual(libro.sheetnames, ["Resumen", "FAR 2030"])
        self.assertEqual(libro["Resumen"].cell(row=5, column=18).value, 40)
        _, libro = self.libro(periodo="", area=self.area.pk)
        self.assertEqual(libro.sheetnames, ["Resumen", "FAR 2031", "FAR 2030"])
        respuesta, _ = self.libro(periodo="")
        self.assertIn("consolidado-proyecciones-todos.xlsx", respuesta["Content-Disposition"])

    def test_nombre_de_hoja_valido_y_unico(self):
        usados = {"resumen"}
        self.assertEqual(nombre_hoja("Resumen", usados), "Resumen (2)")
        self.assertEqual(nombre_hoja("A/B:C*D?E[F]G\\H", usados), "A-B-C-D-E-F-G-H")
        largo = nombre_hoja("X" * 40, usados)
        self.assertEqual(len(largo), 31)
        self.assertEqual(nombre_hoja("X" * 40, usados), "X" * 27 + " (2)")


class PermisosConsolidadoTests(BaseConsolidado):
    def test_coordinador_y_proveedor_reciben_403(self):
        for usuario in (self.coordinador, self.proveedor):
            self.client.force_login(usuario)
            for url in (self.url, self.url_exportar):
                with self.subTest(rol=usuario.rol, url=url):
                    self.assertEqual(self.client.get(url).status_code, 403)
                    self.assertEqual(self.client.get(url, {"periodo": "", "area": self.area.pk}).status_code, 403)

    def test_sin_sesion_redirige_al_ingreso(self):
        for url in (self.url, self.url_exportar):
            with self.subTest(url=url):
                respuesta = self.client.get(url)
                self.assertEqual(respuesta.status_code, 302)
                self.assertTrue(respuesta["Location"].startswith(reverse("cuentas:ingresar")))

    def test_administracion_entra_y_solo_lectura(self):
        for usuario in (self.administrador, self.desarrollador):
            self.client.force_login(usuario)
            for url in (self.url, self.url_exportar):
                with self.subTest(rol=usuario.rol, url=url):
                    self.assertEqual(self.client.get(url).status_code, 200)
                    self.assertEqual(self.client.post(url).status_code, 405)

    def test_menu_muestra_consolidado_solo_a_administracion(self):
        self.client.force_login(self.administrador)
        self.assertContains(self.client.get("/"), f'href="{self.url}"')
        self.client.force_login(self.coordinador)
        self.assertNotContains(self.client.get("/"), f'href="{self.url}"')
