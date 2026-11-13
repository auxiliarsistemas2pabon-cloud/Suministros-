"""A11: Excel, confirmación transaccional y alcance por área."""

from datetime import timedelta
from decimal import Decimal
from io import BytesIO
import re
from zipfile import ZipFile
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from openpyxl import Workbook, load_workbook

from bitacora.models import RegistroBitacora
from proyecciones import importar, servicios
from proyecciones.models import Linea, Periodo, ProyeccionArea
from proyecciones.tests_revision import BaseRevision, MOTIVO
from proyecciones.views import CLAVE_IMPORTACION


class ImportacionTests(BaseRevision):
    def setUp(self):
        super().setUp()
        self.proyeccion.estado = ProyeccionArea.Estado.BORRADOR
        self.proyeccion.fecha_envio = None
        self.proyeccion.enviado_por = None
        self.proyeccion.save()
        self.url = reverse("proyecciones:importar_excel", args=[self.proyeccion.pk])
        self.url_plantilla = reverse("proyecciones:plantilla_excel")

    def fila(self, **cambios):
        datos = dict(zip(importar.CAMPOS, ["Gasas ficticias", "Urgencias", "cja", *([1] * 12), "12.50"]))
        datos.update(cambios)
        return [datos[c] for c in importar.CAMPOS]

    def archivo(self, filas=None, encabezados=importar.ENCABEZADOS):
        libro = Workbook()
        libro.active.title = "Proyección"
        libro.active.append(encabezados)
        for fila in filas if filas is not None else [self.fila()]:
            libro.active.append(fila)
        salida = BytesIO()
        libro.save(salida)
        return SimpleUploadedFile("proyeccion.xlsx", salida.getvalue())

    def preparar(self, filas=None):
        return servicios.preparar_importacion(self.proyeccion, self.archivo(filas), actor=self.coordinador)

    def confirmar(self, previa, **opciones):
        return servicios.confirmar_importacion(
            self.proyeccion, previa, actor=opciones.pop("actor", self.coordinador),
            modo=opciones.pop("modo", "agregar"), motivo=opciones.pop("motivo", MOTIVO), **opciones,
        )

    def test_plantilla_tiene_columnas_instrucciones_y_validacion(self):
        libro = load_workbook(BytesIO(importar.plantilla_excel()))
        self.assertEqual(tuple(c.value for c in libro.active[1]), importar.ENCABEZADOS)
        self.assertIn("Instrucciones", libro.sheetnames)
        self.assertEqual(len(libro.active.data_validations.dataValidation), 1)
        self.assertEqual(libro["Unidades"].sheet_state, "hidden")
        self.assertEqual(libro.active["A1"].fill.fgColor.rgb, "00172554")

    def test_previa_no_guarda_y_conserva_decimal_y_doce_meses(self):
        antes = Linea.objects.count()
        previa = self.preparar()
        self.assertEqual(Linea.objects.count(), antes)
        self.assertEqual(previa["errores"], [])
        self.assertEqual(previa["filas"][0]["datos"]["precio_estimado"], "12.50")
        self.confirmar(previa)
        linea = self.proyeccion.lineas.get(producto_servicio="Gasas ficticias")
        self.assertEqual(linea.total_anual, 12)
        self.assertEqual(linea.costo_anual, Decimal("150.00"))

    def test_filas_invalidas_tienen_numero_y_no_se_guardan(self):
        previa = self.preparar([self.fila(), self.fila(cantidad_enero=-1), self.fila(cantidad_enero="1.5")])
        self.assertEqual([f["fila"] for f in previa["errores"]], [3, 4])
        self.assertEqual(self.confirmar(previa), 1)
        self.assertEqual(self.proyeccion.lineas.count(), 3)

    def test_validaciones_por_fila(self):
        casos = [
            {"producto_servicio": ""}, {"producto_servicio": "X" * 256},
            {"unidad_id": "inexistente"}, {"cantidad_enero": True},
            {"cantidad_enero": 2147483648}, {"precio_estimado": "-0.01"},
            {"precio_estimado": "1.001"}, {"precio_estimado": "NaN"},
            {"precio_estimado": "Infinity"}, {"precio_estimado": None},
            {"cantidad_enero": "=1+1"}, {"producto_servicio": "=HYPERLINK(\"x\")"},
        ]
        for cambios in casos:
            with self.subTest(cambios=cambios):
                previa = self.preparar([self.fila(**cambios)])
                self.assertEqual(len(previa["errores"]), 1)
                self.assertFalse(previa["filas"])

    def test_meses_vacios_cero_unidad_sin_mayusculas_y_filas_vacias_omitidas(self):
        previa = self.preparar([[None] * 16, self.fila(cantidad_enero=None, unidad_id=" CJA ")])
        self.assertEqual(len(previa["filas"]), 1)
        self.assertEqual(previa["filas"][0]["fila"], 3)
        self.assertEqual(previa["filas"][0]["datos"]["cantidad_enero"], 0)

    def test_no_excel_extension_falsa_archivo_vacio_y_encabezados(self):
        archivos = [SimpleUploadedFile("mal.xlsx", b"no es excel"), SimpleUploadedFile("mal.txt", b"x"),
                    SimpleUploadedFile("vacio.xlsx", b""), self.archivo(encabezados=["Otro"]), self.archivo([])]
        for archivo in archivos:
            with self.subTest(archivo=archivo.name), self.assertRaises(ValidationError):
                servicios.preparar_importacion(self.proyeccion, archivo, actor=self.coordinador)

    def test_limites_de_tamano_filas_y_contenido_descomprimido(self):
        with patch.object(importar, "MAX_BYTES", 10), self.assertRaises(ValidationError):
            self.preparar()
        with patch.object(importar, "MAX_FILAS", 1), self.assertRaises(ValidationError):
            self.preparar([self.fila(), self.fila()])
        with patch.object(importar, "MAX_DESCOMPRIMIDO", 1), self.assertRaises(ValidationError):
            self.preparar()

    def test_reemplazar_conserva_historial_y_no_toca_otra_area(self):
        ids = set(self.proyeccion.lineas.values_list("pk", flat=True))
        self.confirmar(self.preparar(), modo="reemplazar")
        self.assertEqual(self.proyeccion.lineas.count(), 1)
        self.assertFalse(Linea.objects.filter(pk__in=ids).exists())
        self.assertTrue(Linea.objects.filter(pk=self.linea_ajena.pk).exists())
        eliminados = RegistroBitacora.objects.filter(accion="linea.eliminada")
        self.assertEqual(eliminados.count(), 2)
        self.assertEqual({r.valor_anterior["producto_servicio"] for r in eliminados},
                         {self.linea.producto_servicio, self.linea_dos.producto_servicio})
        registro = RegistroBitacora.objects.get(accion="proyeccion_area.importada")
        self.assertEqual(registro.actor, self.coordinador)
        self.assertEqual(registro.motivo, MOTIVO)
        self.assertEqual(registro.valor_nuevo["filas_importadas"], 1)

    def test_reemplazo_se_revierte_si_falla_el_guardado(self):
        previa = self.preparar()
        antes = set(self.proyeccion.lineas.values_list("pk", flat=True))
        with patch.object(servicios, "guardar_linea", side_effect=ValidationError("Fallo simulado")):
            with self.assertRaises(ValidationError):
                self.confirmar(previa, modo="reemplazar")
        self.assertEqual(set(self.proyeccion.lineas.values_list("pk", flat=True)), antes)
        self.assertFalse(RegistroBitacora.objects.filter(accion="linea.eliminada").exists())

    def test_no_reemplaza_si_no_hay_validas_o_falta_motivo(self):
        for previa, motivo in [(self.preparar([self.fila(precio_estimado=-1)]), MOTIVO), (self.preparar(), " ")]:
            with self.assertRaises(ValidationError):
                self.confirmar(previa, modo="reemplazar", motivo=motivo)
        self.assertEqual(self.proyeccion.lineas.count(), 2)

    def test_unidad_desactivada_tras_previa_impide_reemplazo(self):
        previa = self.preparar()
        self.unidad.activa = False
        self.unidad.save()
        with self.assertRaises(ValidationError):
            self.confirmar(previa, modo="reemplazar")
        self.assertEqual(self.proyeccion.lineas.count(), 2)

    def test_cambio_tras_previa_y_repeticion_rechazados(self):
        previa = self.preparar()
        self.linea.cantidad_enero += 1
        self.linea.save()
        with self.assertRaisesMessage(ValidationError, "cambió"):
            self.confirmar(previa)
        previa = self.preparar()
        self.confirmar(previa)
        with self.assertRaisesMessage(ValidationError, "cambió"):
            self.confirmar(previa)

    def test_vista_previa_vencida(self):
        previa = self.preparar()
        previa["creada"] = (timezone.now() - timedelta(minutes=31)).isoformat()
        with self.assertRaisesMessage(ValidationError, "venció"):
            self.confirmar(previa)

    def test_coordinador_no_importa_otra_area_servicio_y_vista(self):
        self.client.force_login(self.coordinador)
        url = reverse("proyecciones:importar_excel", args=[self.otra_proyeccion.pk])
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(url, {"archivo": self.archivo()}).status_code, 403)
        with self.assertRaises(PermissionDenied):
            servicios.preparar_importacion(self.otra_proyeccion, self.archivo(), actor=self.coordinador)

    def test_roles_y_anonimos_en_ambas_vistas(self):
        for url in (self.url, self.url_plantilla):
            self.client.logout()
            self.assertEqual(self.client.get(url).status_code, 302)
            self.client.force_login(self.proveedor)
            self.assertEqual(self.client.get(url).status_code, 403)
            self.assertEqual(self.client.post(url).status_code, 403)
            for usuario in (self.administrador, self.desarrollador, self.coordinador):
                self.client.force_login(usuario)
                self.assertEqual(self.client.get(url).status_code, 200)
        with self.assertRaises(PermissionDenied):
            servicios.preparar_importacion(self.proyeccion, self.archivo(), actor=self.proveedor)

    def test_cerrada_enviada_y_aprobada(self):
        previa = self.preparar()
        self.periodo.estado = Periodo.Estado.CERRADO
        self.periodo.save()
        with self.assertRaises(ValidationError):
            self.confirmar(previa)
        self.periodo.estado = Periodo.Estado.ABIERTO
        self.periodo.save()
        self.proyeccion.estado = ProyeccionArea.Estado.ENVIADA
        self.proyeccion.fecha_envio = timezone.now()
        self.proyeccion.enviado_por = self.coordinador
        self.proyeccion.save()
        with self.assertRaises(ValidationError):
            self.preparar()
        previa = servicios.preparar_importacion(self.proyeccion, self.archivo(), actor=self.administrador)
        self.confirmar(previa, actor=self.administrador, modo="reemplazar")
        self.proyeccion.estado = ProyeccionArea.Estado.APROBADA
        self.proyeccion.save()
        for actor in (self.administrador, self.desarrollador):
            with self.assertRaises(ValidationError):
                servicios.preparar_importacion(self.proyeccion, self.archivo(), actor=actor)

    def test_confirmacion_http_ignora_filas_del_navegador_y_no_se_repite(self):
        self.client.force_login(self.coordinador)
        respuesta = self.client.post(self.url, {"archivo": self.archivo()})
        self.assertContains(respuesta, "Vista previa")
        self.assertEqual(self.proyeccion.lineas.count(), 2)
        previa = self.client.session[CLAVE_IMPORTACION]
        datos = {"accion": "confirmar", "token": previa["token"], "modo": "agregar", "motivo": MOTIVO,
                 "filas": '[{"producto_servicio":"Manipulado"}]'}
        self.assertEqual(self.client.post(self.url, datos).status_code, 302)
        self.assertNotIn(CLAVE_IMPORTACION, self.client.session)
        self.assertEqual(self.proyeccion.lineas.count(), 3)
        self.assertFalse(Linea.objects.filter(producto_servicio="Manipulado").exists())
        self.assertEqual(self.client.post(self.url, datos).status_code, 403)

    def test_token_incorrecto_y_carga_invalida_invalida_previa(self):
        self.client.force_login(self.coordinador)
        self.client.post(self.url, {"archivo": self.archivo()})
        self.assertEqual(self.client.post(self.url, {"accion": "confirmar", "token": "ajeno", "modo": "agregar", "motivo": MOTIVO}).status_code, 403)
        self.client.post(self.url, {"archivo": SimpleUploadedFile("mal.xlsx", b"mal")})
        self.assertNotIn(CLAVE_IMPORTACION, self.client.session)

    def test_confirmar_sin_csrf_rechazado(self):
        from django.test import Client

        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(self.coordinador)
        self.assertEqual(cliente.post(self.url, {"accion": "confirmar"}).status_code, 403)

    def test_previa_no_se_puede_usar_para_otro_actor_o_destino(self):
        previa = self.preparar()
        with self.assertRaises(PermissionDenied):
            self.confirmar(previa, actor=self.administrador)
        with self.assertRaises(PermissionDenied):
            servicios.confirmar_importacion(self.otra_proyeccion, previa, actor=self.administrador, modo="agregar", motivo=MOTIVO)

    def test_aprobaciones_parciales_impiden_importar(self):
        from proyecciones.models import AprobacionProyeccion

        self.proyeccion.estado = ProyeccionArea.Estado.ENVIADA
        self.proyeccion.fecha_envio = timezone.now()
        self.proyeccion.enviado_por = self.coordinador
        self.proyeccion.save()
        AprobacionProyeccion.objects.create(
            proyeccion=self.proyeccion, usuario=self.administrador,
            fecha_envio_aprobada=self.proyeccion.fecha_envio, motivo=MOTIVO,
        )
        with self.assertRaisesMessage(ValidationError, "aprobaciones registradas"):
            servicios.preparar_importacion(self.proyeccion, self.archivo(), actor=self.desarrollador)

    def archivo_con_dimension_falsa(self, filas, extra_xml=None):
        origen = self.archivo(filas)
        salida = BytesIO()
        with ZipFile(origen) as entrada, ZipFile(salida, "w") as destino:
            for nombre in entrada.namelist():
                contenido = entrada.read(nombre)
                if nombre == "xl/worksheets/sheet1.xml":
                    contenido = re.sub(rb'<dimension ref="[^"]+"', b'<dimension ref="A1:A1"', contenido)
                    if extra_xml:
                        contenido = contenido.replace(b"</sheetData>", extra_xml + b"</sheetData>")
                destino.writestr(nombre, contenido)
        return SimpleUploadedFile("dimension.xlsx", salida.getvalue())

    def test_dimension_falsa_no_oculta_filas_validas(self):
        archivo = self.archivo_con_dimension_falsa([self.fila(), self.fila(producto_servicio="Otro")])
        previa = servicios.preparar_importacion(self.proyeccion, archivo, actor=self.coordinador)
        self.assertEqual(len(previa["filas"]), 2)

    def test_dimension_falsa_no_elude_limites_reales(self):
        for extra in (b'<row r="1002"><c r="A1002" t="n"><v>1</v></c></row>',
                      b'<row r="3"><c r="R3" t="n"><v>1</v></c></row>'):
            archivo = self.archivo_con_dimension_falsa([self.fila()], extra)
            with self.subTest(extra=extra), self.assertRaises(ValidationError):
                servicios.preparar_importacion(self.proyeccion, archivo, actor=self.coordinador)
