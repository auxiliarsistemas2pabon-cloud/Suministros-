from copy import deepcopy
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse

from bitacora.models import RegistroBitacora
from bitacora.servicios import registrar
from compras import cotizacion_servicios, oferta_servicios as ofertas, tests_cotizaciones
from compras.importes import calcular_importes
from compras.models import Cotizacion, Oferta, PdfOferta, RevisionOferta, TarifaImpuesto
from parametros.catalogo import DECIMALES_OFERTA, REDONDEO_OFERTA
from parametros.models import Parametro
from parametros.servicios import cambiar_valor
from proveedores import archivos
from proveedores.tests.utilidades import MediaTemporal, crear_proveedor, pdf

MOTIVO = "Oferta ficticia validada con importes reproducibles"
REGLAS = {"decimales": 0, "modo": "ROUND_HALF_UP"}


class ImportesTests(SimpleTestCase):
    def test_exento_y_tarifa_con_cantidades_fraccionarias_a_pesos(self):
        exento = calcular_importes("2.5", "100.15", "0", REGLAS)
        gravado = calcular_importes("2.5", "100.15", "19", REGLAS)
        self.assertEqual(exento, {"subtotal": Decimal(250), "impuesto": Decimal(0), "total": Decimal(250)})
        self.assertEqual(gravado, {"subtotal": Decimal(250), "impuesto": Decimal(48), "total": Decimal(298)})
        self.assertIsInstance(gravado["total"], Decimal)

    def test_centavos_y_redondeos_distintos_con_resultados_manuales(self):
        calculo = calcular_importes("2.5", "100.15", "19", {**REGLAS, "decimales": 2})
        self.assertEqual(calculo, {"subtotal": Decimal("250.38"), "impuesto": Decimal("47.57"), "total": Decimal("297.95")})
        self.assertEqual(calcular_importes("1", "100.5", "0", REGLAS)["total"], 101)
        self.assertEqual(calcular_importes("1", "100.5", "0", {**REGLAS, "modo": "ROUND_HALF_EVEN"})["total"], 100)

    def test_rechaza_no_finitos_flotantes_negativos_y_porcentajes_fuera_de_rango(self):
        for precio in [True, 0.1, "NaN", "Infinity", "-1"]:
            with self.subTest(precio=precio), self.assertRaises(ValidationError):
                calcular_importes("1", precio, "0", REGLAS)
        for cantidad, porcentaje in [("0", "0"), ("1", "101"), ("1", "-1")]:
            with self.assertRaises(ValidationError):
                calcular_importes(cantidad, "1", porcentaje, REGLAS)


