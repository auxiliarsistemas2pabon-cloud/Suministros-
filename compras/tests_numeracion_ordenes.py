from datetime import datetime, date, timezone as zona_utc
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, connection, connections, transaction
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse

from bitacora.models import RegistroBitacora
from compras import numeracion_ordenes as numeros, orden_servicios, tests_ordenes
from compras.models import ContadorOrdenCompra, OrdenCompra
from parametros.catalogo import ANIO_ORDEN, ETIQUETA_VALIDEZ_ORDEN, LONGITUD_ORDEN, PREFIJO_ORDEN, REINICIO_ORDEN
from parametros.models import Parametro
from parametros.servicios import cambiar_valor

MOTIVO = "Emisión ficticia para verificar consecutivo y anulación"


class DatosNumeracion:
    calificar = tests_ordenes.OrdenesTests.calificar
    asignaciones = tests_ordenes.OrdenesTests.asignaciones
    decidir = tests_ordenes.OrdenesTests.decidir
    ofertar = tests_ordenes.OrdenesTests.ofertar
    proponer = tests_ordenes.OrdenesTests.proponer
    aprobar = tests_ordenes.OrdenesTests.aprobar
    crear = tests_ordenes.OrdenesTests.crear

    def setUp(self):
        tests_ordenes.OrdenesTests.setUp(self)
        self.aprobar(lineas=True)
        self.uno, self.dos = self.crear()

    def parametro(self, clave, valor):
        return cambiar_valor(Parametro.objects.get(clave=clave), valor, actor=self.admin, motivo=MOTIVO)

    def preparar_emision(self, orden):
        from compras.pruebas_operacion import preparar_numeracion
        preparar_numeracion(orden, self.admin, self.dev)

    def emitir(self, orden=None, anio=2026, instante=None, **cambios):
        orden = orden or self.uno
        if orden.estado == "borrador":
            self.preparar_emision(orden)
        datos = {"actor": self.admin, "motivo": MOTIVO}
        datos.update(cambios)
        with patch("compras.numeracion_ordenes.timezone.now", return_value=instante or datetime(anio, 6, 1, 12, tzinfo=zona_utc.utc)):
            return numeros.numerar_al_emitir(orden, **datos)


