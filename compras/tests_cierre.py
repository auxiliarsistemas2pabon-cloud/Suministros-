from copy import deepcopy
from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch

from django.apps import apps
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client, TestCase
from django.urls import reverse
from openpyxl import load_workbook

from bitacora.models import RegistroBitacora
from compras import calificacion_servicios, cierre_servicios, decision_servicios, servicios, tests_decision
from compras.cotizacion_origen import preparar_cotizacion
from compras.models import CalificacionElegible, CierreListaElegibles, ListaElegibles, Necesidad
from parametros.catalogo import CONTROL_DOCUMENTAL_ELEGIBLES
from parametros.models import Parametro
from parametros.servicios import cambiar_valor

MOTIVO = "Cierre ficticio de elegibles verificado"


class CierreElegiblesTests(TestCase):
    def setUp(self):
        tests_decision.DecisionElegiblesTests.setUp(self)
        self.decidir()

    def calificar(self, valores=None):
        return tests_decision.DecisionElegiblesTests.calificar(self, valores)

    def asignaciones(self, cantidades=None, justificaciones=None):
        return tests_decision.DecisionElegiblesTests.asignaciones(self, cantidades, justificaciones)

    def decidir(self, **kwargs):
        return tests_decision.DecisionElegiblesTests.decidir(self, **kwargs)

    def cerrar(self, **cambios):
        datos = dict(actor=self.admin, motivo=MOTIVO, justificacion_documental=MOTIVO)
        datos.update(cambios)
        self.lista_actual = cierre_servicios.cerrar_lista(self.lista_actual, **datos)
        return self.lista_actual

    def test_cierre_guarda_actor_fecha_resultado_documentos_y_archivo(self):
        lista = self.cerrar()
        self.assertEqual(lista.estado, "cerrada")
        self.assertEqual(lista.cerrada_por, self.admin)
        self.assertTrue(lista.fecha_cierre)
        self.assertEqual(lista.documental_por, self.admin)
        self.p1.refresh_from_db()
        self.assertTrue(self.p1.estado_documental)
        self.assertEqual(lista.resultado_cierre["filas"][0]["total"], "5.0000")
        cierre = lista.cierres.get()
        self.assertEqual(cierre.actor, self.admin)
        self.assertEqual(cierre.fecha, lista.fecha_cierre)
        self.assertEqual(cierre.motivo, MOTIVO)
        self.assertEqual(cierre.contenido["resultado"], lista.resultado_cierre)
        self.assertTrue(cierre.contenido["documental"]["filas"])
        self.assertTrue(RegistroBitacora.objects.filter(accion="elegibles.lista_cerrada", actor=self.admin, motivo=MOTIVO).exists())

    def test_cierre_no_crea_otras_entidades_y_precarga_no_escritura(self):
        modelos = [m for m in apps.get_models() if m not in (CierreListaElegibles, RegistroBitacora)]
        antes = {m._meta.label: m.objects.count() for m in modelos}
        self.cerrar()
        self.assertEqual({m._meta.label: m.objects.count() for m in modelos}, antes)
        todos = {m: m.objects.count() for m in apps.get_models()}
        datos = preparar_cotizacion(self.lista_actual, actor=self.admin)
        self.assertEqual(datos["lista"], self.lista_actual.pk)
        self.assertEqual(datos["invitados"][0]["proveedor"], self.p1.proveedor_id)
        self.assertEqual({m: m.objects.count() for m in apps.get_models()}, todos)

    def test_calificacion_incompleta_o_decision_obsoleta_impiden_cierre(self):
        p2 = tests_decision.DecisionElegiblesTests.agregar(self)
        with self.assertRaises(ValidationError):
            self.cerrar()
        self.calificar({p2.pk: 3})
        with self.assertRaises(ValidationError):
            self.cerrar()
        self.assertFalse(CierreListaElegibles.objects.exists())
        self.lista_actual.refresh_from_db()
        self.assertEqual(self.lista_actual.estado, "borrador")

    def test_cierre_valida_advertencias_y_bloqueo_documental_sin_cambios_parciales(self):
        with self.assertRaises(ValidationError):
            self.cerrar(justificacion_documental="")
        cambiar_valor(Parametro.objects.get(clave=CONTROL_DOCUMENTAL_ELEGIBLES), "bloquear", actor=self.admin, motivo=MOTIVO)
        with self.assertRaises(ValidationError):
            self.cerrar()
        self.lista_actual.refresh_from_db()
        self.assertEqual(self.lista_actual.estado, "borrador")
        self.assertIsNone(self.lista_actual.fecha_cierre)
        self.assertEqual(self.lista_actual.resultado_cierre, {})
        self.assertFalse(self.lista_actual.cierres.exists())

    def test_fallo_al_conservar_documentos_revierte_estado_y_bitacora(self):
        antes = RegistroBitacora.objects.count()
        with patch("compras.cierre_servicios.documental_servicios.conservar_al_cerrar", side_effect=RuntimeError("Fallo simulado")):
            with self.assertRaises(RuntimeError):
                self.cerrar()
        self.lista_actual.refresh_from_db()
        self.assertEqual(self.lista_actual.estado, "borrador")
        self.assertEqual(self.lista_actual.justificacion_documental, "")
        self.assertEqual(self.lista_actual.resultado_cierre, {})
        self.assertEqual(RegistroBitacora.objects.count(), antes)

    def test_fallo_al_archivar_revierte_tambien_las_fotos(self):
        with patch("compras.cierre_servicios.CierreListaElegibles.save", side_effect=RuntimeError("Fallo simulado")):
            with self.assertRaises(RuntimeError):
                self.cerrar()
        self.lista_actual.refresh_from_db()
        self.p1.refresh_from_db()
        self.assertEqual(self.lista_actual.estado, "borrador")
        self.assertIsNone(self.lista_actual.documental_fecha)
        self.assertEqual(self.p1.estado_documental, {})
        self.assertFalse(CierreListaElegibles.objects.exists())

    def test_cerrada_es_solo_lectura_y_totales_salen_de_la_foto(self):
        self.cerrar()
        with self.assertRaises(ValidationError):
            servicios.agregar_participante(self.lista_actual, self.ficha, actor=self.admin, motivo=MOTIVO)
        with self.assertRaises(ValidationError):
            calificacion_servicios.guardar_matriz(self.lista_actual, [], actor=self.admin, motivo=MOTIVO)
        with self.assertRaises(ValidationError):
            self.decidir()
        # Incluso una modificación directa de la fuente no reescribe la foto.
        CalificacionElegible.objects.filter(participante=self.p1)._transicion(cumplimiento=Decimal(1))
        Necesidad.objects.filter(pk=self.necesidad.pk).update(objeto="Objeto modificado fuera del flujo", cantidad_base=Decimal(999))
        resultado = decision_servicios.obtener_puestos(self.lista_actual)
        self.assertEqual(resultado["filas"][0]["total"], Decimal(5))
        self.assertEqual(resultado["base"]["cantidad"], Decimal(10))
        self.assertTrue(resultado["historico"])
        self.client.force_login(self.admin)
        self.assertNotContains(self.client.get(reverse("compras:lista_calificar", args=[self.lista_actual.pk])), "Guardar calificaciones y recalcular")
        self.assertNotContains(self.client.get(reverse("compras:lista_decision", args=[self.lista_actual.pk])), "Registrar decisión y cantidades")

    def test_reapertura_conserva_archivo_y_exige_decidir_otra_vez(self):
        self.cerrar()
        primero = self.lista_actual.cierres.get()
        contenido = deepcopy(primero.contenido)
        self.lista_actual = cierre_servicios.reabrir_lista(self.lista_actual, actor=self.dev, motivo=MOTIVO)
        self.assertEqual(self.lista_actual.estado, "borrador")
        self.assertEqual(self.lista_actual.reabierta_por, self.dev)
        self.assertTrue(self.lista_actual.fecha_reapertura)
        self.assertIsNone(self.lista_actual.fecha_cierre)
        self.assertIsNone(self.lista_actual.documental_fecha)
        self.assertFalse(decision_servicios.estado_decision(self.lista_actual)["vigente"])
        with self.assertRaises(ValidationError):
            self.cerrar()
        self.calificar({self.p1.pk: 3})
        self.decidir()
        self.cerrar()
        primero.refresh_from_db()
        self.assertEqual(primero.contenido, contenido)
        self.assertEqual(self.lista_actual.cierres.count(), 2)
        self.assertEqual(decision_servicios.obtener_puestos(self.lista_actual)["filas"][0]["total"], Decimal(3))

    def test_desempate_conservado_se_consulta_y_exporta_desde_el_cierre(self):
        p2 = tests_decision.DecisionElegiblesTests.agregar(self)
        self.calificar()
        decision_servicios.guardar_desempate(self.lista_actual, orden=[self.p1.pk, p2.pk], justificacion=MOTIVO, actor=self.admin, motivo=MOTIVO)
        self.decidir()
        self.cerrar()
        resultado = decision_servicios.obtener_puestos(self.lista_actual)
        self.assertEqual([f["puesto"] for f in resultado["filas"]], [1, 2])
        self.assertTrue(resultado["filas"][0]["desempate"].justificacion)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("compras:lista_decision", args=[self.lista_actual.pk])).status_code, 200)
        respuesta = self.client.get(reverse("compras:lista_exportar", args=[self.lista_actual.pk]))
        libro = load_workbook(BytesIO(respuesta.content))
        self.addCleanup(libro.close)
        self.assertEqual(libro["Elegibles"]["F9"].value, 1)
        self.assertEqual(libro["Elegibles"]["F10"].value, 2)

    def test_con_cotizacion_asociada_no_se_reabre_ni_anula_y_se_indica_el_estado(self):
        self.cerrar()
        modelo = SimpleNamespace(objects=SimpleNamespace(filter=lambda **kwargs: SimpleNamespace(exists=lambda: True)))
        registro_apps = SimpleNamespace(get_model=lambda *args: modelo)
        # Adaptador de la asociación real que incorporará B9, sin crear ese módulo anticipadamente.
        with patch("compras.cotizacion_origen.apps", registro_apps):
            self.assertEqual(self.lista_actual.estado_flujo, "Con cotización")
            with self.assertRaises(ValidationError):
                cierre_servicios.reabrir_lista(self.lista_actual, actor=self.admin, motivo=MOTIVO)
            with self.assertRaises(ValidationError):
                cierre_servicios.anular_lista(self.lista_actual, actor=self.admin, motivo=MOTIVO)
        self.lista_actual.refresh_from_db()
        self.assertEqual(self.lista_actual.estado, "cerrada")

    def test_anulacion_conserva_cierre_y_es_terminal(self):
        self.cerrar()
        foto = deepcopy(self.lista_actual.resultado_cierre)
        self.lista_actual = cierre_servicios.anular_lista(self.lista_actual, actor=self.admin, motivo=MOTIVO)
        self.assertEqual(self.lista_actual.estado, "anulada")
        self.assertEqual(self.lista_actual.anulada_por, self.admin)
        self.assertEqual(self.lista_actual.motivo_anulacion, MOTIVO)
        self.assertTrue(self.lista_actual.fecha_anulacion)
        self.assertEqual(self.lista_actual.resultado_cierre, foto)
        self.assertEqual(self.lista_actual.cierres.count(), 1)
        with self.assertRaises(ValidationError):
            self.cerrar()
        with self.assertRaises(ValidationError):
            cierre_servicios.reabrir_lista(self.lista_actual, actor=self.admin, motivo=MOTIVO)
        with self.assertRaises(ValidationError):
            cierre_servicios.anular_lista(self.lista_actual, actor=self.admin, motivo=MOTIVO)

    def test_anular_borrador_sin_calificar_no_exige_cierre(self):
        nueva = servicios.crear_lista(self.necesidad, fecha=self.fecha, actor=self.admin, motivo=MOTIVO)
        nueva = cierre_servicios.anular_lista(nueva, actor=self.admin, motivo=MOTIVO)
        self.assertEqual(nueva.estado, "anulada")
        self.assertFalse(nueva.cierres.exists())

    def test_archivo_no_se_edita_ni_elimina(self):
        self.cerrar()
        cierre = self.lista_actual.cierres.get()
        for operacion in [lambda: cierre.save(), lambda: cierre.delete(),
                          lambda: CierreListaElegibles.objects.filter(pk=cierre.pk).update(motivo="Otro"),
                          lambda: CierreListaElegibles.objects.filter(pk=cierre.pk).delete()]:
            with self.assertRaises(ValidationError):
                operacion()

    def test_precarga_solo_cerrada_completa_e_invita_solo_a_elegidos(self):
        with self.assertRaises(ValidationError):
            preparar_cotizacion(self.lista_actual, actor=self.admin)
        p2 = tests_decision.DecisionElegiblesTests.agregar(self)
        self.calificar({p2.pk: 3})
        self.decidir()
        self.cerrar()
        original = self.lista_actual.resultado_cierre["necesidad"]["objeto"]
        Necesidad.objects.filter(pk=self.necesidad.pk).update(objeto="Cambio posterior")
        datos = preparar_cotizacion(self.lista_actual, actor=self.admin)
        self.assertEqual(datos["necesidad"]["objeto"], original)
        self.assertEqual(len(datos["invitados"]), 1)
        self.assertEqual(datos["invitados"][0]["proveedor"], self.p1.proveedor_id)

    def test_vistas_transiciones_estado_necesidades_y_precarga(self):
        self.client.force_login(self.admin)
        detalle = reverse("compras:lista_detalle", args=[self.lista_actual.pk])
        self.assertNotContains(self.client.get(detalle), "Iniciar cotización")
        respuesta = self.client.post(reverse("compras:lista_cerrar", args=[self.lista_actual.pk]),
            {"cierre-motivo": MOTIVO, "cierre-justificacion_documental": MOTIVO})
        self.assertRedirects(respuesta, detalle)
        self.assertContains(self.client.get(detalle), "Iniciar cotización")
        self.assertContains(self.client.get(reverse("compras:necesidades")), "Cerrada")
        preparar = reverse("compras:cotizacion_iniciar", args=[self.lista_actual.pk])
        self.assertContains(self.client.get(preparar), "La cotización aún no se ha creado")
        self.assertEqual(self.client.post(preparar, {}).status_code, 405)
        cierre = CierreListaElegibles.objects.get(lista=self.lista_actual)
        historial = reverse("compras:lista_cierre_detalle", args=[self.lista_actual.pk, cierre.pk])
        self.assertContains(self.client.get(historial), "Cierre histórico")
        nueva = servicios.crear_lista(self.necesidad, fecha=self.fecha, actor=self.admin, motivo=MOTIVO)
        self.assertEqual(self.client.get(reverse("compras:lista_cierre_detalle", args=[nueva.pk, cierre.pk])).status_code, 404)
        self.assertRedirects(self.client.post(reverse("compras:lista_reabrir", args=[self.lista_actual.pk]), {"reapertura-motivo": MOTIVO}), detalle)
        self.assertRedirects(self.client.post(reverse("compras:lista_anular", args=[self.lista_actual.pk]), {"anulacion-motivo": MOTIVO}), detalle)
        self.assertContains(self.client.get(reverse("compras:necesidades")), "Anulada")

    def test_permisos_metodos_csrf_y_motivos(self):
        urls = [reverse(f"compras:lista_{accion}", args=[self.lista_actual.pk]) for accion in ("cerrar", "reabrir", "anular")]
        preparar = reverse("compras:cotizacion_iniciar", args=[self.lista_actual.pk])
        for usuario in [self.coordinador, self.usuario_proveedor]:
            self.client.force_login(usuario)
            for url in urls + [preparar]:
                self.assertEqual(self.client.get(url).status_code, 403)
                self.assertEqual(self.client.post(url, {}).status_code, 403)
        self.client.force_login(self.dev)
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 405)
        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(self.admin)
        self.assertEqual(cliente.post(urls[0], {"cierre-motivo": MOTIVO}).status_code, 403)
        for operacion in [cierre_servicios.cerrar_lista, cierre_servicios.reabrir_lista, cierre_servicios.anular_lista]:
            for usuario in [self.coordinador, self.usuario_proveedor, AnonymousUser()]:
                with self.assertRaises(PermissionDenied):
                    operacion(self.lista_actual, actor=usuario, motivo=MOTIVO)
            with self.assertRaises(ValidationError):
                operacion(self.lista_actual, actor=self.admin, motivo=" ")
        with self.assertRaises(PermissionDenied):
            preparar_cotizacion(self.lista_actual, actor=self.usuario_proveedor)
