from copy import deepcopy
from datetime import date, datetime, timedelta, timezone as utc
from decimal import Decimal
from io import BytesIO, StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from django.core.exceptions import ValidationError, PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, SimpleTestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook
from compras.tests_aprobacion_ordenes import DatosOrdenOperativa
from compras import recepcion_servicios, contrato_servicios, decision_cotizacion_servicios
from compras.models import Contrato
from parametros.catalogo import AUTO_SEGUIMIENTO, REABRIR_SEGUIMIENTO, CIERRE_CON_SALDO, CONSULTA_COORDINADOR_SEGUIMIENTO
from seguimientos import servicios, estados, reportes
from seguimientos.models import Seguimiento, TipoSeguimiento, TipoEvento, EventoSeguimiento, PlantillaHito, ResultadoCierre
from bitacora.models import RegistroBitacora

MOTIVO = "Seguimiento ficticio con trazabilidad y movimiento conservado"


class EstadosTests(SimpleTestCase):
    def test_deriva_cada_estado_con_fecha_fija(self):
        hoy = date(2026, 6, 10)
        evento = {"id": 1, "tipo_id": 1, "fecha": datetime(2026, 6, 8, tzinfo=utc.utc), "funcion": "solicita_documentos", "corrige_id": None}
        datos = dict(cerrado=False, eventos=[], lineas=[{"pendiente": 1, "recibido": 0}], hitos=[], hoy=hoy)
        self.assertEqual(estados.derivar(**datos), "abierto")
        self.assertEqual(estados.derivar(**{**datos, "eventos": [evento]}), "en_espera_documentos")
        self.assertEqual(estados.derivar(**{**datos, "lineas": [{"pendiente": 1, "recibido": 1}]}), "parcial")
        self.assertEqual(estados.derivar(**{**datos, "lineas": [{"pendiente": 0, "recibido": 1}]}), "completo")
        self.assertEqual(estados.derivar(**{**datos, "fecha_esperada": hoy-timedelta(days=1)}), "atrasado")
        self.assertEqual(estados.derivar(**{**datos, "cerrado": True, "hitos": [{"atrasado": True}]}), "cerrado")

    def test_hito_vencido_cumplido_correccion_y_evento_futuro(self):
        apertura = datetime(2026, 6, 1, tzinfo=utc.utc)
        hito = dict(nombre="Ficticio", referencia_id=None, cumple_id=2, plazo_dias=2)
        self.assertTrue(estados.evaluar_hitos([hito], [], apertura, date(2026, 6, 4))[0]["atrasado"])
        evento = dict(id=1, tipo_id=2, fecha=datetime(2026, 6, 5, tzinfo=utc.utc), funcion="recibe_documentos", corrige_id=None)
        self.assertFalse(estados.evaluar_hitos([hito], [evento], apertura, date(2026, 6, 4))[0]["cumplido"])
        self.assertTrue(estados.evaluar_hitos([hito], [evento], apertura, date(2026, 6, 5))[0]["cumplido"])
        correccion = {**evento, "id": 2, "tipo_id": 3, "corrige_id": 1}
        self.assertTrue(estados.evaluar_hitos([hito], [evento, correccion], apertura, date(2026, 6, 6))[0]["atrasado"])


