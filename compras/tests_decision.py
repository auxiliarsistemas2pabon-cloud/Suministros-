from decimal import Decimal
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client, TestCase
from django.urls import reverse
from openpyxl import load_workbook

from bitacora.models import RegistroBitacora
from bitacora.servicios import guardar_con_bitacora
from compras import calificacion_servicios, decision_servicios as decisiones, servicios, tests_calificacion
from compras.models import DecisionElegibles, ListaElegibles, Necesidad
from proveedores.tests.utilidades import crear_proveedor
from proyecciones import servicios as proyecciones_servicios, tests_revision

MOTIVO = "Decisión ficticia documentada para la prueba"


class DecisionElegiblesTests(TestCase):
    def setUp(self):
        tests_calificacion.CalificacionElegiblesTests.setUp(self)
        tests_calificacion.CalificacionElegiblesTests.publicar(self)
        decisiones.definir_cantidad(self.necesidad, cantidad_base=Decimal(10), unidad_base="cajas", actor=self.admin, motivo=MOTIVO)
        self.lista_actual = tests_calificacion.CalificacionElegiblesTests.lista(self)
        self.p1 = self.lista_actual.participantes.get()
        self.calificar()

    def agregar(self):
        return servicios.agregar_participante(self.lista_actual, crear_proveedor(), actor=self.admin, motivo=MOTIVO)

    def calificar(self, valores=None):
        valores = valores or {}
        celdas = [{"participante": p.pk, "criterio": c.pk, "cumplimiento": Decimal(valores.get(p.pk, 5)), "observacion": ""}
                  for p in self.lista_actual.participantes.filter(activo=True) for c in self.version.criterios.all()]
        calificacion_servicios.guardar_matriz(self.lista_actual, celdas, actor=self.admin, motivo=MOTIVO)

    def asignaciones(self, cantidades=None, justificaciones=None):
        cantidades, justificaciones = cantidades or {}, justificaciones or {}
        return [{"participante": p.pk, "cantidad_autorizada": cantidades.get(p.pk, "0"), "observacion": "Observación ficticia",
                 "justificacion_eleccion": justificaciones.get(p.pk, "")} for p in self.lista_actual.participantes.filter(activo=True)]

    def decidir(self, cantidades=None, justificaciones=None, **cambios):
        datos = dict(justificacion_unico=MOTIVO, actor=self.admin, motivo=MOTIVO)
        datos.update(cambios)
        return decisiones.guardar_decision(self.lista_actual, self.asignaciones(cantidades or {self.p1.pk: "1"}, justificaciones), **datos)

    def test_puestos_densos_empates_y_pendientes(self):
        p2, p3 = self.agregar(), self.agregar()
        self.calificar({p3.pk: 3})
        resultado = decisiones.obtener_puestos(self.lista_actual)
        filas = {f["participante"].pk: f for f in resultado["filas"]}
        self.assertEqual([filas[p.pk]["puesto"] for p in [self.p1, p2, p3]], [1, 1, 2])
        self.assertTrue(filas[self.p1.pk]["empate"])
        self.assertFalse(filas[p3.pk]["empate"])
        p4 = self.agregar()
        fila = next(f for f in decisiones.obtener_puestos(self.lista_actual)["filas"] if f["participante"].pk == p4.pk)
        self.assertIsNone(fila["puesto"])
        with self.assertRaises(ValidationError):
            self.decidir()

    def test_desempate_manual_justificado_y_restablecimiento_auditados(self):
        p2, p3 = self.agregar(), self.agregar()
        self.calificar({p3.pk: 3})
        with self.assertRaises(ValidationError):
            decisiones.guardar_desempate(self.lista_actual, orden=[p2.pk, self.p1.pk], justificacion=" ", actor=self.admin, motivo=MOTIVO)
        desempate = decisiones.guardar_desempate(self.lista_actual, orden=[p2.pk, self.p1.pk], justificacion="Mayor disponibilidad ficticia", actor=self.dev, motivo=MOTIVO)
        filas = {f["participante"].pk: f for f in decisiones.obtener_puestos(self.lista_actual)["filas"]}
        self.assertEqual([filas[p.pk]["puesto"] for p in [self.p1, p2, p3]], [2, 1, 3])
        self.assertEqual([filas[p.pk]["puesto_calculado"] for p in [self.p1, p2, p3]], [1, 1, 2])
        self.assertEqual(desempate.registrado_por, self.dev)
        self.assertTrue(RegistroBitacora.objects.filter(accion="elegibles.desempate_registrado", actor=self.dev).exists())
        decisiones.restablecer_empate(self.lista_actual, desempate, actor=self.admin, motivo=MOTIVO)
        self.assertEqual([f["puesto"] for f in decisiones.obtener_puestos(self.lista_actual)["filas"]], [1, 1, 2])

    def test_orden_invalido_ajeno_o_repetido_rechazado(self):
        p2, p3 = self.agregar(), self.agregar()
        self.calificar({p3.pk: 3})
        for orden in [[self.p1.pk, self.p1.pk], [self.p1.pk, p3.pk], [p2.pk], [True, p2.pk]]:
            with self.subTest(orden=orden), self.assertRaises(ValidationError):
                decisiones.guardar_desempate(self.lista_actual, orden=orden, justificacion=MOTIVO, actor=self.admin, motivo=MOTIVO)
        self.assertFalse(self.lista_actual.desempates.exists())

    def test_eleccion_fuera_del_primer_puesto_exige_justificacion_y_actor_fecha(self):
        p2 = self.agregar()
        self.calificar({p2.pk: 3})
        antes = RegistroBitacora.objects.count()
        with self.assertRaises(ValidationError):
            self.decidir({p2.pk: "2"})
        self.assertEqual(RegistroBitacora.objects.count(), antes)
        p2.refresh_from_db()
        self.assertEqual(p2.cantidad_autorizada, 0)
        registro = self.decidir({p2.pk: "2"}, {p2.pk: "Entrega inmediata ficticia"})
        p2.refresh_from_db()
        self.assertEqual(p2.cantidad_autorizada, 2)
        self.assertEqual(p2.decision_por, self.admin)
        self.assertEqual(p2.decision_fecha, registro.fecha)
        self.assertEqual(p2.justificacion_eleccion, "Entrega inmediata ficticia")
        self.assertTrue(decisiones.estado_decision(self.lista_actual)["vigente"])

    def test_proveedor_unico_sin_justificacion_bloquea_decision_y_validacion_para_cierre(self):
        with self.assertRaises(ValidationError):
            self.decidir(justificacion_unico=" ")
        with self.assertRaises(ValidationError):
            decisiones.validar_para_cierre(self.lista_actual)
        self.decidir()
        self.assertTrue(decisiones.validar_para_cierre(self.lista_actual)["completa"])
        self.lista_actual.refresh_from_db()
        self.assertEqual(self.lista_actual.estado, "borrador")

    def test_cantidades_decimales_suma_y_excepcion_explicita(self):
        p2 = self.agregar()
        self.calificar()
        self.decidir({self.p1.pk: "0.125", p2.pk: "9.875"})
        self.assertEqual(decisiones.estado_decision(self.lista_actual)["total_autorizado"], Decimal("10.000"))
        with self.assertRaises(ValidationError):
            self.decidir({self.p1.pk: "10", p2.pk: "0.001"})
        decision = self.decidir({self.p1.pk: "10", p2.pk: "0.001"}, justificacion_cantidad="Ampliación ficticia expresamente justificada")
        self.assertEqual(decisiones.estado_decision(self.lista_actual)["total_autorizado"], Decimal("10.001"))
        self.assertTrue(decision.justificacion_cantidad)
        for valor in ["-1", "NaN", "Infinity", "0.0001", 1.0, True]:
            with self.subTest(valor=valor), self.assertRaises(ValidationError):
                self.decidir({self.p1.pk: valor})

    def test_cantidad_no_definida_y_asignacion_cero_no_permiten_decision(self):
        with self.assertRaises(ValidationError):
            self.decidir({self.p1.pk: "0"})
        Necesidad.objects.filter(pk=self.necesidad.pk).update(cantidad_base=None, unidad_base="")
        with self.assertRaises(ValidationError):
            self.decidir()
        self.assertFalse(DecisionElegibles.objects.exists())

    def test_editar_calificacion_invalida_decision_y_desempate_pero_no_un_guardado_sin_cambios(self):
        p2 = self.agregar()
        self.calificar()
        desempate = decisiones.guardar_desempate(self.lista_actual, orden=[self.p1.pk, p2.pk], justificacion=MOTIVO, actor=self.admin, motivo=MOTIVO)
        self.decidir()
        self.calificar()
        self.assertTrue(decisiones.estado_decision(self.lista_actual)["vigente"])
        self.calificar({p2.pk: 3})
        self.assertFalse(decisiones.estado_decision(self.lista_actual)["vigente"])
        desempate.refresh_from_db()
        self.assertFalse(desempate.activo)
        with self.assertRaises(ValidationError):
            decisiones.validar_para_cierre(self.lista_actual)
        self.assertTrue(RegistroBitacora.objects.filter(accion="elegibles.decision_invalidada").exists())

    def test_altas_retiros_y_reactivaciones_exigen_revisar_decision(self):
        self.decidir()
        p2 = self.agregar()
        self.assertFalse(decisiones.estado_decision(self.lista_actual)["vigente"])
        self.calificar()
        self.decidir()
        servicios.quitar_participante(self.lista_actual, p2, actor=self.admin, motivo=MOTIVO)
        self.assertFalse(decisiones.estado_decision(self.lista_actual)["vigente"])
        self.decidir()
        servicios.agregar_participante(self.lista_actual, p2.proveedor, actor=self.admin, motivo=MOTIVO)
        self.assertFalse(decisiones.estado_decision(self.lista_actual)["vigente"])

    def test_cambio_base_invalida_decision_y_se_bloquea_si_hay_lista_cerrada(self):
        self.decidir()
        decisiones.definir_cantidad(self.necesidad, cantidad_base=Decimal("12.5"), unidad_base="cajas", actor=self.admin, motivo=MOTIVO)
        self.assertFalse(decisiones.estado_decision(self.lista_actual)["vigente"])
        ListaElegibles.objects.filter(pk=self.lista_actual.pk).update(estado="cerrada")
        with self.assertRaises(ValidationError):
            decisiones.definir_cantidad(self.necesidad, cantidad_base=Decimal(15), unidad_base="cajas", actor=self.admin, motivo=MOTIVO)
        self.necesidad.refresh_from_db()
        self.assertEqual(self.necesidad.cantidad_base, Decimal("12.5"))

    def test_ajenos_estados_y_permisos_de_servicios(self):
        p2 = self.agregar()
        self.calificar()
        desempate = decisiones.guardar_desempate(self.lista_actual, orden=[self.p1.pk, p2.pk], justificacion=MOTIVO, actor=self.admin, motivo=MOTIVO)
        operaciones = [
            lambda actor, motivo: decisiones.definir_cantidad(self.necesidad, cantidad_base=Decimal(1), unidad_base="lote", actor=actor, motivo=motivo),
            lambda actor, motivo: decisiones.guardar_desempate(self.lista_actual, orden=[self.p1.pk, p2.pk], justificacion=MOTIVO, actor=actor, motivo=motivo),
            lambda actor, motivo: decisiones.restablecer_empate(self.lista_actual, desempate, actor=actor, motivo=motivo),
            lambda actor, motivo: decisiones.guardar_decision(self.lista_actual, self.asignaciones({self.p1.pk: "1"}), actor=actor, motivo=motivo),
        ]
        for operacion in operaciones:
            for actor in [self.coordinador, self.usuario_proveedor, AnonymousUser()]:
                with self.assertRaises(PermissionDenied):
                    operacion(actor, MOTIVO)
            with self.assertRaises(ValidationError):
                operacion(self.admin, " ")
        for estado in ["cerrada", "anulada"]:
            ListaElegibles.objects.filter(pk=self.lista_actual.pk).update(estado=estado)
            for operacion in operaciones:
                with self.assertRaises(ValidationError):
                    operacion(self.admin, MOTIVO)

    def test_fallo_auditoria_revierte_asignaciones_y_decision(self):
        def fallo(instancia, *args, **kwargs):
            if isinstance(instancia, DecisionElegibles):
                raise RuntimeError("Fallo simulado al registrar decisión")
            return guardar_con_bitacora(instancia, *args, **kwargs)
        antes = RegistroBitacora.objects.count()
        with patch("compras.decision_servicios.guardar_con_bitacora", side_effect=fallo):
            with self.assertRaises(RuntimeError):
                self.decidir()
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.cantidad_autorizada, 0)
        self.assertIsNone(self.p1.decision_fecha)
        self.assertFalse(DecisionElegibles.objects.exists())
        self.assertEqual(RegistroBitacora.objects.count(), antes)

    def test_excel_valores_formatos_y_texto_sin_formulas(self):
        self.p1.razon_social = "=1+1"
        self.p1.save()
        self.decidir({self.p1.pk: "2.5"})
        self.client.force_login(self.admin)
        respuesta = self.client.get(reverse("compras:lista_exportar", args=[self.lista_actual.pk]))
        self.assertEqual(respuesta.status_code, 200)
        libro = load_workbook(BytesIO(respuesta.content))
        self.addCleanup(libro.close)
        hoja = libro["Elegibles"]
        self.assertEqual(hoja["A9"].value, self.p1.nit)
        self.assertEqual(hoja["B9"].value, "=1+1")
        self.assertEqual(hoja["B9"].data_type, "s")
        self.assertEqual(hoja["C9"].value, 5)
        self.assertEqual(hoja["F9"].value, 1)
        self.assertEqual(hoja["H9"].value, 2.5)
        self.assertEqual(hoja["H9"].number_format, "0.000")
        self.assertEqual(hoja.freeze_panes, "A9")
        self.assertEqual(hoja["A8"].fill.fgColor.rgb[-6:], "172554")
        self.assertEqual(libro["Calificaciones"]["F2"].value, 1.5)
        self.assertFalse(any(c.data_type == "f" for h in libro for fila in h for c in fila))
        self.assertTrue(RegistroBitacora.objects.filter(accion="elegibles.exportados", actor=self.admin).exists())

    def test_formulario_decision_y_revision_de_datos_modificados(self):
        self.client.force_login(self.admin)
        url = reverse("compras:lista_decision", args=[self.lista_actual.pk])
        respuesta = self.client.get(url)
        self.assertEqual(respuesta.status_code, 200)
        formulario = respuesta.context["formulario"]
        datos = {"revision": formulario["revision"].value(), "motivo": MOTIVO, "justificacion_unico": MOTIVO}
        for _, clave in formulario.asignaciones:
            datos[clave + "_cantidad"] = "2"
        self.assertRedirects(self.client.post(url, datos), url)
        self.calificar({self.p1.pk: 3})
        respuesta = self.client.post(url, datos)
        self.assertContains(respuesta, "Recargue la decisión")
        self.assertFalse(decisiones.estado_decision(self.lista_actual)["vigente"])

    def test_desempate_desde_selectores_y_vistas_protegidas(self):
        p2 = self.agregar()
        self.calificar()
        self.client.force_login(self.dev)
        respuesta = self.client.post(reverse("compras:lista_desempatar", args=[self.lista_actual.pk]),
            {"total": "5.0000", "puesto_1": p2.pk, "puesto_2": self.p1.pk, "justificacion": MOTIVO, "motivo": MOTIVO})
        self.assertEqual(respuesta.status_code, 302)
        desempate = self.lista_actual.desempates.get()
        self.assertEqual(desempate.orden, [p2.pk, self.p1.pk])
        lecturas = [reverse("compras:lista_decision", args=[self.lista_actual.pk]), reverse("compras:lista_exportar", args=[self.lista_actual.pk]),
                    reverse("compras:necesidad_cantidad", args=[self.necesidad.pk])]
        escrituras = [reverse("compras:lista_desempatar", args=[self.lista_actual.pk]),
                      reverse("compras:lista_restablecer_empate", args=[self.lista_actual.pk, desempate.pk])]
        for usuario in [self.coordinador, self.usuario_proveedor]:
            self.client.force_login(usuario)
            for url in lecturas + escrituras:
                self.assertEqual(self.client.get(url).status_code, 403)
                self.assertEqual(self.client.post(url, {}).status_code, 403)
        for usuario in [self.admin, self.dev]:
            self.client.force_login(usuario)
            for url in lecturas:
                self.assertEqual(self.client.get(url).status_code, 200)
            for url in escrituras:
                self.assertEqual(self.client.get(url).status_code, 405)
        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(self.admin)
        self.assertEqual(cliente.post(lecturas[0], {}).status_code, 403)


