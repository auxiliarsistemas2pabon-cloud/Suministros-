from copy import deepcopy
from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError, PermissionDenied
from django.test import SimpleTestCase, TestCase, Client
from django.urls import reverse

from bitacora.models import RegistroBitacora
from compras import orden_servicios, tests_ordenes, numeracion_ordenes
from compras.importes_orden import calcular_orden
from compras.models import TipoRetencion, TarifaImpuesto, ContadorOrdenCompra
from compras.orden_forms import FormularioOrden
from compras.retencion_views import guardar_retencion
from parametros.catalogo import DECIMALES_ORDEN, DESCUENTO_ORDEN, NIVEL_REDONDEO_ORDEN
from parametros.models import Parametro
from parametros.servicios import cambiar_valor

REGLAS = {"decimales": 2, "modo": "ROUND_HALF_UP", "orden_descuento": "antes_impuesto", "nivel_redondeo": "linea"}
MOTIVO = "Ejemplo ficticio de cálculo pendiente de validar con financiera"


class MotorImportesOrdenTests(SimpleTestCase):
    def linea(self, precio="100", descuento="0", porcentaje="19", cantidad="1"):
        return dict(cantidad=cantidad, precio_unitario=precio, descuento=descuento, porcentaje=porcentaje)

    def test_tabla_fija_pendiente_de_validar_con_financiera(self):
        casos = [
            ("gravada", [self.linea()], {}, (), ("100", "0", "100", "19", "0", "119")),
            ("exenta", [self.linea(porcentaje="0")], {}, (), ("100", "0", "100", "0", "0", "100")),
            ("descuento antes", [self.linea(descuento="10")], {}, (), ("100", "10", "90", "17.10", "0", "107.10")),
            ("descuento después", [self.linea(descuento="10")], {"orden_descuento": "despues_impuesto"}, (), ("100", "10", "90", "19", "0", "109")),
            ("mixta", [self.linea(descuento="10"), self.linea(precio="50", porcentaje="0")], {}, (), ("150", "10", "140", "17.10", "0", "157.10")),
            ("mínimo inclusivo", [self.linea(descuento="10")], {}, ({"nombre": "Ficticia", "porcentaje": "2.5", "base_minima": "90"},), ("100", "10", "90", "17.10", "2.25", "104.85")),
            ("bajo mínimo", [self.linea(descuento="10")], {}, ({"nombre": "Ficticia", "porcentaje": "2.5", "base_minima": "90.01"},), ("100", "10", "90", "17.10", "0", "107.10")),
        ]
        for nombre, lineas, cambios, retenciones, esperado in casos:
            with self.subTest(nombre=nombre):
                resultado = calcular_orden(lineas, {**REGLAS, **cambios}, retenciones)
                self.assertEqual(tuple(resultado[k] for k in ("subtotal", "descuento", "base", "impuesto", "retencion", "total")), tuple(map(Decimal, esperado)))

    def test_redondeo_linea_o_total_distribuye_residuos_y_empata_por_posicion(self):
        lineas = [self.linea(precio="0.005", porcentaje="0") for _ in range(3)]
        por_linea = calcular_orden(lineas, REGLAS)
        total = calcular_orden(lineas, {**REGLAS, "nivel_redondeo": "total"})
        self.assertEqual(por_linea["total"], Decimal("0.03"))
        self.assertEqual(total["total"], Decimal("0.02"))
        self.assertEqual([l["total"] for l in total["lineas"]], [Decimal(".01"), Decimal(".01"), 0])
        self.assertEqual(sum(l["total"] for l in total["lineas"]), total["total"])

    def test_total_descuento_completo_nunca_asigna_base_negativa(self):
        lineas = [self.linea(precio="0.006", descuento="0.006", porcentaje="0"), self.linea(precio="0.004", descuento="0.004", porcentaje="0")]
        for modo in ("ROUND_HALF_UP", "ROUND_HALF_EVEN", "ROUND_UP", "ROUND_DOWN"):
            resultado = calcular_orden(lineas, {**REGLAS, "modo": modo, "nivel_redondeo": "total"})
            self.assertEqual(resultado["total"], 0)
            self.assertTrue(all(l["base"] >= 0 for l in resultado["lineas"]))

    def test_modos_y_decimales(self):
        for modo, esperado in (("ROUND_HALF_UP", ".13"), ("ROUND_HALF_EVEN", ".12"), ("ROUND_DOWN", ".12"), ("ROUND_UP", ".13")):
            self.assertEqual(calcular_orden([self.linea(precio=".125", porcentaje="0")], {**REGLAS, "modo": modo})["total"], Decimal(esperado))
        self.assertEqual(calcular_orden([self.linea(precio=".125", porcentaje="0")], {**REGLAS, "decimales": 1})["total"], Decimal(".1"))

    def test_bases_retencion_bruta_neta_y_con_impuestos(self):
        tipos = [{"nombre": base, "porcentaje": "1", "base_calculo": base} for base in ("subtotal", "base_neta", "total_con_impuestos")]
        resultado = calcular_orden([self.linea(descuento="10")], REGLAS, tipos)
        self.assertEqual([Decimal(r["importe"]) for r in resultado["retenciones_aplicadas"]], [Decimal("1"), Decimal(".9"), Decimal("1.07")])
        self.assertEqual(resultado["total"], Decimal("104.13"))

    def test_rechaza_valores_no_finitos_float_negativos_y_descuentos_excesivos(self):
        for campo, valor in (("precio_unitario", 0.1), ("cantidad", True), ("cantidad", 0), ("precio_unitario", "NaN"), ("precio_unitario", "Infinity"), ("precio_unitario", "1e100"), ("descuento", -1), ("descuento", "101"), ("porcentaje", 101)):
            with self.subTest(campo=campo, valor=valor), self.assertRaises(ValidationError):
                calcular_orden([{**self.linea(), campo: valor}], REGLAS)
        with self.assertRaises(ValidationError):
            calcular_orden([self.linea()], REGLAS, [{"nombre": "Excesiva", "porcentaje": "100", "base_calculo": "total_con_impuestos"}] * 2)
        with self.assertRaises(ValidationError):
            calcular_orden([], REGLAS)

    def test_reglas_y_retenciones_invalidas_se_rechazan(self):
        for cambios in ({"decimales": 3}, {"modo": "desconocido"}, {"orden_descuento": "otro"}, {"nivel_redondeo": "otro"}):
            with self.subTest(cambios=cambios), self.assertRaises(ValidationError):
                calcular_orden([self.linea()], {**REGLAS, **cambios})
        for cambios in ({"porcentaje": 101}, {"porcentaje": "NaN"}, {"base_minima": -1}, {"base_calculo": "otro"}):
            with self.subTest(cambios=cambios), self.assertRaises(ValidationError):
                calcular_orden([self.linea()], REGLAS, [{"nombre": "Ficticia", "porcentaje": 1, **cambios}])

    def test_totales_grandes_con_lineas_sin_limite_de_negocio_conservan_precision(self):
        from types import SimpleNamespace
        from compras.orden_calculo_servicios import aplicar
        lineas = [self.linea(cantidad="10000000000", precio="10000000000000", porcentaje="0") for _ in range(2000)]
        resultado = calcular_orden(lineas, REGLAS)
        orden = SimpleNamespace(reglas_importes=REGLAS)
        aplicar(orden, [SimpleNamespace() for _ in lineas], resultado)
        self.assertEqual(orden.total, Decimal("200000000000000000000000000.00"))


