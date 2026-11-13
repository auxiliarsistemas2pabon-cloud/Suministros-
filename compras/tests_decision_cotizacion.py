from copy import deepcopy
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch
from unittest import skipUnless
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.contrib.auth.models import AnonymousUser
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, connections
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from openpyxl import load_workbook

from bitacora.models import RegistroBitacora
from bitacora.servicios import registrar
from compras import cierre_servicios, comparativo, cotizacion_servicios, decision_cotizacion_servicios as servicios, oferta_servicios, proveedor_unico_servicios, tests_cotizaciones, verificacion_servicios
from compras.models import AdjudicacionCotizacion, AprobacionCotizacion, CausalProveedorUnico, Cotizacion, DecisionCotizacion, EstadoVerificacion, TarifaImpuesto, TipoVerificacion
from cuentas.models import Usuario
from parametros.catalogo import APROBACIONES_COTIZACION, CONTROL_VERIFICACIONES, EVIDENCIA_UNICO_OBLIGATORIA, MODALIDAD_ADJUDICACION, ROLES_DECISION_COTIZACION
from parametros.models import Parametro
from parametros.servicios import cambiar_valor
from proveedores.tests.utilidades import MediaTemporal, crear_proveedor, pdf

MOTIVO = "Decisión ficticia revisada con sus ofertas y evidencias"


