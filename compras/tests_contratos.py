from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal
import json
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.test import Client, TestCase
from django.urls import reverse

from bitacora.models import RegistroBitacora
from bitacora.servicios import registrar
from compras import contrato_servicios as servicios, cotizacion_servicios, decision_cotizacion_servicios as decisiones, oferta_servicios, tests_cotizaciones
from compras.models import AprobacionCotizacion, Contrato, Cotizacion, DecisionCotizacion, PdfContractual, Poliza, RevisionContrato, TarifaImpuesto, TipoPoliza
from parametros.catalogo import APROBACIONES_COTIZACION, CAMPOS_CONTRATO, CAMPOS_POLIZA, DIAS_ALERTA_VENCIMIENTO, EXIGIR_POLIZA
from parametros.models import Parametro
from parametros.servicios import cambiar_valor
from proveedores import archivos
from proveedores.tests.utilidades import MediaTemporal, crear_proveedor, pdf

MOTIVO = "Contrato ficticio revisado con supervisor y evidencias"


class ContratosTests(MediaTemporal, TestCase):
    def setUp(self):
        super().setUp()
        tests_cotizaciones.CotizacionesTests.setUp(self)
        self.ref = date(2031, 2, 1)
        self.otro = crear_proveedor()
        self.cotizacion = self.cotizar(True)
        self.decision = self.proponer()
        self.tipo_poliza = TipoPoliza.objects.get(nombre="Cumplimiento")
        self.contrato = None

    def calificar(self, valores=None):
        return tests_cotizaciones.CotizacionesTests.calificar(self, valores)

    def asignaciones(self, cantidades=None, justificaciones=None):
        return tests_cotizaciones.CotizacionesTests.asignaciones(self, cantidades, justificaciones)

    def decidir(self, **kwargs):
        return tests_cotizaciones.CotizacionesTests.decidir(self, **kwargs)

    def cotizar(self, requiere):
        cotizacion = cotizacion_servicios.crear_cotizacion(necesidad=self.necesidad, fecha=self.fecha, tipo=self.tipo,
            objeto="Compra ficticia contractual", lineas=[{"descripcion": "Insumo", "unidad": self.unidad, "cantidad": 1}],
            invitados=[self.ficha, self.otro], actor=self.admin, motivo=MOTIVO)
        cotizacion = servicios.guardar_requiere(cotizacion, requiere_contrato=requiere, actor=self.admin, motivo=MOTIVO)
        tarifa = TarifaImpuesto.objects.get(nombre="Exento/No gravado")
        for valor, invitado in enumerate(cotizacion.invitados.all(), 10):
            oferta_servicios.guardar_oferta(cotizacion, invitado, contacto_nombre="Contacto ficticio", contacto_correo="contrato@ejemplo.test", contacto_telefono="6015550100", fecha=self.ref,
                precios=[{"linea": cotizacion.lineas.get().pk, "precio_unitario": valor, "tarifa": tarifa}], actor=self.admin, motivo=MOTIVO)
        return cotizacion

    def proponer(self, cotizacion=None):
        cotizacion = cotizacion or self.cotizacion
        oferta = cotizacion.ofertas.order_by("total", "pk").first()
        return decisiones.proponer_decision(cotizacion, modalidad="completa", oferta_id=oferta.pk, recomendacion=MOTIVO, actor=self.admin, motivo=MOTIVO)

    def guardar(self, **cambios):
        datos = dict(numero="CT-FICTICIO-1", supervisor_texto="Supervisor ficticio", cargo="Cargo ficticio", fecha_inicio=self.ref,
            fecha_fin=self.ref + timedelta(days=365), forma_pago="Pago ficticio a treinta días", valor=Decimal("10.00"), actor=self.admin, motivo=MOTIVO)
        datos.update(cambios)
        self.contrato = servicios.guardar_contrato(self.decision, **datos)
        return self.contrato

    def poliza(self, poliza=None, **cambios):
        if self.contrato is None:
            self.guardar()
        datos = dict(poliza=poliza, tipo=self.tipo_poliza, aseguradora="Aseguradora ficticia", numero="P-FICTICIA-1", valor_asegurado=Decimal("10.00"),
            vigencia_desde=self.ref, vigencia_hasta=self.ref + timedelta(days=365), archivo=pdf("poliza.pdf"), actor=self.admin, motivo=MOTIVO)
        datos.update(cambios)
        return servicios.guardar_poliza(self.contrato, **datos)

    def aprobar(self):
        return decisiones.aprobar_decision(self.decision, actor=self.admin, motivo=MOTIVO)

    def parametro(self, clave, valor):
        return cambiar_valor(Parametro.objects.get(clave=clave), valor, actor=self.admin, motivo=MOTIVO)

    def obligatorios(self, clave, **cambios):
        datos = json.loads(Parametro.objects.get(clave=clave).valor)
        datos.update(cambios)
        self.parametro(clave, json.dumps(datos))
        return datos

    def dos_firmas(self):
        decisiones.anular_decision(self.decision, actor=self.admin, motivo=MOTIVO)
        self.parametro(APROBACIONES_COTIZACION, "2")
        self.decision = self.proponer()

    def url(self, nombre="contrato", *extra, cotizacion=None, decision=None):
        return reverse("compras:" + nombre, args=[(cotizacion or self.cotizacion).pk, (decision or self.decision).pk, *extra])

    def test_compra_sin_contrato_no_pide_datos_ni_polizas(self):
        otra = self.cotizar(False)
        decision = self.proponer(otra)
        self.parametro(EXIGIR_POLIZA, "true")
        self.obligatorios(CAMPOS_CONTRATO, pdf=True)
        decision = decisiones.aprobar_decision(decision, actor=self.admin, motivo=MOTIVO)
        self.assertEqual(decision.estado, "aprobada")
        self.assertEqual(decision.aprobaciones.get().contrato_datos, {"requiere_contrato": False})
        self.assertFalse(Contrato.objects.filter(decision=decision).exists())
        with self.assertRaises(ValidationError):
            servicios.guardar_contrato(decision, actor=self.admin, motivo=MOTIVO)

    def test_requiere_contrato_bloquea_sin_registro_o_con_borrador_incompleto(self):
        with self.assertRaises(ValidationError):
            self.aprobar()
        contrato = self.guardar(numero="", supervisor_texto="", cargo="", fecha_inicio=None, fecha_fin=None, forma_pago="", valor=None)
        self.assertEqual(contrato.revision, 1)
        with self.assertRaises(ValidationError):
            self.aprobar()
        self.assertFalse(AprobacionCotizacion.objects.exists())
        self.guardar()
        decision = self.aprobar()
        self.assertEqual(decision.estado, "aprobada")
        self.assertEqual(decision.aprobaciones.get().contrato_datos["contrato"]["numero"], "CT-FICTICIO-1")

    def test_cada_campo_contractual_puede_ser_opcional_y_cero_es_valor(self):
        self.guardar(cargo="", valor=Decimal(0))
        with self.assertRaises(ValidationError):
            self.aprobar()
        self.obligatorios(CAMPOS_CONTRATO, cargo=False)
        self.assertEqual(self.aprobar().estado, "aprobada")

    def test_supervisor_usuario_o_texto_sin_mezclar_y_nombre_conservado(self):
        with self.assertRaises(ValidationError):
            self.guardar(supervisor=self.admin)
        contrato = self.guardar(supervisor=self.coordinador, supervisor_texto="")
        nombre = contrato.supervisor_nombre
        self.coordinador.nombre = "Nombre posterior ficticio"
        self.coordinador.save()
        contrato.refresh_from_db()
        self.assertEqual(contrato.supervisor_nombre, nombre)
        self.assertEqual(contrato.supervisor_id, self.coordinador.pk)
        self.aprobar()

    def test_fechas_invertidas_y_valores_invalidos_no_se_guardan(self):
        for cambios in [{"fecha_fin": self.ref - timedelta(days=1)}, {"valor": Decimal(-1)}, {"valor": Decimal("NaN")}, {"valor": 0.1}]:
            with self.assertRaises(ValidationError):
                self.guardar(**cambios)
        self.guardar()
        for cambios in [{"vigencia_hasta": self.ref - timedelta(days=1)}, {"valor_asegurado": Decimal(-1)}, {"valor_asegurado": Decimal("Infinity")}, {"valor_asegurado": 0.5}]:
            with self.assertRaises(ValidationError):
                self.poliza(**cambios)
        self.assertFalse(Poliza.objects.exists())

    def test_poliza_opcional_o_exigida_y_campos_de_cada_poliza(self):
        self.guardar()
        self.parametro(EXIGIR_POLIZA, "true")
        with self.assertRaises(ValidationError):
            self.aprobar()
        p = self.poliza(aseguradora="", archivo=None)
        with self.assertRaises(ValidationError):
            self.aprobar()
        self.poliza(p)
        self.assertEqual(self.aprobar().estado, "aprobada")

    def test_pdf_contractual_y_de_poliza_exigibles_por_separado(self):
        self.guardar()
        self.poliza(archivo=None)
        with self.assertRaises(ValidationError):
            self.aprobar()
        self.obligatorios(CAMPOS_POLIZA, pdf=False)
        self.obligatorios(CAMPOS_CONTRATO, pdf=True)
        with self.assertRaises(ValidationError):
            self.aprobar()
        self.guardar(archivo=pdf("contrato.pdf"))
        self.aprobar()

    def test_poliza_inactiva_no_cumple_exigencia_y_no_desaparece_del_historial(self):
        p = self.poliza()
        self.poliza(p, activo=False, archivo=None)
        self.parametro(EXIGIR_POLIZA, "true")
        with self.assertRaises(ValidationError):
            self.aprobar()
        self.assertEqual(servicios.tablero_polizas(self.contrato, referencia=self.ref), [])
        self.assertFalse(servicios.foto(self.contrato)["polizas"][0]["activo"])
        self.assertTrue(self.contrato.revisiones.first().contenido["contrato"]["polizas"])

    def test_alertas_reutilizan_vencimientos_inclusive_y_umbral_particular(self):
        self.parametro(DIAS_ALERTA_VENCIMIENTO, "25")
        p = self.poliza(vigencia_hasta=self.ref + timedelta(days=25))
        self.assertEqual(servicios.tablero_polizas(self.contrato, referencia=self.ref)[0]["estado"], "por_vencer")
        self.tipo_poliza.dias_alerta = 5
        servicios.guardar_tipo(self.tipo_poliza, actor=self.admin, motivo=MOTIVO)
        self.assertEqual(servicios.tablero_polizas(self.contrato, referencia=self.ref)[0]["estado"], "vigente")
        self.poliza(p, vigencia_hasta=self.ref, archivo=None)
        self.tipo_poliza.dias_alerta = 0
        servicios.guardar_tipo(self.tipo_poliza, actor=self.admin, motivo=MOTIVO)
        self.assertEqual(servicios.tablero_polizas(self.contrato, referencia=self.ref)[0]["estado"], "por_vencer")
        self.assertEqual(servicios.tablero_polizas(self.contrato, referencia=self.ref + timedelta(days=1))[0]["estado"], "vencido")

    def test_vigencia_futura_o_sin_fechas_no_acredita_cobertura(self):
        p = self.poliza(vigencia_desde=self.ref + timedelta(days=1))
        self.assertEqual(servicios.tablero_polizas(self.contrato, referencia=self.ref)[0]["estado"], "faltante")
        self.poliza(p, vigencia_desde=None, vigencia_hasta=None, archivo=None)
        self.assertEqual(servicios.tablero_polizas(self.contrato, referencia=self.ref)[0]["estado"], "faltante")

    def test_primera_firma_protege_contrato_polizas_y_foto(self):
        self.dos_firmas()
        self.guardar()
        p = self.poliza()
        decision = self.aprobar()
        self.assertEqual(decision.estado, "pendiente")
        foto = deepcopy(decision.aprobaciones.get().contrato_datos)
        with self.assertRaises(ValidationError):
            self.guardar(numero="Cambio")
        with self.assertRaises(ValidationError):
            self.poliza(p)
        self.assertEqual(decision.aprobaciones.get().contrato_datos, foto)
        with self.assertRaises(ValidationError):
            self.contrato.save()

    def test_cambio_obligatoriedad_entre_firmas_no_reutiliza_aceptacion(self):
        self.dos_firmas()
        self.guardar()
        self.aprobar()
        self.obligatorios(CAMPOS_CONTRATO, pdf=True)
        from cuentas.tests.utilidades import crear_usuario
        otro = crear_usuario("administrador", correo="segunda.firma@ejemplo.test")
        with self.assertRaisesMessage(ValidationError, "pdf"):
            decisiones.aprobar_decision(self.decision, actor=otro, motivo=MOTIVO)
        self.assertEqual(self.decision.aprobaciones.count(), 1)

    def test_nueva_obligatoriedad_entre_firmas_se_revisa_aunque_los_datos_cumplan(self):
        self.dos_firmas()
        self.guardar(archivo=pdf("contrato.pdf"))
        self.aprobar()
        self.obligatorios(CAMPOS_CONTRATO, pdf=True)
        from cuentas.tests.utilidades import crear_usuario
        otro = crear_usuario("administrador", correo="segunda.firma@ejemplo.test")
        with self.assertRaisesMessage(ValidationError, "obligatoriedad"):
            decisiones.aprobar_decision(self.decision, actor=otro, motivo=MOTIVO)
        self.assertEqual(self.decision.aprobaciones.count(), 1)

    def test_anular_conserva_contrato_pdf_y_alertas_generales_excluyen_historicos(self):
        self.guardar(archivo=pdf("contrato.pdf"))
        self.poliza()
        self.aprobar()
        decisiones.anular_decision(self.decision, actor=self.admin, motivo=MOTIVO)
        self.assertEqual(servicios.tablero_polizas(referencia=self.ref), [])
        self.assertEqual(len(servicios.tablero_polizas(self.contrato, referencia=self.ref)), 1)
        with self.assertRaises(ValidationError):
            self.guardar()
        self.assertTrue(Path(self.contrato.pdf.archivo.path).exists())

    def test_flag_se_fija_antes_de_proponer_y_revision_esperada(self):
        with self.assertRaises(ValidationError):
            servicios.guardar_requiere(self.cotizacion, requiere_contrato=False, actor=self.admin, motivo=MOTIVO)
        decisiones.anular_decision(self.decision, actor=self.admin, motivo=MOTIVO)
        actual = servicios.guardar_requiere(self.cotizacion, requiere_contrato=False, revision_esperada=1, actor=self.admin, motivo=MOTIVO)
        with self.assertRaises(ValidationError):
            servicios.guardar_requiere(actual, requiere_contrato=True, revision_esperada=1, actor=self.admin, motivo=MOTIVO)
        self.assertTrue(RegistroBitacora.objects.filter(accion="contrato.requerimiento_modificado", actor=self.admin).exists())

    def test_modelo_no_pasa_a_decidida_sin_aprobacion_contractual(self):
        self.cotizacion.estado = "decidida"
        with self.assertRaisesMessage(ValidationError, "contrato"):
            self.cotizacion.save(update_fields=["estado"])
        self.guardar()
        self.assertEqual(self.aprobar().estado, "aprobada")

    def test_no_traslada_contratos_polizas_ni_evidencia_a_otras_decisiones(self):
        p = self.poliza()
        otra_cotizacion = self.cotizar(True)
        otra_decision = self.proponer(otra_cotizacion)
        otro_contrato = servicios.guardar_contrato(otra_decision, actor=self.admin, motivo=MOTIVO)
        with self.assertRaises(ValidationError):
            servicios.guardar_poliza(otro_contrato, poliza=p, actor=self.admin, motivo=MOTIVO)
        self.contrato.decision = otra_decision
        with self.assertRaises(ValidationError):
            self.contrato.save()
        p.pdf.contrato = otro_contrato
        with self.assertRaises(ValidationError):
            p.pdf.full_clean()

    def test_fallo_auditoria_de_poliza_revierte_revision_y_pdf(self):
        self.guardar(archivo=pdf("contrato.pdf"))
        def fallo(accion, **kwargs):
            if accion == "poliza.guardada":
                raise RuntimeError("Fallo ficticio")
            return registrar(accion, **kwargs)
        with patch("compras.contrato_servicios.registrar", side_effect=fallo), self.assertRaises(RuntimeError):
            self.poliza()
        self.contrato.refresh_from_db()
        self.assertEqual(self.contrato.revision, 1)
        self.assertFalse(Poliza.objects.exists())
        self.assertEqual(PdfContractual.objects.count(), 1)
        self.assertEqual(len(list(Path(settings.MEDIA_ROOT).rglob("*.pdf"))), 1)

    def test_revision_de_contrato_detecta_cambios_en_cualquier_poliza(self):
        contrato = self.guardar(revision_esperada=0)
        self.poliza(revision_esperada=1)
        with self.assertRaises(ValidationError):
            self.guardar(revision_esperada=1)
        with self.assertRaises(ValidationError):
            self.poliza(revision_esperada=1)
        self.assertEqual(Contrato.objects.get(pk=contrato.pk).revision, 2)

    def test_catalogo_tipos_editable_desactivable_y_no_reescribe_nombres(self):
        p = self.poliza()
        self.tipo_poliza.nombre, self.tipo_poliza.activo = "Amparo renombrado ficticio", False
        servicios.guardar_tipo(self.tipo_poliza, actor=self.admin, motivo=MOTIVO)
        p.refresh_from_db()
        self.assertEqual(p.tipo_nombre, "Cumplimiento")
        with self.assertRaises(ValidationError):
            self.poliza(p)
        retirada = self.poliza(p, activo=False, archivo=None)
        self.assertEqual(retirada.tipo_nombre, "Cumplimiento")
        self.assertFalse(retirada.activo)
        with self.assertRaises(ValidationError):
            servicios.guardar_tipo(TipoPoliza(nombre=" AMPARO RENOMBRADO FICTICIO "), actor=self.admin, motivo=MOTIVO)

    def test_parametros_obligatoriedad_rechazan_campos_desconocidos_y_no_booleanos(self):
        for clave in [CAMPOS_CONTRATO, CAMPOS_POLIZA]:
            for valor in ['{}', '[]', '{"numero":"si"}', '{"desconocido":true}']:
                with self.assertRaises(ValidationError):
                    self.parametro(clave, valor)

    def test_pdf_reemplazados_retirados_conservan_historial_y_descargas(self):
        self.guardar(archivo=pdf("uno.pdf"))
        primero = self.contrato.pdf
        self.guardar(archivo=pdf("dos.pdf"))
        self.guardar(quitar_pdf=True)
        p = self.poliza()
        evidencia_p = p.pdf
        self.poliza(p, archivo=None, quitar_pdf=True)
        archivos.borrar_sin_referencias(primero.archivo.name)
        archivos.borrar_sin_referencias(evidencia_p.archivo.name)
        self.assertTrue(Path(primero.archivo.path).exists())
        self.assertTrue(Path(evidencia_p.archivo.path).exists())
        self.assertEqual(self.contrato.revisiones.get(numero=1).contenido["contrato"]["pdf_id"], primero.pk)
        for objeto in [primero, self.contrato.revisiones.first()]:
            with self.assertRaises(ValidationError):
                objeto.save()
            with self.assertRaises(ValidationError):
                objeto.delete()

    def test_fallo_auditoria_compensa_pdf_nuevo_sin_eliminar_el_anterior(self):
        self.guardar(archivo=pdf("anterior.pdf"))
        anterior = self.contrato.pdf_id
        def fallo(accion, **kwargs):
            if accion == "contrato.guardado":
                raise RuntimeError("Fallo ficticio")
            return registrar(accion, **kwargs)
        with patch("compras.contrato_servicios.registrar", side_effect=fallo), self.assertRaises(RuntimeError):
            self.guardar(archivo=pdf("fallido.pdf"))
        self.contrato.refresh_from_db()
        self.assertEqual(self.contrato.pdf_id, anterior)
        self.assertEqual(self.contrato.revisiones.count(), 1)
        self.assertEqual(len(list(Path(settings.MEDIA_ROOT).rglob("*.pdf"))), 1)

    def test_pdf_invalido_o_carga_en_transaccion_externa_no_dejan_residuos(self):
        grande = pdf()
        grande.size = archivos.TAMANO_MAXIMO + 1
        for archivo in [pdf("mal.exe"), pdf("mal.pdf", b"falso"), grande]:
            with self.assertRaises(ValidationError):
                self.guardar(archivo=archivo)
        with self.assertRaises(ValidationError), transaction.atomic():
            self.guardar(archivo=pdf())
        with self.assertRaises(ValidationError):
            self.guardar(archivo=pdf(), quitar_pdf=True)
        self.assertFalse(list(Path(settings.MEDIA_ROOT).rglob("*.pdf")))

    def test_servicios_exigen_administracion_y_motivo(self):
        for actor in [self.coordinador, self.usuario_proveedor, AnonymousUser()]:
            for servicio in [lambda: self.guardar(actor=actor), lambda: servicios.validar_para_aprobar(self.decision, actor=actor), lambda: servicios.guardar_tipo(self.tipo_poliza, actor=actor, motivo=MOTIVO), lambda: servicios.guardar_requiere(self.cotizacion, requiere_contrato=True, actor=actor, motivo=MOTIVO)]:
                with self.assertRaises(PermissionDenied):
                    servicio()
        with self.assertRaises(ValidationError):
            self.guardar(motivo=" ")

    def test_pantallas_formularios_y_csrf_guardan_borradores(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.url()).status_code, 200)
        self.assertFalse(Contrato.objects.exists())
        datos = {"numero": "CT-UI", "supervisor_texto": "Supervisor ficticio", "cargo": "Cargo", "fecha_inicio": "2031-02-01", "fecha_fin": "2032-02-01", "forma_pago": "Pago ficticio", "valor": "10.00", "revision_esperada": 0, "motivo": MOTIVO}
        self.assertEqual(self.client.post(self.url(), datos).status_code, 302)
        self.contrato = Contrato.objects.get()
        datos_p = {"tipo": self.tipo_poliza.pk, "aseguradora": "Aseguradora ficticia", "numero": "P-UI", "valor_asegurado": "10.00", "vigencia_desde": "2031-02-01", "vigencia_hasta": "2032-02-01", "activo": "on", "revision_esperada": 1, "motivo": MOTIVO, "archivo": pdf()}
        self.assertEqual(self.client.post(self.url("poliza_nueva"), datos_p).status_code, 302)
        self.assertEqual(Poliza.objects.count(), 1)
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.admin)
        self.assertEqual(csrf.post(self.url(), datos).status_code, 403)
        self.assertEqual(self.client.get(self.url("contrato_revision", self.contrato.revisiones.first().pk)).status_code, 200)

    def test_evidencia_privada_con_alcance_y_permiso_sin_otorgar_acceso_al_supervisor(self):
        self.guardar(supervisor=self.coordinador, supervisor_texto="", archivo=pdf("contrato.pdf"))
        url = self.url("contrato_pdf", self.contrato.pdf_id)
        for actor in [self.admin, self.dev]:
            self.client.force_login(actor)
            respuesta = self.client.get(url)
            self.assertEqual(respuesta.status_code, 200)
            self.assertIn("no-store", respuesta["Cache-Control"])
            self.assertEqual(respuesta["X-Content-Type-Options"], "nosniff")
            self.assertTrue(b"".join(respuesta.streaming_content).startswith(b"%PDF-"))
        self.assertEqual(self.client.get(reverse("compras:contrato_pdf", args=[999999, self.decision.pk, self.contrato.pdf_id])).status_code, 404)
        self.assertEqual(self.client.get(reverse("compras:contrato_pdf", args=[self.cotizacion.pk, 999999, self.contrato.pdf_id])).status_code, 404)
        rutas = [url, self.url(), self.url("poliza_nueva"), reverse("compras:polizas_alertas"), reverse("compras:poliza_tipos")]
        for actor in [self.coordinador, self.usuario_proveedor]:
            self.client.force_login(actor)
            for ruta in rutas:
                self.assertEqual(self.client.get(ruta).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_filtro_alertas_a_fecha_y_estado_sin_mutaciones(self):
        self.poliza(vigencia_hasta=self.ref)
        self.client.force_login(self.admin)
        url = reverse("compras:polizas_alertas")
        respuesta = self.client.get(url, {"fecha": self.ref.isoformat(), "estado": "por_vencer"})
        self.assertEqual(len(respuesta.context["filas"]), 1)
        self.assertEqual(len(self.client.get(url, {"fecha": (self.ref + timedelta(days=1)).isoformat(), "estado": "por_vencer"}).context["filas"]), 0)
        self.assertEqual(self.client.get(url, {"fecha": "incorrecta"}).context["filas"], [])
