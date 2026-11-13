import json
from copy import deepcopy
from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse

from cuentas.models import Rol
from cuentas.tests.utilidades import crear_usuario
from parametros import servicios as parametros
from parametros.catalogo import REGLAS_FR14, REGLAS_FR14_DEFECTO, validar_reglas_fr14
from parametros.models import Parametro
from proveedores import matrices_servicios
from proveedores.evaluacion import calcular_evaluacion
from proveedores.evaluacion_servicios import finalizar_evaluacion, obtener_resultado
from proveedores.models import RespuestaEvaluacion
from proveedores.respuestas_servicios import guardar_respuesta
from proveedores.tests import test_matrices
from proveedores.tests.utilidades import MOTIVO


class CalculoPuroTests(SimpleTestCase):
    def calcular(self, respuestas, **cambios):
        reglas = {**json.loads(REGLAS_FR14_DEFECTO), **cambios}
        filas = [{"grupo": "calidad", "peso": peso, "respuesta": respuesta} for peso, respuesta in respuestas]
        copia = deepcopy(filas)
        resultado = calcular_evaluacion(filas, reglas)
        self.assertEqual(filas, copia)
        return resultado

    def test_todo_si_todo_no_y_pesos_diferentes(self):
        for respuesta, puntos, porcentaje, nota in (("si", "3", "100.00", 5), ("no", "0", "0.00", 1)):
            resultado = self.calcular([(1, respuesta), (2, respuesta)])
            self.assertEqual((resultado["puntos"], resultado["maximo"], resultado["porcentaje"], resultado["calificacion"]), (puntos, "3", porcentaje, nota))

    def test_hoja_validada_pendiente_de_entrega_por_negocio(self):
        # Caso fijo provisional; reemplazar por la hoja validada que entregue la clínica.
        resultado = self.calcular([(2, "si"), (1, "no"), (2, "na")])
        self.assertEqual(resultado["puntos"], "2")
        self.assertEqual(resultado["maximo"], "3")
        self.assertEqual(resultado["porcentaje"], "66.67")
        self.assertEqual(resultado["calificacion"], 3)
        self.assertEqual(resultado["lineas"][2]["maximo"], "0")
        grupos = calcular_evaluacion([
            {"grupo": "calidad", "peso": 2, "respuesta": "si"},
            {"grupo": "ambiental", "peso": 1, "respuesta": "no"},
            {"grupo": "sgsst", "peso": 2, "respuesta": "na"},
        ], json.loads(REGLAS_FR14_DEFECTO))["grupos"]
        self.assertEqual([g["puntos"] for g in grupos], ["2", "0", "0"])
        self.assertEqual([g["maximo"] for g in grupos], ["2", "1", "0"])

    def test_todo_na_y_sin_respuestas_no_finalizables(self):
        resultado = self.calcular([(1, "na"), (2, "na")])
        self.assertIsNone(resultado["porcentaje"])
        self.assertIsNone(resultado["calificacion"])
        self.assertFalse(resultado["finalizable"])
        self.assertFalse(self.calcular([(1, None)])["finalizable"])
        self.assertFalse(self.calcular([])["finalizable"])

    def test_reglas_alternativas_decimales_y_limites_de_umbrales(self):
        resultado = self.calcular([(2, "si"), (2, "no"), (1, "na")], si="0.5", no="0.25", excluir_na=False)
        self.assertEqual(Decimal(resultado["puntos"]), Decimal("1.50"))
        self.assertEqual(resultado["maximo"], "5")
        self.assertEqual(resultado["porcentaje"], "30.00")
        for umbral, esperado in (("66.67", 5), ("66.68", 3)):
            self.assertEqual(self.calcular([(2, "si"), (1, "no")], umbral5=umbral)["calificacion"], esperado)

    def test_rechaza_parametros_incoherentes_o_no_finitos(self):
        for cambios in ({"si": "NaN"}, {"no": "-1"}, {"umbral3": "90", "umbral5": "80"}, {"umbral5": "101"}, {"pendiente": "false"}, {"si": 0.5}):
            with self.subTest(cambios=cambios), self.assertRaises(ValidationError):
                validar_reglas_fr14(json.dumps({**json.loads(REGLAS_FR14_DEFECTO), **cambios}))


