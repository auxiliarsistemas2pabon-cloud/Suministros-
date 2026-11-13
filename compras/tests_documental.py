from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.test import Client, TestCase
from django.urls import reverse
from openpyxl import load_workbook

from bitacora.models import RegistroBitacora
from bitacora.servicios import guardar_con_bitacora
from compras import documental_servicios as documental, servicios
from compras.models import ListaElegibles
from cuentas.models import Rol
from cuentas.tests.utilidades import crear_area, crear_usuario
from parametros.catalogo import CONTROL_DOCUMENTAL_ELEGIBLES, MESES_EVALUACION_ELEGIBLES
from parametros.models import Parametro
from parametros.servicios import cambiar_valor
from proveedores import matrices_servicios, servicios as proveedores_servicios
from proveedores.evaluacion_servicios import finalizar_evaluacion
from proveedores.historial_servicios import anular_evaluacion
from proveedores.models import DocumentoExigido, DocumentoProveedor
from proveedores.respuestas_servicios import guardar_respuesta
from proveedores.tests import test_matrices
from proveedores.tests.utilidades import crear_proveedor, tipo_documento

MOTIVO = "Control documental ficticio para elegibles"


class VinculoDocumentalTests(TestCase):
    def setUp(self):
        test_matrices.MatricesTests.setUp(self)
        self.area = crear_area()
        self.dev = crear_usuario(Rol.DESARROLLADOR)
        self.coordinador = crear_usuario(Rol.COORDINADOR, area=self.area)
        self.usuario_proveedor = crear_usuario(Rol.PROVEEDOR)
        self.ref = date(2026, 8, 15)
        matrices_servicios.publicar_version(self.version, desde=self.fecha, actor=self.admin, motivo=MOTIVO)
        self.proveedor.categoria = self.categoria
        self.proveedor.save()
        necesidad = servicios.crear_necesidad(objeto="Compra ficticia con respaldo documental", area=self.area,
            fecha=self.ref, origen_texto="Solicitud ficticia", actor=self.admin, motivo=MOTIVO)
        self.lista = servicios.crear_lista(necesidad, fecha=self.ref, actor=self.admin, motivo=MOTIVO)
        self.p = servicios.agregar_participante(self.lista, self.proveedor, actor=self.admin, motivo=MOTIVO)
        self.p.cantidad_autorizada = Decimal(1)
        self.p.save()
        self.tipo = tipo_documento()
        self.exigido = proveedores_servicios.guardar_catalogo(DocumentoExigido(categoria=self.categoria, tipo=self.tipo,
            requisito=self.req, obligatorio=True), actor=self.admin, motivo=MOTIVO)

    def evaluar(self, fecha=None):
        ev = matrices_servicios.crear_evaluacion(self.proveedor, self.categoria, fecha or self.ref, actor=self.admin, motivo=MOTIVO)
        guardar_respuesta(ev, self.req, respuesta="si", observacion="Verificación ficticia", confirma_na=False, actor=self.admin, motivo=MOTIVO)
        return finalizar_evaluacion(ev, actor=self.admin, motivo=MOTIVO)

    def documento(self, vence=None, expedicion=None):
        return DocumentoProveedor.objects.create(proveedor=self.proveedor, tipo=self.tipo,
            fecha_expedicion=expedicion or self.ref - timedelta(days=100), fecha_vencimiento=vence,
            enlace="https://documentos.ejemplo.test/soporte", cargado_por=self.admin)

    def modo(self, valor):
        cambiar_valor(Parametro.objects.get(clave=CONTROL_DOCUMENTAL_ELEGIBLES), valor, actor=self.admin, motivo=MOTIVO)

    def control(self, **kwargs):
        return documental.obtener_control(self.lista, referencia=self.ref, **kwargs)

    def validar(self, **kwargs):
        return documental.validar_para_cierre(self.lista, referencia=self.ref, **kwargs)

    def congelar(self, **kwargs):
        documental.guardar_justificacion(self.lista, justificacion=MOTIVO, referencia=self.ref, actor=self.admin, motivo=MOTIVO)
        with transaction.atomic():
            ListaElegibles.objects.filter(pk=self.lista.pk).update(estado="cerrada")
            return documental.conservar_al_cerrar(self.lista, actor=self.admin, motivo=MOTIVO, referencia=self.ref, **kwargs)

    def test_sin_evaluacion_advertir_exige_justificacion_y_bloquear_rechaza(self):
        fila = self.control()["filas"][0]
        self.assertIsNone(fila["foto"]["evaluacion"])
        self.assertIn("sin_evaluacion", fila["foto"]["causas_bloqueo"])
        with self.assertRaises(ValidationError):
            self.validar()
        self.assertTrue(self.validar(justificacion=MOTIVO)["filas"])
        self.modo("bloquear")
        with self.assertRaises(ValidationError):
            self.validar(justificacion=MOTIVO)

    def test_usa_evaluacion_vigente_de_fr14_y_ignora_borradores_y_anuladas(self):
        ev = self.evaluar()
        matrices_servicios.crear_evaluacion(self.proveedor, self.categoria, self.ref, actor=self.admin, motivo=MOTIVO)
        nueva = self.evaluar()
        self.assertEqual(self.control()["filas"][0]["foto"]["evaluacion"]["id"], nueva.pk)
        anular_evaluacion(nueva, actor=self.admin, motivo=MOTIVO)
        foto = self.control()["filas"][0]["foto"]
        self.assertEqual(foto["evaluacion"]["id"], ev.pk)
        self.assertEqual(foto["evaluacion"]["calificacion"], 5)
        self.assertEqual(foto["evaluacion"]["categoria"], self.categoria.nombre)

    def test_antiguedad_meses_calendario_y_limites(self):
        ev = self.evaluar(date(2026, 1, 31))
        self.assertEqual(documental.limite_antiguedad(date(2024, 2, 29), 12), date(2025, 2, 28))
        self.assertEqual(documental.limite_antiguedad(date(2026, 1, 31), 1), date(2026, 2, 28))
        self.assertEqual(documental.limite_antiguedad(ev.fecha, 999999999), date.max)
        cambiar_valor(Parametro.objects.get(clave=MESES_EVALUACION_ELEGIBLES), "6", actor=self.admin, motivo=MOTIVO)
        control = self.control()
        self.assertIn("evaluacion_antigua", control["filas"][0]["foto"]["causas_bloqueo"])
        foto_limite = documental.obtener_control(self.lista, referencia=date(2026, 7, 31))["filas"][0]["foto"]
        self.assertTrue(foto_limite["evaluacion"]["vigente"])
        self.modo("bloquear")
        with self.assertRaises(ValidationError):
            self.validar(justificacion=MOTIVO)

    def test_fecha_futura_no_se_presenta_como_evaluacion_vigente(self):
        self.evaluar(self.ref + timedelta(days=1))
        foto = self.control()["filas"][0]["foto"]
        self.assertFalse(foto["evaluacion"]["vigente"])
        self.assertIn("evaluacion_futura", foto["causas_bloqueo"])

    def test_documentos_vencidos_obligatorios_ambos_modos_y_faltantes(self):
        self.evaluar()
        doc = self.documento(self.ref - timedelta(days=1))
        foto = self.control()["filas"][0]["foto"]
        self.assertEqual(foto["documentos"][0]["documento_id"], doc.pk)
        self.assertEqual(foto["documentos"][0]["estado"], "vencido")
        self.validar(justificacion=MOTIVO)
        self.modo("bloquear")
        with self.assertRaises(ValidationError):
            self.validar(justificacion=MOTIVO)
        self.documento(self.ref + timedelta(days=100), expedicion=self.ref - timedelta(days=1))
        self.assertFalse(self.validar()["filas"][0]["foto"]["advertencias"])

    def test_faltante_y_opcional_vencido_se_advierten_sin_inventar_otro_bloqueo(self):
        self.evaluar()
        self.modo("bloquear")
        self.assertEqual(self.control()["filas"][0]["foto"]["documentos"][0]["estado"], "faltante")
        with self.assertRaises(ValidationError):
            self.validar()
        self.validar(justificacion=MOTIVO)
        self.exigido.obligatorio = False
        proveedores_servicios.guardar_catalogo(self.exigido, actor=self.admin, motivo=MOTIVO)
        self.documento(self.ref - timedelta(days=1))
        self.assertFalse(self.control()["filas"][0]["foto"]["causas_bloqueo"])
        self.validar(justificacion=MOTIVO)

    def test_proximo_a_vencer_es_informativo_y_no_exige_justificacion(self):
        self.evaluar()
        self.documento(self.ref + timedelta(days=10))
        self.modo("bloquear")
        foto = self.validar()["filas"][0]["foto"]
        self.assertFalse(foto["advertencias"])
        self.assertTrue(foto["informativas"])

    def test_no_elegidos_no_bloquean_ni_exigen_justificacion(self):
        self.p.cantidad_autorizada = 0
        self.p.save()
        self.modo("bloquear")
        self.assertTrue(self.validar()["filas"])
        self.assertTrue(self.control()["filas"][0]["foto"]["advertencias"])

    def test_justificacion_guardada_con_motivo_se_revalida_al_cierre(self):
        documental.guardar_justificacion(self.lista, justificacion=MOTIVO, actor=self.admin, motivo=MOTIVO, referencia=self.ref)
        self.assertTrue(RegistroBitacora.objects.filter(accion="elegibles.justificacion_documental", actor=self.admin).exists())
        self.validar()
        self.modo("bloquear")
        with self.assertRaises(ValidationError):
            self.validar()

    def test_foto_y_referencia_no_cambian_tras_nueva_evaluacion_documentos_y_parametros(self):
        ev = self.evaluar()
        self.documento(self.ref - timedelta(days=1))
        self.lista = self.congelar()
        self.p.refresh_from_db()
        foto = deepcopy(self.p.estado_documental)
        self.assertEqual(self.p.evaluacion_fr14_id, ev.pk)
        self.assertEqual(self.lista.documental_por, self.admin)
        self.assertEqual(self.lista.documental_referencia, self.ref)
        self.assertTrue(self.lista.documental_fecha)
        nueva = self.evaluar(self.ref + timedelta(days=1))
        self.documento(self.ref + timedelta(days=100), expedicion=self.ref)
        self.modo("bloquear")
        control = documental.obtener_control(self.lista, referencia=self.ref + timedelta(days=300))
        self.assertTrue(control["historico"])
        self.assertEqual(control["filas"][0]["foto"], foto)
        self.assertEqual(control["reglas"]["modo"], "advertir")
        self.assertNotEqual(control["filas"][0]["foto"]["evaluacion"]["id"], nueva.pk)
        with self.assertRaises(ValidationError):
            documental.conservar_al_cerrar(self.lista, actor=self.admin, motivo=MOTIVO)
        with self.assertRaises(ValidationError):
            documental.guardar_justificacion(self.lista, justificacion="Otra", actor=self.admin, motivo=MOTIVO)

    def test_lista_antigua_sin_foto_no_usa_datos_actuales(self):
        self.evaluar()
        ListaElegibles.objects.filter(pk=self.lista.pk).update(estado="cerrada")
        self.lista.refresh_from_db()
        control = self.control()
        self.assertTrue(control["sin_foto"])
        self.assertEqual(control["filas"][0]["foto"], {})
        with self.assertRaises(ValidationError):
            self.validar()

    def test_foto_no_se_guarda_en_borrador_y_el_fallo_revierte_toda_la_captura(self):
        with self.assertRaises(ValidationError):
            documental.conservar_al_cerrar(self.lista, actor=self.admin, motivo=MOTIVO)
        def fallo(instancia, *args, **kwargs):
            if isinstance(instancia, ListaElegibles):
                raise RuntimeError("Fallo simulado de auditoría")
            return guardar_con_bitacora(instancia, *args, **kwargs)
        documental.guardar_justificacion(self.lista, justificacion=MOTIVO, actor=self.admin, motivo=MOTIVO, referencia=self.ref)
        with patch("compras.documental_servicios.guardar_con_bitacora", side_effect=fallo):
            with self.assertRaises(RuntimeError), transaction.atomic():
                ListaElegibles.objects.filter(pk=self.lista.pk).update(estado="cerrada")
                documental.conservar_al_cerrar(self.lista, actor=self.admin, motivo=MOTIVO, referencia=self.ref)
        self.lista.refresh_from_db()
        self.p.refresh_from_db()
        self.assertEqual(self.lista.estado, "borrador")
        self.assertIsNone(self.lista.documental_fecha)
        self.assertEqual(self.p.estado_documental, {})

    def test_parametros_rechazan_modos_y_antiguedades_invalidas(self):
        for clave, valor in [(CONTROL_DOCUMENTAL_ELEGIBLES, "ignorar"), (MESES_EVALUACION_ELEGIBLES, "0"), (MESES_EVALUACION_ELEGIBLES, "1.5")]:
            with self.subTest(valor=valor), self.assertRaises(ValidationError):
                cambiar_valor(Parametro.objects.get(clave=clave), valor, actor=self.admin, motivo=MOTIVO)

    def test_vista_documental_permisos_csrf_y_guardado(self):
        url = reverse("compras:lista_documental", args=[self.lista.pk])
        for usuario in [self.coordinador, self.usuario_proveedor]:
            self.client.force_login(usuario)
            self.assertEqual(self.client.get(url).status_code, 403)
            self.assertEqual(self.client.post(url, {}).status_code, 403)
        for usuario in [self.admin, self.dev]:
            self.client.force_login(usuario)
            self.assertContains(self.client.get(url), "Sin evaluación FR-GDS-14")
        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(self.admin)
        self.assertEqual(cliente.post(url, {"justificacion": MOTIVO, "motivo": MOTIVO}).status_code, 403)
        self.assertRedirects(self.client.post(url, {"justificacion": MOTIVO, "motivo": MOTIVO}), url)
        for actor in [self.coordinador, self.usuario_proveedor, AnonymousUser()]:
            with self.assertRaises(PermissionDenied):
                documental.guardar_justificacion(self.lista, justificacion=MOTIVO, actor=actor, motivo=MOTIVO)
            with self.assertRaises(PermissionDenied):
                documental.conservar_al_cerrar(self.lista, actor=actor, motivo=MOTIVO)
        with self.assertRaises(ValidationError):
            documental.guardar_justificacion(self.lista, justificacion=MOTIVO, actor=self.admin, motivo=" ")

    def test_excel_exporta_foto_conservada_y_enlace_fr14(self):
        ev = self.evaluar()
        self.documento(self.ref - timedelta(days=1))
        self.lista = self.congelar()
        self.client.force_login(self.admin)
        respuesta = self.client.get(reverse("compras:lista_documental", args=[self.lista.pk]))
        self.assertContains(respuesta, reverse("proveedores:evaluacion_detalle", args=[ev.pk]))
        self.assertContains(respuesta, "Foto conservada al cierre")
        respuesta = self.client.get(reverse("compras:lista_exportar", args=[self.lista.pk]))
        libro = load_workbook(BytesIO(respuesta.content))
        self.addCleanup(libro.close)
        hoja = libro["Estado documental"]
        self.assertEqual(hoja["B1"].value, "Histórico conservado")
        self.assertEqual(hoja["D6"].value, ev.pk)
        self.assertEqual(hoja["F6"].value, 5)
        self.assertEqual(hoja["K6"].value, "Vencido")
        self.assertEqual(hoja.freeze_panes, "A6")