class ImportesOrdenTests(TestCase):
    setUp = tests_ordenes.OrdenesTests.setUp
    calificar = tests_ordenes.OrdenesTests.calificar
    asignaciones = tests_ordenes.OrdenesTests.asignaciones
    decidir = tests_ordenes.OrdenesTests.decidir
    ofertar = tests_ordenes.OrdenesTests.ofertar
    proponer = tests_ordenes.OrdenesTests.proponer
    aprobar = tests_ordenes.OrdenesTests.aprobar
    crear = tests_ordenes.OrdenesTests.crear
    guardar = tests_ordenes.OrdenesTests.guardar

    def retencion(self, **cambios):
        tipo = TipoRetencion(nombre="Retención ficticia", porcentaje="10", **cambios)
        guardar_retencion(tipo, actor=self.admin, motivo=MOTIVO)
        return tipo

    def parametro(self, clave, valor):
        cambiar_valor(Parametro.objects.get(clave=clave), valor, actor=self.admin, motivo=MOTIVO)

    def test_descuento_tarifa_retencion_y_original_auditados(self):
        orden, = self.crear()
        originales = [deepcopy(l.original) for l in orden.lineas.all()]
        retencion = self.retencion()
        tarifa = TarifaImpuesto.objects.create(nombre="Ficticia 19", porcentaje=19)
        lineas = list(orden.lineas.all())
        orden = self.guardar(orden, [{"id": lineas[0].pk, "descuento": "2", "tarifa_id": tarifa.pk}, {"id": lineas[1].pk}], retenciones=[retencion.pk])
        self.assertEqual((orden.subtotal, orden.descuento, orden.base, orden.impuesto, orden.retencion, orden.total), (52, 2, 50, 2, 5, 47))
        self.assertEqual([l.original for l in orden.lineas.all()], originales)
        self.assertEqual(orden.revision, 2)
        self.assertEqual(orden.revisiones.first().contenido["retenciones_aplicadas"][0]["porcentaje"], "10.0000")
        self.assertTrue(orden.lineas.first().modificada)
        self.assertTrue(RegistroBitacora.objects.filter(accion="orden.borrador_modificado").exists())

    def test_cambios_catalogo_y_parametros_no_recalculan_hasta_adopcion_explicita(self):
        orden, = self.crear()
        tipo = self.retencion()
        orden = self.guardar(orden, retenciones=[tipo.pk])
        tipo.porcentaje = 20
        guardar_retencion(tipo, actor=self.admin, motivo=MOTIVO)
        self.parametro(DECIMALES_ORDEN, "2")
        orden = self.guardar(orden, condiciones_pago="Otro pago")
        self.assertEqual(orden.retencion, 5)
        self.assertEqual(orden.reglas_importes["decimales"], 0)
        orden = self.guardar(orden, actualizar_reglas=True)
        self.assertEqual(orden.retencion, Decimal("10.40"))
        self.assertEqual(orden.reglas_importes["decimales"], 2)
        self.assertIn("reglas", orden.lineas.first().cambios)

    def test_retencion_inactiva_guardada_se_conserva_pero_no_se_actualiza(self):
        orden, = self.crear()
        tipo = self.retencion()
        orden = self.guardar(orden, retenciones=[tipo.pk])
        tipo.activo = False
        guardar_retencion(tipo, actor=self.admin, motivo=MOTIVO)
        formulario = FormularioOrden(orden=orden)
        self.assertIn(tipo, formulario.fields["retenciones"].queryset)
        orden = self.guardar(orden, condiciones_pago="Conserva foto")
        self.assertEqual(orden.retencion, 5)
        with self.assertRaises(ValidationError):
            self.guardar(orden, actualizar_reglas=True)
        orden = self.guardar(orden, retenciones=[])
        self.assertEqual(orden.total, 52)
        with self.assertRaises(ValidationError):
            self.guardar(orden, retenciones=[tipo.pk])

    def test_fallo_o_descuento_invalido_revierte_todo(self):
        orden, = self.crear()
        ids = list(orden.lineas.values_list("pk", flat=True))
        for descuento in ("100", "-1", "NaN", "1.001"):
            with self.assertRaises(ValidationError):
                self.guardar(orden, [{"id": ids[0], "descuento": descuento}, {"id": ids[1]}])
        with patch("compras.orden_servicios.registrar", side_effect=RuntimeError("Fallo ficticio")), self.assertRaises(RuntimeError):
            self.guardar(orden, [{"id": ids[0], "descuento": "1"}, {"id": ids[1]}])
        orden.refresh_from_db()
        self.assertEqual((orden.total, orden.revision), (52, 1))
        self.assertFalse(orden.lineas.first().modificada)

    def test_foto_emision_congela_impuestos_y_retenciones_y_sigue_inmutable_al_anular(self):
        orden, = self.crear()
        tipo = self.retencion()
        orden = self.guardar(orden, retenciones=[tipo.pk])
        from compras.pruebas_operacion import preparar_numeracion
        preparar_numeracion(orden, self.admin, self.dev)
        tipo.porcentaje = 50
        guardar_retencion(tipo, actor=self.admin, motivo=MOTIVO)
        orden = numeracion_ordenes.numerar_al_emitir(orden, actor=self.admin, motivo=MOTIVO)
        foto = deepcopy(orden.calculo_emision)
        self.assertEqual(foto["retenciones"][0]["porcentaje"], "10.0000")
        self.assertEqual(Decimal(foto["totales"]["total"]), 47)
        with self.assertRaises(ValidationError):
            self.guardar(orden, condiciones_pago="No debe cambiar")
        orden = numeracion_ordenes.anular_orden(orden, actor=self.admin, motivo=MOTIVO)
        self.assertEqual(orden.calculo_emision, foto)

    def test_emision_inconsistente_no_reserva_numero(self):
        orden, = self.crear()
        from compras.pruebas_operacion import preparar_numeracion
        preparar_numeracion(orden, self.admin, self.dev)
        type(orden)._base_manager.filter(pk=orden.pk).update(total=999)
        anterior = ContadorOrdenCompra.objects.get(pk="global").ultimo
        with self.assertRaises(ValidationError):
            numeracion_ordenes.numerar_al_emitir(orden, actor=self.admin, motivo=MOTIVO)
        self.assertEqual(ContadorOrdenCompra.objects.get(pk="global").ultimo, anterior)
        orden.refresh_from_db()
        self.assertIsNone(orden.numero)
        self.assertFalse(orden.calculo_emision)

    def test_catalogo_permisos_csrf_validacion_y_bitacora(self):
        self.assertFalse(TipoRetencion.objects.exists())
        url = reverse("compras:retenciones")
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(url), "No hay retenciones configuradas")
        datos = dict(nombre="Ficticia UI", porcentaje="2.5", base_minima="100", base_calculo="base_neta", activo="on", motivo=MOTIVO)
        self.assertEqual(self.client.post(url, datos).status_code, 302)
        self.assertTrue(RegistroBitacora.objects.filter(accion="orden.retencion_creada").exists())
        self.assertEqual(self.client.get(reverse("compras:retencion_editar", args=[TipoRetencion.objects.get().pk])).status_code, 200)
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.admin)
        self.assertEqual(csrf.post(url, datos).status_code, 403)
        for actor in (self.coordinador, self.usuario_proveedor):
            self.client.force_login(actor)
            self.assertEqual(self.client.get(url).status_code, 403)
            with self.assertRaises(PermissionDenied):
                guardar_retencion(TipoRetencion(**{k: v for k, v in datos.items() if k != "motivo"}), actor=actor, motivo=MOTIVO)
        with self.assertRaises(ValidationError):
            guardar_retencion(TipoRetencion(nombre="FICTICIA UI", porcentaje=5), actor=self.admin, motivo=MOTIVO)
        with self.assertRaises(ValidationError):
            guardar_retencion(TipoRetencion(nombre="Otra", porcentaje=101), actor=self.admin, motivo=MOTIVO)

    def test_pantalla_borrador_con_descuento_retencion_y_desglose(self):
        orden, = self.crear()
        tipo = self.retencion()
        self.client.force_login(self.admin)
        url = reverse("compras:orden_editar", args=[orden.pk])
        datos = {"fecha_elaboracion": self.fecha.isoformat(), "revision_esperada": orden.revision, "retenciones": [tipo.pk], "motivo": MOTIVO,
            "lineas-TOTAL_FORMS": 2, "lineas-INITIAL_FORMS": 2}
        for i, l in enumerate(orden.lineas.all()):
            datos.update({f"lineas-{i}-id": l.pk, f"lineas-{i}-descripcion": l.descripcion, f"lineas-{i}-unidad": l.unidad,
                f"lineas-{i}-cantidad": str(l.cantidad), f"lineas-{i}-precio_unitario": str(l.precio_unitario), f"lineas-{i}-descuento": "2"})
        self.assertEqual(self.client.post(url, datos).status_code, 302)
        orden.refresh_from_db()
        self.assertEqual((orden.descuento, orden.retencion, orden.total), (4, 5, 43))
        detalle = self.client.get(reverse("compras:orden_detalle", args=[orden.pk]))
        self.assertContains(detalle, "Desglose de importes")
        self.assertContains(detalle, "Retención ficticia")
        self.assertContains(detalle, "pendiente de validar con financiera")

    def test_total_mezcla_tarifas_y_reparte_por_posicion_aunque_formulario_invierta_orden(self):
        orden, = self.crear()
        self.parametro(DECIMALES_ORDEN, "2")
        self.parametro(NIVEL_REDONDEO_ORDEN, "total")
        self.parametro(DESCUENTO_ORDEN, "despues_impuesto")
        tarifa = TarifaImpuesto.objects.create(nombre="Ficticia mixta", porcentaje=19)
        lineas = list(orden.lineas.all())
        orden = self.guardar(orden, [{"id": lineas[1].pk, "precio_unitario": ".0025", "descuento": 0},
            {"id": lineas[0].pk, "precio_unitario": ".005", "descuento": 0, "tarifa_id": tarifa.pk}], actualizar_reglas=True)
        self.assertEqual(orden.total, Decimal(".01"))
        self.assertEqual([l.subtotal for l in orden.lineas.all()], [Decimal(".01"), Decimal(0)])
        self.assertEqual(sum(l.total for l in orden.lineas.all()), orden.total)
        with self.assertRaisesMessage(ValidationError, "No hay cambios"):
            self.guardar(orden)

    def test_migracion_conserva_totales_fotos_originales_y_revisiones(self):
        from importlib import import_module
        from types import SimpleNamespace
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor
        orden, = self.crear()
        originales = [deepcopy(l.original) for l in orden.lineas.all()]
        historial = deepcopy(orden.revisiones.first().contenido)
        apps = MigrationExecutor(connection).loader.project_state([("compras", "0021_importes_ordenes")]).apps
        historico = apps.get_model("compras", "OrdenCompra")
        historico.objects.filter(pk=orden.pk).update(base=0, total_sin_retenciones=0, reglas_importes={})
        import_module("compras.migrations.0022_conservar_importes_previos").conservar(apps, SimpleNamespace(connection=connection))
        orden.refresh_from_db()
        self.assertEqual((orden.subtotal, orden.total, orden.base, orden.total_sin_retenciones, orden.retencion), (52, 52, 52, 52, 0))
        self.assertEqual([l.original for l in orden.lineas.all()], originales)
        self.assertEqual(orden.revisiones.first().contenido, historial)

    def test_reglas_de_linea_inconsistentes_impiden_emitir(self):
        orden, = self.crear()
        from compras.pruebas_operacion import preparar_numeracion
        preparar_numeracion(orden, self.admin, self.dev)
        linea = orden.lineas.first()
        type(linea)._base_manager.filter(pk=linea.pk).update(reglas_calculo={**orden.reglas_importes, "orden_descuento": "despues_impuesto"})
        with self.assertRaisesMessage(ValidationError, "Las reglas de una línea"):
            numeracion_ordenes.numerar_al_emitir(orden, actor=self.admin, motivo=MOTIVO)
