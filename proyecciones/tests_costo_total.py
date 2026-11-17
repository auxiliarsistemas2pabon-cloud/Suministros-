"""Un total anual informado conserva su valor en revisión y consolidado."""

from decimal import Decimal
from io import BytesIO

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.urls import reverse
from openpyxl import load_workbook

from bitacora.models import RegistroBitacora
from proyecciones import consolidado, servicios
from proyecciones.exportar import exportar_consolidado
from proyecciones.forms import FormularioCorreccionLinea
from proyecciones.models import Linea, ProyeccionArea
from proyecciones.tests_revision import BaseRevision, MOTIVO


class CostoProyectadoTotalTests(BaseRevision):
    def asignar_total(self, importe):
        self.linea.costo_proyectado_total = importe
        servicios.corregir_linea(self.linea, actor=self.administrador, motivo=MOTIVO)
        self.linea.refresh_from_db()

    def consulta(self):
        return ProyeccionArea.objects.filter(pk=self.proyeccion.pk)

    def test_total_informado_prevalece_y_cero_no_se_confunde_con_vacio(self):
        for informado, esperado in ((None, "62.50"), (Decimal("123.45"), "123.45"), (Decimal("0"), "0")):
            with self.subTest(informado=informado):
                self.linea.costo_proyectado_total = informado
                self.linea.save()
                self.linea.refresh_from_db()
                self.assertEqual(self.linea.costo_anual, Decimal(esperado))
                self.assertEqual(servicios.costo_total(self.consulta()), Decimal(esperado) + Decimal("11.00"))
                self.assertEqual(consolidado.totales(self.consulta())["costo"], Decimal(esperado) + Decimal("11.00"))

    def test_total_cero_con_meses_cero_y_precio_no_cero_no_recalcula(self):
        self.linea.cantidad_enero = 0
        self.linea.cantidad_febrero = 0
        self.asignar_total(Decimal("1250.37"))
        self.assertEqual(self.linea.total_anual, 0)
        self.assertEqual(self.linea.costo_anual, Decimal("1250.37"))
        self.assertEqual(consolidado.totales(self.consulta())["costo"], Decimal("1261.37"))

    def test_correccion_conserva_total_exactamente_y_registra_bitacora(self):
        self.asignar_total(Decimal("1000000.37"))
        self.assertEqual(self.linea.precio_estimado, Decimal("12.50"))
        registro = RegistroBitacora.objects.filter(accion="linea.corregida", objeto_id=str(self.linea.pk)).latest("pk")
        self.assertEqual(Decimal(registro.valor_nuevo["costo_proyectado_total"]), Decimal("1000000.37"))
        self.assertEqual(servicios.resumen_revision(self.consulta()).get().costo_total, Decimal("1000011.37"))

    def test_costos_vigentes_no_multiplican_el_total_por_los_meses(self):
        self.asignar_total(Decimal("123.45"))
        servicios.aprobar_proyeccion(self.proyeccion, actor=self.administrador, motivo=MOTIVO)
        for campo, valor in (("cantidad_enero", "100"), ("precio_estimado", "9876.54")):
            servicios.registrar_ajuste(self.linea, campo, valor, actor=self.administrador, justificacion=MOTIVO)
        linea = servicios.anotar_vigentes([self.linea])[0]
        self.assertEqual(linea.costo_vigente, Decimal("123.45"))
        self.assertEqual(consolidado.totales(self.consulta())["costo_ajustado"], Decimal("134.45"))
        servicios.registrar_ajuste(self.linea, "costo_proyectado_total", "130.17", actor=self.administrador, justificacion=MOTIVO)
        linea = servicios.anotar_vigentes([Linea.objects.get(pk=self.linea.pk)])[0]
        self.assertEqual(linea.costo_anual, Decimal("123.45"))
        self.assertEqual(linea.costo_vigente, Decimal("130.17"))
        self.assertEqual(consolidado.totales(self.consulta())["costo_ajustado"], Decimal("141.17"))
        servicios.registrar_ajuste(self.linea, "costo_proyectado_total", "0", actor=self.administrador, justificacion=MOTIVO)
        self.assertEqual(servicios.anotar_vigentes([self.linea])[0].costo_vigente, Decimal("0"))
        self.assertEqual(consolidado.totales(self.consulta())["costo_ajustado"], Decimal("11.00"))

    def test_total_ajustado_desde_original_vacio_no_se_pierde(self):
        servicios.aprobar_proyeccion(self.proyeccion, actor=self.administrador, motivo=MOTIVO)
        servicios.registrar_ajuste(self.linea, "costo_proyectado_total", "15.37", actor=self.administrador, justificacion=MOTIVO)
        fila = consolidado.lineas_de(self.proyeccion).get(pk=self.linea.pk)
        self.assertEqual(fila.costo, Decimal("62.50"))
        self.assertEqual(fila.v_costo, Decimal("15.37"))

    def test_total_negativo_se_rechaza_en_modelo_y_base(self):
        self.linea.costo_proyectado_total = Decimal("-0.01")
        with self.assertRaises(ValidationError):
            self.linea.full_clean()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.linea.save()

    def test_formulario_y_revision_muestran_total_informado(self):
        formulario = FormularioCorreccionLinea(self.datos_correccion(costo_proyectado_total="123.45"), instance=self.linea)
        self.assertTrue(formulario.is_valid(), formulario.errors)
        servicios.corregir_linea(formulario.save(commit=False), actor=self.administrador, motivo=MOTIVO)
        self.client.force_login(self.administrador)
        respuesta = self.client.get(self.url_detalle)
        self.assertContains(respuesta, "Total anual informado")
        self.assertContains(respuesta, "123,45")

    def test_excel_conserva_costos_sin_ampliar_sus_columnas(self):
        self.asignar_total(Decimal("1000000.37"))
        libro = load_workbook(BytesIO(exportar_consolidado(self.consulta())))
        hoja = libro["FAR 2031"]
        self.assertEqual(hoja.max_column, 23)
        self.assertEqual(Decimal(str(hoja.cell(5, 18).value)), Decimal("1000000.37"))
        self.assertEqual(Decimal(str(hoja.cell(5, 23).value)), Decimal("1000000.37"))
        self.assertEqual(Decimal(str(libro["Resumen"].cell(5, 19).value)), Decimal("1000011.37"))

    def test_referencia_unitaria_tecnica_no_se_presenta_como_precio_real(self):
        self.linea.precio_estimado = Decimal("0")
        self.client.force_login(self.administrador)
        for importe in (Decimal("75.25"), Decimal("0")):
            with self.subTest(importe=importe):
                self.asignar_total(importe)
                respuesta = self.client.get(self.url_detalle)
                self.assertEqual(respuesta.status_code, 200)
                libro = load_workbook(BytesIO(exportar_consolidado(self.consulta())))
                self.assertEqual(libro["FAR 2031"].cell(5, 17).value, "No informado")
                self.assertEqual(Decimal(str(libro["FAR 2031"].cell(5, 18).value)), importe)
                self.assertEqual(Decimal(str(libro["FAR 2031"].cell(5, 23).value)), importe)