class OfertasTests(MediaTemporal, TestCase):
    def setUp(self):
        super().setUp()
        tests_cotizaciones.CotizacionesTests.setUp(self)
        self.cotizacion = cotizacion_servicios.crear_cotizacion(necesidad=self.necesidad, fecha=self.fecha, tipo=self.tipo,
            objeto="Cotización ficticia para ofertas", lineas=[
                {"descripcion": "Insumo ficticio A", "unidad": self.unidad, "cantidad": Decimal("2.5")},
                {"descripcion": "Insumo ficticio B", "unidad": self.unidad, "cantidad": Decimal("3")}],
            invitados=[self.ficha], actor=self.admin, motivo=MOTIVO)
        self.invitado = self.cotizacion.invitados.get()
        self.cero = TarifaImpuesto.objects.get(nombre="Exento/No gravado")
        self.t19 = ofertas.guardar_tarifa(TarifaImpuesto(nombre="Tarifa ficticia 19", porcentaje=Decimal(19)), actor=self.admin, motivo=MOTIVO)
        self.t5 = ofertas.guardar_tarifa(TarifaImpuesto(nombre="Tarifa ficticia 5", porcentaje=Decimal(5)), actor=self.admin, motivo=MOTIVO)

    def calificar(self, valores=None):
        return tests_cotizaciones.CotizacionesTests.calificar(self, valores)

    def asignaciones(self, cantidades=None, justificaciones=None):
        return tests_cotizaciones.CotizacionesTests.asignaciones(self, cantidades, justificaciones)

    def decidir(self, **kwargs):
        return tests_cotizaciones.CotizacionesTests.decidir(self, **kwargs)

    def precios(self):
        lineas = list(self.cotizacion.lineas.all())
        return [{"linea": lineas[0].pk, "precio_unitario": Decimal("100.15"), "tarifa": self.t19},
                {"linea": lineas[1].pk, "precio_unitario": Decimal("12.34"), "tarifa": self.t5}]

    def guardar(self, **cambios):
        datos = dict(contacto_nombre="Contacto ficticio", contacto_correo="oferta@ejemplo.test", contacto_telefono="601 555 0100",
            fecha=self.fecha, vigente_hasta=date(2031, 3, 1), precios=self.precios(), actor=self.admin, motivo=MOTIVO)
        datos.update(cambios)
        return ofertas.guardar_oferta(self.cotizacion, self.invitado, **datos)

    def datos_post(self, revision=0, **cambios):
        datos = {"contacto_nombre": "Contacto ficticio", "contacto_correo": "oferta@ejemplo.test", "contacto_telefono": "601 555 0100",
            "fecha": "2031-02-01", "vigente_hasta": "2031-03-01", "motivo": MOTIVO, "revision_esperada": revision,
            "precios-TOTAL_FORMS": "2", "precios-INITIAL_FORMS": "2", "precios-0-precio_unitario": "100.15",
            "precios-0-tarifa": self.t19.pk, "precios-1-precio_unitario": "12.34", "precios-1-tarifa": self.t5.pk}
        datos.update(cambios)
        return datos

    def test_totales_por_linea_y_encabezado_tarifas_distintas_sin_mezclar_proveedor(self):
        oferta = self.guardar()
        self.assertEqual((oferta.subtotal, oferta.impuesto, oferta.total), (Decimal(287), Decimal(50), Decimal(337)))
        self.assertEqual([l.total for l in oferta.lineas.all()], [Decimal(298), Decimal(39)])
        self.assertEqual(oferta.nit, self.invitado.nit)
        self.assertEqual(oferta.revision, 1)
        self.assertEqual(oferta.revisiones.get().actor, self.admin)
        self.assertTrue(RegistroBitacora.objects.filter(accion="oferta.creada", motivo=MOTIVO, actor=self.admin).exists())

    def test_oferta_unica_se_actualiza_con_revision_inmutable_y_reglas_conservadas(self):
        oferta = self.guardar()
        revision = oferta.revisiones.get()
        foto = deepcopy(revision.contenido)
        self.t19.porcentaje = Decimal(25)
        ofertas.guardar_tarifa(self.t19, actor=self.admin, motivo=MOTIVO)
        cambiar_valor(Parametro.objects.get(clave=DECIMALES_OFERTA), "2", actor=self.admin, motivo=MOTIVO)
        oferta.refresh_from_db()
        self.assertEqual(oferta.total, 337)
        self.assertEqual(oferta.lineas.first().porcentaje, 19)
        actualizada = self.guardar(revision_esperada=1)
        self.assertEqual(actualizada.pk, oferta.pk)
        self.assertEqual(Oferta.objects.count(), 1)
        self.assertEqual(actualizada.total, Decimal("351.85"))
        self.assertEqual(actualizada.revisiones.count(), 2)
        revision.refresh_from_db()
        self.assertEqual(revision.contenido, foto)
        self.assertEqual(actualizada.reglas_calculo["decimales"], 2)
        with self.assertRaises(ValidationError):
            revision.save()

    def test_exento_cero_y_precio_cero_son_validos(self):
        precios = self.precios()
        for precio in precios:
            precio["tarifa"] = self.cero
        precios[1]["precio_unitario"] = Decimal(0)
        oferta = self.guardar(precios=precios)
        self.assertEqual(oferta.impuesto, 0)
        self.assertEqual(oferta.total, 250)

    def test_precios_invalidos_fechas_y_tarifas_inactivas_revierten_todo(self):
        for valor in ["-1", "NaN", "Infinity", True, 1.0, "1.00001"]:
            precios = self.precios()
            precios[-1]["precio_unitario"] = valor
            with self.subTest(valor=valor), self.assertRaises(ValidationError):
                self.guardar(precios=precios)
        with self.assertRaises(ValidationError):
            self.guardar(vigente_hasta=date(2030, 1, 1))
        self.t5.activo = False
        ofertas.guardar_tarifa(self.t5, actor=self.admin, motivo=MOTIVO)
        with self.assertRaises(ValidationError):
            self.guardar()
        self.assertFalse(Oferta.objects.exists())

    def test_lineas_ajenas_repetidas_o_incompletas_no_se_guardan(self):
        otra = cotizacion_servicios.crear_cotizacion(necesidad=self.necesidad, fecha=self.fecha, tipo=self.tipo, objeto="Otra ficticia",
            lineas=[{"descripcion": "Ajena", "unidad": self.unidad, "cantidad": Decimal(1)}], actor=self.admin, motivo=MOTIVO)
        precios = self.precios()
        precios[0]["linea"] = otra.lineas.get().pk
        for seleccion in [precios, [self.precios()[0]], [self.precios()[0], self.precios()[0]]]:
            with self.assertRaises(ValidationError):
                self.guardar(precios=seleccion)
        self.assertFalse(Oferta.objects.exists())

    def test_invitacion_de_otra_cotizacion_no_se_puede_usar(self):
        otra = cotizacion_servicios.crear_cotizacion(necesidad=self.necesidad, fecha=self.fecha, tipo=self.tipo, objeto="Otro proceso ficticio",
            lineas=[{"descripcion": "Ajena", "unidad": self.unidad, "cantidad": Decimal(1)}], invitados=[crear_proveedor()], actor=self.admin, motivo=MOTIVO)
        with self.assertRaises(ValidationError):
            ofertas.guardar_oferta(self.cotizacion, otra.invitados.get(), contacto_nombre="Ficticio", contacto_correo="contacto@ejemplo.test",
                contacto_telefono="601 555 0300", fecha=self.fecha, precios=self.precios(), actor=self.admin, motivo=MOTIVO)
        self.assertFalse(Oferta.objects.exists())

    def test_no_se_pueden_trasladar_identidades_ni_precios_por_orm(self):
        oferta = self.guardar()
        otro = crear_proveedor()
        oferta.proveedor = otro
        with self.assertRaises(ValidationError):
            oferta.save()
        precio = oferta.lineas.first()
        precio.linea = self.cotizacion.lineas.last()
        with self.assertRaises(ValidationError):
            precio.save()
        with self.assertRaises(ValidationError):
            Oferta.objects.filter(pk=oferta.pk).update(total=0)

    def test_proveedores_distintos_tienen_ofertas_separadas(self):
        primera = self.guardar()
        invitado = ofertas.invitar_proveedor(self.cotizacion, crear_proveedor(), actor=self.admin, motivo=MOTIVO)
        segunda = ofertas.guardar_oferta(self.cotizacion, invitado, contacto_nombre="Otro ficticio", contacto_correo="otro@ejemplo.test",
            contacto_telefono="601 555 0200", fecha=self.fecha, precios=[{**p, "precio_unitario": Decimal(1)} for p in self.precios()], actor=self.admin, motivo=MOTIVO)
        self.assertNotEqual(primera.pk, segunda.pk)
        primera.refresh_from_db()
        self.assertEqual(primera.total, 337)
        self.assertNotEqual(primera.nit, segunda.nit)

    def test_cotizacion_decidida_o_anulada_es_solo_lectura(self):
        oferta = self.guardar()
        from compras import proveedor_unico_servicios
        from compras.models import CausalProveedorUnico
        self.cotizacion = proveedor_unico_servicios.guardar_caso(self.cotizacion, proveedor_unico=True,
            causal=CausalProveedorUnico.objects.get(nombre="Otra"), justificacion=MOTIVO, actor=self.admin, motivo=MOTIVO)
        for estado in ["decidida", "anulada"]:
            self.cotizacion.estado = estado
            self.cotizacion.save(update_fields=["estado"])
            with self.assertRaises(ValidationError):
                self.guardar()
            with self.assertRaises(ValidationError):
                oferta.save()
            with self.assertRaises(ValidationError):
                ofertas.invitar_proveedor(self.cotizacion, crear_proveedor(), actor=self.admin, motivo=MOTIVO)

    def test_pdf_validado_privado_reemplazo_y_retirada_conservan_archivos_anteriores(self):
        oferta = self.guardar(archivo=pdf("primero.pdf"))
        anterior = oferta.pdf
        ruta = Path(anterior.archivo.path)
        oferta = self.guardar(archivo=pdf("segundo.pdf"))
        self.assertNotEqual(oferta.pdf_id, anterior.pk)
        self.assertTrue(ruta.exists())
        archivos.borrar_sin_referencias(anterior.archivo.name)
        self.assertTrue(ruta.exists())
        oferta = self.guardar(quitar_pdf=True)
        self.assertIsNone(oferta.pdf_id)
        self.assertEqual(PdfOferta.objects.count(), 2)
        self.assertEqual(oferta.revisiones.first().numero, 3)
        self.assertEqual(oferta.revisiones.get(numero=1).pdf_id, anterior.pk)

    def test_archivo_invalido_o_transaccion_externa_no_dejan_residuos(self):
        grande = pdf("grande.pdf")
        grande.size = archivos.TAMANO_MAXIMO + 1
        for archivo in [pdf("no.exe"), pdf("invalido.pdf", b"no es PDF"), grande]:
            with self.assertRaises(ValidationError):
                self.guardar(archivo=archivo)
        with self.assertRaises(ValidationError), transaction.atomic():
            self.guardar(archivo=pdf())
        self.assertFalse(Oferta.objects.exists())
        self.assertFalse(list(Path(settings.MEDIA_ROOT).rglob("*.pdf")))

    def test_fallo_de_auditoria_limpia_pdf_nuevo_y_revierte_base(self):
        def fallo(accion, **kwargs):
            if accion == "oferta.creada":
                raise RuntimeError("Fallo de auditoría simulado")
            return registrar(accion, **kwargs)
        antes = RegistroBitacora.objects.count()
        with patch("compras.oferta_servicios.registrar", side_effect=fallo):
            with self.assertRaises(RuntimeError):
                self.guardar(archivo=pdf())
        self.assertFalse(Oferta.objects.exists())
        self.assertFalse(PdfOferta.objects.exists())
        self.assertFalse(RevisionOferta.objects.exists())
        self.assertFalse(list(Path(settings.MEDIA_ROOT).rglob("*.pdf")))
        self.assertEqual(RegistroBitacora.objects.count(), antes)

    def test_reemplazo_fallido_conserva_pdf_y_revision_anteriores(self):
        oferta = self.guardar(archivo=pdf("anterior.pdf"))
        anterior = oferta.pdf_id
        ruta = Path(oferta.pdf.archivo.path)
        def fallo(accion, **kwargs):
            if accion == "oferta.modificada":
                raise RuntimeError("Fallo simulado al reemplazar")
            return registrar(accion, **kwargs)
        with patch("compras.oferta_servicios.registrar", side_effect=fallo):
            with self.assertRaises(RuntimeError):
                self.guardar(archivo=pdf("nuevo.pdf"))
        oferta.refresh_from_db()
        self.assertEqual(oferta.pdf_id, anterior)
        self.assertEqual(oferta.revision, 1)
        self.assertEqual(oferta.revisiones.count(), 1)
        self.assertTrue(ruta.exists())
        self.assertEqual(list(Path(settings.MEDIA_ROOT).rglob("*.pdf")), [ruta])

    def test_revision_obsoleta_no_sobrescribe_otro_guardado(self):
        oferta = self.guardar(revision_esperada=0)
        with self.assertRaises(ValidationError):
            self.guardar(revision_esperada=0)
        oferta.refresh_from_db()
        self.assertEqual(oferta.revision, 1)

    def test_formulario_ignora_totales_cliente_y_guarda_calculo_real(self):
        self.client.force_login(self.admin)
        url = reverse("compras:oferta_guardar", args=[self.cotizacion.pk, self.invitado.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        respuesta = self.client.post(url, self.datos_post(total="0", subtotal="0", impuesto="0", **{"precios-0-linea": "999999"}))
        oferta = Oferta.objects.get()
        self.assertRedirects(respuesta, reverse("compras:oferta_detalle", args=[self.cotizacion.pk, oferta.pk]))
        self.assertEqual(oferta.total, 337)
        self.assertEqual(set(oferta.lineas.values_list("linea_id", flat=True)), set(self.cotizacion.lineas.values_list("pk", flat=True)))

    def test_tarifas_y_redondeo_configurables_sin_asumir_iva(self):
        self.assertEqual(self.cero.porcentaje, 0)
        self.assertEqual(TarifaImpuesto.objects.filter(nombre="Exento/No gravado").count(), 1)
        for porcentaje in [Decimal(-1), Decimal(101), Decimal("NaN"), 19.0]:
            with self.assertRaises(ValidationError):
                ofertas.guardar_tarifa(TarifaImpuesto(nombre="Inválida", porcentaje=porcentaje), actor=self.admin, motivo=MOTIVO)
        for clave, valor in [(DECIMALES_OFERTA, "3"), (REDONDEO_OFERTA, "OTRO")]:
            with self.assertRaises(ValidationError):
                cambiar_valor(Parametro.objects.get(clave=clave), valor, actor=self.admin, motivo=MOTIVO)

    def test_invitar_registrado_respeta_limite_y_elegidos_de_lista(self):
        ofertas.invitar_proveedor(self.cotizacion, crear_proveedor(), actor=self.admin, motivo=MOTIVO)
        ofertas.invitar_proveedor(self.cotizacion, crear_proveedor(), actor=self.admin, motivo=MOTIVO)
        with self.assertRaises(ValidationError):
            ofertas.invitar_proveedor(self.cotizacion, crear_proveedor(), actor=self.admin, motivo=MOTIVO)
        from compras.cierre_servicios import cerrar_lista
        lista = cerrar_lista(self.lista_actual, actor=self.admin, motivo=MOTIVO, justificacion_documental=MOTIVO)
        desde_lista = cotizacion_servicios.crear_cotizacion(necesidad=self.necesidad, fecha=self.fecha, tipo=self.tipo,
            objeto="Desde elegibles", lista_elegibles=lista, lineas=[{"descripcion": "Otra", "unidad": self.unidad, "cantidad": Decimal(1)}], actor=self.admin, motivo=MOTIVO)
        with self.assertRaises(ValidationError):
            ofertas.invitar_proveedor(desde_lista, crear_proveedor(), actor=self.admin, motivo=MOTIVO)

    def test_descarga_y_revision_respetan_permisos_y_pertenencia(self):
        oferta = self.guardar(archivo=pdf())
        revision = oferta.revisiones.get()
        urls = [reverse("compras:oferta_detalle", args=[self.cotizacion.pk, oferta.pk]),
            reverse("compras:oferta_revision", args=[self.cotizacion.pk, oferta.pk, revision.pk]),
            reverse("compras:oferta_pdf", args=[self.cotizacion.pk, oferta.pk, oferta.pdf_id]),
            reverse("compras:oferta_guardar", args=[self.cotizacion.pk, self.invitado.pk]), reverse("compras:oferta_tarifas")]
        for usuario in [self.coordinador, self.usuario_proveedor]:
            self.client.force_login(usuario)
            for url in urls:
                self.assertEqual(self.client.get(url).status_code, 403)
                self.assertEqual(self.client.post(url, {}).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(urls[1]).status_code, 200)
        respuesta = self.client.get(urls[2])
        self.assertEqual(respuesta["Content-Type"], "application/pdf")
        self.assertEqual(respuesta["X-Content-Type-Options"], "nosniff")
        self.assertTrue(b"".join(respuesta.streaming_content).startswith(b"%PDF-"))
        self.assertEqual(self.client.get(reverse("compras:oferta_pdf", args=[999999, oferta.pk, oferta.pdf_id])).status_code, 404)
        self.assertEqual(self.client.get(reverse("compras:oferta_pdf", args=[self.cotizacion.pk, oferta.pk, 999999])).status_code, 404)

    def test_servicios_requieren_rol_y_motivo_y_formularios_csrf(self):
        for usuario in [self.coordinador, self.usuario_proveedor, AnonymousUser()]:
            with self.assertRaises(PermissionDenied):
                self.guardar(actor=usuario)
            with self.assertRaises(PermissionDenied):
                ofertas.guardar_tarifa(TarifaImpuesto(nombre="Otra", porcentaje=0), actor=usuario, motivo=MOTIVO)
        with self.assertRaises(ValidationError):
            self.guardar(motivo=" ")
        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(self.admin)
        self.assertEqual(cliente.post(reverse("compras:oferta_guardar", args=[self.cotizacion.pk, self.invitado.pk]), self.datos_post()).status_code, 403)
