from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from bitacora.models import RegistroBitacora
from bitacora.servicios import registrar
from compras import cierre_servicios, cotizacion_servicios as cotizaciones, servicios, tests_decision
from compras.models import Cotizacion, InvitadoCotizacion, OrigenNecesidad, SecuenciaCotizacion, TipoCotizacion
from parametros.catalogo import MAX_LINEAS_COTIZACION, MAX_OFERENTES_COTIZACION
from parametros.models import Parametro
from parametros.servicios import cambiar_valor
from proveedores.tests.utilidades import crear_proveedor
from proyecciones.models import Linea, Periodo, ProyeccionArea, UnidadMedida
from proyecciones.servicios import aprobar_proyeccion

MOTIVO = "Cotización ficticia con origen verificado"


class CotizacionesTests(TestCase):
    def setUp(self):
        tests_decision.DecisionElegiblesTests.setUp(self)
        self.decidir()
        self.tipo = TipoCotizacion.objects.get(nombre="Compra")
        self.unidad = UnidadMedida.objects.create(nombre="Caja", abreviatura="cja")

    def calificar(self, valores=None):
        return tests_decision.DecisionElegiblesTests.calificar(self, valores)

    def asignaciones(self, cantidades=None, justificaciones=None):
        return tests_decision.DecisionElegiblesTests.asignaciones(self, cantidades, justificaciones)

    def decidir(self, **kwargs):
        return tests_decision.DecisionElegiblesTests.decidir(self, **kwargs)

    def cerrar(self):
        self.lista_actual = cierre_servicios.cerrar_lista(self.lista_actual, actor=self.admin, motivo=MOTIVO, justificacion_documental=MOTIVO)
        return self.lista_actual

    def linea(self, **cambios):
        dato = {"descripcion": "Insumo ficticio", "unidad": self.unidad, "cantidad": Decimal("2.125"), "especificacion": "Presentación ficticia"}
        dato.update(cambios)
        return dato

    def crear(self, **cambios):
        datos = dict(necesidad=self.necesidad, fecha=self.fecha, tipo=self.tipo, objeto="Compra ficticia cotizada",
            lineas=[self.linea()], invitados=[self.ficha], actor=self.admin, motivo=MOTIVO)
        datos.update(cambios)
        if datos.get("lista_elegibles"):
            datos.setdefault("cierre_esperado_id", datos["lista_elegibles"].cierres.first().pk if datos["lista_elegibles"].cierres.exists() else None)
            if "invitados" not in cambios:
                datos["invitados"] = ()
        return cotizaciones.crear_cotizacion(**datos)

    def datos_post(self, **cambios):
        datos = {"necesidad": self.necesidad.pk, "objeto": "Cotización ficticia por formulario", "fecha": "2031-02-01",
            "tipo": self.tipo.pk, "motivo": MOTIVO, "invitados": [self.ficha.pk],
            "lineas-TOTAL_FORMS": "1", "lineas-INITIAL_FORMS": "0", "lineas-0-descripcion": "Insumo ficticio",
            "lineas-0-cantidad": "2.125", "lineas-0-unidad": self.unidad.pk, "lineas-0-especificacion": "Especificación ficticia"}
        datos.update(cambios)
        return datos

    def test_creacion_manual_guarda_encabezado_especificacion_invitado_y_auditoria(self):
        cotizacion = self.crear()
        self.assertEqual(cotizacion.consecutivo, "COT-2031-000001")
        self.assertEqual(cotizacion.estado, "borrador")
        self.assertEqual(cotizacion.area, self.area)
        self.assertEqual(cotizacion.responsable, self.admin)
        self.assertEqual(cotizacion.necesidad, self.necesidad)
        self.assertIsNone(cotizacion.lista_elegibles_id)
        linea = cotizacion.lineas.get()
        self.assertEqual(linea.cantidad, Decimal("2.125"))
        self.assertEqual(linea.unidad_texto, str(self.unidad))
        self.assertEqual(linea.especificacion, "Presentación ficticia")
        self.assertEqual(cotizacion.invitados.get().nit, self.ficha.nit)
        self.assertIsNone(cotizacion.invitados.get().cantidad_autorizada)
        self.assertTrue(RegistroBitacora.objects.filter(accion="cotizacion.creada", actor=self.admin, motivo=MOTIVO).exists())

    def test_consecutivos_distintos_no_dependen_del_numero_de_cotizaciones_del_ano(self):
        primera = self.crear()
        segunda = self.crear(fecha=date(2032, 1, 1))
        self.assertEqual((primera.numero, segunda.numero), (1, 2))
        self.assertEqual(segunda.consecutivo, "COT-2032-000002")
        self.assertEqual(SecuenciaCotizacion.objects.get(pk=1).ultimo, 2)

    def test_fallo_de_auditoria_revierte_encabezado_lineas_invitados_y_consecutivo(self):
        def fallo(accion, **kwargs):
            if accion == "cotizacion.creada":
                raise RuntimeError("Fallo simulado de auditoría")
            return registrar(accion, **kwargs)
        antes = RegistroBitacora.objects.count()
        with patch("compras.cotizacion_servicios.registrar", side_effect=fallo):
            with self.assertRaises(RuntimeError):
                self.crear()
        self.assertFalse(Cotizacion.objects.exists())
        self.assertEqual(SecuenciaCotizacion.objects.get(pk=1).ultimo, 0)
        self.assertEqual(RegistroBitacora.objects.count(), antes)
        self.assertEqual(self.crear().numero, 1)

    def test_cantidades_invalidas_y_lineas_vacias_rechazadas_sin_consumir_numero(self):
        for valor in ["0", "-1", "NaN", "Infinity", "0.0001", 1.0, True]:
            with self.subTest(valor=valor), self.assertRaises(ValidationError):
                self.crear(lineas=[self.linea(cantidad=valor)])
        with self.assertRaises(ValidationError):
            self.crear(lineas=[])
        self.assertFalse(Cotizacion.objects.exists())
        self.assertEqual(SecuenciaCotizacion.objects.get(pk=1).ultimo, 0)

    def test_catalogo_desactivable_conserva_cotizaciones_y_exige_nombres_unicos(self):
        cotizacion = self.crear()
        self.tipo.activo = False
        cotizaciones.guardar_tipo(self.tipo, actor=self.dev, motivo=MOTIVO)
        with self.assertRaises(ValidationError):
            self.crear()
        cotizacion.refresh_from_db()
        self.assertEqual(cotizacion.tipo_id, self.tipo.pk)
        with self.assertRaises(ValidationError):
            cotizaciones.guardar_tipo(TipoCotizacion(nombre=" compra "), actor=self.admin, motivo=MOTIVO)
        self.assertTrue(RegistroBitacora.objects.filter(accion="cotizacion.tipo_modificado", actor=self.dev).exists())

    def test_limites_predeterminados_se_aplican_y_cero_permite_superarlos(self):
        invitados = [self.ficha] + [crear_proveedor() for _ in range(3)]
        with self.assertRaises(ValidationError):
            self.crear(invitados=invitados)
        lineas = [self.linea(descripcion=f"Insumo ficticio {n}") for n in range(11)]
        with self.assertRaises(ValidationError):
            self.crear(lineas=lineas)
        for clave in [MAX_LINEAS_COTIZACION, MAX_OFERENTES_COTIZACION]:
            cambiar_valor(Parametro.objects.get(clave=clave), "0", actor=self.admin, motivo=MOTIVO)
        cotizacion = self.crear(invitados=invitados, lineas=lineas)
        self.assertEqual(cotizacion.lineas.count(), 11)
        self.assertEqual(cotizacion.invitados.count(), 4)
        self.assertEqual(cotizacion.limites_aplicados, {"lineas": 0, "oferentes": 0})

    def test_limites_exactos_diez_y_tres_son_validos_y_parametros_invalidos_no(self):
        invitados = [self.ficha, crear_proveedor(), crear_proveedor()]
        cotizacion = self.crear(invitados=invitados, lineas=[self.linea() for _ in range(10)])
        self.assertEqual(cotizacion.lineas.count(), 10)
        self.assertEqual(cotizacion.invitados.count(), 3)
        for clave, valor in [(MAX_LINEAS_COTIZACION, "-1"), (MAX_OFERENTES_COTIZACION, "2.5")]:
            with self.assertRaises(ValidationError):
                cambiar_valor(Parametro.objects.get(clave=clave), valor, actor=self.admin, motivo=MOTIVO)

    def test_invitados_duplicados_o_inactivos_y_unidad_inactiva_se_rechazan(self):
        with self.assertRaises(ValidationError):
            self.crear(invitados=[self.ficha, self.ficha])
        inactivo = crear_proveedor(estado="inactivo")
        with self.assertRaises(ValidationError):
            self.crear(invitados=[inactivo])
        self.unidad.activa = False
        self.unidad.save()
        with self.assertRaises(ValidationError):
            self.crear()
        self.assertFalse(Cotizacion.objects.exists())

    def test_unicidad_de_nit_en_la_cotizacion_tambien_en_base(self):
        cotizacion = self.crear()
        otro = crear_proveedor()
        with self.assertRaises(IntegrityError), transaction.atomic():
            InvitadoCotizacion.objects.create(cotizacion=cotizacion, proveedor=otro, nit=self.ficha.nit, razon_social="Duplicado ficticio")
        self.assertEqual(cotizacion.invitados.count(), 1)

    def test_creacion_desde_lista_cerrada_copia_solo_elegidos_y_bloquea_reapertura_real(self):
        p2 = tests_decision.DecisionElegiblesTests.agregar(self)
        self.calificar({p2.pk: 3})
        self.decidir()
        self.cerrar()
        nit = self.lista_actual.resultado_cierre["filas"][0]["nit"]
        self.ficha.nit = "900123456"
        self.ficha.save()
        cotizacion = self.crear(lista_elegibles=self.lista_actual)
        invitado = cotizacion.invitados.get()
        self.assertEqual(invitado.nit, nit)
        self.assertEqual(invitado.participante_origen_id, self.p1.pk)
        self.assertEqual(invitado.cantidad_autorizada, Decimal(1))
        self.assertEqual(cotizacion.cierre_origen, self.lista_actual.cierres.get())
        self.assertEqual(self.lista_actual.estado_flujo, "Con cotización")
        with self.assertRaises(ValidationError):
            cierre_servicios.reabrir_lista(self.lista_actual, actor=self.admin, motivo=MOTIVO)
        with self.assertRaises(ValidationError):
            cierre_servicios.anular_lista(self.lista_actual, actor=self.admin, motivo=MOTIVO)

    def test_no_admite_lista_no_cerrada_de_otra_necesidad_ni_invitados_manipulados(self):
        with self.assertRaises(ValidationError):
            self.crear(lista_elegibles=self.lista_actual)
        self.cerrar()
        otra = servicios.crear_necesidad(objeto="Otra necesidad ficticia", area=self.area, fecha=self.fecha,
            origen_texto="Solicitud ficticia", actor=self.admin, motivo=MOTIVO)
        with self.assertRaises(ValidationError):
            self.crear(lista_elegibles=self.lista_actual, necesidad=otra)
        with self.assertRaises(ValidationError):
            self.crear(lista_elegibles=self.lista_actual, invitados=[crear_proveedor()])
        self.assertFalse(Cotizacion.objects.exists())

    def test_precarga_no_trunca_elegidos_cuando_el_limite_cambia(self):
        p2 = tests_decision.DecisionElegiblesTests.agregar(self)
        self.calificar()
        asignaciones = self.asignaciones({self.p1.pk: "1", p2.pk: "1"})
        from compras.decision_servicios import guardar_decision
        guardar_decision(self.lista_actual, asignaciones, actor=self.admin, motivo=MOTIVO)
        self.cerrar()
        cambiar_valor(Parametro.objects.get(clave=MAX_OFERENTES_COTIZACION), "1", actor=self.admin, motivo=MOTIVO)
        with self.assertRaises(ValidationError):
            self.crear(lista_elegibles=self.lista_actual)
        self.assertFalse(Cotizacion.objects.exists())
        self.assertEqual(SecuenciaCotizacion.objects.get(pk=1).ultimo, 0)

    def test_linea_de_necesidad_vinculada_y_navegacion_hasta_proyeccion(self):
        periodo = Periodo.objects.create(anio=2031, fecha_apertura=date(2031, 1, 1), fecha_limite_diligenciamiento=date(2031, 12, 15), creado_por=self.admin)
        proyeccion = ProyeccionArea.objects.create(periodo=periodo, area=self.area, estado="enviada", fecha_envio=timezone.now(), enviado_por=self.coordinador)
        linea = Linea.objects.create(proyeccion=proyeccion, producto_servicio="Producto de origen ficticio", unidad=self.unidad, cantidad_enero=5, precio_estimado=Decimal("1.00"))
        aprobar_proyeccion(proyeccion, actor=self.admin, motivo=MOTIVO)
        origen = OrigenNecesidad.objects.create(necesidad=self.necesidad, linea=linea, cantidad=Decimal("2.125"),
            datos_origen={"producto": linea.producto_servicio, "unidad": str(self.unidad), "periodo": 2031, "cantidad_autorizada": 5})
        self.cerrar()
        cotizacion = self.crear(lista_elegibles=self.lista_actual, lineas=[self.linea(origen=origen)])
        self.assertEqual(cotizacion.lineas.get().origen, origen)
        self.assertEqual(cotizacion.lineas.get().origen_datos["producto"], linea.producto_servicio)
        self.client.force_login(self.admin)
        respuesta = self.client.get(reverse("compras:cotizacion_detalle", args=[cotizacion.pk]))
        self.assertContains(respuesta, reverse("compras:necesidad_detalle", args=[self.necesidad.pk]))
        self.assertContains(respuesta, reverse("compras:lista_detalle", args=[self.lista_actual.pk]))
        self.assertContains(respuesta, reverse("proyecciones:revision_detalle", args=[proyeccion.pk]))
        otra = servicios.crear_necesidad(objeto="Necesidad ajena ficticia", area=self.area, fecha=self.fecha,
            origen_texto="Solicitud ficticia", actor=self.admin, motivo=MOTIVO)
        with self.assertRaises(ValidationError):
            self.crear(necesidad=otra, lineas=[self.linea(origen=origen)])

    def test_formulario_manual_crea_y_catalogo_es_configurable(self):
        self.client.force_login(self.dev)
        url = reverse("compras:cotizacion_nueva")
        self.assertEqual(self.client.get(url, {"necesidad": self.necesidad.pk}).status_code, 200)
        respuesta = self.client.post(url, self.datos_post())
        cotizacion = Cotizacion.objects.get()
        self.assertRedirects(respuesta, reverse("compras:cotizacion_detalle", args=[cotizacion.pk]))
        self.assertEqual(cotizacion.responsable, self.dev)
        respuesta = self.client.post(reverse("compras:cotizacion_tipos"), {"nombre": "Otro tipo ficticio", "descripcion": "Descripción", "activo": "on", "motivo": MOTIVO})
        self.assertRedirects(respuesta, reverse("compras:cotizacion_tipos"))
        self.assertTrue(TipoCotizacion.objects.filter(nombre="Otro tipo ficticio").exists())

    def test_formulario_desde_lista_no_crea_en_get_y_rechaza_revision_antigua(self):
        self.cerrar()
        self.client.force_login(self.admin)
        url = reverse("compras:cotizacion_desde_lista", args=[self.lista_actual.pk])
        respuesta = self.client.get(url)
        self.assertFalse(Cotizacion.objects.exists())
        firma = respuesta.context["formulario"]["revision_origen"].value()
        self.lista_actual = cierre_servicios.reabrir_lista(self.lista_actual, actor=self.admin, motivo=MOTIVO)
        self.decidir()
        self.cerrar()
        respuesta = self.client.post(url, self.datos_post(revision_origen=firma))
        self.assertContains(respuesta, "El cierre de origen cambió")
        self.assertFalse(Cotizacion.objects.exists())
        firma = self.client.get(url).context["formulario"]["revision_origen"].value()
        respuesta = self.client.post(url, self.datos_post(revision_origen=firma))
        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(Cotizacion.objects.get().lista_elegibles_id, self.lista_actual.pk)

    def test_permisos_vistas_servicios_y_csrf(self):
        cotizacion = self.crear()
        urls = [reverse("compras:cotizaciones"), reverse("compras:cotizacion_nueva"),
            reverse("compras:cotizacion_detalle", args=[cotizacion.pk]), reverse("compras:cotizacion_tipos"),
            reverse("compras:cotizacion_tipo_editar", args=[self.tipo.pk])]
        for usuario in [self.coordinador, self.usuario_proveedor]:
            self.client.force_login(usuario)
            for url in urls:
                self.assertEqual(self.client.get(url).status_code, 403)
                self.assertEqual(self.client.post(url, {}).status_code, 403)
        self.client.force_login(self.admin)
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 200)
        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(self.admin)
        self.assertEqual(cliente.post(reverse("compras:cotizacion_nueva"), self.datos_post()).status_code, 403)
        for actor in [self.coordinador, self.usuario_proveedor, AnonymousUser()]:
            with self.assertRaises(PermissionDenied):
                self.crear(actor=actor)
            with self.assertRaises(PermissionDenied):
                cotizaciones.guardar_tipo(TipoCotizacion(nombre="Otro"), actor=actor, motivo=MOTIVO)
        with self.assertRaises(ValidationError):
            self.crear(motivo=" ")