class NumeracionOrdenesTests(DatosNumeracion, TestCase):
    def test_borradores_sin_numero_no_consumen_contador(self):
        self.assertIsNone(self.uno.numero)
        self.assertIsNone(self.dos.consecutivo)
        self.assertEqual(ContadorOrdenCompra.objects.get(pk="global").ultimo, 0)
        with self.assertRaises(ValidationError):
            numeros.numerar_al_emitir(self.uno, actor=self.admin, motivo=MOTIVO)

    def test_emision_normal_consecutiva_guarda_usuario_fecha_reglas_y_revision(self):
        uno = self.emitir(actor=self.dev)
        dos = self.emitir(self.dos)
        self.assertEqual([uno.consecutivo, dos.consecutivo], ["OC-2026-0001", "OC-2026-0002"])
        self.assertEqual(uno.emitida_por, self.dev)
        self.assertEqual(uno.fecha_emision, datetime(2026, 6, 1, 12, tzinfo=zona_utc.utc))
        self.assertEqual(uno.estado, "emitida")
        self.assertEqual(uno.reglas_consecutivo["longitud"], 4)
        self.assertEqual(uno.revisiones.first().contenido["consecutivo"], uno.consecutivo)
        self.assertEqual(uno.revisiones.first().actor, self.dev)
        self.assertEqual(ContadorOrdenCompra.objects.get(pk="global").ultimo, 2)

    def test_anular_numero_emitido_lo_conserva_y_no_lo_reutiliza(self):
        uno = self.emitir()
        anulada = numeros.anular_orden(uno, actor=self.dev, motivo=MOTIVO)
        self.assertEqual(anulada.consecutivo, "OC-2026-0001")
        self.assertEqual(anulada.numero, 1)
        self.assertEqual(anulada.anulada_por, self.dev)
        self.assertIsNotNone(anulada.fecha_anulacion)
        self.assertEqual(anulada.motivo_anulacion, MOTIVO)
        self.assertEqual(anulada.revisiones.first().contenido["consecutivo"], "OC-2026-0001")
        self.assertEqual(self.emitir(self.dos).numero, 2)
        with self.assertRaises(ValidationError):
            self.emitir(anulada)

    def test_anular_borrador_no_consumio_numero_y_no_reactiva(self):
        orden = numeros.anular_orden(self.uno, actor=self.admin, motivo=MOTIVO)
        self.assertIsNone(orden.numero)
        self.assertEqual(ContadorOrdenCompra.objects.get(pk="global").ultimo, 0)
        orden.estado = "borrador"
        with self.assertRaises(ValidationError):
            orden.save()

    def test_formato_sin_anio_prefijo_y_longitud_editables_sin_renumerar(self):
        uno = self.emitir()
        self.parametro(PREFIJO_ORDEN, " sum-oc ")
        self.parametro(ANIO_ORDEN, "false")
        self.parametro(LONGITUD_ORDEN, "6")
        dos = self.emitir(self.dos)
        self.assertEqual(dos.consecutivo, "SUM-OC-000002")
        uno.refresh_from_db()
        self.assertEqual(uno.consecutivo, "OC-2026-0001")
        self.assertEqual(uno.reglas_consecutivo["prefijo"], "OC")

    def test_reinicio_anual_contadores_por_anio_y_sin_reinicio_global(self):
        self.parametro(REINICIO_ORDEN, "true")
        uno = self.emitir(anio=2026)
        dos = self.emitir(self.dos, anio=2027)
        self.assertEqual([uno.numero, dos.numero], [1, 1])
        self.assertNotEqual(uno.consecutivo, dos.consecutivo)
        self.assertEqual(ContadorOrdenCompra.objects.get(pk="anio:2026").ultimo, 1)
        self.assertEqual(ContadorOrdenCompra.objects.get(pk="anio:2027").ultimo, 1)

    def test_sin_reinicio_el_cambio_de_anio_continua(self):
        self.emitir(anio=2026)
        dos = self.emitir(self.dos, anio=2027)
        self.assertEqual(dos.consecutivo, "OC-2027-0002")

    def test_activar_reinicio_tras_emisiones_globales_no_colisiona(self):
        self.emitir(anio=2026)
        self.parametro(REINICIO_ORDEN, "true")
        dos = self.emitir(self.dos, anio=2026)
        self.assertEqual(dos.numero, 2)
        self.assertEqual(dos.serie_consecutivo, "anio:2026")

    def test_reinicio_anual_sin_anio_es_invalido_sin_consumir_numero(self):
        self.parametro(REINICIO_ORDEN, "true")
        self.parametro(ANIO_ORDEN, "false")
        with self.assertRaisesMessage(ValidationError, "incluir el año"):
            self.emitir()
        self.assertFalse(ContadorOrdenCompra.objects.filter(clave__startswith="anio:").exists())
        self.assertIsNone(OrdenCompra.objects.get(pk=self.uno.pk).numero)

    def test_anio_es_de_emision_en_bogota_y_no_de_elaboracion(self):
        instante = datetime(2027, 1, 1, 0, 30, tzinfo=zona_utc.utc)  # En Bogotá sigue siendo 2026.
        uno = self.emitir(instante=instante)
        self.assertEqual(uno.fecha_elaboracion.year, 2031)
        self.assertEqual(uno.consecutivo, "OC-2026-0001")

    def test_ancho_minimo_no_trunca_al_superar_9999(self):
        contador = ContadorOrdenCompra.objects.get(pk="global")
        contador.ultimo = 9999
        contador.save()
        self.assertEqual(self.emitir().consecutivo, "OC-2026-10000")

    def test_repetir_emision_rechaza_sin_consumir_otro_numero(self):
        uno = self.emitir()
        with self.assertRaises(ValidationError):
            self.emitir(uno)
        self.assertEqual(ContadorOrdenCompra.objects.get(pk="global").ultimo, 1)

    def test_revision_atrasada_y_origen_no_vigente_no_emiten(self):
        with self.assertRaises(ValidationError):
            self.emitir(revision_esperada=0)
        self.uno.refresh_from_db()
        self.assertIsNone(self.uno.numero)
        self.uno.cotizacion.estado = "en_comparacion"
        self.uno.cotizacion.save(update_fields=["estado"])
        with self.assertRaises(ValidationError):
            self.emitir()

    def test_fallo_de_auditoria_revierte_orden_numero_y_contador(self):
        self.preparar_emision(self.uno)
        self.parametro(REINICIO_ORDEN, "true")
        with patch("compras.orden_servicios.registrar", side_effect=RuntimeError("Fallo ficticio")), self.assertRaises(RuntimeError):
            self.emitir()
        self.assertFalse(ContadorOrdenCompra.objects.filter(pk="anio:2026").exists())
        self.uno.refresh_from_db()
        self.assertIsNone(self.uno.numero)
        self.assertEqual(self.uno.estado, "en_aprobacion")
        self.assertEqual(self.emitir().numero, 1)

    def test_fallo_de_anulacion_revierte_estado_y_conserva_numero(self):
        uno = self.emitir()
        with patch("compras.orden_servicios.registrar", side_effect=RuntimeError("Fallo ficticio")), self.assertRaises(RuntimeError):
            numeros.anular_orden(uno, actor=self.admin, motivo=MOTIVO)
        uno.refresh_from_db()
        self.assertEqual(uno.estado, "emitida")
        self.assertIsNone(uno.fecha_anulacion)
        self.assertEqual(uno.numero, 1)

    def test_numeracion_y_contadores_no_se_reescriben_o_retroceden(self):
        uno = self.emitir()
        uno.consecutivo = "ALTERADO"
        with self.assertRaises(ValidationError):
            uno.save()
        contador = ContadorOrdenCompra.objects.get(pk="global")
        contador.ultimo = 0
        with self.assertRaises(ValidationError):
            contador.save()
        with self.assertRaises(ValidationError):
            contador.delete()

    def test_restriccion_real_de_base_impide_consecutivos_duplicados(self):
        uno = self.emitir()
        datos = {c: getattr(uno, c) for c in ("numero", "consecutivo", "anio_consecutivo", "serie_consecutivo", "reglas_consecutivo", "fecha_emision", "emitida_por_id", "etiqueta_vencimiento")}
        with self.assertRaises(IntegrityError), transaction.atomic():
            OrdenCompra._base_manager.filter(pk=self.dos.pk).update(**datos)

    def test_validez_opcional_etiqueta_actual_y_conservada_al_emitir(self):
        self.parametro(ETIQUETA_VALIDEZ_ORDEN, "Vigencia de la oferta de compra")
        self.uno.fecha_vencimiento = date(2032, 1, 1)
        self.uno.save(update_fields=["fecha_vencimiento"])
        uno = self.emitir()
        self.assertEqual(uno.etiqueta_vencimiento, "Vigencia de la oferta de compra")
        self.parametro(ETIQUETA_VALIDEZ_ORDEN, "Fecha límite (provisional)")
        self.assertEqual(orden_servicios.foto(uno)["etiqueta_vencimiento"], "Vigencia de la oferta de compra")
        self.assertIsNone(self.dos.fecha_vencimiento)

    def test_validez_anterior_a_elaboracion_no_se_guarda(self):
        self.uno.fecha_vencimiento = date(2030, 1, 1)
        with self.assertRaises(ValidationError):
            self.uno.full_clean()

    def test_parametros_rechazan_formatos_invalidos(self):
        for clave, valor in [(PREFIJO_ORDEN, "OC/2026"), (PREFIJO_ORDEN, "-OC"), (LONGITUD_ORDEN, "0"), (LONGITUD_ORDEN, "21"), (ETIQUETA_VALIDEZ_ORDEN, "X" * 81)]:
            with self.assertRaises(ValidationError):
                self.parametro(clave, valor)

    def test_roles_motivo_y_csrf_de_anulacion(self):
        self.preparar_emision(self.uno)
        for actor in [self.coordinador, self.usuario_proveedor, AnonymousUser()]:
            with self.assertRaises(PermissionDenied):
                numeros.numerar_al_emitir(self.uno, actor=actor, motivo=MOTIVO)
            with self.assertRaises(PermissionDenied):
                numeros.anular_orden(self.uno, actor=actor, motivo=MOTIVO)
        with self.assertRaises(ValidationError):
            numeros.numerar_al_emitir(self.uno, actor=self.admin, motivo=" ")
        self.client.force_login(self.admin)
        url = reverse("compras:orden_anular", args=[self.uno.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.admin)
        self.assertEqual(csrf.post(url, {"motivo": MOTIVO, "revision_esperada": self.uno.revision}).status_code, 403)
        self.assertEqual(self.client.post(url, {"motivo": MOTIVO, "revision_esperada": self.uno.revision}).status_code, 302)
        self.uno.refresh_from_db()
        self.assertEqual(self.uno.estado, "anulada")

    def test_formulario_de_borrador_presenta_validez_configurable(self):
        self.parametro(ETIQUETA_VALIDEZ_ORDEN, "Validez pactada")
        self.client.force_login(self.admin)
        respuesta = self.client.get(reverse("compras:orden_editar", args=[self.uno.pk]))
        self.assertContains(respuesta, "Validez pactada")
        self.assertContains(respuesta, 'name="fecha_vencimiento"')
        linea = self.uno.lineas.get()
        datos = {"fecha_elaboracion": self.fecha.isoformat(), "fecha_vencimiento": "2032-01-01", "revision_esperada": self.uno.revision,
            "motivo": MOTIVO, "lineas-TOTAL_FORMS": "1", "lineas-INITIAL_FORMS": "1", "lineas-0-id": linea.pk,
            "lineas-0-descripcion": linea.descripcion, "lineas-0-unidad": linea.unidad, "lineas-0-cantidad": str(linea.cantidad), "lineas-0-precio_unitario": str(linea.precio_unitario)}
        self.assertEqual(self.client.post(reverse("compras:orden_editar", args=[self.uno.pk]), datos).status_code, 302)
        self.uno.refresh_from_db()
        self.assertEqual(self.uno.fecha_vencimiento, date(2032, 1, 1))
        self.assertEqual(self.uno.revisiones.first().contenido["fecha_vencimiento"], "2032-01-01")


@skipUnless(connection.vendor == "postgresql", "Las emisiones concurrentes requieren PostgreSQL.")
class NumeracionConcurrenteTests(TransactionTestCase):
    def setUp(self):
        from areas.models import Area
        from compras import decision_cotizacion_servicios, oferta_servicios
        from compras.models import Cotizacion, InvitadoCotizacion, LineaCotizacion, Necesidad, TarifaImpuesto, TipoCotizacion
        from cuentas.tests.utilidades import crear_usuario
        from proveedores.tests.utilidades import crear_proveedor
        from proyecciones.models import UnidadMedida
        from django.utils import timezone
        self.admin = crear_usuario("administrador", correo="numeracion@ejemplo.test")
        self.dev = crear_usuario("desarrollador", correo="firma.numeracion@ejemplo.test")
        area = Area.objects.create(nombre="Área ficticia numeración", codigo_area="NUM")
        unidad = UnidadMedida.objects.create(nombre="Unidad ficticia numeración", abreviatura="num")
        tipo, _ = TipoCotizacion.objects.get_or_create(nombre="Tipo ficticio numeración")
        tarifa, _ = TarifaImpuesto.objects.get_or_create(nombre="Tarifa ficticia numeración", defaults={"porcentaje": 0})
        proveedores = [crear_proveedor(), crear_proveedor()]
        self.ordenes = []
        for numero in [1, 2]:
            necesidad = Necesidad.objects.create(objeto="Necesidad ficticia", area=area, responsable=self.admin)
            cotizacion = Cotizacion.objects.create(necesidad=necesidad, area=area, responsable=self.admin, tipo=tipo, objeto="Cotización ficticia numeración",
                numero=numero, consecutivo=f"COT-NUM-{numero}")
            linea = LineaCotizacion.objects.create(cotizacion=cotizacion, orden=1, descripcion="Insumo", unidad=unidad, unidad_texto=str(unidad), cantidad=1)
            ofertas = []
            for precio, proveedor in enumerate(proveedores, 10):
                invitado = InvitadoCotizacion.objects.create(cotizacion=cotizacion, proveedor=proveedor, nit=proveedor.nit, razon_social=proveedor.razon_social)
                ofertas.append(oferta_servicios.guardar_oferta(cotizacion, invitado, contacto_nombre="Contacto", contacto_correo="numeracion@ejemplo.test", contacto_telefono="6015550100",
                    fecha=timezone.localdate(), precios=[{"linea": linea.pk, "precio_unitario": precio, "tarifa": tarifa}], actor=self.admin, motivo=MOTIVO))
            decision = decision_cotizacion_servicios.proponer_decision(cotizacion, modalidad="completa", oferta_id=ofertas[0].pk, recomendacion=MOTIVO, actor=self.admin, motivo=MOTIVO)
            decision = decision_cotizacion_servicios.aprobar_decision(decision, actor=self.admin, motivo=MOTIVO)
            orden, = orden_servicios.crear_orden_desde_decision(decision, actor=self.admin, motivo=MOTIVO)
            from compras.pruebas_operacion import preparar_numeracion
            preparar_numeracion(orden, self.admin, self.dev)
            self.ordenes.append(orden)

    def simultaneas(self, ids):
        from cuentas.models import Usuario
        barrera = Barrier(2)
        def emitir(pk):
            try:
                actor = Usuario.objects.get(pk=self.admin.pk)
                orden = OrdenCompra.objects.get(pk=pk)
                barrera.wait(timeout=15)
                try:
                    return numeros.numerar_al_emitir(orden, actor=actor, motivo=MOTIVO).numero
                except ValidationError:
                    return "rechazada"
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as ejecutor:
            futuros = [ejecutor.submit(emitir, pk) for pk in ids]
            return [f.result(timeout=40) for f in futuros]

    def test_dos_cotizaciones_emiten_numeros_distintos_con_un_contador(self):
        resultado = self.simultaneas([o.pk for o in self.ordenes])
        self.assertCountEqual(resultado, [1, 2])
        self.assertEqual(OrdenCompra.objects.exclude(consecutivo=None).values("consecutivo").distinct().count(), 2)
        self.assertEqual(ContadorOrdenCompra.objects.get(pk="global").ultimo, 2)
        self.assertEqual(RegistroBitacora.objects.filter(accion="orden.emitida_numerada").count(), 2)

    def test_doble_emision_de_la_misma_orden_solo_asigna_un_numero(self):
        resultado = self.simultaneas([self.ordenes[0].pk] * 2)
        self.assertCountEqual(resultado, [1, "rechazada"])

    def test_dos_respuestas_simultaneas_no_duplican_firma_ni_emision(self):
        from compras.models import AprobacionOrden
        from compras.aprobacion_orden_servicios import votar
        from cuentas.models import Usuario
        orden = self.ordenes[0]
        # Retira únicamente la firma ficticia preparada por este fixture del motor B16.
        AprobacionOrden._base_manager.filter(orden=orden).delete()
        barrera = Barrier(2)
        def responder():
            try:
                actor = Usuario.objects.get(pk=self.dev.pk)
                actual = OrdenCompra.objects.get(pk=orden.pk)
                barrera.wait(timeout=15)
                try:
                    return votar(actual, decision="aprueba", actor=actor, motivo=MOTIVO).numero
                except ValidationError:
                    return "rechazada"
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as ejecutor:
            futuros = [ejecutor.submit(responder) for _ in range(2)]
            resultados = [f.result(timeout=40) for f in futuros]
        self.assertCountEqual(resultados, [1, "rechazada"])
        self.assertEqual(AprobacionOrden.objects.filter(orden=orden).count(), 1)
        self.assertEqual(ContadorOrdenCompra.objects.get(pk="global").ultimo, 1)
        self.assertEqual(RegistroBitacora.objects.filter(accion="orden.emitida_numerada").count(), 1)