class SeguimientosTests(DatosOrdenOperativa, TestCase):
    def test_fallo_al_incorporar_recepcion_revierte_seguimiento_y_eventos(self):
        self.parametro(AUTO_SEGUIMIENTO, "false")
        orden = self.emitir()
        recepcion = self.recibir(orden)
        registrar = servicios.registrar
        def fallar(accion, **datos):
            if accion == "seguimiento.recepcion_vinculada":
                raise RuntimeError("Fallo ficticio al incorporar historial")
            return registrar(accion, **datos)
        with patch("seguimientos.servicios.registrar", side_effect=fallar), self.assertRaises(RuntimeError):
            servicios.crear(orden=orden, actor=self.admin, motivo=MOTIVO)
        self.assertFalse(Seguimiento.objects.filter(orden=orden).exists())
        self.assertFalse(EventoSeguimiento.objects.filter(recepcion=recepcion).exists())
        self.assertEqual(recepcion.lineas.count(), 2)
        self.assertFalse(RegistroBitacora.objects.filter(accion="seguimiento.creado").exists())

    def test_seguimiento_tardio_incorpora_movimientos_previos_sin_duplicar_pdf(self):
        self.parametro(AUTO_SEGUIMIENTO, "false")
        orden = self.emitir()
        with TemporaryDirectory() as carpeta, override_settings(MEDIA_ROOT=carpeta):
            soporte = SimpleUploadedFile("anterior.pdf", b"%PDF-1.4 soporte ficticio", content_type="application/pdf")
            recepcion = self.recibir(orden, archivo=soporte, actor=self.dev)
            devolucion = self.recibir(orden, tipo="devolucion", lineas=[{"id": orden.lineas.first().pk, "devuelta": ".25"}])
            seguimiento = servicios.crear(orden=orden, actor=self.admin, motivo=MOTIVO)
            self.assertEqual(seguimiento.eventos.count(), 2)
            evento = seguimiento.eventos.get(recepcion=recepcion)
            self.assertEqual(evento.registrado_por_id, self.dev.pk)
            self.assertEqual(evento.nota, f"Recepción {recepcion.pk}: {recepcion.observacion}")
            self.assertEqual(evento.archivo.name, recepcion.archivo.name)
            bitacora = RegistroBitacora.objects.get(accion="seguimiento.recepcion_vinculada", objeto_id=str(evento.pk))
            self.assertEqual(bitacora.actor_id, self.admin.pk)
            self.assertTrue(bitacora.valor_nuevo["incorporacion_historica"])
            self.assertEqual(seguimiento.eventos.get(recepcion=devolucion).funcion, "devolucion")
            self.assertEqual(len(list(Path(carpeta).rglob("*.pdf"))), 1)
            self.assertEqual(servicios.crear(orden=orden, actor=self.admin, motivo=MOTIVO).pk, seguimiento.pk)
            self.assertEqual(seguimiento.eventos.count(), 2)

    def evento(self, seguimiento, **cambios):
        datos = dict(tipo=TipoEvento.objects.get(codigo="comunicacion"), fecha=timezone.now(), nota="Nota ficticia conservada", actor=self.admin, motivo=MOTIVO)
        datos.update(cambios)
        return servicios.agregar_evento(seguimiento, **datos)

    def recibir(self, orden, **cambios):
        datos = dict(fecha=timezone.localdate(), lineas=[{"id": l.pk, "cantidad": l.cantidad} for l in orden.lineas.all()], actor=self.admin, motivo=MOTIVO)
        datos.update(cambios)
        return recepcion_servicios.registrar_recepcion(orden, **datos)

    def test_auto_creacion_copia_origen_es_idempotente_y_no_reescribe(self):
        orden = self.emitir()
        seguimiento = Seguimiento.objects.get(orden=orden)
        self.assertEqual(seguimiento.valor, orden.total)
        self.assertEqual(seguimiento.objeto, orden.origen_datos["trazabilidad"]["objeto"])
        self.assertEqual(servicios.crear(orden=orden, actor=self.admin, motivo=MOTIVO).pk, seguimiento.pk)
        origen = deepcopy(seguimiento.origen_datos)
        seguimiento = servicios.corregir(seguimiento, proveedor=self.ficha, objeto="Objeto ficticio corregido", valor=70,
            tipo=seguimiento.tipo, actor=self.admin, motivo=MOTIVO, revision_esperada=seguimiento.revision)
        self.assertEqual(seguimiento.origen_datos, origen)
        self.assertEqual(orden.total, 52)
        self.assertTrue(RegistroBitacora.objects.filter(accion="seguimiento.corregido", valor_anterior__valor="52.00").exists())
        with self.assertRaises(ValidationError):
            seguimiento.save()

    def test_desactivar_auto_y_crear_manualmente_desde_orden_o_contrato(self):
        self.parametro(AUTO_SEGUIMIENTO, "false")
        contrato_servicios.guardar_requiere(self.cotizacion, requiere_contrato=True, actor=self.admin, motivo=MOTIVO)
        self.proponer()
        contrato = contrato_servicios.guardar_contrato(self.decision, numero="CT-FICTICIO-SEG", supervisor_texto="Supervisor ficticio", cargo="Cargo", fecha_inicio=self.fecha,
            fecha_fin=self.fecha, forma_pago="Pago ficticio", valor=52, actor=self.admin, motivo=MOTIVO)
        self.decision = decision_cotizacion_servicios.aprobar_decision(self.decision, actor=self.admin, motivo=MOTIVO)
        orden = self.emitir()
        self.assertFalse(Seguimiento.objects.exists())
        seguimiento = servicios.crear(contrato=contrato, actor=self.admin, motivo=MOTIVO)
        self.assertEqual(seguimiento.valor, 52)
        self.assertIsNone(seguimiento.orden_id)
        self.assertEqual(servicios.crear(contrato=contrato, actor=self.admin, motivo=MOTIVO).pk, seguimiento.pk)
        desde_orden = servicios.crear(orden=orden, actor=self.admin, motivo=MOTIVO)
        self.assertEqual(desde_orden.contrato, contrato)

    def test_eventos_cronologia_correccion_inmutable_y_nombre_conservado(self):
        seguimiento = self.emitir().seguimiento
        primero = self.evento(seguimiento, fecha=timezone.now()-timedelta(days=2))
        segundo = self.evento(seguimiento)
        correccion = self.evento(seguimiento, corrige_id=primero.pk, nota="Corrección ficticia")
        self.assertEqual(list(seguimiento.eventos.values_list("pk", flat=True)), [primero.pk, segundo.pk, correccion.pk])
        tipo = primero.tipo
        tipo.nombre = "Nombre posterior"
        servicios.guardar_catalogo(tipo, actor=self.admin, motivo=MOTIVO)
        primero.refresh_from_db()
        self.assertEqual(primero.tipo_nombre, "Comunicación con proveedor")
        with self.assertRaises(ValidationError):
            primero.save()
        with self.assertRaises(ValidationError):
            primero.delete()
        with self.assertRaises(ValidationError):
            self.evento(seguimiento, corrige_id=primero.pk)

    def test_recepciones_devolucion_ajuste_generan_eventos_y_saldo_real(self):
        orden = self.emitir()
        seguimiento = orden.seguimiento
        self.recibir(orden)
        linea = orden.lineas.first()
        devolucion = self.recibir(orden, tipo="devolucion", lineas=[{"id": linea.pk, "devuelta": ".25"}])
        fila = servicios.lineas(seguimiento)[0]
        self.assertEqual((fila["recibido"], fila["devuelto"], fila["pendiente"]), (Decimal(".75"), Decimal(".25"), Decimal(".25")))
        self.assertEqual(seguimiento.eventos.count(), 2)
        self.assertEqual(seguimiento.eventos.last().recepcion_id, devolucion.pk)
        self.assertEqual(seguimiento.eventos.last().funcion, "devolucion")
        with self.assertRaises(ValidationError):
            self.recibir(orden, tipo="devolucion", lineas=[{"id": linea.pk, "devuelta": 2}])
        self.recibir(orden, tipo="ajuste", ajusta_id=devolucion.pk, lineas=[{"id": linea.pk, "cantidad": ".1", "devuelta": "-.1"}])
        self.assertEqual(servicios.lineas(seguimiento)[0]["pendiente"], Decimal(".15"))

    def test_cerrar_linea_con_motivo_impide_movimientos_hasta_reabrir(self):
        orden = self.emitir()
        seguimiento = orden.seguimiento
        linea = orden.lineas.first()
        with self.assertRaises(ValidationError):
            servicios.mover_linea(seguimiento, linea_id=linea.pk, accion="cerrar", actor=self.admin, motivo=" ")
        servicios.mover_linea(seguimiento, linea_id=linea.pk, accion="cerrar", actor=self.admin, motivo=MOTIVO)
        self.assertEqual(servicios.lineas(seguimiento)[0]["estado"], "cerrada con saldo")
        with self.assertRaises(ValidationError):
            self.recibir(orden)
        servicios.mover_linea(seguimiento, linea_id=linea.pk, accion="reabrir", actor=self.admin, motivo=MOTIVO)
        self.recibir(orden)

    def test_hitos_con_foto_plazo_vence_y_cumplimiento_lo_actualiza(self):
        orden = self.emitir()
        seguimiento = orden.seguimiento
        tipo = TipoEvento.objects.get(codigo="documentos_recibidos")
        plantilla = servicios.guardar_catalogo(PlantillaHito(tipo_seguimiento=seguimiento.tipo, nombre="Documento ficticio", cumple=tipo, plazo_dias=1), actor=self.admin, motivo=MOTIVO)
        seguimiento = servicios.actualizar_hitos(seguimiento, actor=self.admin, motivo=MOTIVO)
        plantilla.plazo_dias = 30
        servicios.guardar_catalogo(plantilla, actor=self.admin, motivo=MOTIVO)
        hoy = timezone.localdate()+timedelta(days=2)
        self.assertEqual(servicios.tablero(seguimiento, hoy=hoy)["estado"], "atrasado")
        self.evento(seguimiento, tipo=tipo, fecha=timezone.now()+timedelta(days=1))
        self.assertEqual(servicios.tablero(seguimiento, hoy=hoy)["estado"], "abierto")
        salida = StringIO()
        call_command("seguimientos_atrasados", fecha=hoy, stdout=salida)
        self.assertEqual(salida.getvalue(), "")

    def test_fecha_esperada_vencida_deriva_atrasado_sin_inventar_sla(self):
        orden, = self.crear(fecha_elaboracion=timezone.localdate()-timedelta(days=5), fecha_esperada_entrega=timezone.localdate()-timedelta(days=1))
        orden = self.emitir(orden)
        self.assertEqual(servicios.tablero(orden.seguimiento)["estado"], "atrasado")

    def test_cierre_saldo_reapertura_parametro_e_historial_conservado(self):
        orden = self.emitir()
        seguimiento = orden.seguimiento
        self.evento(seguimiento)
        resultado = ResultadoCierre.objects.get(codigo="cumplido_novedades")
        with self.assertRaises(ValidationError):
            servicios.cerrar(seguimiento, resultado=resultado, fecha=timezone.localdate(), actor=self.admin, motivo=MOTIVO)
        self.parametro(CIERRE_CON_SALDO, "advertir")
        seguimiento = servicios.cerrar(seguimiento, resultado=resultado, fecha=timezone.localdate(), actor=self.admin, motivo=MOTIVO)
        orden.refresh_from_db()
        self.assertEqual(orden.estado, "cerrada")
        self.assertEqual(seguimiento.eventos.count(), 1)
        with self.assertRaises(ValidationError):
            self.evento(seguimiento)
        with self.assertRaises(ValidationError):
            servicios.reabrir(seguimiento, actor=self.admin, motivo=MOTIVO)
        self.parametro(REABRIR_SEGUIMIENTO, "true")
        seguimiento = servicios.reabrir(seguimiento, actor=self.admin, motivo=MOTIVO)
        orden.refresh_from_db()
        self.assertEqual(orden.estado, "emitida")
        self.assertEqual(seguimiento.cierres.count(), 2)
        self.assertEqual(seguimiento.eventos.count(), 1)

    def test_reportes_filtros_agregados_por_unidad_y_excel_coinciden(self):
        orden = self.emitir()
        seguimiento = orden.seguimiento
        self.recibir(orden, lineas=[{"id": orden.lineas.first().pk, "cantidad": ".5"}])
        filtros = dict(periodo=timezone.localdate().year, desde=timezone.localdate(), hasta=timezone.localdate(), area=seguimiento.area,
            proveedor=seguimiento.nit, tipo=seguimiento.tipo, estado="parcial")
        datos = reportes.consulta(filtros, self.admin)
        self.assertEqual(datos["totales"]["cantidad"], 1)
        self.assertEqual((datos["totales"]["valor"], datos["totales"]["valor_ordenes"]), (52, 52))
        self.assertEqual((datos["cantidades"][0]["recibido"], datos["cantidades"][0]["pendiente"]), (Decimal(".5"), Decimal("2.5")))
        libro = load_workbook(BytesIO(reportes.exportar(datos)), data_only=True)
        self.assertEqual(libro["Seguimientos"]["A2"].value, seguimiento.pk)
        self.assertEqual(libro["Seguimientos"]["H3"].value, 52)
        self.assertEqual(libro["Cantidades por unidad"]["C2"].value, .5)
        for cambios in ({"periodo": 2000}, {"desde": timezone.localdate()+timedelta(days=1)}, {"proveedor": "No existe"}, {"estado": "cerrado"}, {"tipo": TipoSeguimiento.objects.get(codigo="contratos")}):
            with self.subTest(cambios=cambios):
                self.assertEqual(reportes.consulta({**filtros, **cambios}, self.admin)["totales"]["cantidad"], 0)

    def test_pantallas_permisos_alcance_csrf_archivos_privados_y_reversion(self):
        orden = self.emitir()
        seguimiento = orden.seguimiento
        self.client.force_login(self.admin)
        for url in (reverse("seguimientos:lista"), reverse("seguimientos:detalle", args=[seguimiento.pk]), reverse("seguimientos:crear"),
                reverse("seguimientos:corregir", args=[seguimiento.pk]), reverse("seguimientos:evento", args=[seguimiento.pk]),
                reverse("seguimientos:cerrar", args=[seguimiento.pk]), reverse("seguimientos:catalogo", args=["hitos"])):
            self.assertEqual(self.client.get(url).status_code, 200, url)
        self.assertEqual(self.client.get(reverse("seguimientos:lista")+"?formato=excel").status_code, 200)
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.admin)
        self.assertEqual(csrf.post(reverse("seguimientos:evento", args=[seguimiento.pk]), {}).status_code, 403)
        with TemporaryDirectory() as carpeta, override_settings(MEDIA_ROOT=carpeta):
            pdf = lambda: SimpleUploadedFile("evento.pdf", b"%PDF-1.4 ficticio", content_type="application/pdf")
            with patch("seguimientos.servicios.registrar", side_effect=RuntimeError("Fallo ficticio")), self.assertRaises(RuntimeError):
                self.evento(seguimiento, archivo=pdf())
            self.assertFalse(EventoSeguimiento.objects.exists())
            self.assertEqual(list(Path(carpeta).rglob("*.pdf")), [])
            evento = self.evento(seguimiento, archivo=pdf())
            respuesta = self.client.get(reverse("seguimientos:evento_pdf", args=[seguimiento.pk, evento.pk]))
            self.assertEqual(b"".join(respuesta.streaming_content), b"%PDF-1.4 ficticio")
        self.client.force_login(self.coordinador)
        self.assertEqual(self.client.get(reverse("seguimientos:lista")).status_code, 403)
        self.parametro(CONSULTA_COORDINADOR_SEGUIMIENTO, "true")
        self.coordinador.area = seguimiento.area
        self.coordinador.save()
        self.assertEqual(self.client.get(reverse("seguimientos:lista")).status_code, 200)
        self.coordinador.area = self.otra_area if hasattr(self, "otra_area") else None
        with self.assertRaises(PermissionDenied):
            servicios.agregar_evento(seguimiento, tipo=TipoEvento.objects.first(), fecha=timezone.now(), nota="No autorizado", actor=self.coordinador, motivo=MOTIVO)
