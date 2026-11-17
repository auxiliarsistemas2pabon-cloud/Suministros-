"""Regresiones con información ficticia, únicamente en la base aislada de pruebas."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zipfile import ZipFile
from xml.sax.saxutils import escape

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse

from areas.models import Area
from bitacora.models import RegistroBitacora
from compras.models import ContadorOrdenCompra, OrdenCompra
from compras.tests_numeracion_ordenes import DatosNumeracion
from cuentas.models import Rol, Usuario
from fuentes.lectura import compras_historicas, leer_libro
from fuentes.models import CompraHistorica, ElegibleHistorico, FormatoInstitucional, SerieArea
from fuentes.servicios import cargar, preparar
from proveedores.models import Peso, Proveedor, Requisito


def libro(path, nombre, celdas):
    xmlns = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    rows = {}
    import re
    for address, text in celdas.items():
        row = int(re.search(r'\d+', address)[0])
        rows.setdefault(row, []).append(f'<c r="{address}" t="inlineStr"><is><t>{escape(str(text))}</t></is></c>')
    with ZipFile(path, 'w') as z:
        z.writestr('xl/workbook.xml', f'<workbook xmlns="{xmlns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="{nombre}" sheetId="1" r:id="r1"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="r1" Target="worksheets/sheet1.xml"/></Relationships>')
        content = ''.join(f'<row r="{row}">{"".join(values)}</row>' for row, values in sorted(rows.items()))
        z.writestr('xl/worksheets/sheet1.xml', f'<worksheet xmlns="{xmlns}"><sheetData>{content}</sheetData></worksheet>')


class CargaInstitucionalTests(TestCase):
    def setUp(self):
        self.temporal = TemporaryDirectory()
        self.addCleanup(self.temporal.cleanup)
        self.raiz = Path(self.temporal.name)
        self.entorno = override_settings(MEDIA_ROOT=self.raiz / 'privados')
        self.entorno.enable()
        self.addCleanup(self.entorno.disable)
        self.actor = Usuario.objects.create_user(correo='carga@ejemplo.test', nombre='Responsable ficticio', rol=Rol.ADMINISTRADOR, debe_cambiar_clave=False)
        for code in ['11', '21', '28']:
            libro(self.raiz / f'FR-GDS-{code} ejemplo.xlsx', 'Formato', {'A1': f'Formato ficticio {code}'})
        cells = {f'{c}1': f'Categoría ficticia {c}' for c in 'BCDEFGHIJKL'}
        for n in range(1, 27):
            cells[f'A{n+1}'] = f'Requisito ficticio {n}'
            for c in 'BCDEFGHIJKL':
                cells[f'{c}{n+1}'] = '1'
        libro(self.raiz / 'FR-GDS-14 ejemplo.xlsx', 'M_pesos', cells)
        libro(self.raiz / 'FR-GDS-20 ejemplo.xlsx', 'Elegibles', {'A1': 'Formato ficticio 20', 'F6': '.3', 'G6': '.2', 'H6': '.2', 'I6': '.3', 'E9': 'CRITERIOS ADM', 'D9': '<script>Proveedor ficticio</script>', 'C9': 'Área ficticia', 'J9': '80', 'K9': 'PUESTO 2'})
        libro(self.raiz / 'FR-GDS-27 ejemplo.xlsx', 'Histórico', {'A1': 'Formato ficticio 27', 'C5': 'No. ORDEN DE COMPRA (si aplica)', 'C6': 'TEC-40', 'F6': 'Proveedor ficticio sin identificación', 'G6': 'Objeto ficticio', 'H6': '100', 'L6': 'Entrega indicada en el archivo'})
        self.corte = {'series': [{'code': 'TEC', 'last': 40, 'digits': 2, 'name': 'Área ficticia TEC', 'note': 'Corte ficticio', 'source': {'sheet': 'Histórico', 'cell': 'C6', 'raw': 'TEC-40'}}]}
        self.fuentes = preparar(self.raiz, self.corte)

    def cargar(self):
        return cargar(self.fuentes, self.corte, actor=self.actor, motivo='Carga ficticia en base de pruebas aislada')

    def test_carga_datos_reales_del_archivo_sin_crear_aprobaciones_ni_nits(self):
        resultado = self.cargar()
        self.assertEqual(resultado['formatos_nuevos'], 6)
        self.assertEqual(CompraHistorica.objects.get().orden_original, 'TEC-40')
        self.assertEqual(ElegibleHistorico.objects.count(), 1)
        self.assertEqual(Requisito.objects.count(), 26)
        self.assertEqual(Peso.objects.count(), 286)
        self.assertEqual(Proveedor.objects.count(), 0)
        self.assertEqual(OrdenCompra.objects.count(), 0)
        self.assertEqual(SerieArea.objects.get().ultimo_historico, 40)
        self.assertEqual(ContadorOrdenCompra.objects.get(pk=SerieArea.objects.get().clave_contador).ultimo, 40)

    def test_repetir_carga_no_duplica_fuentes_historico_ni_bitacora(self):
        self.cargar()
        antes = RegistroBitacora.objects.count()
        resultado = self.cargar()
        self.assertEqual(resultado['formatos_nuevos'], 0)
        self.assertEqual(FormatoInstitucional.objects.count(), 6)
        self.assertEqual(CompraHistorica.objects.count(), 1)
        self.assertEqual(RegistroBitacora.objects.count(), antes)

    def test_error_revierte_toda_la_carga_de_base(self):
        with patch('fuentes.servicios._matriz', side_effect=ValidationError('Fallo ficticio')):
            with self.assertRaises(ValidationError):
                self.cargar()
        self.assertFalse(FormatoInstitucional.objects.exists())
        self.assertFalse(Area.objects.exists())
        self.assertFalse(CompraHistorica.objects.exists())

    def test_corte_sin_celda_correspondiente_es_rechazado(self):
        corte = deepcopy(self.corte)
        corte['series'][0]['last'] = 100
        with self.assertRaises(ValidationError):
            preparar(self.raiz, corte)

    def test_fuentes_descargas_y_busquedas_exigen_rol_administrativo(self):
        self.cargar()
        fuente = FormatoInstitucional.objects.first()
        for name, args in [('inicio', []), ('historico', []), ('elegibles', []), ('consecutivos', []), ('detalle', [fuente.pk]), ('descargar', [fuente.pk])]:
            self.assertEqual(self.client.get(reverse('fuentes:' + name, args=args)).status_code, 302)
        from cuentas.tests.utilidades import crear_usuario
        proveedor = crear_usuario(Rol.PROVEEDOR, debe_cambiar_clave=False)
        self.client.force_login(proveedor)
        self.assertEqual(self.client.get(reverse('fuentes:descargar', args=[fuente.pk])).status_code, 403)

    def test_paginas_principales_y_enlaces_operativos_responden(self):
        self.cargar()
        self.client.force_login(self.actor)
        for name in ['inicio', 'historico', 'elegibles', 'consecutivos']:
            with self.subTest(name=name):
                respuesta = self.client.get(reverse('fuentes:' + name))
                self.assertEqual(respuesta.status_code, 200)
        self.assertContains(self.client.get(reverse('fuentes:consecutivos')), 'TEC-41')
        self.assertContains(self.client.get(reverse('fuentes:historico') + '?q=TEC-40'), 'Objeto ficticio')

    def test_valores_de_excel_se_escapan_en_html_y_descarga_conserva_huella(self):
        self.cargar()
        self.client.force_login(self.actor)
        respuesta = self.client.get(reverse('fuentes:elegibles'))
        self.assertNotContains(respuesta, '<script>Proveedor ficticio</script>')
        self.assertContains(respuesta, '&lt;script&gt;Proveedor ficticio&lt;/script&gt;')
        fuente = FormatoInstitucional.objects.get(codigo='FR-GDS-20')
        respuesta = self.client.get(reverse('fuentes:descargar', args=[fuente.pk]))
        contenido = b''.join(respuesta.streaming_content)
        self.assertEqual(sha256(contenido).hexdigest(), fuente.sha256)
        self.assertIn('no-store', respuesta['Cache-Control'])
        self.assertContains(self.client.get(reverse('fuentes:detalle', args=[fuente.pk])), 'Celda de origen')

    def test_corte_no_retrocede_ni_disminuye_un_contador_avanzado(self):
        self.cargar()
        serie = SerieArea.objects.get()
        contador = ContadorOrdenCompra.objects.get(pk=serie.clave_contador)
        contador.ultimo = 45
        contador.save()
        self.cargar()
        contador.refresh_from_db()
        self.assertEqual(contador.ultimo, 45)
        serie.ultimo_historico = 39
        with self.assertRaises(ValidationError):
            serie.save()

    def test_completar_ficha_solo_precarga_nombre_no_crea_ni_verifica_proveedor(self):
        self.client.force_login(self.actor)
        respuesta = self.client.get(reverse('proveedores:nuevo'), {'nombre': 'Nombre ficticio del archivo'})
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.context['formulario'].initial['razon_social'], 'Nombre ficticio del archivo')
        self.assertFalse(Proveedor.objects.exists())

    def test_lee_encabezado_desplazado_sin_confundir_columna_fecha(self):
        hoja = [{'nombre': 'Prueba', 'celdas': {'C96': 'No. ORDEN DE COMPRA (si aplica)', 'C97': 'TEC-40', 'D97': 'N/A', 'F97': 'Proveedor ficticio'}}]
        filas = list(compras_historicas(hoja))
        self.assertEqual(filas[0]['fila'], 97)
        self.assertEqual(filas[0]['orden_original'], 'TEC-40')

    def test_reglas_del_archivo_reemplazan_defectos_sin_simular_aprobacion(self):
        self.cargar()
        from fuentes.servicios import reglas_desde_formulas
        from parametros.catalogo import REGLAS_FR14, REGLAS_ELEGIBLES
        from parametros.servicios import obtener
        import json
        fr14 = FormatoInstitucional.objects.get(codigo='FR-GDS-14')
        fr14.contenido.append({'nombre': 'Evaluacion', 'celdas': {}, 'formulas': {'J13': 'IF(I13<50%,1,IF(I13<90%,3,5))', 'F13': 'IF(D13="SI",E13,0)', 'G13': 'IF(D13="N/A",0,E13)'}})
        fr20 = FormatoInstitucional.objects.get(codigo='FR-GDS-20')
        fr20.contenido[0]['formulas'] = {'H9': 'F9*$F$6/5%'}
        reglas_desde_formulas(fr14, fr20, actor=self.actor, motivo='Reglas ficticias para comprobar reconocimiento de fórmulas')
        self.assertEqual(json.loads(obtener(REGLAS_FR14))['umbral3'], '50')
        self.assertEqual(json.loads(obtener(REGLAS_FR14))['umbral5'], '90')
        self.assertEqual(json.loads(obtener(REGLAS_ELEGIBLES))['metodo'], 'escalado')
        self.assertTrue(json.loads(obtener(REGLAS_FR14))['pendiente'])
        antes = RegistroBitacora.objects.count()
        reglas_desde_formulas(fr14, fr20, actor=self.actor, motivo='Repetición ficticia')
        self.assertEqual(antes, RegistroBitacora.objects.count())


class NumeracionInstitucionalTests(DatosNumeracion, TestCase):
    def setUp(self):
        super().setUp()
        self.fuente = FormatoInstitucional.objects.create(codigo='FR-GDS-27', titulo='Fuente ficticia', nombre_original='ficticio.xlsx', sha256='f'*64, archivo='ficticio.xlsx')
        self.serie = SerieArea.objects.create(area=self.uno.cotizacion.area, fuente=self.fuente, codigo='TEC', ultimo_historico=40, longitud=2, celda_origen='Hoja!C6', referencia_original='TEC-40')

    def test_emite_desde_corte_del_area_y_anular_no_reutiliza(self):
        uno = self.emitir(actor=self.dev)
        self.assertEqual(uno.consecutivo, 'TEC-41')
        self.assertEqual(uno.serie_consecutivo, self.serie.clave_contador)
        from compras.numeracion_ordenes import anular_orden
        anular_orden(uno, actor=self.dev, motivo='Anulación ficticia de prueba')
        self.assertEqual(self.emitir(self.dos).consecutivo, 'TEC-42')

    def test_farmacia_sin_prefijo_y_serie_deshabilitada(self):
        self.serie.sin_prefijo = True
        # La identidad se fija antes de emitir; se prepara una serie ficticia independiente para este caso.
        SerieArea.objects.filter(pk=self.serie.pk).update(sin_prefijo=True)
        self.assertEqual(self.emitir().consecutivo, '41')
        self.serie.refresh_from_db()
        self.serie.habilitada = False
        self.serie.save()
        with self.assertRaises(ValidationError):
            self.emitir(self.dos)
        self.assertEqual(ContadorOrdenCompra.objects.get(pk=self.serie.clave_contador).ultimo, 41)

    def test_contador_de_otra_area_no_altera_el_numero(self):
        otra = Area.objects.create(nombre='Otra área ficticia', codigo_area='OTRA')
        serie = SerieArea.objects.create(area=otra, fuente=self.fuente, codigo='OTRA', ultimo_historico=900, celda_origen='Hoja!C7', referencia_original='OTRA-900')
        ContadorOrdenCompra.objects.create(clave=serie.clave_contador, ultimo=900)
        self.assertEqual(self.emitir().consecutivo, 'TEC-41')
