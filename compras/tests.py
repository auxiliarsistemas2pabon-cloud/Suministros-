"""B4: origen de necesidades, identidad de participantes, permisos y auditoría."""

from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import Client, TestCase
from django.urls import reverse

from bitacora.models import RegistroBitacora
from compras import servicios
from compras.models import ListaElegibles, Necesidad, OrigenNecesidad, ParticipanteElegible, TipoOrigen
from proveedores.models import Proveedor
from proveedores.tests.utilidades import crear_proveedor
from proyecciones import servicios as proyecciones_servicios, tests_revision
from proyecciones.models import ProyeccionArea

MOTIVO = "Necesidad ficticia verificada con el área"


class ComprasTests(TestCase):
    def setUp(self):
        tests_revision.BaseRevision.setUp(self)
        proyecciones_servicios.aprobar_proyeccion(self.proyeccion, actor=self.administrador, motivo=MOTIVO)
        self.fecha = date(2031, 2, 1)
        self.ficha = self.proveedor.proveedor

    def necesidad(self, **cambios):
        datos = dict(objeto="Compra ficticia de suministros", area=self.area, fecha=self.fecha,
                     origen_texto="Solicitud puntual ficticia", actor=self.administrador, motivo=MOTIVO)
        datos.update(cambios)
        return servicios.crear_necesidad(**datos)

    def lista(self, **cambios):
        datos = dict(fecha=self.fecha, actor=self.administrador, motivo=MOTIVO)
        datos.update(cambios)
        return servicios.crear_lista(self.necesidad(), **datos)

    def agregar(self, lista, ficha=None, **cambios):
        return servicios.agregar_participante(lista, ficha or self.ficha,
            actor=cambios.get("actor", self.administrador), motivo=cambios.get("motivo", MOTIVO))

    def datos_post(self, **cambios):
        datos = {"objeto": "Compra ficticia", "area": self.area.pk, "fecha": "2031-02-01",
                 "origen_texto": "Solicitud puntual", "motivo": MOTIVO, "periodo": self.periodo.pk,
                 "origenes-TOTAL_FORMS": "1", "origenes-INITIAL_FORMS": "0",
                 "origenes-0-linea": "", "origenes-0-cantidad": ""}
        datos.update(cambios)
        return datos

    def test_necesidad_manual_con_responsable_fecha_y_bitacora(self):
        necesidad = self.necesidad()
        self.assertEqual(necesidad.responsable, self.administrador)
        self.assertEqual(necesidad.fecha, self.fecha)
        self.assertFalse(necesidad.lineas.exists())
        registro = RegistroBitacora.objects.get(accion="necesidad.creada", objeto_id=str(necesidad.pk))
        self.assertEqual(registro.actor, self.administrador)
        self.assertEqual(registro.motivo, MOTIVO)
        self.assertEqual(registro.valor_nuevo["area"]["id"], self.area.pk)
        self.assertTrue(registro.fecha)
        with self.assertRaises(ValidationError):
            self.necesidad(origen_texto=" ")

    def test_tipo_origen_configurable_conserva_historico_y_rechaza_inactivo(self):
        tipo = servicios.guardar_tipo_origen(TipoOrigen(nombre=" Comité ficticio "), actor=self.administrador, motivo=MOTIVO)
        necesidad = self.necesidad(tipo_origen=tipo, origen_texto="")
        tipo.activo = False
        servicios.guardar_tipo_origen(tipo, actor=self.administrador, motivo=MOTIVO)
        necesidad.refresh_from_db()
        self.assertEqual(necesidad.tipo_origen_id, tipo.pk)
        with self.assertRaises(ValidationError):
            self.necesidad(tipo_origen=tipo)
        with self.assertRaises(ProtectedError):
            tipo.delete()
        self.assertTrue(RegistroBitacora.objects.filter(accion="tipo_origen.modificado", valor_anterior__activo=True, valor_nuevo__activo=False).exists())
        with self.assertRaises(ValidationError):
            servicios.guardar_tipo_origen(TipoOrigen(nombre="COMITÉ FICTICIO"), actor=self.administrador, motivo=MOTIVO)

    def test_agrupa_y_divide_con_decimal_y_foto_de_origen(self):
        primera = self.necesidad(origen_texto="", lineas=[(self.linea.pk, Decimal("1.125")), (self.linea_dos.pk, Decimal("2"))])
        segunda = self.necesidad(origen_texto="", lineas=[(self.linea.pk, Decimal("3.875"))])
        self.assertEqual(primera.lineas.count(), 2)
        origen = primera.origenes.get(linea=self.linea)
        self.assertEqual(origen.cantidad, Decimal("1.125"))
        self.assertEqual(segunda.origenes.get().cantidad, Decimal("3.875"))
        self.assertEqual(origen.datos_origen, {"producto": "Guantes de examen", "unidad": str(self.unidad), "periodo": 2031, "cantidad_autorizada": 5})
        proyecciones_servicios.registrar_ajuste(self.linea, "cantidad_autorizada", 10,
            actor=self.administrador, justificacion=MOTIVO)
        origen.refresh_from_db()
        self.assertEqual(origen.datos_origen["cantidad_autorizada"], 5)
        tercera = self.necesidad(lineas=[(self.linea.pk, "0.001")])
        self.assertEqual(tercera.origenes.get().datos_origen["cantidad_autorizada"], 10)

    def test_rechaza_borrador_area_ajena_e_inexistente_sin_guardado_parcial(self):
        for linea_id in [self.linea_ajena.pk, 99999999]:
            with self.subTest(linea_id=linea_id):
                registros = RegistroBitacora.objects.count()
                with self.assertRaises(ValidationError):
                    self.necesidad(lineas=[(self.linea.pk, "1"), (linea_id, "1")])
                self.assertFalse(Necesidad.objects.exists())
                self.assertEqual(RegistroBitacora.objects.count(), registros)
        ProyeccionArea.objects.filter(pk=self.otra_proyeccion.pk).update(estado="aprobada")
        with self.assertRaises(ValidationError):
            self.necesidad(lineas=[(self.linea_ajena.pk, "1")])
        self.area.activa = False
        self.area.save()
        with self.assertRaises(ValidationError):
            self.necesidad()

    def test_cantidades_invalidas_y_repetidas_revierten_todo(self):
        for cantidad in ["0", "-1", "0.0001", "NaN", "Infinity", 0.1, True, "9999999999999999", "abc"]:
            with self.subTest(cantidad=cantidad), self.assertRaises(ValidationError):
                self.necesidad(lineas=[(self.linea.pk, cantidad)])
        with self.assertRaises(ValidationError):
            self.necesidad(lineas=[(self.linea.pk, "1"), (self.linea.pk, "2")])
        self.assertFalse(Necesidad.objects.exists())

    def test_error_de_bitacora_revierte_necesidad_y_origenes(self):
        with patch("compras.servicios.registrar", side_effect=RuntimeError("Fallo simulado")):
            with self.assertRaises(RuntimeError):
                self.necesidad(lineas=[(self.linea.pk, "1")])
        self.assertFalse(Necesidad.objects.exists())
        self.assertFalse(OrigenNecesidad.objects.exists())

    def test_identidad_unica_por_proveedor_y_por_nit_incluso_si_cambia_la_ficha(self):
        lista = self.lista()
        participante = self.agregar(lista)
        with self.assertRaises(ValidationError):
            self.agregar(lista)
        nit_original = participante.nit
        self.ficha.nit = "900123456"
        self.ficha.razon_social = "Nombre actualizado ficticio"
        self.ficha.save()
        participante.refresh_from_db()
        self.assertEqual(participante.nit, nit_original)
        self.assertNotEqual(participante.razon_social, self.ficha.razon_social)
        otra = crear_proveedor(nit=nit_original)
        with self.assertRaises(ValidationError):
            self.agregar(lista, otra)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ParticipanteElegible.objects.create(lista=lista, proveedor=otra, nit=nit_original, razon_social="Duplicado")
        self.assertEqual(lista.participantes.count(), 1)

    def test_retirar_y_reactivar_conserva_fila_y_audita_valores_anteriores(self):
        lista = self.lista()
        participante = self.agregar(lista)
        servicios.quitar_participante(lista, participante, actor=self.administrador, motivo=MOTIVO)
        participante.refresh_from_db()
        self.assertFalse(participante.activo)
        registro = RegistroBitacora.objects.get(accion="participante.retirado")
        self.assertEqual(registro.valor_anterior, {"activo": True})
        self.assertEqual(registro.valor_nuevo, {"activo": False})
        self.assertEqual(registro.actor, self.administrador)
        self.ficha.nit = "900123456"
        self.ficha.razon_social = "Otro nombre ficticio"
        self.ficha.save()
        reactivado = self.agregar(lista)
        self.assertEqual(reactivado.pk, participante.pk)
        self.assertEqual(lista.participantes.count(), 1)
        self.assertTrue(reactivado.activo)
        self.assertEqual(reactivado.nit, participante.nit)
        self.assertEqual(reactivado.razon_social, participante.razon_social)
        self.assertTrue(RegistroBitacora.objects.filter(accion="participante.reactivado", motivo=MOTIVO).exists())

    def test_solo_borrador_admite_participantes_y_solo_necesidad_abierta_admite_listas(self):
        lista = self.lista()
        participante = self.agregar(lista)
        self.assertEqual(lista.creada_por, self.administrador)
        self.assertEqual(lista.fecha, self.fecha)
        self.assertTrue(RegistroBitacora.objects.filter(accion="lista_elegibles.creada", objeto_id=str(lista.pk)).exists())
        for estado in ["cerrada", "anulada"]:
            ListaElegibles.objects.filter(pk=lista.pk).update(estado=estado)
            with self.subTest(estado=estado):
                with self.assertRaises(ValidationError):
                    self.agregar(lista)
                with self.assertRaises(ValidationError):
                    servicios.quitar_participante(lista, participante, actor=self.administrador, motivo=MOTIVO)
                Necesidad.objects.filter(pk=lista.necesidad_id).update(estado=estado)
                with self.assertRaises(ValidationError):
                    servicios.crear_lista(lista.necesidad, fecha=self.fecha, actor=self.administrador, motivo=MOTIVO)
        participante.refresh_from_db()
        self.assertTrue(participante.activo)

    def test_proveedor_inactivo_y_participante_de_otra_lista_se_rechazan(self):
        lista, otra = self.lista(), self.lista()
        participante = self.agregar(otra)
        with self.assertRaises(ValidationError):
            servicios.quitar_participante(lista, participante, actor=self.administrador, motivo=MOTIVO)
        Proveedor.objects.filter(pk=self.ficha.pk).update(estado=Proveedor.Estado.INACTIVO)
        with self.assertRaises(ValidationError):
            self.agregar(lista)

    def test_servicios_exigen_rol_administrativo_y_motivo(self):
        lista = self.lista()
        participante = self.agregar(lista)
        operaciones = [
            lambda actor, motivo: self.necesidad(actor=actor, motivo=motivo),
            lambda actor, motivo: servicios.crear_lista(lista.necesidad, fecha=self.fecha, actor=actor, motivo=motivo),
            lambda actor, motivo: self.agregar(lista, actor=actor, motivo=motivo),
            lambda actor, motivo: servicios.quitar_participante(lista, participante, actor=actor, motivo=motivo),
            lambda actor, motivo: servicios.guardar_tipo_origen(TipoOrigen(nombre="Otro"), actor=actor, motivo=motivo),
        ]
        for operacion in operaciones:
            for actor in [self.coordinador, self.proveedor, AnonymousUser()]:
                with self.subTest(operacion=operacion, rol=str(actor)), self.assertRaises(PermissionDenied):
                    operacion(actor, MOTIVO)
            with self.assertRaises(ValidationError):
                operacion(self.administrador, " ")

    def test_filtro_por_area_periodo_y_aprobacion(self):
        self.assertEqual(set(servicios.lineas_disponibles(area=self.area, periodo=self.periodo)), {self.linea, self.linea_dos})
        self.assertFalse(servicios.lineas_disponibles(area=self.otra_area).exists())
        self.assertFalse(servicios.lineas_disponibles(periodo=99999999).exists())
        self.client.force_login(self.administrador)
        respuesta = self.client.get(reverse("compras:necesidad_nueva"), {"area": self.area.pk, "periodo": self.periodo.pk})
        self.assertEqual(set(respuesta.context["origenes"].forms[0].fields["linea"].queryset), {self.linea, self.linea_dos})
        self.assertContains(respuesta, 'id="filtro_area"')

    def test_pantallas_crean_necesidad_lista_y_participante(self):
        self.client.force_login(self.administrador)
        datos = self.datos_post(**{"origenes-0-linea": self.linea.pk, "origenes-0-cantidad": "1.125"})
        respuesta = self.client.post(reverse("compras:necesidad_nueva"), datos)
        necesidad = Necesidad.objects.get()
        self.assertRedirects(respuesta, reverse("compras:necesidad_detalle", args=[necesidad.pk]))
        self.assertEqual(necesidad.origenes.get().cantidad, Decimal("1.125"))
        respuesta = self.client.post(respuesta.url, {"fecha": "2031-02-02", "motivo": MOTIVO})
        lista = ListaElegibles.objects.get()
        self.assertRedirects(respuesta, reverse("compras:lista_detalle", args=[lista.pk]))
        respuesta = self.client.post(respuesta.url, {"proveedor": self.ficha.pk, "motivo": MOTIVO})
        self.assertRedirects(respuesta, reverse("compras:lista_detalle", args=[lista.pk]))
        self.assertEqual(lista.participantes.get().proveedor, self.ficha)
        self.assertContains(self.client.get(respuesta.url), self.ficha.nit)

    def test_formulario_rechaza_lineas_manipuladas_y_cantidades_sin_linea(self):
        self.client.force_login(self.administrador)
        for cambios in [{"origenes-0-linea": self.linea_ajena.pk, "origenes-0-cantidad": "1"},
                        {"origenes-0-cantidad": "1"}, {"motivo": ""}, {"periodo": "no-valido"}]:
            with self.subTest(cambios=cambios):
                respuesta = self.client.post(reverse("compras:necesidad_nueva"), self.datos_post(**cambios))
                self.assertEqual(respuesta.status_code, 200)
                self.assertFalse(Necesidad.objects.exists())

    def test_retiro_post_con_motivo_y_pertenencia_y_csrf(self):
        lista = self.lista()
        participante = self.agregar(lista)
        url = reverse("compras:participante_quitar", args=[lista.pk, participante.pk])
        self.client.force_login(self.administrador)
        self.assertEqual(self.client.get(url).status_code, 405)
        cliente_csrf = Client(enforce_csrf_checks=True)
        cliente_csrf.force_login(self.administrador)
        self.assertEqual(cliente_csrf.post(url, {"motivo": MOTIVO}).status_code, 403)
        self.client.post(url, {"motivo": ""})
        participante.refresh_from_db()
        self.assertTrue(participante.activo)
        otra = self.lista()
        self.assertEqual(self.client.post(reverse("compras:participante_quitar", args=[otra.pk, participante.pk]), {"motivo": MOTIVO}).status_code, 404)
        self.client.post(url, {"motivo": MOTIVO})
        participante.refresh_from_db()
        self.assertFalse(participante.activo)

    def test_permisos_de_todas_las_vistas_y_menu(self):
        lista = self.lista()
        participante = self.agregar(lista)
        tipo = TipoOrigen.objects.create(nombre="Solicitud ficticia")
        urls = [reverse("compras:necesidades"), reverse("compras:necesidad_nueva"),
                reverse("compras:necesidad_detalle", args=[lista.necesidad_id]),
                reverse("compras:lista_detalle", args=[lista.pk]), reverse("compras:origenes"),
                reverse("compras:origen_editar", args=[tipo.pk])]
        retiro = reverse("compras:participante_quitar", args=[lista.pk, participante.pk])
        for usuario in [self.coordinador, self.proveedor]:
            self.client.force_login(usuario)
            for url in urls + [retiro]:
                with self.subTest(rol=usuario.rol, url=url):
                    self.assertEqual(self.client.get(url).status_code, 403)
                    self.assertEqual(self.client.post(url, {}).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(urls[0]).status_code, 302)
        for usuario in [self.administrador, self.desarrollador]:
            self.client.force_login(usuario)
            for url in urls:
                with self.subTest(rol=usuario.rol, url=url):
                    self.assertEqual(self.client.get(url).status_code, 200)
            self.assertContains(self.client.get(reverse("inicio")), reverse("compras:necesidades"))