class FinalizacionTests(TestCase):
    def setUp(self):
        test_matrices.MatricesTests.setUp(self)
        matrices_servicios.publicar_version(self.version, desde=self.fecha, actor=self.admin, motivo=MOTIVO)
        self.ev = matrices_servicios.crear_evaluacion(self.proveedor, self.categoria, self.fecha, actor=self.admin, motivo=MOTIVO)
        self.url = reverse("proveedores:evaluacion_finalizar", args=[self.ev.pk])

    def responder(self, valor="si"):
        return guardar_respuesta(self.ev, self.req, respuesta=valor, observacion="Justificado", confirma_na=valor == "na", actor=self.admin, motivo=MOTIVO)

    def test_resultado_conservado_tras_cambiar_umbrales_y_matriz(self):
        self.responder()
        finalizada = finalizar_evaluacion(self.ev, actor=self.admin, motivo=MOTIVO)
        foto = deepcopy(finalizada.resultado)
        parametro = Parametro.objects.get(clave=REGLAS_FR14)
        reglas = {**json.loads(REGLAS_FR14_DEFECTO), "umbral3": "10", "umbral5": "20", "si": "0", "pendiente": False}
        parametros.cambiar_valor(parametro, json.dumps(reglas), actor=self.admin, motivo=MOTIVO)
        copia = matrices_servicios.copiar_version(self.version, actor=self.admin, motivo=MOTIVO)
        matrices_servicios.publicar_version(copia, desde=self.fecha.replace(month=2), actor=self.admin, motivo=MOTIVO)
        finalizada.refresh_from_db()
        self.assertEqual(obtener_resultado(finalizada), foto)
        self.assertEqual(foto["calificacion"], 5)
        self.assertEqual(finalizada.finalizada_por, self.admin)
        self.assertTrue(finalizada.fecha_finalizacion)

    def test_finalizar_bloquea_correccion_y_repeticion(self):
        respuesta = self.responder()
        finalizar_evaluacion(self.ev, actor=self.admin, motivo=MOTIVO)
        for operacion in (lambda: self.responder("no"), lambda: respuesta.save(),
                          lambda: RespuestaEvaluacion.objects.filter(pk=respuesta.pk).update(respuesta="no"),
                          lambda: finalizar_evaluacion(self.ev, actor=self.admin, motivo=MOTIVO)):
            with self.assertRaises(ValidationError):
                operacion()

    def test_incompleta_y_todo_na_se_bloquean(self):
        with self.assertRaises(ValidationError):
            finalizar_evaluacion(self.ev, actor=self.admin, motivo=MOTIVO)
        self.responder("na")
        with self.assertRaises(ValidationError):
            finalizar_evaluacion(self.ev, actor=self.admin, motivo=MOTIVO)
        self.ev.refresh_from_db()
        self.assertEqual(self.ev.estado, "borrador")

    def test_fallo_auditoria_revierte_finalizacion(self):
        self.responder()
        with patch("proveedores.evaluacion_servicios.registrar", side_effect=RuntimeError("Fallo simulado")), self.assertRaises(RuntimeError):
            finalizar_evaluacion(self.ev, actor=self.admin, motivo=MOTIVO)
        self.ev.refresh_from_db()
        self.assertEqual(self.ev.estado, "borrador")
        self.assertEqual(self.ev.resultado, {})

    def test_permisos_post_csrf_y_resultado_en_pantalla(self):
        self.responder()
        for rol in (Rol.COORDINADOR, Rol.PROVEEDOR):
            actor = crear_usuario(rol)
            self.client.force_login(actor)
            self.assertEqual(self.client.get(self.url).status_code, 403)
            self.assertEqual(self.client.post(self.url, {"motivo": MOTIVO}).status_code, 403)
            with self.assertRaises(PermissionDenied):
                finalizar_evaluacion(self.ev, actor=actor, motivo=MOTIVO)
        self.client.logout()
        self.assertEqual(self.client.post(self.url).status_code, 302)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.url).status_code, 405)
        protegido = Client(enforce_csrf_checks=True)
        protegido.force_login(self.admin)
        self.assertEqual(protegido.post(self.url, {"motivo": MOTIVO}).status_code, 403)
        self.assertEqual(self.client.post(self.url, {"motivo": MOTIVO}).status_code, 302)
        detalle = self.client.get(reverse("proveedores:evaluacion_detalle", args=[self.ev.pk]))
        self.assertContains(detalle, "100.00")
        self.assertContains(detalle, "pendientes de aprobación")