class CantidadesOrigenTests(TestCase):
    def setUp(self):
        tests_revision.BaseRevision.setUp(self)

    def crear_necesidad(self):
        proyecciones_servicios.aprobar_proyeccion(self.proyeccion, actor=self.administrador, motivo=MOTIVO)
        return servicios.crear_necesidad(objeto="Agrupación ficticia", area=self.area, fecha=self.periodo.fecha_apertura,
            lineas=[(self.linea.pk, "1.125"), (self.linea_dos.pk, "3.875")], actor=self.administrador, motivo=MOTIVO)

    def test_origenes_de_la_misma_unidad_se_suman_con_decimal(self):
        necesidad = self.crear_necesidad()
        base = decisiones.cantidad_necesidad(necesidad)
        self.assertEqual(base["cantidad"], Decimal("5.000"))
        self.assertEqual(base["unidad"], str(self.unidad))

    def test_unidades_distintas_requieren_base_explicita(self):
        self.linea_dos.unidad = self.otra_unidad
        self.linea_dos.save()
        necesidad = self.crear_necesidad()
        self.assertIsNone(decisiones.cantidad_necesidad(necesidad)["cantidad"])
        necesidad = decisiones.definir_cantidad(necesidad, cantidad_base=Decimal(1), unidad_base="lote", actor=self.administrador, motivo=MOTIVO)
        self.assertEqual(decisiones.cantidad_necesidad(necesidad)["cantidad"], 1)
        self.assertEqual(necesidad.origenes.count(), 2)
