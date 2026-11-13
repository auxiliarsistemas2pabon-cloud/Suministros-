from copy import deepcopy
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from bitacora.models import RegistroBitacora
from bitacora.servicios import registrar
from compras import cierre_servicios, contrato_servicios, cotizacion_servicios, decision_cotizacion_servicios as decisiones, oferta_servicios, orden_servicios as servicios, proveedor_unico_servicios, tests_cotizaciones
from compras.models import CausalProveedorUnico, DecisionCotizacion, OfertaLinea, OrdenCompra, OrdenLinea, OrigenNecesidad, RevisionOrdenCompra, TarifaImpuesto
from parametros.catalogo import DECIMALES_OFERTA
from parametros.models import Parametro
from parametros.servicios import cambiar_valor
from proveedores.tests.utilidades import crear_proveedor

MOTIVO = "Orden ficticia creada desde valores adjudicados y conservados"


class OrdenesTests(TestCase):
    def setUp(self):
        tests_cotizaciones.CotizacionesTests.setUp(self)
        self.otro = crear_proveedor(razon_social="Otro oferente ficticio")
        self.cotizacion = cotizacion_servicios.crear_cotizacion(necesidad=self.necesidad, fecha=self.fecha, tipo=self.tipo, objeto="Orden desde decisión ficticia",
            lineas=[{"descripcion": "Insumo A", "unidad": self.unidad, "cantidad": 1}, {"descripcion": "Insumo B", "unidad": self.unidad, "cantidad": 2}],
            invitados=[self.ficha, self.otro], actor=self.admin, motivo=MOTIVO)
        self.lineas = list(self.cotizacion.lineas.all())
        self.cero = TarifaImpuesto.objects.get(nombre="Exento/No gravado")
        self.a = self.ofertar(self.ficha, [10, 30])
        self.b = self.ofertar(self.otro, [12, 20])
        self.decision = None

    def calificar(self, valores=None):
        return tests_cotizaciones.CotizacionesTests.calificar(self, valores)

    def asignaciones(self, cantidades=None, justificaciones=None):
        return tests_cotizaciones.CotizacionesTests.asignaciones(self, cantidades, justificaciones)

    def decidir(self, **kwargs):
        return tests_cotizaciones.CotizacionesTests.decidir(self, **kwargs)

    def ofertar(self, proveedor, precios, tarifa=None):
        return oferta_servicios.guardar_oferta(self.cotizacion, self.cotizacion.invitados.get(proveedor=proveedor), contacto_nombre="Contacto de la oferta ficticia",
            contacto_correo="oferta@ejemplo.test", contacto_telefono="6015550100", fecha=self.fecha,
            precios=[{"linea": l.pk, "precio_unitario": p, "tarifa": tarifa or self.cero} for l, p in zip(self.lineas, precios)], actor=self.admin, motivo=MOTIVO)

    def proponer(self, *, lineas=False):
        self.decision = decisiones.proponer_decision(self.cotizacion, modalidad="lineas" if lineas else "completa", oferta_id=None if lineas else self.b.pk,
            selecciones=[{"linea_id": self.lineas[0].pk, "oferta_id": self.a.pk}, {"linea_id": self.lineas[1].pk, "oferta_id": self.b.pk}] if lineas else None,
            recomendacion=MOTIVO, actor=self.admin, motivo=MOTIVO)
        return self.decision

    def aprobar(self, *, lineas=False):
        self.decision = decisiones.aprobar_decision(self.proponer(lineas=lineas), actor=self.admin, motivo=MOTIVO)
        return self.decision

    def crear(self, **cambios):
        if self.decision is None:
            self.aprobar()
        datos = dict(fecha_elaboracion=self.fecha, actor=self.admin, motivo=MOTIVO)
        datos.update(cambios)
        return servicios.crear_orden_desde_decision(self.decision, **datos)

    def guardar(self, orden, lineas=None, **cambios):
        datos = dict(lineas=lineas or [{"id": l.pk, "cantidad": l.cantidad, "precio_unitario": l.precio_unitario} for l in orden.lineas.all()],
            fecha_elaboracion=orden.fecha_elaboracion, condiciones_pago=orden.condiciones_pago, revision_esperada=orden.revision, actor=self.admin, motivo=MOTIVO)
        datos.update(cambios)
        return servicios.guardar_borrador(orden, **datos)

    def test_preparar_no_escribe_y_creacion_completa_copia_valores_usuario_fecha(self):
        self.aprobar()
        grupos = servicios.preparar_ordenes(self.decision, actor=self.admin)
        self.assertEqual(len(grupos), 1)
        self.assertFalse(OrdenCompra.objects.exists())
        orden, = self.crear(actor=self.dev)
        self.assertEqual(orden.elaborada_por, self.dev)
        self.assertEqual(orden.fecha_elaboracion, self.fecha)
        self.assertEqual(orden.estado, "borrador")
        self.assertEqual(orden.proveedor_id, self.otro.pk)
        self.assertEqual(orden.total, Decimal(52))
        self.assertEqual(orden.lineas.count(), 2)
        self.assertEqual(orden.revision, 1)
        self.assertEqual(orden.origen_datos["proveedor"]["contacto_correo"], "oferta@ejemplo.test")
        self.assertEqual(orden.lineas.last().original["cantidad"], "2")
        self.assertTrue(RegistroBitacora.objects.filter(accion="orden.creada_desde_decision", actor=self.dev, motivo=MOTIVO).exists())

    def test_por_lineas_crea_una_orden_por_proveedor_solo_con_lo_adjudicado(self):
        self.aprobar(lineas=True)
        ordenes = self.crear()
        self.assertEqual(len(ordenes), 2)
        self.assertEqual({o.proveedor_id: o.total for o in ordenes}, {self.ficha.pk: Decimal(10), self.otro.pk: Decimal(40)})
        self.assertTrue(all(o.lineas.count() == 1 for o in ordenes))
        self.assertEqual(sum(o.total for o in ordenes), Decimal(50))

    def test_repetir_creacion_no_duplica_ni_sobrescribe_orden_editada(self):
        orden, = self.crear()
        lineas = [{"id": l.pk, "precio_unitario": Decimal(30)} for l in orden.lineas.all()]
        orden = self.guardar(orden, lineas)
        repetida, = self.crear(condiciones_pago="Otra condición ficticia")
        self.assertEqual(repetida.pk, orden.pk)
        self.assertEqual(repetida.total, orden.total)
        self.assertEqual(repetida.revision, 2)
        self.assertEqual(OrdenCompra.objects.count(), 1)

    def test_no_crea_desde_pendiente_anulada_o_cotizacion_no_decidida(self):
        self.proponer()
        with self.assertRaises(ValidationError):
            self.crear()
        decisiones.anular_decision(self.decision, actor=self.admin, motivo=MOTIVO)
        with self.assertRaises(ValidationError):
            self.crear()
        self.aprobar()
        self.cotizacion.refresh_from_db()
        self.cotizacion.estado = "en_comparacion"
        self.cotizacion.save(update_fields=["estado"])
        with self.assertRaises(ValidationError):
            self.crear()
        self.assertFalse(OrdenCompra.objects.exists())

    def test_copia_foto_aprobada_aunque_cambie_catalogo_proveedor_o_precio_vivo(self):
        self.aprobar()
        nombre = self.otro.razon_social
        self.otro.razon_social = "Razón social posterior ficticia"
        self.otro.contacto_correo = "posterior@ejemplo.test"
        self.otro.save()
        # Simula reparación externa del registro vivo: la orden debe usar la revisión aprobada.
        OfertaLinea._base_manager.filter(oferta=self.b).update(precio_unitario=999, total=999)
        self.cero.nombre = "Tarifa renombrada ficticia"
        oferta_servicios.guardar_tarifa(self.cero, actor=self.admin, motivo=MOTIVO)
        orden, = self.crear()
        self.assertEqual(orden.razon_social, nombre)
        self.assertEqual(orden.total, 52)
        self.assertEqual(orden.lineas.first().precio_unitario, 12)
        self.assertEqual(orden.lineas.first().tarifa_nombre, "Exento/No gravado")
        self.assertEqual(orden.origen_datos["proveedor"]["contacto_correo"], "oferta@ejemplo.test")

    def test_copia_pago_de_la_aprobacion_contractual(self):
        contrato_servicios.guardar_requiere(self.cotizacion, requiere_contrato=True, actor=self.admin, motivo=MOTIVO)
        self.proponer()
        contrato_servicios.guardar_contrato(self.decision, numero="CT-FICTICIO", supervisor_texto="Supervisor", cargo="Cargo", fecha_inicio=self.fecha,
            fecha_fin=self.fecha, forma_pago="Pago contractual ficticio", valor=52, actor=self.admin, motivo=MOTIVO)
        self.decision = decisiones.aprobar_decision(self.decision, actor=self.admin, motivo=MOTIVO)
        orden, = self.crear()
        self.assertEqual(orden.condiciones_pago, "Pago contractual ficticio")
        self.assertEqual(orden.origen_datos["contrato"]["contrato"]["numero"], "CT-FICTICIO")

    def test_impuestos_copiados_y_cambios_recalculados_con_redondeo_de_origen(self):
        tarifa = oferta_servicios.guardar_tarifa(TarifaImpuesto(nombre="Tarifa ficticia 19", porcentaje=19), actor=self.admin, motivo=MOTIVO)
        self.b = self.ofertar(self.otro, [12, 20], tarifa)
        orden, = self.crear()
        self.assertEqual(orden.impuesto, 10)
        self.assertEqual(orden.total, 62)
        cambiar_valor(Parametro.objects.get(clave=DECIMALES_OFERTA), "2", actor=self.admin, motivo=MOTIVO)
        lineas = [{"id": l.pk, "cantidad": "2.5", "precio_unitario": "100.15"} for l in orden.lineas.all()]
        orden = self.guardar(orden, lineas)
        self.assertEqual(orden.total, 596)  # Dos líneas: 250 + 48 con redondeo de origen a pesos.
        self.assertEqual(orden.lineas.first().reglas_calculo["decimales"], 0)

    def test_cambios_guardan_original_actual_motivo_y_revision_sin_editar_oferta(self):
        orden, = self.crear()
        original = deepcopy(orden.lineas.first().original)
        lineas = [{"id": l.pk, "cantidad": Decimal(3), "precio_unitario": l.precio_unitario} for l in orden.lineas.all()]
        orden = self.guardar(orden, lineas, actor=self.dev)
        linea = orden.lineas.first()
        self.assertTrue(linea.modificada)
        self.assertEqual(linea.original, original)
        self.assertEqual(linea.cambios["cantidad"]["original"], "1")
        self.assertEqual(linea.cambios["cantidad"]["actual"], "3")
        self.assertEqual(orden.revisiones.first().actor, self.dev)
        self.assertEqual(orden.revisiones.first().motivo, MOTIVO)
        self.assertEqual(orden.revisiones.get(numero=1).contenido["total"], "52.00")
        self.b.refresh_from_db()
        self.assertEqual(self.b.total, 52)

    def test_restaurar_original_mantiene_marca_e_historial(self):
        orden, = self.crear()
        lineas = [{"id": l.pk, "precio_unitario": 50} for l in orden.lineas.all()]
        orden = self.guardar(orden, lineas)
        originales = [{"id": l.pk, "precio_unitario": l.original["precio_unitario"]} for l in orden.lineas.all()]
        orden = self.guardar(orden, originales)
        self.assertTrue(all(l.modificada and not l.cambios for l in orden.lineas.all()))
        self.assertEqual(orden.total, 52)
        self.assertEqual(orden.revisiones.count(), 3)

    def test_modificacion_exige_motivo_y_revision_actual(self):
        orden, = self.crear()
        lineas = [{"id": l.pk, "precio_unitario": 30} for l in orden.lineas.all()]
        with self.assertRaises(ValidationError):
            self.guardar(orden, lineas, motivo=" ")
        self.guardar(orden, lineas)
        with self.assertRaises(ValidationError):
            self.guardar(orden, lineas)
        self.assertEqual(OrdenCompra.objects.get(pk=orden.pk).revision, 2)

    def test_no_acepta_lineas_ajenas_omitidas_repetidas_o_totales_del_cliente(self):
        orden, = self.crear()
        ids = list(orden.lineas.values_list("pk", flat=True))
        for lineas in [[], [{"id": ids[0]}], [{"id": ids[0]}, {"id": ids[0]}], [{"id": ids[0]}, {"id": 999999}], [{"id": ids[0], "total": 0}, {"id": ids[1]}], [{"id": ids[0], "porcentaje": 0}, {"id": ids[1]}]]:
            with self.assertRaises(ValidationError):
                servicios.guardar_borrador(orden, lineas=lineas, fecha_elaboracion=self.fecha, actor=self.admin, motivo=MOTIVO)
        self.assertEqual(orden.revisiones.count(), 1)

    def test_cantidades_y_precios_invalidos_o_fuera_de_escala_no_persisten(self):
        orden, = self.crear()
        ids = list(orden.lineas.values_list("pk", flat=True))
        for campo, valor in [("cantidad", 0), ("cantidad", "1.0001"), ("cantidad", "NaN"), ("precio_unitario", -1), ("precio_unitario", 0.1), ("precio_unitario", "Infinity"), ("precio_unitario", "1.00001")]:
            with self.assertRaises(ValidationError):
                self.guardar(orden, [{"id": ids[0], campo: valor}, {"id": ids[1]}])
        self.assertEqual(orden.revisiones.count(), 1)

    def test_noop_no_crea_revision_y_cabecera_cambiada_si(self):
        orden, = self.crear()
        with self.assertRaisesMessage(ValidationError, "No hay cambios"):
            self.guardar(orden)
        orden = self.guardar(orden, condiciones_pago="Pago ficticio actualizado")
        self.assertEqual(orden.revision, 2)
        self.assertTrue(all(not l.modificada for l in orden.lineas.all()))

    def test_creacion_multiple_y_auditoria_se_revierten_juntas(self):
        self.aprobar(lineas=True)
        llamadas = []
        def fallo(accion, **kwargs):
            if accion == "orden.creada_desde_decision":
                llamadas.append(accion)
                if len(llamadas) == 2:
                    raise RuntimeError("Fallo ficticio de segunda orden")
            return registrar(accion, **kwargs)
        with patch("compras.orden_servicios.registrar", side_effect=fallo), self.assertRaises(RuntimeError):
            self.crear()
        self.assertFalse(OrdenCompra.objects.exists())
        self.assertFalse(OrdenLinea.objects.exists())
        self.assertFalse(RevisionOrdenCompra.objects.exists())

    def test_fallo_auditoria_al_modificar_revierte_importes_e_historial(self):
        orden, = self.crear()
        lineas = [{"id": l.pk, "precio_unitario": 100} for l in orden.lineas.all()]
        with patch("compras.orden_servicios.registrar", side_effect=RuntimeError("Fallo ficticio")), self.assertRaises(RuntimeError):
            self.guardar(orden, lineas)
        orden.refresh_from_db()
        self.assertEqual(orden.total, 52)
        self.assertEqual(orden.revision, 1)
        self.assertTrue(all(not l.modificada for l in orden.lineas.all()))

    def test_anular_decision_anula_borradores_con_motivo_y_conserva_fotos(self):
        orden, = self.crear()
        original = deepcopy(orden.origen_datos)
        decisiones.anular_decision(self.decision, actor=self.dev, motivo=MOTIVO)
        orden.refresh_from_db()
        self.assertEqual(orden.estado, "anulada")
        self.assertEqual(orden.origen_datos, original)
        self.assertEqual(orden.revisiones.first().actor, self.dev)
        self.assertEqual(orden.revisiones.first().motivo, MOTIVO)
        with self.assertRaises(ValidationError):
            self.guardar(orden, condiciones_pago="Cambio")
        with self.assertRaises(ValidationError):
            self.crear()

    def test_decision_con_orden_que_avanzo_del_borrador_no_se_anula(self):
        orden, = self.crear()
        orden.estado = "en_aprobacion"  # Preparación del flujo futuro de aprobación B18.
        orden.save(update_fields=["estado"])
        with self.assertRaises(ValidationError):
            decisiones.anular_decision(self.decision, actor=self.admin, motivo=MOTIVO)
        self.decision.refresh_from_db()
        self.assertEqual(self.decision.estado, "aprobada")

    def test_anulacion_fallida_revierte_tambien_las_ordenes(self):
        orden, = self.crear()
        with patch("compras.decision_cotizacion_servicios.registrar", side_effect=RuntimeError("Fallo ficticio")), self.assertRaises(RuntimeError):
            decisiones.anular_decision(self.decision, actor=self.admin, motivo=MOTIVO)
        orden.refresh_from_db()
        self.assertEqual(orden.estado, "borrador")
        self.assertEqual(orden.revision, 1)

    def test_identidad_originales_y_revisiones_no_admiten_cambios(self):
        orden, = self.crear()
        orden.proveedor = self.ficha
        with self.assertRaises(ValidationError):
            orden.save()
        linea = OrdenLinea.objects.first()
        linea.original["cantidad"] = "999"
        with self.assertRaises(ValidationError):
            linea.save()
        for objeto in [orden.revisiones.first(), linea]:
            with self.assertRaises(ValidationError):
                objeto.delete()
        with self.assertRaises(ValidationError):
            orden.revisiones.first().save()
        with self.assertRaises(ValidationError):
            OrdenCompra.objects.update(total=0)

    def test_permisos_de_servicios_y_motivos_obligatorios(self):
        self.aprobar()
        orden, = self.crear()
        for actor in [self.coordinador, self.usuario_proveedor, AnonymousUser()]:
            with self.assertRaises(PermissionDenied):
                servicios.preparar_ordenes(self.decision, actor=actor)
            with self.assertRaises(PermissionDenied):
                self.crear(actor=actor)
            with self.assertRaises(PermissionDenied):
                self.guardar(orden, actor=actor)
            with self.assertRaises(PermissionDenied):
                servicios.anular_borradores_de_decision(self.decision, actor=actor, motivo=MOTIVO)
        with self.assertRaises(ValidationError):
            self.crear(motivo=" ")

    def test_pantallas_creacion_edicion_historial_csrf_y_alcance(self):
        self.aprobar()
        self.client.force_login(self.admin)
        crear = reverse("compras:orden_crear", args=[self.cotizacion.pk, self.decision.pk])
        self.assertEqual(self.client.get(crear).status_code, 200)
        self.assertFalse(OrdenCompra.objects.exists())
        self.assertEqual(self.client.post(crear, {"fecha_elaboracion": self.fecha.isoformat(), "motivo": MOTIVO}).status_code, 302)
        orden = OrdenCompra.objects.get()
        detalle = reverse("compras:orden_detalle", args=[orden.pk])
        self.assertContains(self.client.get(detalle), "52,00")
        editar = reverse("compras:orden_editar", args=[orden.pk])
        self.assertEqual(self.client.get(editar).status_code, 200)
        lineas = list(orden.lineas.all())
        datos = {"fecha_elaboracion": self.fecha.isoformat(), "condiciones_pago": "Pago de prueba", "revision_esperada": 1, "motivo": MOTIVO,
            "lineas-TOTAL_FORMS": "2", "lineas-INITIAL_FORMS": "2"}
        for i, l in enumerate(lineas):
            datos.update({f"lineas-{i}-id": l.pk, f"lineas-{i}-descripcion": l.descripcion, f"lineas-{i}-unidad": l.unidad,
                f"lineas-{i}-cantidad": "3", f"lineas-{i}-precio_unitario": str(l.precio_unitario)})
        self.assertEqual(self.client.post(editar, datos).status_code, 302)
        self.assertContains(self.client.get(detalle), "Con historial de modificación")
        self.assertEqual(self.client.get(reverse("compras:orden_revision", args=[orden.pk, orden.revisiones.first().pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("compras:orden_revision", args=[999999, orden.revisiones.first().pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("compras:orden_crear", args=[999999, self.decision.pk])).status_code, 404)
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.admin)
        self.assertEqual(csrf.post(editar, datos).status_code, 403)
        for actor in [self.coordinador, self.usuario_proveedor]:
            self.client.force_login(actor)
            for ruta in [crear, editar, detalle, reverse("compras:ordenes")]:
                self.assertEqual(self.client.get(ruta).status_code, 403)

    def test_trazabilidad_hasta_lista_cierre_fr14_necesidad_y_proyeccion(self):
        from proveedores.models import CategoriaProveedor, Peso, Requisito, VersionMatriz
        from proveedores import matrices_servicios, evaluacion_servicios, respuestas_servicios
        from proyecciones.models import Linea, Periodo, ProyeccionArea
        from proyecciones.servicios import aprobar_proyeccion
        categoria = CategoriaProveedor.objects.create(nombre="Categoría ficticia de origen")
        self.ficha.categoria = categoria
        self.ficha.save()
        version = VersionMatriz.objects.get(numero=1)
        requisito = Requisito.objects.create(version=version, numero=1, grupo="calidad", texto="Requisito ficticio")
        Peso.objects.create(requisito=requisito, categoria=categoria, valor=1)
        matrices_servicios.publicar_version(version, desde=date(2026, 1, 1), actor=self.admin, motivo=MOTIVO)
        evaluacion = matrices_servicios.crear_evaluacion(self.ficha, categoria, timezone.localdate(), actor=self.admin, motivo=MOTIVO)
        respuestas_servicios.guardar_respuesta(evaluacion, requisito, respuesta="si", observacion="Revisado", confirma_na=False, actor=self.admin, motivo=MOTIVO)
        evaluacion = evaluacion_servicios.finalizar_evaluacion(evaluacion, actor=self.admin, motivo=MOTIVO)
        periodo = Periodo.objects.create(anio=2031, fecha_apertura=date(2031, 1, 1), fecha_limite_diligenciamiento=date(2031, 12, 15), creado_por=self.admin)
        proyeccion = ProyeccionArea.objects.create(periodo=periodo, area=self.area, estado="enviada", fecha_envio=timezone.now(), enviado_por=self.coordinador)
        linea = Linea.objects.create(proyeccion=proyeccion, producto_servicio="Producto de origen ficticio", unidad=self.unidad, cantidad_enero=5, precio_estimado=Decimal(1))
        aprobar_proyeccion(proyeccion, actor=self.admin, motivo=MOTIVO)
        origen = OrigenNecesidad.objects.create(necesidad=self.necesidad, linea=linea, cantidad=Decimal(1), datos_origen={"producto": linea.producto_servicio, "unidad": str(self.unidad), "periodo": 2031, "cantidad_autorizada": 5})
        lista = cierre_servicios.cerrar_lista(self.lista_actual, actor=self.admin, motivo=MOTIVO, justificacion_documental=MOTIVO)
        cotizacion = cotizacion_servicios.crear_cotizacion(necesidad=self.necesidad, lista_elegibles=lista, fecha=self.fecha, tipo=self.tipo, objeto="Orden trazable ficticia",
            lineas=[{"descripcion": "Insumo de origen", "unidad": self.unidad, "cantidad": 1, "origen": origen}], actor=self.admin, motivo=MOTIVO)
        oferta = oferta_servicios.guardar_oferta(cotizacion, cotizacion.invitados.get(), contacto_nombre="Contacto", contacto_correo="origen@ejemplo.test", contacto_telefono="6015550100", fecha=self.fecha,
            precios=[{"linea": cotizacion.lineas.get().pk, "precio_unitario": 10, "tarifa": self.cero}], actor=self.admin, motivo=MOTIVO)
        proveedor_unico_servicios.guardar_caso(cotizacion, proveedor_unico=True, causal=CausalProveedorUnico.objects.get(nombre="Otra"), justificacion=MOTIVO, actor=self.admin, motivo=MOTIVO)
        decision = decisiones.proponer_decision(cotizacion, modalidad="completa", oferta_id=oferta.pk, recomendacion=MOTIVO, actor=self.admin, motivo=MOTIVO)
        decision = decisiones.aprobar_decision(decision, actor=self.admin, motivo=MOTIVO)
        posterior = matrices_servicios.crear_evaluacion(self.ficha, categoria, timezone.localdate(), actor=self.admin, motivo=MOTIVO)
        respuestas_servicios.guardar_respuesta(posterior, requisito, respuesta="si", observacion="Evaluación posterior", confirma_na=False, actor=self.admin, motivo=MOTIVO)
        posterior = evaluacion_servicios.finalizar_evaluacion(posterior, actor=self.admin, motivo=MOTIVO)
        orden, = servicios.crear_orden_desde_decision(decision, actor=self.admin, motivo=MOTIVO)
        self.assertEqual(orden.evaluacion_origen_id, evaluacion.pk)
        self.assertNotEqual(orden.evaluacion_origen_id, posterior.pk)
        self.assertEqual(orden.lineas.get().proyeccion_origen_id, linea.pk)
        self.client.force_login(self.admin)
        respuesta = self.client.get(reverse("compras:orden_detalle", args=[orden.pk]))
        for ruta in [reverse("compras:lista_detalle", args=[lista.pk]), reverse("compras:lista_cierre_detalle", args=[lista.pk, lista.cierres.get().pk]),
                reverse("proveedores:evaluacion_detalle", args=[evaluacion.pk]), reverse("proyecciones:revision_detalle", args=[proyeccion.pk]), reverse("compras:necesidad_detalle", args=[self.necesidad.pk])]:
            self.assertContains(respuesta, ruta)
