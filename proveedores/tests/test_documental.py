from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from cuentas.models import Rol
from cuentas.tests.utilidades import crear_usuario
from parametros.catalogo import BLOQUEAR_SI_VENCIDO, DIAS_ALERTA_VENCIMIENTO
from parametros.models import Parametro
from proveedores import matrices_servicios, servicios
from proveedores.documental import clasificar, tablero
from proveedores.evaluacion_servicios import finalizar_evaluacion
from proveedores.models import DocumentoExigido, DocumentoProveedor, RespuestaEvaluacion
from proveedores.respuestas_servicios import guardar_respuesta
from proveedores.tests import test_matrices
from proveedores.tests.utilidades import MOTIVO, tipo_documento


class DocumentalTests(TestCase):
    def setUp(self):
        test_matrices.MatricesTests.setUp(self)
        self.ref = date(2026, 1, 15)
        self.tipo = tipo_documento()
        matrices_servicios.publicar_version(self.version, desde=self.fecha, actor=self.admin, motivo=MOTIVO)
        self.ev = matrices_servicios.crear_evaluacion(self.proveedor, self.categoria, self.ref, actor=self.admin, motivo=MOTIVO)
        self.exigido = servicios.guardar_catalogo(DocumentoExigido(categoria=self.categoria, tipo=self.tipo, requisito=self.req), actor=self.admin, motivo=MOTIVO)
        self.proveedor.categoria = self.categoria
        self.proveedor.save()

    def doc(self, vence, exp=None, tipo=None):
        return DocumentoProveedor.objects.create(proveedor=self.proveedor, tipo=tipo or self.tipo,
            fecha_expedicion=exp or self.ref - timedelta(days=90), fecha_vencimiento=vence,
            enlace="https://documentos.ejemplo.test/soporte", cargado_por=self.admin)

    def filas(self, **kwargs):
        return tablero(self.proveedor, categoria=self.categoria, version=self.version, hoy=self.ref, **kwargs)

    def responder(self, documento=None, **kwargs):
        return guardar_respuesta(self.ev, self.req, respuesta="si", observacion="Revisado", confirma_na=False,
            documento=documento, actor=self.admin, motivo=MOTIVO, **kwargs)

    def test_cuatro_estados_con_fechas_fijas_y_bordes(self):
        casos = [(None, "vigente"), (self.ref + timedelta(days=31), "vigente"),
                 (self.ref + timedelta(days=30), "por_vencer"), (self.ref, "por_vencer"),
                 (self.ref - timedelta(days=1), "vencido")]
        for vence, esperado in casos:
            self.assertEqual(clasificar(expedicion=self.ref, vencimiento=vence, referencia=self.ref), esperado)
        self.assertEqual(clasificar(expedicion=self.ref + timedelta(days=1), vencimiento=None, referencia=self.ref), "faltante")
        self.assertEqual(self.filas()[0]["estado"], "faltante")
        self.assertEqual(clasificar(expedicion=self.ref, vencimiento=None, referencia=self.ref, requiere_vencimiento=True), "faltante")

    def test_tablero_vigente_proximo_vencido_y_renovacion(self):
        viejo = self.doc(self.ref - timedelta(days=1))
        self.assertEqual(self.filas()[0]["estado"], "vencido")
        nuevo = self.doc(self.ref + timedelta(days=20), exp=self.ref - timedelta(days=1))
        self.assertEqual(self.filas()[0]["documento"].pk, nuevo.pk)
        self.assertEqual(self.filas()[0]["estado"], "por_vencer")
        nuevo.fecha_vencimiento = self.ref + timedelta(days=60)
        nuevo.save()
        self.assertEqual(self.filas()[0]["estado"], "vigente")

    def test_documento_expedido_despues_de_evaluacion_no_es_vigente(self):
        self.doc(self.ref + timedelta(days=200), exp=self.ref + timedelta(days=1))
        self.assertEqual(self.filas()[0]["estado"], "faltante")

    def test_plazo_general_y_por_tipo_configurables(self):
        self.doc(self.ref + timedelta(days=45))
        self.assertEqual(self.filas()[0]["estado"], "vigente")
        Parametro.objects.filter(clave=DIAS_ALERTA_VENCIMIENTO).update(valor="60")
        self.assertEqual(self.filas()[0]["estado"], "por_vencer")
        self.tipo.usar_alerta_general = False
        self.tipo.dias_alerta = 10
        self.tipo.save()
        self.assertEqual(self.filas()[0]["estado"], "vigente")

    def test_si_vencido_advierte_por_defecto_y_bloquea_por_parametro(self):
        doc = self.doc(self.ref - timedelta(days=1))
        respuesta = self.responder(doc)
        self.assertEqual(respuesta.control_documental["estado_evidencia"], "vencido")
        self.assertTrue(respuesta.control_documental["advertencias"])
        Parametro.objects.filter(clave=BLOQUEAR_SI_VENCIDO).update(valor="true")
        with self.assertRaises(ValidationError):
            self.responder(doc)
        from proveedores.historial_servicios import copiar_evaluacion
        with self.assertRaises(ValidationError):
            copiar_evaluacion(self.ev, actor=self.admin, motivo=MOTIVO)
        self.assertEqual(RespuestaEvaluacion.objects.count(), 1)

    def test_evidencia_no_expedida_y_tipo_no_asociado_rechazados(self):
        doc = self.doc(self.ref + timedelta(days=200), exp=self.ref + timedelta(days=1))
        self.assertEqual(self.responder(doc).control_documental["estado_evidencia"], "faltante")
        Parametro.objects.filter(clave=BLOQUEAR_SI_VENCIDO).update(valor="true")
        with self.assertRaises(ValidationError):
            self.responder(doc)
        otro = self.doc(self.ref + timedelta(days=10), tipo=tipo_documento("Otro tipo"))
        with self.assertRaises(ValidationError):
            self.responder(otro)

    def test_estado_de_evidencia_es_del_documento_elegido_no_de_renovacion(self):
        viejo = self.doc(self.ref - timedelta(days=1))
        self.doc(self.ref + timedelta(days=90), exp=self.ref)
        self.assertEqual(self.filas()[0]["estado"], "vigente")
        self.assertEqual(self.responder(viejo).control_documental["estado_evidencia"], "vencido")

    def test_finalizada_conserva_estado_documental_guardado(self):
        doc = self.doc(self.ref - timedelta(days=1))
        respuesta = self.responder(doc)
        finalizar_evaluacion(self.ev, actor=self.admin, motivo=MOTIVO)
        doc.fecha_vencimiento = self.ref + timedelta(days=100)
        doc.save()
        self.client.force_login(self.admin)
        detalle = self.client.get(reverse("proveedores:evaluacion_detalle", args=[self.ev.pk]))
        self.assertContains(detalle, "Vencido")
        respuesta.refresh_from_db()
        self.assertEqual(respuesta.control_documental["estado_evidencia"], "vencido")

    def test_catalogo_crud_sin_borrar_y_permisos(self):
        rutas = [reverse("configuracion:catalogos_proveedores", args=["documentos-exigidos"]),
                 reverse("configuracion:catalogo_proveedor_nuevo", args=["documentos-exigidos"]),
                 reverse("configuracion:catalogo_proveedor_editar", args=["documentos-exigidos", self.exigido.pk]),
                 reverse("configuracion:catalogo_proveedor_estado", args=["documentos-exigidos", self.exigido.pk])]
        for rol in (Rol.COORDINADOR, Rol.PROVEEDOR):
            self.client.force_login(crear_usuario(rol))
            for url in rutas:
                self.assertEqual(self.client.get(url).status_code, 403)
                self.assertEqual(self.client.post(url, {}).status_code, 403)
        for usuario in (self.admin, crear_usuario(Rol.DESARROLLADOR)):
            self.client.force_login(usuario)
            for url in rutas:
                self.assertEqual(self.client.get(url).status_code, 200)
        respuesta = self.client.post(rutas[2], {"categoria": self.categoria.pk, "tipo": self.tipo.pk, "requisito": self.req.pk, "motivo": MOTIVO})
        self.assertEqual(respuesta.status_code, 302)
        self.exigido.refresh_from_db()
        self.assertFalse(self.exigido.obligatorio)
        self.client.post(rutas[3], {"motivo": MOTIVO})
        self.exigido.refresh_from_db()
        self.assertFalse(self.exigido.activo)

    def test_unicidad_de_exigencias_con_y_sin_requisito(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            DocumentoExigido.objects.create(categoria=self.categoria, tipo=self.tipo, requisito=self.req)
        DocumentoExigido.objects.create(categoria=self.categoria, tipo=self.tipo)
        with self.assertRaises(IntegrityError), transaction.atomic():
            DocumentoExigido.objects.create(categoria=self.categoria, tipo=self.tipo)

    def test_vencimientos_filtrables_y_alertas_visibles(self):
        from django.utils import timezone
        hoy = timezone.localdate()
        self.doc(hoy - timedelta(days=1), exp=hoy - timedelta(days=90))
        self.client.force_login(self.admin)
        url = reverse("proveedores:vencimientos")
        datos = {"q": self.proveedor.nit_formateado, "tipo": self.tipo.pk, "estado": "vencido", "categoria": self.categoria.pk}
        self.assertEqual(len(self.client.get(url, datos).context["vencidos"]), 1)
        self.assertEqual(len(self.client.get(url, {"q": "No existe"}).context["vencidos"]), 0)
        ficha = self.client.get(reverse("proveedores:detalle", args=[self.proveedor.pk]))
        self.assertContains(ficha, "Documentos exigidos por categoría")
        self.assertContains(ficha, "vigencia--vencido")

    def test_advertencia_http_y_colores(self):
        doc = self.doc(self.ref - timedelta(days=1))
        self.client.force_login(self.admin)
        url = reverse("proveedores:evaluacion_responder", args=[self.ev.pk, self.req.pk])
        respuesta = self.client.post(url, {"respuesta": "si", "documento": doc.pk, "motivo": MOTIVO}, follow=True)
        self.assertContains(respuesta, "Se permite con advertencia")
        self.assertContains(respuesta, "vigencia--vencido")
