from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.test import Client, TestCase
from django.urls import reverse

from bitacora.models import RegistroBitacora
from bitacora.servicios import registrar
from compras import cotizacion_servicios, oferta_servicios, tests_cotizaciones, verificacion_servicios as servicios
from compras.models import Cotizacion, EstadoVerificacion, PdfVerificacionOferta, TipoVerificacion, VerificacionOferta
from proveedores import archivos
from proveedores.models import CategoriaProveedor, DocumentoExigido, DocumentoProveedor
from proveedores.tests.utilidades import MediaTemporal, crear_proveedor, pdf, tipo_documento

MOTIVO = "Verificación ficticia por responsable autorizado"


class VerificacionesTests(MediaTemporal, TestCase):
    def setUp(self):
        super().setUp()
        tests_cotizaciones.CotizacionesTests.setUp(self)
        self.ref = date(2026, 6, 15)
        self.cotizacion = cotizacion_servicios.crear_cotizacion(necesidad=self.necesidad, fecha=self.fecha, tipo=self.tipo,
            objeto="Cotización ficticia de verificaciones", lineas=[{"descripcion": "Insumo", "unidad": self.unidad, "cantidad": Decimal(2)}],
            invitados=[self.ficha], actor=self.admin, motivo=MOTIVO)
        from compras.models import TarifaImpuesto
        self.tarifa = TarifaImpuesto.objects.get(nombre="Exento/No gravado")
        self.invitado = self.cotizacion.invitados.get()
        self.oferta = self.guardar_oferta()
        self.manual = TipoVerificacion.objects.get(nombre="Requisitos técnicos")
        self.documental = TipoVerificacion.objects.get(origen="documental")
        self.estados = {e.clasificacion: e for e in EstadoVerificacion.objects.all()}
        self.categoria = CategoriaProveedor.objects.create(nombre="Categoría documental ficticia")
        self.ficha.categoria = self.categoria
        self.ficha.save()
        self.tipo_documento = tipo_documento("Documento ficticio exigido")
        self.exigencia = DocumentoExigido.objects.create(categoria=self.categoria, tipo=self.tipo_documento, obligatorio=True)

    def calificar(self, valores=None):
        return tests_cotizaciones.CotizacionesTests.calificar(self, valores)

    def asignaciones(self, cantidades=None, justificaciones=None):
        return tests_cotizaciones.CotizacionesTests.asignaciones(self, cantidades, justificaciones)

    def decidir(self, **kwargs):
        return tests_cotizaciones.CotizacionesTests.decidir(self, **kwargs)

    def guardar_oferta(self):
        return oferta_servicios.guardar_oferta(self.cotizacion, self.invitado, contacto_nombre="Contacto ficticio",
            contacto_correo="contacto@ejemplo.test", contacto_telefono="601 555 0100", fecha=self.ref,
            precios=[{"linea": self.cotizacion.lineas.get().pk, "precio_unitario": Decimal(10), "tarifa": self.tarifa}], actor=self.admin, motivo=MOTIVO)

    def guardar(self, **cambios):
        datos = dict(estado=self.estados["si"], fecha=self.ref, observacion="Revisado por responsable ficticio", actor=self.admin, motivo=MOTIVO)
        datos.update(cambios)
        tipo = datos.pop("tipo", self.manual)
        return servicios.guardar_verificacion(self.oferta, tipo, **datos)

    def guardar_doc(self, **cambios):
        propuesta = servicios.proponer_documental(self.oferta, fecha=self.ref)
        datos = dict(tipo=self.documental, estado=self.estados[propuesta["clasificacion"]], observacion="", confirmar_propuesta=True,
            firma_propuesta=signing.dumps(propuesta, salt="propuesta-verificacion"))
        datos.update(cambios)
        return self.guardar(**datos)

    def doc(self, vence, exp=None):
        return DocumentoProveedor.objects.create(proveedor=self.ficha, tipo=self.tipo_documento,
            fecha_expedicion=exp or self.ref - timedelta(days=20), fecha_vencimiento=vence,
            enlace="https://documentos.ejemplo.test/verificacion", cargado_por=self.admin)

    def test_cuatro_estados_guardan_fecha_actor_proveedor_e_historial(self):
        for n, clase in enumerate(["si", "no", "pendiente", "na"], 1):
            registro = self.guardar(estado=self.estados[clase], actor=self.dev)
            self.assertEqual(registro.fecha, self.ref)
            self.assertEqual(registro.verificado_por, self.dev)
            self.assertEqual(registro.oferta.proveedor_id, self.ficha.pk)
            self.assertEqual(registro.estado_clasificacion, clase)
            self.assertEqual(registro.revision, n)
        self.assertEqual(VerificacionOferta.objects.count(), 1)
        self.assertEqual(registro.revisiones.count(), 4)
        self.assertEqual(registro.revisiones.last().contenido["clasificacion"], "si")
        self.assertTrue(RegistroBitacora.objects.filter(accion="verificacion.confirmada", actor=self.dev, motivo=MOTIVO).exists())

    def test_catalogos_editables_y_foto_anterior_no_cambia_al_renombrar_estado(self):
        registro = self.guardar(estado=self.estados["no"])
        estado = self.estados["no"]
        estado.nombre, estado.clasificacion = "Estado renombrado ficticio", "si"
        servicios.guardar_estado(estado, actor=self.admin, motivo=MOTIVO)
        registro.refresh_from_db()
        self.assertEqual(registro.estado_nombre, "No")
        self.assertEqual(registro.estado_clasificacion, "no")
        self.manual.obligatoria = True
        servicios.guardar_tipo(self.manual, actor=self.admin, motivo=MOTIVO)
        matriz = servicios.matriz_verificaciones(self.cotizacion)
        self.assertEqual(matriz["alertas"], 1)
        servicios.guardar_tipo(TipoVerificacion(nombre="Otra revisión ficticia", orden=5), actor=self.admin, motivo=MOTIVO)
        with self.assertRaises(ValidationError):
            servicios.guardar_tipo(TipoVerificacion(nombre=" REQUISITOS TÉCNICOS "), actor=self.admin, motivo=MOTIVO)

    def test_alertas_obligatorias_no_pendiente_y_falta_de_confirmacion(self):
        self.manual.obligatoria = True
        servicios.guardar_tipo(self.manual, actor=self.admin, motivo=MOTIVO)
        self.assertEqual(servicios.matriz_verificaciones(self.cotizacion)["alertas"], 1)
        for clase, alertas in [("no", 1), ("pendiente", 1), ("si", 0), ("na", 0)]:
            self.guardar(estado=self.estados[clase])
            self.assertEqual(servicios.matriz_verificaciones(self.cotizacion)["alertas"], alertas)

    def test_propuesta_documental_vigente_proximo_vencido_y_faltante_a_fecha(self):
        self.assertEqual(servicios.proponer_documental(self.oferta, fecha=self.ref)["clasificacion"], "no")
        doc = self.doc(self.ref + timedelta(days=90))
        propuesta = servicios.proponer_documental(self.oferta, fecha=self.ref)
        self.assertEqual(propuesta["clasificacion"], "si")
        self.assertEqual(propuesta["documentos"][0]["documento_id"], doc.pk)
        doc.fecha_vencimiento = self.ref
        doc.save()
        propuesta = servicios.proponer_documental(self.oferta, fecha=self.ref)
        self.assertEqual(propuesta["clasificacion"], "si")
        self.assertEqual(propuesta["documentos"][0]["estado"], "por_vencer")
        self.assertEqual(servicios.proponer_documental(self.oferta, fecha=self.ref + timedelta(days=1))["clasificacion"], "no")

    def test_documento_futuro_no_es_vigente_y_opcional_o_catalogo_vacio_es_pendiente(self):
        self.doc(self.ref + timedelta(days=60), exp=self.ref + timedelta(days=1))
        propuesta = servicios.proponer_documental(self.oferta, fecha=self.ref)
        self.assertEqual(propuesta["clasificacion"], "no")
        self.assertIsNone(propuesta["documentos"][0]["documento_id"])
        self.exigencia.obligatorio = False
        self.exigencia.save()
        self.assertEqual(servicios.proponer_documental(self.oferta, fecha=self.ref)["clasificacion"], "pendiente")
        self.exigencia.activo = False
        self.exigencia.save()
        self.assertEqual(servicios.proponer_documental(self.oferta, fecha=self.ref)["clasificacion"], "pendiente")

    def test_propuesta_usa_fr14_a_fecha_y_no_una_evaluacion_futura(self):
        from proveedores import matrices_servicios
        from proveedores.evaluacion_servicios import finalizar_evaluacion
        from proveedores.models import Peso, Requisito, VersionMatriz
        from proveedores.respuestas_servicios import guardar_respuesta
        version = VersionMatriz.objects.get(numero=1)
        requisito = Requisito.objects.create(version=version, numero=1, grupo="calidad", texto="Requisito ficticio")
        Peso.objects.create(requisito=requisito, categoria=self.categoria, valor=1)
        matrices_servicios.publicar_version(version, desde=date(2026, 1, 1), actor=self.admin, motivo=MOTIVO)
        evaluaciones = []
        for fecha in [self.ref, self.ref + timedelta(days=1)]:
            evaluacion = matrices_servicios.crear_evaluacion(self.ficha, self.categoria, fecha, actor=self.admin, motivo=MOTIVO)
            guardar_respuesta(evaluacion, requisito, respuesta="si", observacion="Revisado", confirma_na=False, actor=self.admin, motivo=MOTIVO)
            evaluaciones.append(finalizar_evaluacion(evaluacion, actor=self.admin, motivo=MOTIVO))
        self.doc(self.ref + timedelta(days=90))
        propuesta = servicios.proponer_documental(self.oferta, fecha=self.ref)
        self.assertEqual(propuesta["evaluacion_id"], evaluaciones[0].pk)
        self.assertEqual(propuesta["clasificacion"], "si")

    def test_documental_exige_confirmacion_firma_y_observacion_al_apartarse(self):
        with self.assertRaises(ValidationError):
            self.guardar_doc(confirmar_propuesta=False)
        with self.assertRaises(ValidationError):
            self.guardar_doc(firma_propuesta="firma alterada")
        with self.assertRaises(ValidationError):
            self.guardar_doc(estado=self.estados["si"], observacion=" ")
        registro = self.guardar_doc(estado=self.estados["si"], observacion="Se confirma con revisión adicional ficticia")
        self.assertEqual(registro.propuesta["clasificacion"], "no")
        self.assertEqual(registro.estado_clasificacion, "si")

    def test_propuesta_cambiada_no_se_confirma_con_firma_vieja(self):
        propuesta = servicios.proponer_documental(self.oferta, fecha=self.ref)
        firma = signing.dumps(propuesta, salt="propuesta-verificacion")
        self.doc(self.ref + timedelta(days=90))
        with self.assertRaises(ValidationError):
            self.guardar_doc(firma_propuesta=firma)
        self.assertFalse(VerificacionOferta.objects.exists())

    def test_foto_y_revision_conservadas_al_renovar_documentos(self):
        self.doc(self.ref - timedelta(days=1))
        registro = self.guardar_doc()
        foto = deepcopy(registro.propuesta)
        historico = registro.revisiones.get()
        self.doc(self.ref + timedelta(days=90), exp=self.ref)
        registro.refresh_from_db()
        self.assertEqual(registro.propuesta, foto)
        historico.refresh_from_db()
        self.assertEqual(historico.contenido["propuesta"], foto)
        self.assertEqual(servicios.proponer_documental(self.oferta, fecha=self.ref)["clasificacion"], "si")

    def test_cambio_de_oferta_exige_reconfirmar_sin_reescribir_estado_original(self):
        self.manual.obligatoria = True
        servicios.guardar_tipo(self.manual, actor=self.admin, motivo=MOTIVO)
        registro = self.guardar()
        self.guardar_oferta()
        matriz = servicios.matriz_verificaciones(self.cotizacion)
        celda = next(c for c in matriz["filas"][0]["celdas"] if c["tipo"].pk == self.manual.pk)
        self.assertTrue(celda["desactualizada"])
        self.assertTrue(celda["alerta"])
        self.assertEqual(celda["clasificacion"], "pendiente")
        registro.refresh_from_db()
        self.assertEqual(registro.estado_clasificacion, "si")
        self.assertEqual(registro.oferta_revision, 1)
        with self.assertRaises(ValidationError):
            self.guardar(oferta_revision_esperada=1)

    def test_estado_o_tipo_inactivo_y_revision_vieja_no_modifican_registros(self):
        self.guardar(revision_esperada=0)
        with self.assertRaises(ValidationError):
            self.guardar(revision_esperada=0)
        self.manual.activo = False
        servicios.guardar_tipo(self.manual, actor=self.admin, motivo=MOTIVO)
        with self.assertRaises(ValidationError):
            self.guardar()
        self.manual.activo = True
        servicios.guardar_tipo(self.manual, actor=self.admin, motivo=MOTIVO)
        self.estados["si"].activo = False
        servicios.guardar_estado(self.estados["si"], actor=self.admin, motivo=MOTIVO)
        with self.assertRaises(ValidationError):
            self.guardar()

    def test_estados_finales_solo_lectura_y_no_se_trasladan_verificaciones(self):
        registro = self.guardar()
        registro.tipo = self.documental
        with self.assertRaises(ValidationError):
            registro.save()
        from compras import proveedor_unico_servicios
        from compras.models import CausalProveedorUnico
        self.cotizacion = proveedor_unico_servicios.guardar_caso(self.cotizacion, proveedor_unico=True,
            causal=CausalProveedorUnico.objects.get(nombre="Otra"), justificacion=MOTIVO, actor=self.admin, motivo=MOTIVO)
        for estado in ["decidida", "anulada"]:
            self.cotizacion.estado = estado
            self.cotizacion.save(update_fields=["estado"])
            with self.assertRaises(ValidationError):
                self.guardar()
        self.assertEqual(VerificacionOferta.objects.get().tipo_id, self.manual.pk)

    def test_evidencias_privadas_reemplazo_e_historial_inmutables(self):
        registro = self.guardar(archivo=pdf("primera.pdf"))
        anterior = registro.pdf
        registro = self.guardar(archivo=pdf("segunda.pdf"))
        registro = self.guardar(quitar_pdf=True)
        self.assertIsNone(registro.pdf_id)
        self.assertEqual(registro.revisiones.count(), 3)
        self.assertEqual(registro.revisiones.get(numero=1).pdf_id, anterior.pk)
        archivos.borrar_sin_referencias(anterior.archivo.name)
        self.assertTrue(Path(anterior.archivo.path).exists())
        with self.assertRaises(ValidationError):
            registro.revisiones.first().save()

    def test_fallo_auditoria_limpia_pdf_y_revierte_registro_e_historial(self):
        antes = RegistroBitacora.objects.count()
        def fallo(accion, **kwargs):
            if accion == "verificacion.confirmada":
                raise RuntimeError("Fallo ficticio")
            return registrar(accion, **kwargs)
        with patch("compras.verificacion_servicios.registrar", side_effect=fallo):
            with self.assertRaises(RuntimeError):
                self.guardar(archivo=pdf())
        self.assertFalse(VerificacionOferta.objects.exists())
        self.assertFalse(PdfVerificacionOferta.objects.exists())
        self.assertFalse(list(Path(settings.MEDIA_ROOT).rglob("*.pdf")))
        self.assertEqual(RegistroBitacora.objects.count(), antes)

    def test_pdf_invalido_y_transaccion_externa_se_rechazan(self):
        for archivo in [pdf("no.exe"), pdf("malo.pdf", b"no es pdf")]:
            with self.assertRaises(ValidationError):
                self.guardar(archivo=archivo)
        with self.assertRaises(ValidationError), transaction.atomic():
            self.guardar(archivo=pdf())
        self.assertFalse(VerificacionOferta.objects.exists())

    def test_formulario_documental_propone_sin_guardar_y_exige_confirmar(self):
        self.client.force_login(self.admin)
        url = reverse("compras:verificacion_guardar", args=[self.cotizacion.pk, self.oferta.pk, self.documental.pk]) + "?fecha=" + self.ref.isoformat()
        respuesta = self.client.get(url)
        self.assertContains(respuesta, "Propuesta documental")
        self.assertFalse(VerificacionOferta.objects.exists())
        formulario = respuesta.context["formulario"]
        datos = {"estado": self.estados["no"].pk, "motivo": MOTIVO, "oferta_revision_esperada": 1, "revision_esperada": 0,
                 "firma_propuesta": formulario["firma_propuesta"].value()}
        self.assertContains(self.client.post(url, datos), "confirme expresamente")
        datos["confirmar_propuesta"] = "on"
        respuesta = self.client.post(url, datos)
        registro = VerificacionOferta.objects.get()
        self.assertRedirects(respuesta, reverse("compras:verificacion_detalle", args=[self.cotizacion.pk, self.oferta.pk, registro.pk]))
        self.assertEqual(registro.fecha, self.ref)
        self.assertEqual(registro.estado_clasificacion, "no")

    def test_matriz_y_catalogos_y_descargas_con_permisos_y_csrf(self):
        registro = self.guardar(archivo=pdf())
        revision = registro.revisiones.get()
        base = [self.cotizacion.pk, self.oferta.pk, registro.pk]
        urls = [reverse("compras:verificaciones", args=[self.cotizacion.pk]),
            reverse("compras:verificacion_guardar", args=[self.cotizacion.pk, self.oferta.pk, self.manual.pk]),
            reverse("compras:verificacion_detalle", args=base), reverse("compras:verificacion_revision", args=base + [revision.pk]),
            reverse("compras:verificacion_pdf", args=base + [registro.pdf_id]), reverse("compras:verificacion_catalogo", args=["tipos"]),
            reverse("compras:verificacion_catalogo", args=["estados"])]
        for usuario in [self.coordinador, self.usuario_proveedor]:
            self.client.force_login(usuario)
            for url in urls:
                self.assertEqual(self.client.get(url).status_code, 403)
                self.assertEqual(self.client.post(url, {}).status_code, 403)
        self.client.force_login(self.admin)
        for url in urls[:4] + urls[5:]:
            self.assertEqual(self.client.get(url).status_code, 200)
        respuesta = self.client.get(urls[4])
        self.assertEqual(respuesta["X-Content-Type-Options"], "nosniff")
        self.assertTrue(b"".join(respuesta.streaming_content).startswith(b"%PDF-"))
        self.assertEqual(self.client.get(reverse("compras:verificacion_pdf", args=[99999, self.oferta.pk, registro.pk, registro.pdf_id])).status_code, 404)
        self.assertEqual(self.client.get(reverse("compras:verificacion_pdf", args=base + [99999])).status_code, 404)
        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(self.admin)
        self.assertEqual(cliente.post(urls[1], {}).status_code, 403)
        for usuario in [self.coordinador, self.usuario_proveedor, AnonymousUser()]:
            with self.assertRaises(PermissionDenied):
                self.guardar(actor=usuario)
            with self.assertRaises(PermissionDenied):
                servicios.guardar_estado(EstadoVerificacion(nombre="Otro", clasificacion="pendiente"), actor=usuario, motivo=MOTIVO)
        with self.assertRaises(ValidationError):
            self.guardar(motivo=" ")