class DecisionCotizacionTests(MediaTemporal, TestCase):
    def setUp(self):
        super().setUp()
        tests_cotizaciones.CotizacionesTests.setUp(self)
        self.otro = crear_proveedor(razon_social="Otro oferente ficticio")
        self.cotizacion = cotizacion_servicios.crear_cotizacion(necesidad=self.necesidad, fecha=self.fecha, tipo=self.tipo,
            objeto="Comparación ficticia", lineas=[{"descripcion": "Insumo A", "unidad": self.unidad, "cantidad": 1},
                {"descripcion": "Insumo B", "unidad": self.unidad, "cantidad": 2}], invitados=[self.ficha, self.otro], actor=self.admin, motivo=MOTIVO)
        self.lineas = list(self.cotizacion.lineas.all())
        self.cero = TarifaImpuesto.objects.get(nombre="Exento/No gravado")
        self.a = self.ofertar(self.ficha, [10, 30])  # 10 + 60 = 70
        self.b = self.ofertar(self.otro, [12, 20])  # 12 + 40 = 52
        self.segundo_admin = Usuario.objects.create_user(correo="segunda.aprobacion@ejemplo.test", nombre="Administración ficticia", password="Prueba-segura-2031", rol="administrador")
        self.url = reverse("compras:cotizacion_comparar", args=[self.cotizacion.pk])
        self.tipo_control = TipoVerificacion.objects.get(nombre="Requisitos técnicos")

    def calificar(self, valores=None):
        return tests_cotizaciones.CotizacionesTests.calificar(self, valores)

    def asignaciones(self, cantidades=None, justificaciones=None):
        return tests_cotizaciones.CotizacionesTests.asignaciones(self, cantidades, justificaciones)

    def decidir(self, **kwargs):
        return tests_cotizaciones.CotizacionesTests.decidir(self, **kwargs)

    def ofertar(self, proveedor, precios, tarifa=None):
        invitado = self.cotizacion.invitados.get(proveedor=proveedor)
        return oferta_servicios.guardar_oferta(self.cotizacion, invitado, contacto_nombre="Contacto ficticio", contacto_correo="contacto@ejemplo.test",
            contacto_telefono="601 555 0100", fecha=self.fecha, precios=[{"linea": l.pk, "precio_unitario": p, "tarifa": tarifa or self.cero} for l, p in zip(self.lineas, precios)], actor=self.admin, motivo=MOTIVO)

    def proponer(self, **cambios):
        datos = dict(modalidad="completa", oferta_id=self.b.pk, recomendacion="Compra ficticia recomendada", actor=self.admin, motivo=MOTIVO)
        datos.update(cambios)
        return servicios.proponer_decision(self.cotizacion, **datos)

    def aprobar(self, decision, actor=None, motivo=MOTIVO):
        return servicios.aprobar_decision(decision, actor=actor or self.admin, motivo=motivo)

    def parametro(self, clave, valor):
        return cambiar_valor(Parametro.objects.get(clave=clave), valor, actor=self.admin, motivo=MOTIVO)

    def confirmar(self, oferta=None, estado="si"):
        return verificacion_servicios.guardar_verificacion(oferta or self.b, self.tipo_control, estado=EstadoVerificacion.objects.get(clasificacion=estado), fecha=self.fecha, actor=self.admin, motivo=MOTIVO)

    def firma(self, datos=None):
        return signing.dumps({"cotizacion": self.cotizacion.pk, "huella": comparativo.huella(datos or comparativo.construir(self.cotizacion, actor=self.admin))}, salt="decision-cotizacion")

    def post(self, **cambios):
        datos = {"modalidad": "completa", "oferta_id": self.b.pk, "recomendacion": "Compra ficticia recomendada", "motivo": MOTIVO, "firma": self.firma()}
        datos.update(cambios)
        return datos

    def test_comparativo_fijo_totales_por_linea_azul_y_modalidad_elegida(self):
        datos = comparativo.construir(self.cotizacion, actor=self.admin)
        self.assertEqual([o["total"] for o in datos["ofertas"]], ["70.00", "52.00"])
        self.assertEqual([f["minimo"] for f in datos["filas"]], ["10.00", "40.00"])
        self.assertEqual([next(c["oferta_id"] for c in f["celdas"] if c["menor"]) for f in datos["filas"]], [self.a.pk, self.b.pk])
        self.client.force_login(self.admin)
        respuesta = self.client.get(self.url)
        self.assertContains(respuesta, 'class="comparativo-menor"')
        self.assertEqual(respuesta.context["formulario"]["modalidad"].value(), "completa")
        self.assertFalse(DecisionCotizacion.objects.exists())

    def test_impuestos_guardados_y_empates_de_costo_total(self):
        tarifa = oferta_servicios.guardar_tarifa(TarifaImpuesto(nombre="Tarifa ficticia 20", porcentaje=20), actor=self.admin, motivo=MOTIVO)
        self.ofertar(self.ficha, [10, 20], tarifa)
        datos = comparativo.construir(self.cotizacion, actor=self.admin)
        self.assertTrue(all(c["menor"] for c in datos["filas"][0]["celdas"]))  # 10 + 2 == 12
        tarifa.porcentaje = 90
        oferta_servicios.guardar_tarifa(tarifa, actor=self.admin, motivo=MOTIVO)
        self.assertEqual(comparativo.construir(self.cotizacion, actor=self.admin)["filas"], datos["filas"])

    def test_propuesta_y_aprobacion_guardan_actor_fecha_ofertas_y_solo_lectura(self):
        decision = self.proponer(actor=self.dev)
        self.assertEqual(decision.propuesta_por, self.dev)
        self.assertEqual(decision.adjudicaciones.count(), 2)
        self.assertEqual(set(decision.adjudicaciones.values_list("oferta_id", flat=True)), {self.b.pk})
        self.assertEqual(decision.contenido["total_adjudicado"], "52.00")
        self.cotizacion.refresh_from_db()
        self.assertEqual(self.cotizacion.estado, "en_comparacion")
        decision = self.aprobar(decision)
        self.assertEqual(decision.estado, "aprobada")
        self.assertEqual(decision.decidido_por, self.admin)
        self.assertIsNotNone(decision.fecha_decision)
        self.cotizacion.refresh_from_db()
        self.assertEqual(self.cotizacion.estado, "decidida")
        with self.assertRaises(ValidationError):
            self.ofertar(self.ficha, [1, 1])
        with self.assertRaises(ValidationError):
            self.confirmar()
        with self.assertRaises(ValidationError):
            self.proponer()
        self.assertTrue(RegistroBitacora.objects.filter(accion="cotizacion.decidida", actor=self.admin, motivo=MOTIVO).exists())

    def test_mayor_costo_completo_requiere_justificacion_distinta_del_motivo(self):
        with self.assertRaises(ValidationError):
            self.proponer(oferta_id=self.a.pk, motivo_eleccion=" \n ")
        decision = self.proponer(oferta_id=self.a.pk, motivo_eleccion="Disponibilidad inmediata ficticia")
        self.assertTrue(decision.contenido["mas_costosa"])
        self.assertEqual(decision.motivo_eleccion, "Disponibilidad inmediata ficticia")

    def test_adjudicacion_por_linea_minima_suma_50(self):
        decision = self.proponer(modalidad="lineas", oferta_id=None, selecciones=[{"linea_id": self.lineas[0].pk, "oferta_id": self.a.pk}, {"linea_id": self.lineas[1].pk, "oferta_id": self.b.pk}])
        self.assertEqual(decision.contenido["total_adjudicado"], "50.00")
        self.aprobar(decision)
        self.assertEqual(set(decision.adjudicaciones.values_list("oferta_id", flat=True)), {self.a.pk, self.b.pk})

    def test_linea_mas_costosa_exige_motivo_y_no_admite_lineas_omitidas_o_repetidas(self):
        s = [{"linea_id": self.lineas[0].pk, "oferta_id": self.b.pk}, {"linea_id": self.lineas[1].pk, "oferta_id": self.b.pk}]
        with self.assertRaises(ValidationError):
            self.proponer(modalidad="lineas", oferta_id=None, selecciones=s)
        for seleccion in [s[:1], s + s[:1], [{"linea_id": 999999, "oferta_id": self.a.pk}], [{"linea_id": self.lineas[0].pk, "oferta_id": 99999}]]:
            with self.assertRaises(ValidationError):
                self.proponer(modalidad="lineas", oferta_id=None, selecciones=seleccion, motivo_eleccion=MOTIVO)
        self.proponer(modalidad="lineas", oferta_id=None, selecciones=s, motivo_eleccion=MOTIVO)

    def test_no_acepta_oferta_externa_booleanos_modalidades_ni_mezclas(self):
        for datos in [{"oferta_id": 999999}, {"oferta_id": True}, {"modalidad": "otra"}, {"selecciones": [{"linea_id": self.lineas[0].pk, "oferta_id": self.a.pk}]}]:
            with self.assertRaises(ValidationError):
                self.proponer(**datos)

    def test_varias_aprobaciones_distintas_y_regla_fija_por_propuesta(self):
        self.parametro(APROBACIONES_COTIZACION, "2")
        decision = self.proponer()
        self.parametro(APROBACIONES_COTIZACION, "1")
        self.assertEqual(self.aprobar(decision).estado, "pendiente")
        with self.assertRaises(ValidationError):
            self.aprobar(decision)
        decision = self.aprobar(decision, self.segundo_admin)
        self.assertEqual(decision.estado, "aprobada")
        self.assertEqual(decision.decidido_por, self.segundo_admin)
        self.assertEqual(decision.aprobaciones.count(), 2)

    def test_roles_aprobadores_configurables_y_permiso_actual(self):
        decision = self.proponer()
        with self.assertRaises(PermissionDenied):
            self.aprobar(decision, self.dev)
        servicios.anular_decision(decision, actor=self.admin, motivo=MOTIVO)
        self.parametro(ROLES_DECISION_COTIZACION, "administrador,desarrollador")
        self.assertEqual(self.aprobar(self.proponer(), self.dev).estado, "aprobada")

    def test_parametros_validan_minimo_roles_y_modalidad(self):
        for clave, valor in [(APROBACIONES_COTIZACION, "0"), (MODALIDAD_ADJUDICACION, "desconocida"), (ROLES_DECISION_COTIZACION, "proveedor"), (CONTROL_VERIFICACIONES, "ignorar")]:
            with self.assertRaises(ValidationError):
                self.parametro(clave, valor)
        self.parametro(MODALIDAD_ADJUDICACION, "lineas")
        self.assertEqual(servicios.modalidad_inicial(), "lineas")

    def test_alertas_obligatorias_advertir_exige_justificar_y_bloquear_no_permite(self):
        self.tipo_control.obligatoria = True
        verificacion_servicios.guardar_tipo(self.tipo_control, actor=self.admin, motivo=MOTIVO)
        with self.assertRaises(ValidationError):
            self.proponer()
        decision = self.proponer(justificacion_verificaciones="Revisión adicional ficticia")
        servicios.anular_decision(decision, actor=self.admin, motivo=MOTIVO)
        self.parametro(CONTROL_VERIFICACIONES, "bloquear")
        with self.assertRaises(ValidationError):
            self.proponer(justificacion_verificaciones=MOTIVO)
        self.confirmar()
        self.aprobar(self.proponer())

    def test_alertas_no_seleccionadas_no_bloquean_y_na_no_genera_alerta(self):
        self.tipo_control.obligatoria = True
        verificacion_servicios.guardar_tipo(self.tipo_control, actor=self.admin, motivo=MOTIVO)
        self.parametro(CONTROL_VERIFICACIONES, "bloquear")
        self.confirmar(estado="na")
        self.aprobar(self.proponer())

    def test_revision_oferta_requiere_reconfirmar_y_cambio_impide_aprobacion(self):
        decision = self.proponer()
        self.ofertar(self.otro, [12, 21])
        with self.assertRaises(ValidationError):
            self.aprobar(decision)
        self.assertFalse(AprobacionCotizacion.objects.exists())
        servicios.anular_decision(decision, actor=self.admin, motivo=MOTIVO)
        self.aprobar(self.proponer())

    def test_verificacion_de_revision_anterior_se_trata_como_pendiente(self):
        self.tipo_control.obligatoria = True
        verificacion_servicios.guardar_tipo(self.tipo_control, actor=self.admin, motivo=MOTIVO)
        self.confirmar()
        self.ofertar(self.otro, [12, 20])
        with self.assertRaises(ValidationError):
            self.proponer()
        decision = self.proponer(justificacion_verificaciones=MOTIVO)
        oferta = next(o for o in decision.contenido["comparativo"]["ofertas"] if o["id"] == self.b.pk)
        control = next(c for c in oferta["verificaciones"] if c["tipo_id"] == self.tipo_control.pk)
        self.assertTrue(control["desactualizada"])
        self.assertEqual(control["clasificacion"], "pendiente")

    def test_cambio_tras_aprobacion_parcial_exige_nueva_propuesta_y_nuevas_firmas(self):
        self.parametro(APROBACIONES_COTIZACION, "2")
        decision = self.proponer()
        self.aprobar(decision)
        self.ofertar(self.otro, [12, 21])
        with self.assertRaises(ValidationError):
            self.aprobar(decision, self.segundo_admin)
        servicios.anular_decision(decision, actor=self.admin, motivo=MOTIVO)
        nueva = self.proponer()
        self.assertEqual(nueva.aprobaciones.count(), 0)
        self.assertEqual(decision.aprobaciones.count(), 1)
        self.assertEqual(self.aprobar(nueva, self.segundo_admin).estado, "pendiente")

    def test_fallo_auditoria_al_anular_conserva_decision_y_cotizacion_cerradas(self):
        decision = self.aprobar(self.proponer())
        with patch("compras.decision_cotizacion_servicios.registrar", side_effect=RuntimeError("Fallo ficticio")), self.assertRaises(RuntimeError):
            servicios.anular_decision(decision, actor=self.admin, motivo=MOTIVO)
        decision.refresh_from_db()
        self.cotizacion.refresh_from_db()
        self.assertEqual(decision.estado, "aprobada")
        self.assertEqual(self.cotizacion.estado, "decidida")

    def test_cambio_verificacion_o_catalogo_no_reutiliza_aprobaciones(self):
        decision = self.proponer()
        self.confirmar()
        with self.assertRaises(ValidationError):
            self.aprobar(decision)
        servicios.anular_decision(decision, actor=self.admin, motivo=MOTIVO)
        decision = self.proponer()
        self.tipo_control.obligatoria = True
        verificacion_servicios.guardar_tipo(self.tipo_control, actor=self.admin, motivo=MOTIVO)
        with self.assertRaises(ValidationError):
            self.aprobar(decision)

    def test_firma_de_pantalla_antigua_o_alterada_no_propone(self):
        self.client.force_login(self.admin)
        firma = self.firma()
        self.ofertar(self.otro, [12, 21])
        for valor in [firma, "alterada"]:
            self.assertEqual(self.client.post(self.url, self.post(firma=valor)).status_code, 200)
        self.assertFalse(DecisionCotizacion.objects.exists())

    def test_unico_exige_b12_y_revalida_evidencia_antes_de_aprobar(self):
        unica = cotizacion_servicios.crear_cotizacion(necesidad=self.necesidad, fecha=self.fecha, tipo=self.tipo, objeto="Proveedor único ficticio",
            lineas=[{"descripcion": "Insumo único", "unidad": self.unidad, "cantidad": 1}], invitados=[self.ficha], actor=self.admin, motivo=MOTIVO)
        oferta = oferta_servicios.guardar_oferta(unica, unica.invitados.get(), contacto_nombre="Contacto", contacto_correo="unico@ejemplo.test", contacto_telefono="6015550100",
            fecha=self.fecha, precios=[{"linea": unica.lineas.get().pk, "precio_unitario": 10, "tarifa": self.cero}], actor=self.admin, motivo=MOTIVO)
        datos = dict(modalidad="completa", oferta_id=oferta.pk, recomendacion=MOTIVO, actor=self.admin, motivo=MOTIVO)
        with self.assertRaises(ValidationError):
            servicios.proponer_decision(unica, **datos)
        proveedor_unico_servicios.guardar_caso(unica, proveedor_unico=True, causal=CausalProveedorUnico.objects.get(nombre="Otra"), justificacion=MOTIVO, actor=self.admin, motivo=MOTIVO)
        decision = servicios.proponer_decision(unica, **datos)
        self.parametro(EVIDENCIA_UNICO_OBLIGATORIA, "true")
        with self.assertRaises(ValidationError):
            self.aprobar(decision)

    def test_anular_con_motivo_reabre_y_conserva_foto_firmas_y_seleccion(self):
        decision = self.aprobar(self.proponer())
        foto = deepcopy(decision.contenido)
        with self.assertRaises(ValidationError):
            servicios.anular_decision(decision, actor=self.admin, motivo=" ")
        decision = servicios.anular_decision(decision, actor=self.dev, motivo=MOTIVO)
        self.assertEqual(decision.contenido, foto)
        self.assertEqual(decision.aprobaciones.count(), 1)
        self.assertIsNotNone(decision.fecha_anulacion)
        self.cotizacion.refresh_from_db()
        self.assertEqual(self.cotizacion.estado, "en_comparacion")
        self.ofertar(self.otro, [14, 22])
        self.assertEqual(DecisionCotizacion.objects.get(pk=decision.pk).contenido, foto)
        nueva = self.proponer()
        self.assertNotEqual(nueva.pk, decision.pk)

    def test_propuesta_adjudicaciones_y_aprobaciones_inmutables(self):
        decision = self.proponer()
        decision.recomendacion = "Cambio no permitido"
        with self.assertRaises(ValidationError):
            decision.save()
        decision.refresh_from_db()
        self.aprobar(decision)
        for objeto in [decision.adjudicaciones.first(), decision.aprobaciones.first()]:
            with self.assertRaises(ValidationError):
                objeto.save()
            with self.assertRaises(ValidationError):
                objeto.delete()
        with self.assertRaises(ValidationError):
            DecisionCotizacion.objects.filter(pk=decision.pk).update(estado="anulada")

    def test_auditoria_fallida_revierte_propuesta_y_lineas(self):
        with patch("compras.decision_cotizacion_servicios.registrar", side_effect=RuntimeError("Fallo ficticio")), self.assertRaises(RuntimeError):
            self.proponer()
        self.assertFalse(DecisionCotizacion.objects.exists())
        self.assertFalse(AdjudicacionCotizacion.objects.exists())
        self.cotizacion.refresh_from_db()
        self.assertEqual(self.cotizacion.estado, "borrador")

    def test_auditoria_fallida_revierte_aprobacion_y_estado_final(self):
        decision = self.proponer()
        def fallo(accion, **kwargs):
            if accion == "cotizacion.decidida":
                raise RuntimeError("Fallo ficticio")
            return registrar(accion, **kwargs)
        with patch("compras.decision_cotizacion_servicios.registrar", side_effect=fallo), self.assertRaises(RuntimeError):
            self.aprobar(decision)
        self.assertFalse(AprobacionCotizacion.objects.exists())
        decision.refresh_from_db()
        self.assertEqual(decision.estado, "pendiente")
        self.cotizacion.refresh_from_db()
        self.assertEqual(self.cotizacion.estado, "en_comparacion")

    def test_resumen_elegibles_usa_cierre_historico_real(self):
        lista = cierre_servicios.cerrar_lista(self.lista_actual, actor=self.admin, motivo=MOTIVO, justificacion_documental=MOTIVO)
        cierre = lista.cierres.first()
        origen = cotizacion_servicios.crear_cotizacion(necesidad=self.necesidad, lista_elegibles=lista, fecha=self.fecha, tipo=self.tipo, objeto="Origen conservado",
            lineas=[{"descripcion": "Insumo", "unidad": self.unidad, "cantidad": 1}], actor=self.admin, motivo=MOTIVO)
        oferta_servicios.guardar_oferta(origen, origen.invitados.get(), contacto_nombre="Contacto", contacto_correo="origen@ejemplo.test", contacto_telefono="6015550100", fecha=self.fecha,
            precios=[{"linea": origen.lineas.get().pk, "precio_unitario": 10, "tarifa": self.cero}], actor=self.admin, motivo=MOTIVO)
        datos = comparativo.construir(origen, actor=self.admin)
        self.assertEqual(datos["ofertas"][0]["elegibles"]["total"], cierre.contenido["resultado"]["filas"][0]["total"])
        self.assertEqual(datos["cierre_origen_id"], cierre.pk)

    def test_excel_mismos_valores_colores_y_texto_sin_formulas(self):
        self.cotizacion.objeto = "=1+2"
        self.cotizacion.save(update_fields=["objeto"])
        self.client.force_login(self.admin)
        respuesta = self.client.get(reverse("compras:cotizacion_comparativo_excel", args=[self.cotizacion.pk]))
        libro = load_workbook(BytesIO(respuesta.content))
        hoja = libro["Comparativo"]
        self.assertEqual(hoja["B1"].value, "=1+2")
        self.assertEqual(hoja["B1"].data_type, "s")
        self.assertEqual([hoja["G4"].value, hoja["J5"].value], [10, 40])
        self.assertEqual(hoja["G4"].fill.fgColor.rgb[-6:], "DBEAFE")
        self.assertEqual(hoja["J6"].value, 52)
        self.assertIn("Verificaciones", libro.sheetnames)
        self.assertIn("Elegibles de origen", libro.sheetnames)

    def test_exportacion_historica_conserva_importes_tras_anular_y_editar(self):
        decision = self.aprobar(self.proponer())
        servicios.anular_decision(decision, actor=self.admin, motivo=MOTIVO)
        self.ofertar(self.otro, [100, 100])
        self.client.force_login(self.admin)
        respuesta = self.client.get(reverse("compras:cotizacion_decision_excel", args=[self.cotizacion.pk, decision.pk]))
        libro = load_workbook(BytesIO(respuesta.content))
        self.assertEqual(libro["Comparativo"]["J6"].value, 52)
        self.assertEqual(libro["Decisión"]["B8"].value, 52)

    def test_pantallas_post_aprobar_anular_csrf_y_alcance(self):
        self.client.force_login(self.admin)
        respuesta = self.client.post(self.url, self.post())
        self.assertEqual(respuesta.status_code, 302)
        decision = DecisionCotizacion.objects.get()
        detalle = reverse("compras:cotizacion_decision", args=[self.cotizacion.pk, decision.pk])
        self.assertContains(self.client.get(detalle), "52,00")
        aprobar = reverse("compras:cotizacion_decision_accion", args=[self.cotizacion.pk, decision.pk, "aprobar"])
        self.assertEqual(self.client.get(aprobar).status_code, 405)
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.admin)
        self.assertEqual(csrf.post(aprobar, {"motivo": MOTIVO}).status_code, 403)
        self.assertEqual(self.client.post(aprobar, {"motivo": MOTIVO}).status_code, 302)
        self.assertContains(self.client.get(self.url), "comparativo conservado")
        self.assertEqual(self.client.get(reverse("compras:cotizacion_decision", args=[999999, decision.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("compras:cotizacion_decision_excel", args=[999999, decision.pk])).status_code, 404)
        anular = reverse("compras:cotizacion_decision_accion", args=[self.cotizacion.pk, decision.pk, "anular"])
        self.assertEqual(self.client.post(anular, {"motivo": MOTIVO}).status_code, 302)

    def test_servicios_y_pantallas_solo_administracion_motivo_y_recomendacion(self):
        decision = self.proponer()
        for actor in [self.coordinador, self.usuario_proveedor, AnonymousUser()]:
            for servicio in [lambda: self.proponer(actor=actor), lambda: self.aprobar(decision, actor), lambda: servicios.anular_decision(decision, actor=actor, motivo=MOTIVO), lambda: comparativo.construir(self.cotizacion, actor=actor)]:
                with self.assertRaises(PermissionDenied):
                    servicio()
        for actor in [self.coordinador, self.usuario_proveedor]:
            self.client.force_login(actor)
            for ruta in [self.url, reverse("compras:cotizacion_decision", args=[self.cotizacion.pk, decision.pk]), reverse("compras:cotizacion_comparativo_excel", args=[self.cotizacion.pk])]:
                self.assertEqual(self.client.get(ruta).status_code, 403)
        with self.assertRaises(ValidationError):
            self.aprobar(decision, motivo=" ")
        servicios.anular_decision(decision, actor=self.admin, motivo=MOTIVO)
        for cambio in [{"recomendacion": " "}, {"motivo": " "}]:
            with self.assertRaises(ValidationError):
                self.proponer(**cambio)


@skipUnless(connection.vendor == "postgresql", "La prueba de aprobación simultánea requiere PostgreSQL.")
class AprobacionConcurrenteTests(TransactionTestCase):
    def test_dos_aprobaciones_simultaneas_no_deciden_dos_veces(self):
        from areas.models import Area
        from compras.models import InvitadoCotizacion, LineaCotizacion, Necesidad, TipoCotizacion
        from cuentas.tests.utilidades import crear_usuario
        from proyecciones.models import UnidadMedida
        from django.utils import timezone
        admin = crear_usuario("administrador", correo="firma.uno@ejemplo.test")
        otro = crear_usuario("administrador", correo="firma.dos@ejemplo.test")
        area = Area.objects.create(nombre="Área ficticia simultánea", codigo_area="SIM")
        necesidad = Necesidad.objects.create(objeto="Necesidad ficticia", area=area, responsable=admin)
        tipo, _ = TipoCotizacion.objects.get_or_create(nombre="Tipo ficticio simultáneo")
        cotizacion = Cotizacion.objects.create(necesidad=necesidad, area=area, responsable=admin, tipo=tipo,
            objeto="Cotización ficticia simultánea", numero=1, consecutivo="COT-SIM-1")
        unidad = UnidadMedida.objects.create(nombre="Unidad ficticia simultánea", abreviatura="sim")
        linea = LineaCotizacion.objects.create(cotizacion=cotizacion, orden=1, descripcion="Insumo", unidad=unidad, unidad_texto=str(unidad), cantidad=1)
        tarifa, _ = TarifaImpuesto.objects.get_or_create(nombre="Exento/No gravado", defaults={"porcentaje": 0})
        ofertas = []
        for importe in [10, 12]:
            ficha = crear_proveedor()
            invitado = InvitadoCotizacion.objects.create(cotizacion=cotizacion, proveedor=ficha, nit=ficha.nit, razon_social=ficha.razon_social)
            ofertas.append(oferta_servicios.guardar_oferta(cotizacion, invitado, contacto_nombre="Contacto", contacto_correo="simultaneo@ejemplo.test",
                contacto_telefono="6015550100", fecha=timezone.localdate(), precios=[{"linea": linea.pk, "precio_unitario": importe, "tarifa": tarifa}], actor=admin, motivo=MOTIVO))
        from compras import contrato_servicios
        cotizacion = contrato_servicios.guardar_requiere(cotizacion, requiere_contrato=True, actor=admin, motivo=MOTIVO)
        decision = servicios.proponer_decision(cotizacion, modalidad="completa", oferta_id=ofertas[0].pk, recomendacion=MOTIVO, actor=admin, motivo=MOTIVO)
        hoy = timezone.localdate()
        contrato_servicios.guardar_contrato(decision, numero="CT-SIM", supervisor_texto="Supervisor ficticio", cargo="Cargo ficticio",
            fecha_inicio=hoy, fecha_fin=hoy, forma_pago="Pago ficticio", valor=Decimal(10), actor=admin, motivo=MOTIVO)
        barrera = Barrier(2)
        def aprobar(actor_id):
            try:
                actor = Usuario.objects.get(pk=actor_id)
                copia = DecisionCotizacion.objects.get(pk=decision.pk)
                barrera.wait(timeout=15)
                try:
                    servicios.aprobar_decision(copia, actor=actor, motivo=MOTIVO)
                    return "aprobada"
                except ValidationError:
                    return "rechazada"
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as ejecutor:
            futuros = [ejecutor.submit(aprobar, a.pk) for a in (admin, otro)]
            resultados = [f.result(timeout=30) for f in futuros]
        self.assertCountEqual(resultados, ["aprobada", "rechazada"])
        self.assertEqual(decision.aprobaciones.count(), 1)
        self.assertEqual(RegistroBitacora.objects.filter(accion="cotizacion.decidida").count(), 1)
        cotizacion.refresh_from_db()
        self.assertEqual(cotizacion.estado, "decidida")
        # B15: dos solicitudes simultáneas no duplican las órdenes de esa decisión.
        from compras import orden_servicios
        from compras.models import OrdenCompra
        def crear_orden(actor_id):
            try:
                actor = Usuario.objects.get(pk=actor_id)
                copia = DecisionCotizacion.objects.get(pk=decision.pk)
                barrera.wait(timeout=15)
                return [o.pk for o in orden_servicios.crear_orden_desde_decision(copia, actor=actor, motivo=MOTIVO)]
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as ejecutor:
            futuros = [ejecutor.submit(crear_orden, a.pk) for a in (admin, otro)]
            ordenes = [f.result(timeout=30) for f in futuros]
        self.assertEqual(ordenes[0], ordenes[1])
        self.assertEqual(OrdenCompra.objects.count(), 1)
        self.assertEqual(RegistroBitacora.objects.filter(accion="orden.creada_desde_decision").count(), 1)
